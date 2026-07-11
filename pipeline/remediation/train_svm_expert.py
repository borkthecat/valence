from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parents[1] / "benchmarks"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from moe_guard import EXPERT_SOURCES
from train_text_experts import _rows, _threshold


def _model() -> Pipeline:
    return Pipeline([
        ("features", FeatureUnion([
            ("word", TfidfVectorizer(ngram_range=(1, 3), min_df=1, max_features=50_000, sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 6), min_df=1, max_features=70_000, sublinear_tf=True)),
        ])),
        ("classifier", CalibratedClassifierCV(LinearSVC(class_weight="balanced", random_state=20260711), cv=3, method="sigmoid")),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description="Train one calibrated source-local linear-SVM expert")
    parser.add_argument("--source", choices=sorted(EXPERT_SOURCES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--augmentation", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface"))
    parser.add_argument("--per-label", type=int, default=2000)
    parser.add_argument("--minimum-precision", type=float, default=0.95)
    parser.add_argument("--maximum-fpr", type=float, default=0.05)
    args = parser.parse_args()
    augmentation = [json.loads(line) for line in args.augmentation.read_text(encoding="utf-8").splitlines() if line.strip()]
    train, calibration = _rows(args.source, args.cache, args.per_label, augmentation)
    model = _model().fit([text for text, _ in train], [label for _, label in train])
    scores = model.predict_proba([text for text, _ in calibration])[:, 1].tolist()
    threshold, passed = _threshold(scores, [label for _, label in calibration], args.minimum_precision, args.maximum_fpr)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"kind": "text", "classifier": model, "threshold": threshold}, args.output)
    print(json.dumps({"source": args.source, "artifact": args.output.name, "threshold": threshold, "calibrationGateSatisfied": passed, "trainRecords": len(train), "calibrationRecords": len(calibration)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
