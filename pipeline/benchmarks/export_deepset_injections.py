from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

DATASET = "deepset/prompt-injections"
API = "https://datasets-server.huggingface.co/rows"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export deepset injection labels to PINT-compatible JSONL")
    parser.add_argument("--split", choices=("train", "test"), default="test")
    parser.add_argument("--rows", type=int, default=200)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.rows <= 1000:
        raise ValueError("--rows must be between 1 and 1000")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for offset in range(0, args.rows, 100):
            query = urllib.parse.urlencode({
                "dataset": DATASET,
                "config": "default",
                "split": args.split,
                "offset": offset,
                "length": min(100, args.rows - offset),
            })
            request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "Valence-Injection-Evaluation"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            for item in payload["rows"]:
                row = item["row"]
                hostile = bool(row["label"])
                handle.write(json.dumps({
                    "text": str(row["text"]),
                    "category": "prompt_injection" if hostile else "hard_negatives",
                    "label": hostile,
                    "source": DATASET,
                    "split": args.split,
                }, ensure_ascii=False, separators=(",", ":")) + "\n")
                written += 1
    print(json.dumps({"records": written, "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
