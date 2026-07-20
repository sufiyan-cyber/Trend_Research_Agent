"""Audience bucket registry — an editable table, stored as tracked config.

Edit config/buckets.json directly or via PUT /buckets; no code change needed
to add/remove/reword audiences.
"""

from pathlib import Path

from app.config import PROJECT_ROOT
from app.schemas import BucketRegistry

BUCKETS_PATH = PROJECT_ROOT / "config" / "buckets.json"


def load_buckets(path: Path | None = None) -> BucketRegistry:
    p = path or BUCKETS_PATH
    return BucketRegistry.model_validate_json(p.read_text(encoding="utf-8"))


def save_buckets(registry: BucketRegistry, path: Path | None = None) -> None:
    p = path or BUCKETS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
