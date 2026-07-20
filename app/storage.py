"""Report persistence behind one interface (save / get / list / update).

Backends, selected via .env (STORE_BACKEND or auto-detected):
  local    — JSON files under data/reports (default; zero infra, survives restarts)
  mongo    — MongoDB via MONGODB_URI (free Atlas tier works)
  firebase — Firestore via FIREBASE_CREDENTIALS (service-account JSON; free Spark tier)

Input images are stored once as content-addressed blobs under data/blobs
(sha256 names double as exact-dupe keys for Phase 2).
"""

import base64
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Protocol

from app.config import (
    DATA_DIR,
    FIREBASE_CREDENTIALS,
    FIREBASE_PROJECT_ID,
    MONGODB_DB,
    MONGODB_URI,
    STORE_BACKEND,
)
from app.schemas import ImagePayload, utcnow

REPORTS_DIR = DATA_DIR / "reports"
BLOBS_DIR = DATA_DIR / "blobs"

_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


def image_hashes_of(images: list[ImagePayload]) -> list[str]:
    """sha256 of each image's bytes — exact-duplicate keys for memory."""
    return [hashlib.sha256(base64.b64decode(img.data)).hexdigest() for img in images]


def save_blobs(images: list[ImagePayload]) -> list[dict]:
    """Store images content-addressed; return [{sha256, mime_type, path}]."""
    BLOBS_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for img in images:
        raw = base64.b64decode(img.data)
        digest = hashlib.sha256(raw).hexdigest()
        path = BLOBS_DIR / f"{digest}{_EXT.get(img.mime_type, '.bin')}"
        if not path.exists():
            path.write_bytes(raw)
        out.append({"sha256": digest, "mime_type": img.mime_type, "path": str(path)})
    return out


class ReportStore(Protocol):
    async def save(self, record: dict) -> None: ...
    async def get(self, report_id: str) -> dict | None: ...
    async def list(self, limit: int = 50) -> list[dict]: ...
    async def update(self, report_id: str, fields: dict) -> bool: ...


class LocalJsonStore:
    """One JSON file per report. Atomic writes; fine for hundreds of reports."""

    def __init__(self, root: Path | None = None):
        self.root = root or REPORTS_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, report_id: str) -> Path:
        return self.root / f"{report_id}.json"

    async def save(self, record: dict) -> None:
        path = self._path(record["report_id"])
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, default=str)
        os.replace(tmp, path)

    async def get(self, report_id: str) -> dict | None:
        path = self._path(report_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    async def list(self, limit: int = 50) -> list[dict]:
        records = []
        for path in self.root.glob("*.json"):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return records[:limit]

    async def update(self, report_id: str, fields: dict) -> bool:
        record = await self.get(report_id)
        if record is None:
            return False
        record.update(fields)
        await self.save(record)
        return True


class MongoStore:
    """MongoDB adapter (pymongo async API)."""

    def __init__(self, uri: str, db_name: str):
        from pymongo import AsyncMongoClient

        self.client = AsyncMongoClient(uri)
        self.col = self.client[db_name]["reports"]

    async def save(self, record: dict) -> None:
        await self.col.replace_one({"report_id": record["report_id"]}, record, upsert=True)

    async def get(self, report_id: str) -> dict | None:
        doc = await self.col.find_one({"report_id": report_id}, {"_id": 0})
        return doc

    async def list(self, limit: int = 50) -> list[dict]:
        cursor = self.col.find({}, {"_id": 0}).sort("created_at", -1).limit(limit)
        return [doc async for doc in cursor]

    async def update(self, report_id: str, fields: dict) -> bool:
        res = await self.col.update_one({"report_id": report_id}, {"$set": fields})
        return res.matched_count > 0


class FirestoreStore:
    """Firebase Firestore adapter (google-cloud-firestore async client)."""

    def __init__(self, credentials_path: str, project_id: str = ""):
        from google.cloud import firestore
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            credentials_path, scopes=["https://www.googleapis.com/auth/datastore"]
        )
        client = firestore.AsyncClient(project=project_id or creds.project_id, credentials=creds)
        self.col = client.collection("reports")

    async def save(self, record: dict) -> None:
        await self.col.document(record["report_id"]).set(record)

    async def get(self, report_id: str) -> dict | None:
        doc = await self.col.document(report_id).get()
        return doc.to_dict() if doc.exists else None

    async def list(self, limit: int = 50) -> list[dict]:
        from google.cloud import firestore

        query = self.col.order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit)
        return [doc.to_dict() async for doc in query.stream()]

    async def update(self, report_id: str, fields: dict) -> bool:
        from google.api_core.exceptions import NotFound

        try:
            await self.col.document(report_id).update(fields)
            return True
        except NotFound:
            return False


_store: ReportStore | None = None


def _build_store() -> ReportStore:
    backend = STORE_BACKEND
    if backend == "auto":
        backend = "mongo" if MONGODB_URI else ("firebase" if FIREBASE_CREDENTIALS else "local")
    if backend == "mongo":
        return MongoStore(MONGODB_URI, MONGODB_DB)
    if backend == "firebase":
        return FirestoreStore(FIREBASE_CREDENTIALS, FIREBASE_PROJECT_ID)
    return LocalJsonStore()


def get_store() -> ReportStore:
    global _store
    if _store is None:
        _store = _build_store()
    return _store


def new_report_id() -> str:
    return f"{utcnow():%Y%m%d}-{uuid.uuid4().hex[:10]}"


def make_record(
    report_id: str,
    text: str,
    images: list[ImagePayload],
    report: Any,
    usages: list[Any],
) -> dict:
    return {
        "report_id": report_id,
        "created_at": utcnow().isoformat(),
        "status": "completed",
        "input": {"text": text, "images": save_blobs(images)},
        "report": report.model_dump(),
        "usages": [u.model_dump() for u in usages],
    }
