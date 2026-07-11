from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer

BENCHMARKS = Path(__file__).resolve().parents[1] / "benchmarks"
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from train_transformer_guard import save_model_safely, supervised_contrastive_loss


CONTRASTIVE_WEIGHT = 0.05
EPOCHS = 2
LEARNING_RATE = 2e-5


class CalibrationDataset(Dataset):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, object]:
        return self.rows[index]


def main() -> int:
    parser = argparse.ArgumentParser(description="Two-epoch localized calibration of the V6 provenance guard")
    parser.add_argument("--model", type=Path, required=True); parser.add_argument("--data", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=1); parser.add_argument("--max-length", type=int, default=256)
    args = parser.parse_args()
    if args.batch_size <= 0 or args.max_length <= 0:
        raise ValueError("batch size and max length must be positive")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for calibration")
    rows = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 1450 or sum(not bool(row["label"]) and row["kind"] == "synthetic_hard_negative" for row in rows) != 1000:
        raise ValueError("calibration data must contain 1,000 synthetic negatives and 450 anchors")
    random.Random(20260711).shuffle(rows)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, dtype=torch.float32)
    device = torch.device("cuda"); model.to(device); model.gradient_checkpointing_enable()

    def collate(batch: list[dict[str, object]]) -> tuple[dict[str, torch.Tensor], torch.Tensor]:
        encoded = tokenizer([str(row["text"]) for row in batch], padding=True, truncation=True, max_length=args.max_length, return_tensors="pt")
        return encoded, torch.tensor([int(bool(row["label"])) for row in batch], dtype=torch.long)

    loader = DataLoader(CalibrationDataset(rows), batch_size=args.batch_size, shuffle=True, collate_fn=collate, pin_memory=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=0.01, fused=True)
    scaler = torch.amp.GradScaler("cuda")
    updates = 0
    for epoch in range(EPOCHS):
        model.train()
        for batch, labels in loader:
            batch, labels = {key: value.to(device, non_blocking=True) for key, value in batch.items()}, labels.to(device, non_blocking=True)
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                outputs = model(**batch, labels=labels, output_hidden_states=True)
                loss = outputs.loss + CONTRASTIVE_WEIGHT * supervised_contrastive_loss(outputs.hidden_states[-1][:, 0, :], labels)
            scaler.scale(loss).backward(); scaler.unscale_(optimizer); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); scaler.step(optimizer); scaler.update(); optimizer.zero_grad(set_to_none=True)
            updates += 1
        print(json.dumps({"epoch": epoch + 1, "updates": updates, "loss": float(loss.detach())}), flush=True)
    save_model_safely(model, tokenizer, args.output, device=device, resume_training=False)
    (args.output / "calibration-training.json").write_text(json.dumps({"baseModel": str(args.model), "records": len(rows), "epochs": EPOCHS, "learningRate": LEARNING_RATE, "contrastiveWeight": CONTRASTIVE_WEIGHT, "updates": updates}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
