from __future__ import annotations

import argparse
import ast
import json
import urllib.parse
import urllib.request
from pathlib import Path

DATASET = "gretelai/gretel-pii-masking-en-v1"
API = "https://datasets-server.huggingface.co/rows"


def _spans(text: str, entities: str) -> list[dict[str, int | str]]:
    parsed = ast.literal_eval(entities)
    spans: list[dict[str, int | str]] = []
    for item in parsed:
        value = str(item["entity"])
        label = str(item["types"][0]).upper()
        start = 0
        while value and (index := text.find(value, start)) >= 0:
            spans.append({"start": index, "end": index + len(value), "label": label})
            start = index + len(value)
    return spans


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Gretel PII labels to Valence JSONL")
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.rows <= 60_000:
        raise ValueError("--rows must be between 1 and 60000")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for offset in range(0, args.rows, 100):
            query = urllib.parse.urlencode({
                "dataset": DATASET,
                "config": "default",
                "split": "train",
                "offset": offset,
                "length": min(100, args.rows - offset),
            })
            request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "Valence-PII-Evaluation"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            for item in payload["rows"]:
                row = item["row"]
                text = str(row["text"])
                handle.write(json.dumps({
                    "text": text,
                    "entities": _spans(text, str(row["entities"])),
                    "source": DATASET,
                    "uid": row["uid"],
                }, ensure_ascii=False, separators=(",", ":")) + "\n")
                written += 1
    print(json.dumps({"records": written, "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
