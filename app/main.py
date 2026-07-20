"""Trend Research Agent API.

GET  /                 review UI (submit, read, approve/comment)
POST /analyze          JSON {text, images[{data, mime_type}]} (base64)
POST /analyze/form     multipart: text field + image file uploads
GET  /report/{id}      stored report (?format=markdown for raw markdown)
GET  /reports          recent report summaries
POST /report/{id}/review   approve/reject with comment
GET/PUT /buckets       editable audience bucket registry
GET/PUT /sources       editable radar source registry
POST /radar/scan       run a radar scan now; GET /radar/stats for history
POST /radar/digest     generate the digest now; GET /digest/latest to read it
GET  /alerts           rising-trend alerts
GET  /market-map       player profiles; POST /radar/market-map/refresh
GET  /costs            token spend by node + triage filter rate
POST /report/{id}/outcome  record real campaign results (the moat loop)
GET  /trends           trend lifecycles; GET /trends/{play} for one timeline
POST /ask              natural-language question over memory + market map
GET  /dashboard        trend timelines, market map, digest, alerts, ask box
GET  /analytics        aggregated chart data (verdict mix, plays, relevance, risk)
"""

import base64
import binascii
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.buckets import load_buckets, save_buckets
from app.config import PROJECT_ROOT, RADAR_ENABLED
from app.graph import graph, initial_state
from app.render import report_to_markdown
from app.schemas import (
    Alert,
    AnalyzeRequest,
    AnalyzeResponse,
    AskRequest,
    BucketRegistry,
    CampaignReportV3,
    ImagePayload,
    OutcomeRequest,
    ReportSummary,
    ReviewRequest,
    ScanStats,
    SourceRegistry,
    TrendTimeline,
    utcnow,
)
from app.storage import get_store, make_record, new_report_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("trend_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = None
    if RADAR_ENABLED:
        from app.radar.scheduler import build_scheduler

        sched = build_scheduler()
        sched.start()
    yield
    if sched is not None:
        sched.shutdown(wait=False)


app = FastAPI(
    title="Trend Research Agent",
    version="0.4.0",
    description="Campaign deconstruction + trend verdicts + audience fit, with a proactive trend radar.",
    lifespan=lifespan,
)

MAX_IMAGES = 10
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB per image


app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def review_ui():
    return FileResponse(PROJECT_ROOT / "static" / "index.html")


async def _run_analysis(text: str, images: list[ImagePayload], fmt: str):
    if not text.strip() and not images:
        raise HTTPException(status_code=400, detail="Provide text, images, or both.")

    started = time.perf_counter()
    report_id = new_report_id()
    try:
        state = await graph.ainvoke(initial_state(text, images, report_id))
    except RuntimeError as e:  # missing API key etc.
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:  # schema-invalid model output
        raise HTTPException(status_code=502, detail=str(e)) from e

    # Dedupe short-circuit: memory recognized this input — reuse the stored report.
    if state["existing_report_id"]:
        existing = await get_store().get(state["existing_report_id"])
        if existing is not None:
            logger.info("dedupe hit: %s reused (%.1fs)", existing["report_id"], time.perf_counter() - started)
            report = CampaignReportV3.model_validate(existing["report"])
            markdown = report_to_markdown(report)
            if fmt == "markdown":
                return PlainTextResponse(markdown, media_type="text/markdown")
            return AnalyzeResponse(
                report_id=existing["report_id"], report=report, markdown=markdown,
                usages=[], deduped=True,
            )
        # Memory points at a record the store no longer has — re-run without dedupe.
        logger.warning("dedupe hit on %s but record is missing; re-analyzing", state["existing_report_id"])
        state = await graph.ainvoke(initial_state(text, images, report_id, skip_dedupe=True))

    report: CampaignReportV3 = state["report"]
    usages = state["usages"]
    await get_store().save(make_record(report_id, text, images, report, usages))
    logger.info(
        "report %s done in %.1fs (%d images, %d model calls)",
        report_id, time.perf_counter() - started, len(images), len(usages),
    )

    markdown = report_to_markdown(report)
    if fmt == "markdown":
        return PlainTextResponse(markdown, media_type="text/markdown")
    return AnalyzeResponse(report_id=report_id, report=report, markdown=markdown, usages=usages)


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(body: AnalyzeRequest, format: str = "json"):
    for i, img in enumerate(body.images):
        try:
            raw = base64.b64decode(img.data, validate=True)
        except (binascii.Error, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"images[{i}].data is not valid base64") from e
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail=f"images[{i}] exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    return await _run_analysis(body.text, body.images, format)


@app.post("/analyze/form", response_model=AnalyzeResponse)
async def analyze_form(
    text: str = Form(default=""),
    images: list[UploadFile] = File(default=[]),
    format: str = "json",
):
    if len(images) > MAX_IMAGES:
        raise HTTPException(status_code=400, detail=f"At most {MAX_IMAGES} images.")
    payloads: list[ImagePayload] = []
    for upload in images:
        blob = await upload.read()
        if len(blob) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail=f"{upload.filename} exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        mime = upload.content_type or "image/png"
        if not mime.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"{upload.filename}: only image uploads are supported")
        payloads.append(ImagePayload(data=base64.b64encode(blob).decode("ascii"), mime_type=mime))
    return await _run_analysis(text, payloads, format)


@app.get("/report/{report_id}")
async def get_report(report_id: str, format: str = "json"):
    record = await get_store().get(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No report {report_id}")
    if format == "markdown":
        report = CampaignReportV3.model_validate(record["report"])
        return PlainTextResponse(report_to_markdown(report), media_type="text/markdown")
    return record


@app.post("/report/{report_id}/review")
async def review_report(report_id: str, body: ReviewRequest):
    ok = await get_store().update(
        report_id,
        {
            "status": body.decision,
            "review_comment": body.comment,
            "reviewed_at": utcnow().isoformat(),
        },
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"No report {report_id}")
    return {"report_id": report_id, "status": body.decision}


@app.get("/buckets", response_model=BucketRegistry)
async def get_buckets():
    return load_buckets()


@app.put("/buckets", response_model=BucketRegistry)
async def put_buckets(registry: BucketRegistry):
    if not registry.buckets:
        raise HTTPException(status_code=400, detail="Registry must contain at least one bucket.")
    ids = [b.id for b in registry.buckets]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=400, detail="Bucket ids must be unique.")
    save_buckets(registry)
    return registry


# --- Phase 4: Trend Radar ----------------------------------------------------


@app.get("/sources", response_model=SourceRegistry)
async def get_sources():
    from app.radar.sources import load_sources

    return load_sources()


@app.put("/sources", response_model=SourceRegistry)
async def put_sources(registry: SourceRegistry):
    from app.radar.sources import save_sources

    if not registry.sources:
        raise HTTPException(status_code=400, detail="Registry must contain at least one source.")
    ids = [s.id for s in registry.sources]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=400, detail="Source ids must be unique.")
    for s in registry.sources:
        if s.type == "rss" and not s.url:
            raise HTTPException(status_code=400, detail=f"Source '{s.id}': rss sources need a url.")
        if s.type == "gdelt" and not s.query:
            raise HTTPException(status_code=400, detail=f"Source '{s.id}': gdelt sources need a query.")
    save_sources(registry)
    return registry


@app.post("/radar/scan", response_model=ScanStats)
async def trigger_scan():
    from app.radar.scan import run_scan

    try:
        return await run_scan()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.get("/radar/stats", response_model=list[ScanStats])
async def radar_stats():
    from app.radar.scan import scan_history

    return scan_history()


@app.post("/radar/digest")
async def trigger_digest():
    from app.radar.digest import generate_digest

    return await generate_digest()


@app.get("/digest/latest")
async def digest_latest(format: str = "json"):
    from app.radar.digest import latest_digest

    record = latest_digest()
    if record is None:
        raise HTTPException(status_code=404, detail="No digest yet — POST /radar/digest to generate one.")
    if format == "markdown":
        return PlainTextResponse(record["markdown"], media_type="text/markdown")
    return record


@app.get("/digests", response_model=list[str])
async def digests():
    from app.radar.digest import list_digests

    return list_digests()


@app.get("/alerts", response_model=list[Alert])
async def alerts():
    from app.radar.alerts import list_alerts

    return list(reversed(list_alerts()))


@app.get("/market-map")
async def market_map():
    from app.radar.market_map import current_market_map

    record = current_market_map()
    if record is None:
        raise HTTPException(status_code=404, detail="No market map yet — POST /radar/market-map/refresh.")
    return record


@app.post("/radar/market-map/refresh")
async def market_map_refresh():
    from app.radar.market_map import refresh_market_map

    return await refresh_market_map()


# --- Phase 5: outcomes, lifecycles, ask, dashboard ---------------------------


@app.post("/report/{report_id}/outcome")
async def record_outcome(report_id: str, body: OutcomeRequest):
    """Manually record how a shipped recommendation performed; feeds back into memory."""
    from app.memory import get_memory

    ok = await get_store().update(
        report_id,
        {"outcome": body.model_dump(), "outcome_recorded_at": utcnow().isoformat()},
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"No report {report_id}")
    if body.performance:
        get_memory().set_outcome(report_id, body.performance)
    return {"report_id": report_id, "outcome": body.model_dump()}


@app.get("/trends", response_model=list[TrendTimeline])
async def trends():
    from app.lifecycle import timelines

    return timelines()


@app.get("/trends/{play:path}", response_model=TrendTimeline)
async def trend_timeline(play: str):
    from app.lifecycle import timeline_for

    t = timeline_for(play)
    if t is None:
        raise HTTPException(status_code=404, detail=f"No lifecycle data for play '{play}'")
    return t


@app.post("/ask")
async def ask_endpoint(body: AskRequest):
    from app.ask import ask

    try:
        answer, usage = await ask(body.question)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"question": body.question, **answer.model_dump(), "usage": usage.model_dump()}


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(PROJECT_ROOT / "static" / "dashboard.html")


@app.get("/analytics")
async def analytics():
    """Aggregated chart data for the dashboard — no model calls, nothing invented."""
    import json

    from app.analytics import build_analytics
    from app.lifecycle import TRENDS_PATH
    from app.memory import get_memory

    events: list[dict] = []
    if TRENDS_PATH.exists():
        try:
            events = json.loads(TRENDS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("analytics: could not read %s", TRENDS_PATH)

    return build_analytics(
        reports=await get_store().list(limit=1000),
        payloads=get_memory().all_payloads(),
        events=events,
    )


@app.get("/costs")
async def costs():
    """Token spend by node across stored reports + radar filter effectiveness."""
    from app.radar.scan import scan_history

    by_node: dict[str, dict] = {}
    reports = 0
    for record in await get_store().list(limit=1000):
        reports += 1
        for u in record.get("usages", []):
            node = u.get("node") or "?"
            slot = by_node.setdefault(node, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
            slot["calls"] += 1
            for k in ("input_tokens", "output_tokens", "total_tokens"):
                slot[k] += u.get(k) or 0

    history = scan_history()
    scanned_new = sum(s.new for s in history)
    analyzed = sum(s.analyzed for s in history)
    return {
        "reports": reports,
        "tokens_by_node": by_node,
        "total_tokens": sum(s["total_tokens"] for s in by_node.values()),
        "radar": {
            "runs": len(history),
            "new_items_scanned": scanned_new,
            "deep_analyzed": analyzed,
            "filter_rate": round(1 - analyzed / scanned_new, 3) if scanned_new else None,
            "target_filter_rate": 0.8,
        },
    }


@app.get("/reports", response_model=list[ReportSummary])
async def list_reports(limit: int = 50):
    records = await get_store().list(limit=limit)
    out = []
    for r in records:
        rep = r.get("report", {})
        out.append(
            ReportSummary(
                report_id=r["report_id"],
                created_at=r["created_at"],
                status=r.get("status", "completed"),
                primary_play=(rep.get("strategy") or {}).get("primary_play"),
                trend_verdict=(rep.get("trend") or {}).get("verdict"),
                audience_bucket=(rep.get("audience") or {}).get("bucket_name"),
                takeaway=(rep.get("core") or {}).get("takeaway_for_us"),
            )
        )
    return out
