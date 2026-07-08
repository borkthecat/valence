from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

DATASET = "thebajajra/amazon-esci-english-small"
API = "https://datasets-server.huggingface.co/rows"
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
GRADES = {"E": 3.0, "S": 2.0, "C": 1.0, "I": 0.0}


def _fetch_rows(offset: int, length: int) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({
        "dataset": DATASET,
        "config": "default",
        "split": "test",
        "offset": offset,
        "length": length,
    })
    request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "Valence-ESCI-Evaluation"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return [item["row"] for item in payload["rows"]]


def _tokens(value: Any) -> set[str]:
    return set(TOKEN_PATTERN.findall(str(value or "").casefold()))


def _lexical_relevance(query: str, row: dict[str, Any]) -> float:
    query_tokens = _tokens(query)
    title_tokens = _tokens(row.get("product_title"))
    detail_tokens = _tokens(row.get("product_brand")) | _tokens(row.get("product_description"))
    if not query_tokens:
        return 0.0
    title_recall = len(query_tokens & title_tokens) / len(query_tokens)
    detail_recall = len(query_tokens & detail_tokens) / len(query_tokens)
    exact_phrase = float(query.casefold() in str(row.get("product_title") or "").casefold())
    return round(min(1.0, 0.75 * title_recall + 0.15 * detail_recall + 0.10 * exact_phrase), 4)


def _record(rows: list[dict[str, Any]]) -> dict[str, Any]:
    query = str(rows[0]["query"])
    profiles = []
    relevance: dict[str, float] = {}
    for row in rows:
        product_id = str(row["product_id"])
        profiles.append({
            "id": product_id,
            "age": 0,
            "anniversary": False,
            "channel": "direct",
            "colorway": "not-applicable",
            "era_year": 2026,
            "entity_type": "product",
            "title": str(row.get("product_title") or product_id)[:512],
            "description": str(row.get("product_description") or row.get("product_bullet_point") or "No description")[:4096],
            "attributes": {
                "query": query[:1024],
                "brand": str(row.get("product_brand") or "unknown")[:1024],
                "locale": str(row.get("product_locale") or "unknown")[:1024],
            },
            "source_relevance_score": _lexical_relevance(query, row),
        })
        relevance[product_id] = GRADES[str(row["esci_label"])]
    return {
        "context": {
            "target_channel": "direct",
            "authorized_channels": ["direct"],
            "target_colorway": "not-applicable",
            "target_era_year": 2026,
        },
        "profiles": profiles,
        "relevance": relevance,
        "metadata": {
            "dataset": "amazon-science/esci-data",
            "query_id": int(rows[0]["query_id"]),
            "query": query,
            "split": "test",
            "adapter": "valence-lexical-v1",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export held-out Amazon ESCI labels to Valence JSONL")
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 100 <= args.rows <= 100_000:
        raise ValueError("--rows must be between 100 and 100000")
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for offset in range(0, args.rows, 100):
        for row in _fetch_rows(offset, min(100, args.rows - offset)):
            groups[int(row["query_id"])].append(row)
    records = [_record(rows) for rows in groups.values() if 5 <= len(rows) <= 50 and max(GRADES[str(row["esci_label"])] for row in rows) > 0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"source_rows": args.rows, "evaluation_batches": len(records), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
