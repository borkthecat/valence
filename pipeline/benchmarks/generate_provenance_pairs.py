from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any


CONTEXTS = (
    {
        "name": "user_literal_test",
        "tag": "user_session",
        "attributes": {"intent": "literal_test"},
        "policy": "direct",
        "label": False,
        "expectedAction": "process_literal",
    },
    {
        "name": "raw_web_source",
        "tag": "valence_source",
        "attributes": {"type": "web_scrape", "trust": "untrusted"},
        "policy": "indirect",
        "label": True,
        "expectedAction": "quarantine_source",
    },
    {
        "name": "retrieved_document",
        "tag": "valence_source",
        "attributes": {"type": "retrieved_document", "trust": "untrusted"},
        "policy": "indirect",
        "label": True,
        "expectedAction": "quarantine_source",
    },
    {
        "name": "compiled_article_quote",
        "tag": "valence_article",
        "attributes": {"status": "compiled", "role": "quoted_evidence"},
        "policy": "direct",
        "label": False,
        "expectedAction": "rank_with_citation",
    },
)


def _fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.casefold().split()).encode("utf-8")).hexdigest()


def render_envelope(payload: str, context: dict[str, Any]) -> str:
    attributes = " ".join(
        f'{key}="{html.escape(str(value), quote=True)}"'
        for key, value in sorted(context["attributes"].items())
    )
    tag = context["tag"]
    escaped = html.escape(payload, quote=False)
    return f"<{tag} {attributes}>\n{escaped}\n</{tag}>"


def _load_payloads(path: Path) -> list[dict[str, Any]]:
    payloads = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                raise ValueError(f"line {line_number} must contain an object with text")
            if row.get("label") is False:
                continue
            payloads.append(row)
    if not payloads:
        raise ValueError("input did not contain any attack payload records")
    return payloads


def generate_records(payloads: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    selected = payloads if limit is None else payloads[:limit]
    records = []
    for payload in selected:
        text = payload["text"]
        fingerprint = _fingerprint(text)
        for context in CONTEXTS:
            records.append({
                "text": render_envelope(text, context),
                "label": context["label"],
                "category": f"provenance:{context['name']}",
                "policy": context["policy"],
                "suite": "indirect_provenance",
                "provenance": {
                    "context": context["name"],
                    "sourceCategory": payload.get("category", "unknown"),
                    "baseFingerprint": fingerprint,
                },
                "expectedAction": context["expectedAction"],
            })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate provenance-aware prompt-injection contrastive pairs")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--matrix-output", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be positive")
    records = generate_records(_load_payloads(args.input), args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        for record in records:
            target.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
    if args.matrix_output is not None:
        args.matrix_output.parent.mkdir(parents=True, exist_ok=True)
        positives = sum(record["label"] for record in records)
        args.matrix_output.write_text(json.dumps([{
            "name": "provenance_contrastive",
            "dataset": str(args.input),
            "revision": "local-generated",
            "license": "derived-from-input",
            "policy": "indirect",
            "suite": "indirect_provenance",
            "testRecords": len(records),
            "testPositive": positives,
            "testNegative": len(records) - positives,
            "fixture": str(args.output),
        }], indent=2), encoding="utf-8")
    print(json.dumps({
        "records": len(records),
        "payloads": len(records) // len(CONTEXTS),
        "output": str(args.output),
        "matrixOutput": None if args.matrix_output is None else str(args.matrix_output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
