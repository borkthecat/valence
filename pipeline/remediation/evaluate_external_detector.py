from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1] / "benchmarks"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from evaluate_transformer_guard import _metrics
from injection_corpora import policy_text
from train_text_experts import _rows, _threshold


MODEL_ID = "protectai/deberta-v3-base-prompt-injection-v2"


def _scores(model: object, tokenizer: object, texts: list[str], device: torch.device, batch_size: int) -> list[float]:
    output = []
    for start in range(0, len(texts), batch_size):
        encoded = tokenizer(texts[start:start + batch_size], padding=True, truncation=True, max_length=512, return_tensors="pt")
        batch = {name: value.to(device) for name, value in encoded.items()}
        with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            output.extend(torch.softmax(model(**batch).logits.float(), dim=-1)[:, 1].cpu().tolist())
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate an external detector on a source-local split and evaluate its held-out fixture")
    parser.add_argument("--source", required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_ID, dtype=torch.float16 if device.type == "cuda" else torch.float32).to(device).eval()
    _, calibration = _rows(args.source, args.cache, 2000)
    calibration_scores = _scores(model, tokenizer, [text for text, _ in calibration], device, args.batch_size)
    threshold, calibrated = _threshold(calibration_scores, [label for _, label in calibration], 0.95, 0.05)
    corpus = next(item for item in json.loads(args.matrix.read_text(encoding="utf-8")) if item["name"] == args.source)
    rows = [json.loads(line) for line in Path(corpus["fixture"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    scores = _scores(model, tokenizer, [policy_text(row["text"], corpus["policy"]) for row in rows], device, args.batch_size)
    metrics = _metrics([bool(row["label"]) for row in rows], [score >= threshold for score in scores])
    payload = {"model": MODEL_ID, "source": args.source, "threshold": threshold, "calibrationGateSatisfied": calibrated, "metrics": metrics, "passed": metrics["precision"] >= 0.95 and metrics["falsePositiveRate"] <= 0.05}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
