from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasets import load_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="ai4privacy/pii-masking-300k")
    parser.add_argument("--split", default="validation")
    parser.add_argument("--language", default="English")
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")

    dataset = load_dataset(args.dataset, split=args.split, streaming=True)
    written = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        for row in dataset:
            if args.language and row.get("language") != args.language:
                continue
            output.write(
                json.dumps(
                    {
                        "source_text": row["source_text"],
                        "privacy_mask": row["privacy_mask"],
                        "language": row.get("language"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            written += 1
            if written >= args.limit:
                break
    print(json.dumps({"dataset": args.dataset, "split": args.split, "records": written, "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
