from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from datasets import load_dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1] / "benchmarks"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from injection_corpora import fingerprint, load_corpus, policy_text
from moe_guard import EXPERT_SOURCES


DATASET = "axiotic/ogma-prompt-injection-benign"
REVISION = "089327b0977e1296e4992d9b83a5248d1616edd4"
LICENSE = "Apache-2.0"


def _embeddings(model: object, tokenizer: object, texts: list[str], device: torch.device, batch_size: int) -> np.ndarray:
    chunks = []
    for start in range(0, len(texts), batch_size):
        encoded = tokenizer(texts[start:start + batch_size], padding=True, truncation=True, max_length=256, return_tensors="pt")
        batch = {name: value.to(device) for name, value in encoded.items()}
        with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            chunks.append(model(**batch, output_hidden_states=True).hidden_states[-1][:, 0, :].float().cpu().numpy())
    result = np.concatenate(chunks)
    return result / np.linalg.norm(result, axis=1, keepdims=True).clip(min=1e-12)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import verified public benign records with source, license, and overlap controls")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface"))
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--minimum-similarity", type=float, default=0.85)
    parser.add_argument("--limit-per-source", type=int, default=500)
    parser.add_argument("--anchor-limit", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--dataset", default=DATASET)
    parser.add_argument("--revision", default=REVISION)
    parser.add_argument("--license", default=LICENSE)
    parser.add_argument("--text-field", default="text")
    parser.add_argument("--label-field", default="label")
    parser.add_argument("--benign-value", default="0")
    parser.add_argument("--candidate-limit", type=int, default=0, help="deterministic pre-embedding cap; zero keeps all candidates")
    args = parser.parse_args()
    if not 0 < args.minimum_similarity <= 1 or args.limit_per_source <= 0:
        raise ValueError("invalid selection limits")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for similarity selection")

    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    held_out = {fingerprint(json.loads(line)["text"]) for corpus in matrix for line in Path(corpus["fixture"]).read_text(encoding="utf-8").splitlines() if line.strip()}
    dataset = load_dataset(args.dataset, revision=args.revision, cache_dir=str(args.cache), download_mode="reuse_cache_if_exists")
    rows = [str(row[args.text_field]).strip() for split in dataset.values() for row in split if str(row[args.label_field]) == args.benign_value and str(row[args.text_field]).strip()]
    candidates = sorted({text for text in rows if fingerprint(text) not in held_out}, key=fingerprint)
    if args.candidate_limit:
        candidates = candidates[:args.candidate_limit]
    device = torch.device("cuda")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, dtype=torch.float16).to(device).eval()
    candidate_vectors = _embeddings(model, tokenizer, candidates, device, args.batch_size)
    selected = []
    for source in sorted(EXPERT_SOURCES):
        corpus = load_corpus(args.cache, source)
        anchors = [policy_text(text, corpus.spec.policy) for text, label in corpus.training if label][:args.anchor_limit]
        if not anchors:
            continue
        scores = candidate_vectors @ _embeddings(model, tokenizer, anchors, device, args.batch_size).T
        ranked = sorted(enumerate(scores.max(axis=1).tolist()), key=lambda item: (-item[1], fingerprint(candidates[item[0]])))
        for index, similarity in ranked:
            if similarity < args.minimum_similarity or sum(row["source"] == source for row in selected) >= args.limit_per_source:
                continue
            text = candidates[index]
            selected.append({"record_id": f"{args.dataset}@{args.revision}:{fingerprint(text).hex()}", "source": source, "label": False, "text": text, "similarity": float(similarity), "provenance": {"dataset": args.dataset, "revision": args.revision, "license": args.license, "originalLabel": args.benign_value}})
    selected.sort(key=lambda row: (row["source"], -row["similarity"], row["record_id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        for row in selected:
            target.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
    print(json.dumps({"dataset": args.dataset, "license": args.license, "heldOutExcluded": len(held_out), "candidates": len(candidates), "selected": len(selected)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
