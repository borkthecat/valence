from __future__ import annotations

import argparse
import json
from pathlib import Path

from injection_corpora import fingerprint, load_corpora


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the pinned fifteen-corpus injection benchmark")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface"))
    args = parser.parse_args()
    corpora = load_corpora(args.cache)
    args.output.mkdir(parents=True, exist_ok=True)
    test_hashes = {fingerprint(text) for corpus in corpora for text, _ in corpus.test}
    matrix = []
    for corpus in corpora:
        path = args.output / f"{corpus.spec.name}-test.jsonl"
        with path.open("w", encoding="utf-8", newline="\n") as target:
            for text, label in corpus.test:
                target.write(json.dumps({
                    "text": text,
                    "label": label,
                    "category": corpus.spec.name,
                    "policy": corpus.spec.policy,
                }, ensure_ascii=True, separators=(",", ":")) + "\n")
        matrix.append({
            "name": corpus.spec.name,
            "dataset": corpus.spec.dataset,
            "revision": corpus.spec.revision,
            "license": corpus.spec.license,
            "policy": corpus.spec.policy,
            "trainingRecords": sum(fingerprint(text) not in test_hashes for text, _ in corpus.training),
            "testRecords": len(corpus.test),
            "testPositive": sum(label for _, label in corpus.test),
            "testNegative": sum(not label for _, label in corpus.test),
            "fixture": str(path),
        })
    (args.output / "matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    print(json.dumps({"corpora": len(matrix), "testRecords": sum(item["testRecords"] for item in matrix)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
