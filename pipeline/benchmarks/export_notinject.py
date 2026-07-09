from __future__ import annotations

import argparse
import json
from pathlib import Path

NOTINJECT_DATASET = "leolee99/NotInject"
NOTINJECT_REVISION = "847ae76cf8fea5ed325429e569ae8cfef022d2e0"
NOTINJECT_SPLITS = ("NotInject_one", "NotInject_two", "NotInject_three")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export NotInject benign over-defense prompts as Valence JSONL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--matrix-output", type=Path)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface"))
    parser.add_argument("--revision", default=NOTINJECT_REVISION)
    args = parser.parse_args()
    from datasets import load_dataset

    dataset = load_dataset(
        NOTINJECT_DATASET,
        revision=args.revision,
        cache_dir=str(args.cache),
        download_mode="reuse_cache_if_exists",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    records = 0
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        for split in NOTINJECT_SPLITS:
            for row in dataset[split]:
                target.write(json.dumps({
                    "text": str(row["prompt"]),
                    "label": False,
                    "category": str(row["category"]),
                    "policy": "direct",
                    "suite": "over_defense",
                    "source": NOTINJECT_DATASET,
                    "sourceSplit": split,
                }, ensure_ascii=True, separators=(",", ":")) + "\n")
                records += 1
    if args.matrix_output is not None:
        args.matrix_output.parent.mkdir(parents=True, exist_ok=True)
        args.matrix_output.write_text(json.dumps([{
            "name": "notinject",
            "dataset": NOTINJECT_DATASET,
            "revision": args.revision,
            "license": "see dataset card",
            "policy": "direct",
            "suite": "over_defense",
            "testRecords": records,
            "testPositive": 0,
            "testNegative": records,
            "fixture": str(args.output),
        }], indent=2), encoding="utf-8")
    print(json.dumps({
        "dataset": NOTINJECT_DATASET,
        "revision": args.revision,
        "records": records,
        "output": str(args.output),
        "matrixOutput": None if args.matrix_output is None else str(args.matrix_output),
        "suite": "over_defense",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
