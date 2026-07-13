import json
from pathlib import Path

from benchmarks.build_reproducibility_manifest import build_manifest, sha256_file


def test_manifest_covers_every_artifact_and_release_inputs(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    artifact = results / "result.json"
    artifact.write_text(json.dumps({"dataset": "owner/data", "revision": "abc"}), encoding="utf-8")
    source = tmp_path / "source.jsonl"
    source.write_text("{}\n", encoding="utf-8")
    specs = tmp_path / "specs.json"
    specs.write_text(json.dumps({"release_evidence": [{
        "artifact": artifact.relative_to(tmp_path).as_posix(),
        "command": "python benchmark.py",
        "inputs": [{"path": source.relative_to(tmp_path).as_posix(), "sha256": sha256_file(source)}],
        "split": {"seed": 1},
    }]}), encoding="utf-8")
    from benchmarks import build_reproducibility_manifest as module
    original = module.ROOT
    module.ROOT = tmp_path
    try:
        payload = build_manifest(results, specs)
    finally:
        module.ROOT = original
    assert payload["summary"]["release_ready"] is True
    assert payload["artifacts"][0]["dataset_revisions"] == [{"dataset": "owner/data", "revision": "abc"}]
