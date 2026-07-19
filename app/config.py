"""Environment/config loading. Reads .env from the project root."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
SKILL_PACKS_DIR = Path(__file__).resolve().parent / "skill_packs"
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")

# Cost guardrails: Flash-class everywhere except final report synthesis (Pro).
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_COMPOSER_MODEL = os.getenv("GEMINI_COMPOSER_MODEL", "gemini-2.5-pro")

# Storage: local JSON store by default; set MONGODB_URI to use MongoDB.
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "trend_agent")

# Vector memory: embedded local Qdrant by default (no Docker needed);
# set QDRANT_URL (+ optional QDRANT_API_KEY) to use a server.
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_PATH = str(DATA_DIR / "qdrant")

EMBED_MODEL = os.getenv("EMBED_MODEL", "models/gemini-embedding-001")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))

# Trend Radar (Phase 4): proactive scanning schedule (server-local time).
RADAR_ENABLED = os.getenv("RADAR_ENABLED", "true").lower() in ("1", "true", "yes")
SCAN_HOUR = int(os.getenv("SCAN_HOUR", "7"))  # daily scan at 07:00
DIGEST_WEEKDAY = os.getenv("DIGEST_WEEKDAY", "mon")  # weekly digest Monday...
DIGEST_HOUR = int(os.getenv("DIGEST_HOUR", "8"))  # ...at 08:00
MARKET_MAP_DAY = int(os.getenv("MARKET_MAP_DAY", "1"))  # monthly refresh on the 1st
ALERT_WEBHOOK = os.getenv("ALERT_WEBHOOK", "")  # optional: POST rising-trend alerts here


def get_api_key() -> str:
    """Return the Gemini API key or raise with a setup hint."""
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "No Gemini API key found. Copy .env.example to .env and set "
            "GOOGLE_API_KEY (or GEMINI_API_KEY)."
        )
    return key


def load_prompt(name: str) -> str:
    """Load a versioned prompt document from app/prompts/."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def load_brand() -> str:
    """Editable brand context (config/brand.md) — one of the three swap-for-any-company files."""
    path = PROJECT_ROOT / "config" / "brand.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def brand_prompt(name: str) -> str:
    """A prompt with the brand context appended (composer/audience/digest/ask)."""
    brand = load_brand()
    prompt = load_prompt(name)
    return f"{prompt}\n\n{brand}" if brand else prompt


def load_skill_pack(specialist: str) -> str:
    """Concatenate every markdown doc in app/skill_packs/<specialist>/.

    Dropping a new .md file into the folder upgrades that specialist with
    zero code change — that property is part of the Phase 1 contract.
    """
    folder = SKILL_PACKS_DIR / specialist
    if not folder.is_dir():
        return ""
    docs = sorted(folder.glob("*.md"))
    return "\n\n---\n\n".join(d.read_text(encoding="utf-8") for d in docs)
