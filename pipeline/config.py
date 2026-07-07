"""Centralized, cached settings loader for the Valence pipeline.

All environment-driven configuration is read here exactly once and memoized
with lru_cache, so hot loops never touch os.environ or reparse strings. Call
get_settings.cache_clear() in tests that mutate the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_AUTHORIZED_CHANNELS = "direct,brand-direct,certified-partner,boutique-authorized"


@dataclass(frozen=True, slots=True)
class Settings:
    target_era: int
    target_channel: str
    target_colorway: str
    authorized_channels: frozenset[str]
    max_payload_kb: int
    max_field_bytes: int
    proxy_host: str
    proxy_port: int
    gateway_api_key: str | None


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"environment variable {name} must be an integer, got {raw!r}") from exc


def _str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None and value.strip() != "" else default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    authorized_raw = _str("AUTHORIZED_CHANNELS", DEFAULT_AUTHORIZED_CHANNELS)
    authorized = frozenset(part.strip() for part in authorized_raw.split(",") if part.strip())
    target_channel = _str("TARGET_CHANNEL", "direct")
    gateway_key = os.environ.get("GATEWAY_API_KEY")
    return Settings(
        target_era=_int("TARGET_ERA", 1500),
        target_channel=target_channel,
        target_colorway=_str("TARGET_COLORWAY", "midnight-sapphire"),
        authorized_channels=authorized | {target_channel},
        max_payload_kb=_int("MAX_PAYLOAD_KB", 512),
        max_field_bytes=_int("MAX_FIELD_BYTES", 512),
        proxy_host=_str("PROXY_HOST", "localhost"),
        proxy_port=_int("GATEWAY_PORT", _int("PROXY_PORT", 8443)),
        gateway_api_key=gateway_key if gateway_key else None,
    )
