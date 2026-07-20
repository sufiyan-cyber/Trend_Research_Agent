"""Editable registries: scan sources and tracked market players."""

from pathlib import Path

from app.config import PROJECT_ROOT
from app.schemas import PlayerRegistry, SourceRegistry

SOURCES_PATH = PROJECT_ROOT / "config" / "sources.json"
PLAYERS_PATH = PROJECT_ROOT / "config" / "players.json"


def load_sources(path: Path | None = None) -> SourceRegistry:
    return SourceRegistry.model_validate_json((path or SOURCES_PATH).read_text(encoding="utf-8"))


def save_sources(registry: SourceRegistry, path: Path | None = None) -> None:
    p = path or SOURCES_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(registry.model_dump_json(indent=2), encoding="utf-8")


def load_players(path: Path | None = None) -> PlayerRegistry:
    return PlayerRegistry.model_validate_json((path or PLAYERS_PATH).read_text(encoding="utf-8"))
