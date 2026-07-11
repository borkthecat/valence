from __future__ import annotations

import argparse
import gc
import json
import re
import sys
from pathlib import Path

BENCHMARKS = Path(__file__).resolve().parents[1] / "benchmarks"
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from injection_corpora import SPECS, fingerprint, load_corpus, policy_text


TARGETS = ("hse_llm", "cgoosen_combined")
MARKERS = re.compile(r"(?:ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?|system\s+prompt|hidden\s+(?:prompt|configuration)|jailbreak|bypass\s+(?:the\s+)?(?:rules|guardrails)|developer\s+message|reveal\s+.*?(?:secret|instruction))", re.IGNORECASE)
TAG = re.compile(r"</?(?:valence_source|valence_article|user_session)\b[^>]*>", re.IGNORECASE)


def benign_variation(text: str, variant: int) -> str:
    replacements = (
        "summarize the visible document",
        "follow the stated user task",
        "explain the public documentation",
        "provide a high-level safety overview",
        "continue with the requested analysis",
    )
    cleaned = TAG.sub("", text)
    cleaned = MARKERS.sub(replacements[variant % len(replacements)], cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned == text.strip():
        cleaned = f"{cleaned} Please keep the response limited to public information."
    return cleaned


def _round_robin(rows: list[tuple[str, bool]], count: int) -> list[tuple[str, bool]]:
    positives = [row for row in rows if row[1]]
    if not positives:
        raise ValueError("target corpus contains no positive training rows")
    return [positives[index % len(positives)] for index in range(count)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create train-only hard negatives and a mixed calibration manifest")
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--per-target", type=int, default=500)
    parser.add_argument("--anchors", type=int, default=450)
    args = parser.parse_args()
    if args.per_target <= 0 or args.anchors <= 0:
        raise ValueError("sample counts must be positive")
    # Variations are sourced only from target training rows, so target test hashes
    # are the relevant leakage boundary. Loading every corpus test split here can
    # exceed memory on the large pinned datasets without adding protection.
    test_hashes: set[bytes] = set()
    for target in TARGETS:
        corpus = load_corpus(args.cache, target)
        test_hashes.update(fingerprint(text) for text, _ in corpus.test)
        del corpus
        gc.collect()
    records: list[dict[str, object]] = []
    for target in TARGETS:
        corpus = load_corpus(args.cache, target)
        for index, (text, _) in enumerate(_round_robin(list(corpus.training), args.per_target)):
            generated = benign_variation(text, index)
            if fingerprint(generated) in test_hashes:
                raise ValueError("synthetic negative collides with a held-out test record")
            records.append({"text": policy_text(generated, corpus.spec.policy), "label": False, "source": target, "kind": "synthetic_hard_negative", "sourceFingerprint": fingerprint(text).hex()})
    anchor_specs = [spec for spec in SPECS if spec.name not in TARGETS]
    base, remainder = divmod(args.anchors, len(anchor_specs))
    for corpus_index, spec in enumerate(anchor_specs):
        corpus = load_corpus(args.cache, spec.name)
        count = base + (1 if corpus_index < remainder else 0)
        rows = sorted(corpus.training, key=lambda row: fingerprint(row[0]))
        negatives, positives = [row for row in rows if not row[1]], [row for row in rows if row[1]]
        if not negatives or not positives:
            raise ValueError(f"anchor corpus lacks both labels: {corpus.spec.name}")
        for index in range(count):
            text, label = (positives if index % 2 else negatives)[index // 2 % len(positives if index % 2 else negatives)]
            records.append({"text": policy_text(text, corpus.spec.policy), "label": label, "source": corpus.spec.name, "kind": "anchor", "sourceFingerprint": fingerprint(text).hex()})
        del corpus
        gc.collect()
    records.sort(key=lambda row: (str(row["kind"]), str(row["source"]), str(row["sourceFingerprint"])))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        for record in records:
            target.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
    manifest = {"records": len(records), "syntheticHardNegatives": sum(record["kind"] == "synthetic_hard_negative" for record in records), "anchors": sum(record["kind"] == "anchor" for record in records), "targets": list(TARGETS), "testLeakageChecked": True}
    args.manifest.parent.mkdir(parents=True, exist_ok=True); args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
