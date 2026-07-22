"""Analysis pipeline (Phase 6 shape).

    START -> dedupe -+-> END                     (duplicate: reuse existing report)
                     +-> prep -> [strategy, hook, visual] -> recall -> composer
                                -> trend -> [audience, critique] -> finalize -> END

dedupe:   image-hash overlap or near-identical text -> short-circuit, never analyze twice.
recall:   query memory with the specialists' read -> neighbors feed the composer.
trend:    memory frequency + grounded web search -> new/rising/peaked/fading + citations.
audience: which of our buckets the pattern can carry a message to, the angle,
          and the per-bucket playbook for pulling this campaign's emotional trigger.
critique: the case *against* — weaknesses, copy risk, what we could not verify.
finalize: assemble report v3 (+ scorecard) and index the finished analysis into memory.

Why critique is its own node rather than more fields on the composer: the
composer has just spent its output arguing why the campaign works, and asking
it for the counter-case in the same breath reliably produces praise wearing a
"however". A separate node with an adversarial prompt, no authorship of the
positive read, and a schema that refuses fewer than two weaknesses is what
makes the negative section actually negative. It runs on Flash in parallel
with `audience`, so the honesty costs one cheap call and no wall-clock time.
"""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.buckets import load_buckets
from app.config import GEMINI_COMPOSER_MODEL, brand_prompt, load_brand, load_prompt, load_skill_pack
from app.llm import call_structured
from app.memory import get_memory
from app.palette import extract_palette
from app.emotions import emotion_map_lines, normalize
from app.schemas import (
    AudienceDraft,
    AudienceFit,
    CampaignReport,
    EmotionProfile,
    CampaignReportV3,
    Critique,
    CritiqueDraft,
    HookAnalysis,
    ImagePayload,
    JudgedScores,
    Neighbor,
    PaletteColor,
    StrategyAnalysis,
    TrendDraft,
    TrendVerdict,
    TriggerPlay,
    Usage,
    VisualAnalysis,
    utcnow,
)
from app.scoring import build_scorecard
from app.storage import image_hashes_of
from app.trend import market_signal


class AnalysisState(TypedDict):
    report_id: str
    text: str
    images: list[ImagePayload]
    source: str  # "user" | "scan"
    skip_dedupe: bool
    image_hashes: list[str]
    palette: list[PaletteColor]
    strategy: StrategyAnalysis | None
    hook_copy: HookAnalysis | None
    visual: VisualAnalysis | None
    neighbors: list[Neighbor]
    core: CampaignReport | None
    trend: TrendVerdict | None
    audience: AudienceFit | None
    playbook: list[TriggerPlay]
    critique: Critique | None
    judged: JudgedScores | None
    report: CampaignReportV3 | None
    existing_report_id: str | None
    usages: Annotated[list[Usage], operator.add]


def _specialist_system(prompt_file: str, pack: str) -> str:
    system = load_prompt(prompt_file)
    pack_text = load_skill_pack(pack)
    if pack_text:
        system += f"\n\n# Your skill pack\n\n{pack_text}"
    return system


def _material_message(state: AnalysisState, extra: str = "") -> HumanMessage:
    text = state["text"].strip() or "(no text provided — analyze the images alone)"
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "Campaign material to analyze.\n\n"
                f"Submitter's text/context:\n{text}\n\n"
                f"Attached images: {len(state['images'])}"
                + (f"\n\n{extra}" if extra else "")
            ),
        }
    ]
    for img in state["images"]:
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{img.mime_type};base64,{img.data}"}}
        )
    return HumanMessage(content=content)


# --- nodes -------------------------------------------------------------------


async def dedupe_node(state: AnalysisState) -> dict:
    hashes = image_hashes_of(state["images"])
    if state.get("skip_dedupe"):
        return {"image_hashes": hashes, "existing_report_id": None}
    dup = await get_memory().find_duplicate(state["text"], hashes)
    return {
        "image_hashes": hashes,
        "existing_report_id": dup["report_id"] if dup else None,
    }


def route_after_dedupe(state: AnalysisState) -> str:
    return "reuse" if state["existing_report_id"] else "analyze"


def prep_node(state: AnalysisState) -> dict:
    return {"palette": extract_palette(state["images"])}


async def strategy_node(state: AnalysisState) -> dict:
    parsed, usage = await call_structured(
        StrategyAnalysis,
        [SystemMessage(content=_specialist_system("strategy_v1.md", "strategy")), _material_message(state)],
        node="strategy",
    )
    return {"strategy": parsed, "usages": [usage]}


async def hook_node(state: AnalysisState) -> dict:
    parsed, usage = await call_structured(
        HookAnalysis,
        [SystemMessage(content=_specialist_system("hook_v1.md", "hook")), _material_message(state)],
        node="hook",
    )
    return {"hook_copy": parsed, "usages": [usage]}


async def visual_node(state: AnalysisState) -> dict:
    palette_text = (
        "Programmatically extracted palette (hex, % coverage): "
        + (", ".join(f"{c.hex} ({c.coverage_pct}%)" for c in state["palette"]) or "none — no decodable images")
    )
    parsed, usage = await call_structured(
        VisualAnalysis,
        [
            SystemMessage(content=_specialist_system("visual_v1.md", "visual")),
            _material_message(state, extra=palette_text),
        ],
        node="visual",
    )
    return {"visual": parsed, "usages": [usage]}


async def recall_node(state: AnalysisState) -> dict:
    """Query memory with the specialists' read (works for image-only inputs too)."""
    s, h = state["strategy"], state["hook_copy"]
    query = (
        f"Play: {s.primary_play}. Idea: {s.campaign_idea} "
        f"Hook: {h.hook_quote}. Emotion: {h.dominant_emotion}. "
        f"Visual: {state['visual'].production_signal}"
    )
    neighbors = await get_memory().find_similar(query, exclude_report_id=state["report_id"])
    return {"neighbors": neighbors}


async def composer_node(state: AnalysisState) -> dict:
    if state["neighbors"]:
        neighbor_text = "\n".join(
            f"- {n.report_id} (analyzed {n.analyzed_at[:10]}, similarity {n.similarity}): "
            f"{n.primary_play} — {n.summary}"
            for n in state["neighbors"]
        )
    else:
        neighbor_text = "(memory is empty or nothing similar — this is a first of its kind for us)"

    briefing = (
        "Specialist analyses of the campaign:\n\n"
        f"## Strategy specialist\n{state['strategy'].model_dump_json(indent=2)}\n\n"
        f"## Hook & Copy specialist\n{state['hook_copy'].model_dump_json(indent=2)}\n\n"
        f"## Visual specialist\n{state['visual'].model_dump_json(indent=2)}\n\n"
        f"Extracted palette: {[f'{c.hex} {c.coverage_pct}%' for c in state['palette']]}\n\n"
        f"## Similar campaigns we've analyzed before (from memory)\n{neighbor_text}\n\n"
        f"Original submitter context:\n{state['text'].strip() or '(images only)'}"
    )
    core, usage = await call_structured(
        CampaignReport,
        [SystemMessage(content=brand_prompt("composer_v1.md")), HumanMessage(content=briefing)],
        node="composer",
        model=GEMINI_COMPOSER_MODEL,
    )
    return {"core": core, "usages": [usage]}


async def trend_node(state: AnalysisState) -> dict:
    s = state["strategy"]
    freq = get_memory().play_frequency(s.primary_play)
    topic = f"{s.primary_play} — {s.campaign_idea}"
    signal_text, citations, search_usage = await market_signal(topic)

    briefing = (
        f"Pattern under judgment: {topic}\n\n"
        f"## Evidence stream 1 — our memory frequency\n"
        f"Seen {freq['recent']} time(s) in the last {freq['window_days']} days, "
        f"{freq['prior']} time(s) before that. "
        f"Total analyses in memory: {freq['total_analyses_in_memory']}.\n\n"
        f"## Evidence stream 2 — live market signal (web search)\n{signal_text}"
    )
    draft, usage = await call_structured(
        TrendDraft,
        [SystemMessage(content=load_prompt("trend_v1.md")), HumanMessage(content=briefing)],
        node="trend",
    )
    verdict = TrendVerdict(**draft.model_dump(), citations=citations)
    return {"trend": verdict, "usages": [search_usage, usage]}


async def audience_node(state: AnalysisState) -> dict:
    registry = load_buckets()
    outcomes = get_memory().outcome_summary()
    outcome_block = ""
    if outcomes:
        lines = "\n".join(
            f"- {o['play']}: {o['proven_campaigns']} campaign(s) that performed for us ({', '.join(o['examples'])})"
            for o in outcomes
        )
        outcome_block = f"\n\n## What has worked for our audience historically (recorded outcomes)\n{lines}"

    # The detected trigger, normalized, stated explicitly — the playbook is
    # about transferring THIS trigger, not the campaign's surface content.
    h = state["hook_copy"]
    canon, valence = normalize(h.dominant_emotion)
    trigger_block = (
        f"\n\n## Detected emotional trigger (transfer THIS, not the surface content)\n"
        f"Emotion: {canon or h.dominant_emotion} (valence: {valence}; specialist wrote: '{h.dominant_emotion}')\n"
        f"Fired by: {h.trigger_element}\n\n"
        f"Canonical emotion map for reference:\n{emotion_map_lines()}"
    )
    briefing = (
        f"## Campaign deconstruction (composed)\n{state['core'].model_dump_json(indent=2)}\n\n"
        f"## Trend verdict\n{state['trend'].model_dump_json(indent=2)}\n\n"
        f"## Our audience bucket registry\n{registry.model_dump_json(indent=2)}"
        f"{trigger_block}{outcome_block}"
    )
    draft, usage = await call_structured(
        AudienceDraft,
        [SystemMessage(content=brand_prompt("audience_v1.md")), HumanMessage(content=briefing)],
        node="audience",
    )
    return {"audience": draft.fit, "playbook": draft.trigger_playbook, "usages": [usage]}


async def critique_node(state: AnalysisState) -> dict:
    """The negative section. Attacks the report the rest of the pipeline just wrote.

    Deliberately fed the *composed* deconstruction rather than only the raw
    material: the confident positive read is the thing under review, and the
    critic can only flag over-claiming if it can see the claims.
    """
    briefing = (
        "You are reviewing the analysis below. It is a claim under review, not fact.\n\n"
        f"## The composed deconstruction (the positive read)\n{state['core'].model_dump_json(indent=2)}\n\n"
        f"## Strategy specialist\n{state['strategy'].model_dump_json(indent=2)}\n\n"
        f"## Hook & Copy specialist\n{state['hook_copy'].model_dump_json(indent=2)}\n\n"
        f"## Visual specialist\n{state['visual'].model_dump_json(indent=2)}\n\n"
        f"## Trend verdict\n{state['trend'].model_dump_json(indent=2) if state['trend'] else '(none)'}\n\n"
        "## What the submitter actually gave us\n"
        f"Text: {state['text'].strip() or '(none — images only)'}\n"
        f"Images attached: {len(state['images'])}\n"
        "Results data (spend, reach, conversions, attribution): none. There is "
        "never any in this pipeline — factor that into evidence_strength."
    )
    draft, usage = await call_structured(
        CritiqueDraft,
        [
            SystemMessage(content=_specialist_system("critique_v1.md", "critique") + f"\n\n{load_brand()}"),
            HumanMessage(content=briefing),
        ],
        node="critique",
    )
    return {"critique": draft.critique, "judged": draft.scores, "usages": [usage]}


async def finalize_node(state: AnalysisState) -> dict:
    scorecard = build_scorecard(
        judged=state.get("judged"),
        critique=state.get("critique"),
        strategy=state["strategy"],
        audience=state["audience"],
        trend=state["trend"],
        neighbors=state["neighbors"],
        bucket_channels=sorted({c for b in load_buckets().buckets for c in b.channels}),
    )
    # Emotion profile is derived, not asked: normalize whatever the hook
    # specialist wrote so analytics never fragments across spellings.
    canon, valence = normalize(state["hook_copy"].dominant_emotion)
    emotion = EmotionProfile(
        primary=canon,
        valence=valence,
        raw=state["hook_copy"].dominant_emotion,
        trigger_element=state["hook_copy"].trigger_element,
    )
    report = CampaignReportV3(
        core=state["core"],
        strategy=state["strategy"],
        hook_copy=state["hook_copy"],
        visual=state["visual"],
        palette=state["palette"],
        neighbors=state["neighbors"],
        trend=state["trend"],
        audience=state["audience"],
        critique=state.get("critique"),
        scorecard=scorecard,
        emotion=emotion,
        trigger_playbook=state.get("playbook", []),
    )
    await get_memory().index_report(
        report_id=state["report_id"],
        created_at=utcnow().isoformat(),
        report=report,
        input_text=state["text"],
        image_hashes=state["image_hashes"],
        source=state.get("source", "user"),
        extra_payload={
            "trend_verdict": report.trend.verdict if report.trend else None,
            "audience_bucket": report.audience.bucket_id if report.audience else None,
        },
    )
    if report.trend is not None:
        from app.lifecycle import record_event
        from app.radar.alerts import maybe_alert

        record_event(report.strategy.primary_play, report.trend.verdict, state["report_id"])
        await maybe_alert(
            state["report_id"],
            report.strategy.primary_play,
            report.trend.verdict,
            angle_hint=report.audience.angle if report.audience else "",
        )
    return {"report": report}


def build_graph():
    g = StateGraph(AnalysisState)
    g.add_node("dedupe", dedupe_node)
    g.add_node("prep", prep_node)
    g.add_node("strategy", strategy_node)
    g.add_node("hook", hook_node)
    g.add_node("visual", visual_node)
    g.add_node("recall", recall_node)
    g.add_node("composer", composer_node)
    g.add_node("trend", trend_node)
    g.add_node("audience", audience_node)
    g.add_node("critique", critique_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "dedupe")
    g.add_conditional_edges("dedupe", route_after_dedupe, {"reuse": END, "analyze": "prep"})
    g.add_edge("prep", "strategy")
    g.add_edge("prep", "hook")
    g.add_edge("prep", "visual")
    g.add_edge("strategy", "recall")
    g.add_edge("hook", "recall")
    g.add_edge("visual", "recall")
    g.add_edge("recall", "composer")
    g.add_edge("composer", "trend")
    g.add_edge("trend", "audience")
    g.add_edge("trend", "critique")
    g.add_edge("audience", "finalize")
    g.add_edge("critique", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


graph = build_graph()


def initial_state(
    text: str,
    images: list[ImagePayload],
    report_id: str,
    skip_dedupe: bool = False,
    source: str = "user",
) -> AnalysisState:
    return {
        "report_id": report_id,
        "text": text,
        "images": images,
        "source": source,
        "skip_dedupe": skip_dedupe,
        "image_hashes": [],
        "palette": [],
        "strategy": None,
        "hook_copy": None,
        "visual": None,
        "neighbors": [],
        "core": None,
        "trend": None,
        "audience": None,
        "playbook": [],
        "critique": None,
        "judged": None,
        "report": None,
        "existing_report_id": None,
        "usages": [],
    }
