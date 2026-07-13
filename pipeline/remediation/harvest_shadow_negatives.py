from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except ImportError:  # Optional transformer workflow.
    torch = None  # type: ignore[assignment]
    AutoModelForSequenceClassification = None  # type: ignore[assignment]
    AutoTokenizer = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1] / "benchmarks"
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from injection_corpora import fingerprint, load_corpus, policy_text

TARGETS = ("hse_llm", "cgoosen_combined")
EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"\+?\d[\d ()-]{6,}\d")


def redact_pii(text: str) -> str:
    return PHONE.sub("[REDACTED_PHONE]", EMAIL.sub("[REDACTED_EMAIL]", text))


def _embed(model: object, tokenizer: object, texts: list[str], device: torch.device, batch_size: int) -> np.ndarray:
    vectors = []
    for start in range(0, len(texts), batch_size):
        encoded = tokenizer(texts[start:start + batch_size], padding=True, truncation=True, max_length=256, return_tensors="pt")
        batch = {key: value.to(device) for key, value in encoded.items()}
        with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            vectors.append(model(**batch, output_hidden_states=True).hidden_states[-1][:, 0, :].float().cpu().numpy())
    result = np.concatenate(vectors); return result / np.linalg.norm(result, axis=1, keepdims=True).clip(min=1e-12)


def main() -> int:
    if torch is None or AutoTokenizer is None or AutoModelForSequenceClassification is None:
        raise RuntimeError("Install optional dependencies with: pip install -r requirements-transformer.txt")
    parser = argparse.ArgumentParser(description="Harvest trusted benign high-similarity telemetry for expert-data audit")
    parser.add_argument("--telemetry", type=Path, required=True); parser.add_argument("--model", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface")); parser.add_argument("--minimum-similarity", type=float, default=0.85); parser.add_argument("--anchor-limit", type=int, default=500); parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    if not 0 < args.minimum_similarity <= 1: raise ValueError("minimum similarity must be in (0, 1]")
    telemetry = [json.loads(line) for line in args.telemetry.read_text(encoding="utf-8").splitlines() if line.strip()]
    candidates = [row for row in telemetry if row.get("source") in TARGETS and row.get("label") is False and row.get("trusted_source") is True and isinstance(row.get("text"), str)]
    if not candidates: raise ValueError("no trusted benign target telemetry records")
    if not torch.cuda.is_available(): raise RuntimeError("CUDA is required for embedding harvest")
    device = torch.device("cuda"); tokenizer = AutoTokenizer.from_pretrained(args.model); model = AutoModelForSequenceClassification.from_pretrained(args.model, dtype=torch.float16).to(device).eval(); selected = []
    for source in TARGETS:
        corpus = load_corpus(args.cache, source); anchors = [policy_text(text, corpus.spec.policy) for text, label in corpus.training if label][:args.anchor_limit]
        source_rows = [row for row in candidates if row["source"] == source]
        if not anchors or not source_rows: continue
        texts = [redact_pii(str(row["text"])) for row in source_rows]; scores = _embed(model, tokenizer, texts, device, args.batch_size) @ _embed(model, tokenizer, anchors, device, args.batch_size).T
        for row, text, similarity in zip(source_rows, texts, scores.max(axis=1), strict=True):
            if similarity >= args.minimum_similarity: selected.append({"record_id": str(row.get("request_id") or fingerprint(text).hex()), "source": source, "label": False, "text": text, "similarity": float(similarity), "trusted_source": True})
    selected.sort(key=lambda row: (-float(row["similarity"]), str(row["record_id"]))); args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        for row in selected: target.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
    print(json.dumps({"candidates": len(candidates), "selected": len(selected), "minimumSimilarity": args.minimum_similarity})); return 0


if __name__ == "__main__": raise SystemExit(main())
