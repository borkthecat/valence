from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EXPERT_SOURCES = frozenset({"hse_llm", "cgoosen_combined", "cgoosen_guard", "jcanode", "smooth_3"})


def route_source(source_id: str | None, registry: dict[str, Any]) -> str:
    if source_id is not None and source_id in registry.get("experts", {}):
        return "expert"
    return "global"


def load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("experts"), dict):
        raise ValueError("invalid expert registry")
    return payload
