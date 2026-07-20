"""Backfill memory with collected campaigns.

Layout expected (one subfolder per campaign):

    campaigns/
      blinkit_match_day/
        text.md          (optional context/copy — .md or .txt)
        creative1.png    (any number of .png/.jpg/.jpeg/.webp)
      linkedin_viral_post/
        ...

Usage:
    .venv\\Scripts\\python -m scripts.backfill path\\to\\campaigns

Runs the full pipeline in-process (dedupe -> specialists -> composer -> memory),
so re-running is safe: already-ingested campaigns short-circuit as duplicates.
Requires GOOGLE_API_KEY in .env.
"""

import asyncio
import base64
import sys
from pathlib import Path

from app.graph import graph, initial_state
from app.schemas import ImagePayload
from app.storage import get_store, make_record, new_report_id

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def load_campaign(folder: Path) -> tuple[str, list[ImagePayload]]:
    text = ""
    for name in ("text.md", "text.txt"):
        f = folder / name
        if f.exists():
            text = f.read_text(encoding="utf-8")
            break
    images = [
        ImagePayload(data=base64.b64encode(p.read_bytes()).decode("ascii"), mime_type=_MIME[p.suffix.lower()])
        for p in sorted(folder.iterdir())
        if p.suffix.lower() in _MIME
    ]
    return text, images


async def run(root: Path) -> None:
    folders = [f for f in sorted(root.iterdir()) if f.is_dir()]
    if not folders:
        print(f"No campaign subfolders in {root}")
        return
    done = skipped = failed = 0
    for folder in folders:
        text, images = load_campaign(folder)
        if not text.strip() and not images:
            print(f"-- {folder.name}: empty, skipped")
            continue
        report_id = new_report_id()
        try:
            state = await graph.ainvoke(initial_state(text, images, report_id))
        except Exception as e:
            failed += 1
            print(f"!! {folder.name}: {e}")
            continue
        if state["existing_report_id"]:
            skipped += 1
            print(f"-- {folder.name}: duplicate of {state['existing_report_id']}, skipped")
            continue
        await get_store().save(make_record(report_id, text, images, state["report"], state["usages"]))
        done += 1
        print(f"OK {folder.name}: {report_id} ({state['report'].strategy.primary_play})")
    print(f"\nBackfill: {done} analyzed, {skipped} duplicates, {failed} failed.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"Not a folder: {root}")
        sys.exit(1)
    asyncio.run(run(root))
