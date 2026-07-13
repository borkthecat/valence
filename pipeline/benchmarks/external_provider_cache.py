from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any


class ExternalProviderCache:
    """Rate-limited SQLite evidence cache for domain-age, registry, and reputation providers."""

    def __init__(self, path: Path, *, minimum_interval_seconds: float = 0.5) -> None:
        if minimum_interval_seconds < 0:
            raise ValueError("minimum interval must be non-negative")
        self.path = path
        self.minimum_interval_seconds = minimum_interval_seconds
        # Providers may resolve a cached bootstrap document while populating a
        # cached domain result in the same thread.
        self._lock = threading.RLock()
        self._last_request = 0.0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS provider_cache (cache_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, expires_at REAL NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def lookup(self, provider: str, key: str, *, ttl_seconds: float, fetch: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        if not provider or not key or ttl_seconds <= 0:
            raise ValueError("provider, key, and positive TTL are required")
        cache_key = f"{provider}:{key}"
        with self._lock:
            with closing(self._connect()) as connection, connection:
                cached = connection.execute("SELECT value_json FROM provider_cache WHERE cache_key = ? AND expires_at > ?", (cache_key, time.time())).fetchone()
            if cached:
                return json.loads(cached[0])
            delay = self.minimum_interval_seconds - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            try:
                value = fetch()
                if not isinstance(value, dict):
                    raise ValueError("provider result must be an object")
            except Exception as error:
                value = {"status": "unknown", "error": type(error).__name__}
            self._last_request = time.monotonic()
            with closing(self._connect()) as connection, connection:
                connection.execute("INSERT OR REPLACE INTO provider_cache VALUES (?, ?, ?)", (cache_key, json.dumps(value, sort_keys=True), time.time() + ttl_seconds))
            return value
