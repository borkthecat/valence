from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC

SOURCES = {
    "wambosec_train": (
        "https://huggingface.co/datasets/wambosec/prompt-injections/resolve/"
        "071ee17a60112b7f9f808398156b430aadfaf1d2/data/train-00000-of-00001.parquet?download=true",
        "6e98332144e5ed52658ba7f899cfd583e388cd7fda733720a8c354af340f03e9",
    ),
    "wambosec_test": (
        "https://huggingface.co/datasets/wambosec/prompt-injections/resolve/"
        "071ee17a60112b7f9f808398156b430aadfaf1d2/data/test-00000-of-00001.parquet?download=true",
        "24a7b363225c32260e1e3fddb138315570345c891608e4dd3b32438a9366b782",
    ),
    "deepset_train": (
        "https://huggingface.co/datasets/deepset/prompt-injections/resolve/"
        "4f61ecb038e9c3fb77e21034b22511b523772cdd/data/train-00000-of-00001-9564e8b05b4757ab.parquet?download=true",
        "2e10bc7ab30f542c97e4e83e2a5683000b5057d25ec10908784c631d44124c04",
    ),
    "deepset_test": (
        "https://huggingface.co/datasets/deepset/prompt-injections/resolve/"
        "4f61ecb038e9c3fb77e21034b22511b523772cdd/data/test-00000-of-00001-701d16158af87368.parquet?download=true",
        "39ac797cabc157eeed58435a08593b2952bb6cb16fc394a2d383f447cc7b246e",
    ),
}
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
INVISIBLE_PATTERN = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
MAX_WORDS = 10_000
MAX_WORD_LENGTH = 60
MAX_CHARACTER_TEXT = 16_384
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(name: str, directory: Path) -> Path:
    url, expected = SOURCES[name]
    path = directory / f"{name}.parquet"
    if not path.exists() or _sha256(path) != expected:
        request = urllib.request.Request(url, headers={"User-Agent": "Valence-Guard-Training/1.0"})
        temporary = path.with_suffix(".tmp")
        total = 0
        try:
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as target:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise ValueError(f"{name} download exceeds 10 MiB")
                    target.write(chunk)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"{name} SHA-256 mismatch: {actual}")
    return path


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return " ".join(INVISIBLE_PATTERN.sub("", normalized).split())


def _features(text: str) -> list[str]:
    words = [word[:MAX_WORD_LENGTH] for word in TOKEN_PATTERN.findall(_normalize(text))[:MAX_WORDS]]
    features = [f"w:{word}" for word in words]
    features.extend(f"w:{left}_{right}" for left, right in zip(words, words[1:], strict=False))
    character_text = " ".join(words)[:MAX_CHARACTER_TEXT]
    for size in (3, 4, 5):
        features.extend(f"c:{character_text[index:index + size]}" for index in range(len(character_text) - size + 1))
    return features


def _rows(path: Path, text_column: str) -> list[tuple[str, bool]]:
    frame = pd.read_parquet(path, columns=[text_column, "label"])
    rows = [(str(text), bool(label)) for text, label in frame.itertuples(index=False, name=None)]
    if not rows or any(not text.strip() for text, _ in rows):
        raise ValueError(f"invalid or empty dataset: {path}")
    return rows


def _deduplicate(rows: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    labels: dict[str, tuple[str, bool]] = {}
    for text, label in rows:
        key = hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()
        previous = labels.get(key)
        if previous is not None and previous[1] != label:
            raise ValueError("conflicting labels for a normalized prompt")
        labels[key] = (text, label)
    return list(labels.values())


def _assert_disjoint(training: list[tuple[str, bool]], tests: list[tuple[str, bool]]) -> None:
    training_hashes = {hashlib.sha256(_normalize(text).encode("utf-8")).digest() for text, _ in training}
    test_hashes = {hashlib.sha256(_normalize(text).encode("utf-8")).digest() for text, _ in tests}
    overlap = training_hashes & test_hashes
    if overlap:
        raise ValueError(f"training/test leakage detected: {len(overlap)} normalized prompts")


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the bounded Valence prompt-injection guard")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/guard"))
    parser.add_argument("--max-features", type=int, default=100_000)
    args = parser.parse_args()
    if not 10_000 <= args.max_features <= 150_000:
        raise ValueError("--max-features must be between 10000 and 150000")
    args.cache.mkdir(parents=True, exist_ok=True)
    wambo_train = _rows(_download("wambosec_train", args.cache), "prompt")
    deepset_train = _rows(_download("deepset_train", args.cache), "text")
    wambo_test = _rows(_download("wambosec_test", args.cache), "prompt")
    deepset_test = _rows(_download("deepset_test", args.cache), "text")
    training = _deduplicate(wambo_train + deepset_train)
    tests = _deduplicate(wambo_test + deepset_test)
    _assert_disjoint(training, tests)
    vectorizer = TfidfVectorizer(
        analyzer=_features,
        lowercase=False,
        min_df=2,
        max_features=args.max_features,
        sublinear_tf=True,
        norm="l2",
    )
    matrix = vectorizer.fit_transform([text for text, _ in training])
    classifier = LinearSVC(C=0.5).fit(matrix, [label for _, label in training])
    names = vectorizer.get_feature_names_out()
    coefficients = classifier.coef_[0]
    features = {
        str(name): [round(float(identifier), 7), round(float(coefficient), 7)]
        for name, identifier, coefficient in zip(names, vectorizer.idf_, coefficients, strict=True)
        if not math.isclose(float(coefficient), 0.0, abs_tol=1e-12)
    }
    model = {
        "format": "valence-linear-tfidf-v1",
        "source": "wambosec@071ee17+deepset@4f61ecb",
        "language": "en",
        "trainingRecords": len(training),
        "bias": round(float(classifier.intercept_[0]), 7),
        "threshold": 0.0,
        "features": dict(sorted(features.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "trainingRecords": len(training),
        "reservedTestRecords": len(tests),
        "features": len(features),
        "bytes": args.output.stat().st_size,
        "sha256": _sha256(args.output),
        "output": str(args.output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
