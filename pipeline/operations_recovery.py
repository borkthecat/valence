"""Integrity-checked multi-store backup, restore, and replay drill."""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    databases: int
    backup_seconds: float
    restore_seconds: float
    integrity_verified: bool
    manifest_digest: str


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def backup_databases(sources: dict[str, Path], target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, source in sorted(sources.items()):
        destination = target / f"{name}.sqlite"
        with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
        with closing(sqlite3.connect(destination)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError(f"backup integrity failed: {name}")
        entries.append({"name": name, "file": destination.name, "sha256": _sha(destination)})
    payload = {"version": 1, "databases": entries}
    manifest = target / "manifest.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def restore_databases(manifest: Path, destinations: dict[str, Path]) -> None:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    for entry in payload["databases"]:
        name = entry["name"]
        source = manifest.parent / entry["file"]
        if _sha(source) != entry["sha256"] or name not in destinations:
            raise RuntimeError(f"backup manifest verification failed: {name}")
        destination = destinations[name]
        temporary = destination.with_suffix(destination.suffix + ".restore")
        with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst)
        with closing(sqlite3.connect(temporary)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError(f"restored integrity failed: {name}")
        os.replace(temporary, destination)


def run_recovery_drill(sources: dict[str, Path], drill_root: Path) -> RecoveryReport:
    started = time.perf_counter(); manifest = backup_databases(sources, drill_root / "backup")
    backup_seconds = time.perf_counter() - started
    destinations = {name: drill_root / "restore" / f"{name}.sqlite" for name in sources}
    (drill_root / "restore").mkdir(parents=True, exist_ok=True)
    started = time.perf_counter(); restore_databases(manifest, destinations)
    restore_seconds = time.perf_counter() - started
    return RecoveryReport(len(sources), backup_seconds, restore_seconds, True, _sha(manifest))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an integrity-checked local operations recovery drill")
    parser.add_argument("--database", action="append", required=True, help="name=path; may be repeated")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources: dict[str, Path] = {}
    for value in args.database:
        name, separator, path = value.partition("=")
        if not separator or not name or not Path(path).is_file():
            raise ValueError("each --database must be name=existing-path")
        sources[name] = Path(path)
    print(json.dumps(asdict(run_recovery_drill(sources, args.output)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
