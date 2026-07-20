"""Vector memory over analyzed campaigns (Qdrant).

Embedded local mode by default — persists under data/qdrant, survives
restarts, no Docker. Set QDRANT_URL to point at a server instead.

Two named vector spaces per point:
  "input"    — embedding of the normalized input text (dedupe)
  "analysis" — embedding of the finished analysis summary (seen-before recall)
Points may omit the "input" vector (image-only submissions).
"""

import logging
import uuid

from qdrant_client import QdrantClient, models

from app.config import EMBED_DIM, QDRANT_API_KEY, QDRANT_PATH, QDRANT_URL
from app.embeddings import embed_texts
from app.schemas import CampaignReportV1, Neighbor

logger = logging.getLogger("trend_agent")

COLLECTION = "campaign_analyses"

DUP_TEXT_THRESHOLD = 0.95
RECALL_THRESHOLD = 0.55
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid5 namespace for point ids


def analysis_summary_text(report: CampaignReportV1) -> str:
    """Canonical descriptor embedded into the 'analysis' space."""
    s, h, c = report.strategy, report.hook_copy, report.core
    return (
        f"Play: {s.primary_play}" + (f" + {s.secondary_play}" if s.secondary_play else "") + ". "
        f"Idea: {c.campaign_idea} "
        f"Hook: {h.hook_quote} ({', '.join(h.mechanics)}). "
        f"Emotion: {h.dominant_emotion}. "
        f"Execution: {c.how_it_was_run} "
        f"Visual: {report.visual.production_signal}"
    )


class MemoryIndex:
    def __init__(self, path: str | None = None, url: str | None = None, api_key: str | None = None):
        if url:
            self.client = QdrantClient(url=url, api_key=api_key or None)
        else:
            self.client = QdrantClient(path=path or QDRANT_PATH)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if not self.client.collection_exists(COLLECTION):
            self.client.create_collection(
                COLLECTION,
                vectors_config={
                    "input": models.VectorParams(size=EMBED_DIM, distance=models.Distance.COSINE),
                    "analysis": models.VectorParams(size=EMBED_DIM, distance=models.Distance.COSINE),
                },
            )
            self.client.create_payload_index(COLLECTION, "image_hashes", models.PayloadSchemaType.KEYWORD)
            self.client.create_payload_index(COLLECTION, "primary_play", models.PayloadSchemaType.KEYWORD)
            self.client.create_payload_index(COLLECTION, "created_at", models.PayloadSchemaType.DATETIME)

    # --- write ---------------------------------------------------------------

    async def index_report(
        self,
        report_id: str,
        created_at: str,
        report: CampaignReportV1,
        input_text: str,
        image_hashes: list[str],
        source: str = "user",
        extra_payload: dict | None = None,
    ) -> None:
        from app.palette import palette_family

        summary = analysis_summary_text(report)
        texts = [summary]
        has_input_text = bool(input_text.strip())
        if has_input_text:
            texts.append(input_text.strip().lower())
        embedded = await embed_texts(texts)

        vectors: dict = {"analysis": embedded[0]}
        if has_input_text:
            vectors["input"] = embedded[1]

        payload = {
            "report_id": report_id,
            "created_at": created_at,
            "summary": summary,
            "primary_play": report.strategy.primary_play,
            "secondary_play": report.strategy.secondary_play,
            "emotion": report.hook_copy.dominant_emotion,
            "palette_family": palette_family(report.palette),
            "image_hashes": image_hashes,
            "input_text": input_text,
            "source": source,
            **(extra_payload or {}),
        }
        self.client.upsert(
            COLLECTION,
            [models.PointStruct(id=str(uuid.uuid5(_NS, report_id)), vector=vectors, payload=payload)],
        )
        logger.info("memory: indexed %s (%s)", report_id, payload["primary_play"])

    # --- read ----------------------------------------------------------------

    async def find_duplicate(self, input_text: str, image_hashes: list[str]) -> dict | None:
        """Exact image-hash overlap, else near-identical input text."""
        if image_hashes:
            hits, _ = self.client.scroll(
                COLLECTION,
                scroll_filter=models.Filter(
                    must=[models.FieldCondition(key="image_hashes", match=models.MatchAny(any=image_hashes))]
                ),
                limit=1,
                with_payload=True,
            )
            if hits:
                return hits[0].payload

        text = input_text.strip().lower()
        if len(text) > 20:
            vector = (await embed_texts([text]))[0]
            res = self.client.query_points(
                COLLECTION, query=vector, using="input", limit=1, with_payload=True,
                score_threshold=DUP_TEXT_THRESHOLD,
            )
            if res.points:
                return res.points[0].payload
        return None

    async def find_similar(
        self,
        query_text: str,
        k: int = 4,
        exclude_report_id: str | None = None,
        min_score: float | None = None,
    ) -> list[Neighbor]:
        """Top-k past analyses resembling this campaign descriptor."""
        if self.count() == 0 or not query_text.strip():
            return []
        vector = (await embed_texts([query_text]))[0]
        flt = None
        if exclude_report_id:
            flt = models.Filter(
                must_not=[models.FieldCondition(key="report_id", match=models.MatchValue(value=exclude_report_id))]
            )
        res = self.client.query_points(
            COLLECTION, query=vector, using="analysis", limit=k, with_payload=True,
            score_threshold=RECALL_THRESHOLD if min_score is None else min_score, query_filter=flt,
        )
        return [
            Neighbor(
                report_id=p.payload["report_id"],
                analyzed_at=p.payload["created_at"],
                similarity=round(p.score, 3),
                primary_play=p.payload.get("primary_play", ""),
                summary=p.payload.get("summary", ""),
            )
            for p in res.points
        ]

    def play_frequency(self, play: str, days: int = 30) -> dict:
        """Are we seeing this pattern more often lately? (memory half of the trend check)"""
        from datetime import timedelta

        from app.schemas import utcnow

        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        play_cond = models.FieldCondition(key="primary_play", match=models.MatchValue(value=play))
        recent = self.client.count(
            COLLECTION,
            count_filter=models.Filter(
                must=[play_cond, models.FieldCondition(key="created_at", range=models.DatetimeRange(gte=cutoff))]
            ),
        ).count
        total = self.client.count(COLLECTION, count_filter=models.Filter(must=[play_cond])).count
        return {
            "play": play,
            "window_days": days,
            "recent": recent,
            "prior": total - recent,
            "total_analyses_in_memory": self.count(),
        }

    def set_outcome(self, report_id: str, performance: str) -> None:
        """Attach a real-world outcome rating to a stored analysis — the moat loop."""
        self.client.set_payload(
            COLLECTION,
            payload={"outcome_performance": performance},
            points=[str(uuid.uuid5(_NS, report_id))],
        )

    def outcome_summary(self) -> list[dict]:
        """Plays that actually performed for us, from manually recorded outcomes."""
        from collections import Counter

        rated = [p for p in self.all_payloads() if p.get("outcome_performance") in ("strong", "moderate")]
        plays = Counter(p.get("primary_play", "?") for p in rated)
        return [
            {"play": play, "proven_campaigns": n,
             "examples": [p["report_id"] for p in rated if p.get("primary_play") == play][:3]}
            for play, n in plays.most_common(5)
        ]

    def recent_payloads(self, days: int = 7, limit: int = 200) -> list[dict]:
        """Payloads of analyses from the last N days (digest/lifecycle fuel)."""
        from datetime import timedelta

        from app.schemas import utcnow

        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        hits, _ = self.client.scroll(
            COLLECTION,
            scroll_filter=models.Filter(
                must=[models.FieldCondition(key="created_at", range=models.DatetimeRange(gte=cutoff))]
            ),
            limit=limit,
            with_payload=True,
        )
        return sorted((h.payload for h in hits), key=lambda p: p.get("created_at", ""), reverse=True)

    def all_payloads(self, limit: int = 2000) -> list[dict]:
        """Every stored payload (market map / lifecycle building; fine at this scale)."""
        out: list[dict] = []
        offset = None
        while True:
            hits, offset = self.client.scroll(COLLECTION, limit=256, offset=offset, with_payload=True)
            out.extend(h.payload for h in hits)
            if offset is None or len(out) >= limit:
                break
        return out

    def count(self) -> int:
        return self.client.count(COLLECTION).count

    def close(self) -> None:
        self.client.close()


_memory: MemoryIndex | None = None


def get_memory() -> MemoryIndex:
    global _memory
    if _memory is None:
        _memory = MemoryIndex(url=QDRANT_URL or None, api_key=QDRANT_API_KEY or None)
    return _memory
