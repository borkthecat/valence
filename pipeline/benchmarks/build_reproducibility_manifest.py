"""Build and validate deterministic provenance for checked-in benchmark artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".md", ".txt", ".yaml", ".yml"}


def repository_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in REPOSITORY_TEXT_SUFFIXES:
        return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return data


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_repository_file(path: Path) -> str:
    return hashlib.sha256(repository_bytes(path)).hexdigest()


def sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(child.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(sha256_file(child).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def artifact_commit(path: Path) -> str:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", str(path.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "uncommitted"


def dataset_revisions(value: Any) -> list[dict[str, str]]:
    found: set[tuple[str, str]] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            dataset = node.get("dataset")
            revision = node.get("revision")
            if isinstance(dataset, str) and isinstance(revision, str):
                found.add((dataset, revision))
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return [{"dataset": dataset, "revision": revision} for dataset, revision in sorted(found)]


def input_record(raw: dict[str, Any]) -> dict[str, Any]:
    path = ROOT / raw["path"]
    if not path.exists():
        return {**raw, "sha256": raw.get("sha256", "unavailable")}
    relative_parts = path.relative_to(ROOT).parts
    repository_input = (
        path.is_file()
        and path.suffix.lower() in REPOSITORY_TEXT_SUFFIXES
        and relative_parts[:2] == ("gateway", "benchmarks")
    )
    observed = sha256_tree(path) if path.is_dir() else sha256_repository_file(path) if repository_input else sha256_file(path)
    expected = raw.get("sha256")
    if expected is not None and expected != observed:
        raise ValueError(f"input hash mismatch for {raw['path']}: {observed} != {expected}")
    return {**raw, "sha256": observed}


def build_manifest(results_dir: Path, specs_path: Path) -> dict[str, Any]:
    specs_payload = json.loads(specs_path.read_text(encoding="utf-8"))
    specs = {item["artifact"]: item for item in specs_payload["release_evidence"]}
    artifacts = []
    for path in sorted(item for item in results_dir.iterdir() if item.is_file()):
        relative = path.relative_to(ROOT).as_posix()
        spec = specs.get(relative)
        parsed = json.loads(path.read_text(encoding="utf-8")) if path.suffix == ".json" else None
        inputs = [input_record(item) for item in spec.get("inputs", [])] if spec else []
        complete = bool(
            spec
            and spec.get("command")
            and spec.get("split")
            and inputs
            and all(item["sha256"] != "unavailable" for item in inputs)
        )
        artifacts.append({
            "artifact": relative,
            "artifact_sha256": sha256_repository_file(path),
            "artifact_bytes": len(repository_bytes(path)),
            "artifact_commit": artifact_commit(path),
            "release_evidence": spec is not None,
            "reproducibility_status": "complete" if complete else "archived_incomplete",
            "command": spec.get("command") if spec else None,
            "inputs": inputs,
            "split": spec.get("split") if spec else None,
            "dataset_revisions": dataset_revisions(parsed) if parsed is not None else [],
        })
    missing = sorted(set(specs) - {item["artifact"] for item in artifacts})
    release_incomplete = [item["artifact"] for item in artifacts if item["release_evidence"] and item["reproducibility_status"] != "complete"]
    return {
        "schema_version": "1.0",
        "results_directory": results_dir.relative_to(ROOT).as_posix(),
        "artifacts": artifacts,
        "summary": {
            "artifacts": len(artifacts),
            "release_evidence": len(specs),
            "release_evidence_complete": len(specs) - len(release_incomplete) - len(missing),
            "historical_archival": sum(not item["release_evidence"] for item in artifacts),
            "missing_release_artifacts": missing,
            "incomplete_release_artifacts": release_incomplete,
            "release_ready": not missing and not release_incomplete,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=ROOT / "gateway/benchmarks/results")
    parser.add_argument("--specs", type=Path, default=ROOT / "gateway/benchmarks/reproduction-specs.json")
    parser.add_argument("--output", type=Path, default=ROOT / "gateway/benchmarks/reproducibility-manifest.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = build_manifest(args.results_dir.resolve(), args.specs.resolve())
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            print("reproducibility manifest is stale")
            return 1
    else:
        args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps(payload["summary"], sort_keys=True))
    return 0 if payload["summary"]["release_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
