"""Report quality evals: a small scored test set so improvements are measured, not felt.

Usage (needs a real Gemini key in .env — evals are meaningless against mocks):

    .venv\\Scripts\\python -m scripts.eval_reports

Runs every case in tests/eval_set/ through the live pipeline, scores each
report deterministically (0-100), prints a table, and appends the run to
data/evals/ so score history is comparable across prompt/skill-pack changes.
"""

import asyncio
import json
import sys
from pathlib import Path

from app.config import DATA_DIR, PROJECT_ROOT
from app.schemas import CampaignReportV3, utcnow

EVAL_SET_DIR = PROJECT_ROOT / "tests" / "eval_set"
EVALS_DIR = DATA_DIR / "evals"

CORE_FIELDS = ["campaign_idea", "how_it_was_run", "hook", "emotional_trigger", "visual_notes", "why_it_worked", "takeaway_for_us"]


def _contains_any(haystack: str, needles: list[str]) -> bool:
    hay = haystack.lower()
    return any(n.lower() in hay for n in needles)


def score_report(report: CampaignReportV3, expected: dict) -> dict:
    """Deterministic rubric. Max 100."""
    checks: dict[str, tuple[bool, int]] = {}

    core = report.core
    complete = all(len(getattr(core, f).strip()) >= 20 for f in CORE_FIELDS)
    checks["core_fields_substantive"] = (complete, 20)

    play_text = f"{report.strategy.primary_play} {report.strategy.secondary_play or ''}"
    checks["play_matches_expected"] = (_contains_any(play_text, expected.get("plays_any", [])), 25)

    emotion_text = f"{report.hook_copy.dominant_emotion} {core.emotional_trigger}"
    checks["emotion_matches_expected"] = (_contains_any(emotion_text, expected.get("emotion_any", [])), 15)

    bucket = report.audience.bucket_id if report.audience else ""
    checks["bucket_in_expected"] = (bucket in expected.get("bucket_any", []), 15)

    checks["trend_verdict_present"] = (report.trend is not None, 5)
    checks["trend_has_citations"] = (bool(report.trend and report.trend.citations), 10)

    takeaway = core.takeaway_for_us.lower()
    concrete = any(w in takeaway for w in ("reel", "carousel", "whatsapp", "linkedin", "instagram", "email", "post", "video", "story"))
    checks["takeaway_is_concrete"] = (concrete, 10)

    return {
        "score": sum(pts for ok, pts in checks.values() if ok),
        "max": sum(pts for _, pts in checks.values()),
        "checks": {name: ok for name, (ok, _) in checks.items()},
    }


async def run_evals() -> None:
    from app.graph import graph, initial_state
    from app.storage import new_report_id

    cases = sorted(EVAL_SET_DIR.glob("*.json"))
    if not cases:
        print(f"No eval cases in {EVAL_SET_DIR}")
        return

    results = []
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        print(f"running {case['name']} ...", flush=True)
        try:
            state = await graph.ainvoke(
                initial_state(case["text"], [], new_report_id(), skip_dedupe=True)
            )
            scored = score_report(state["report"], case["expected"])
        except Exception as e:
            scored = {"score": 0, "max": 100, "checks": {}, "error": str(e)}
        results.append({"case": case["name"], **scored})

    print(f"\n{'case':<24}{'score':>8}")
    print("-" * 34)
    for r in results:
        print(f"{r['case']:<24}{r['score']:>5}/{r['max']}")
        for name, ok in r.get("checks", {}).items():
            print(f"    {'PASS' if ok else 'FAIL'}  {name}")
        if "error" in r:
            print(f"    ERROR {r['error']}")
    avg = sum(r["score"] for r in results) / len(results)
    print(f"\naverage: {avg:.1f}/100")

    EVALS_DIR.mkdir(parents=True, exist_ok=True)
    out = EVALS_DIR / f"{utcnow():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"run_at": utcnow().isoformat(), "average": avg, "results": results}, indent=2), encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    sys.exit(asyncio.run(run_evals()))
