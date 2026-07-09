from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class CorpusSpec:
    name: str
    dataset: str
    revision: str
    license: str
    config: str | None
    extractor: Callable[[dict[str, Any]], Iterable[tuple[str, bool]]]
    test_split: str | None = "test"
    policy: str = "direct"


@dataclass(frozen=True)
class Corpus:
    spec: CorpusSpec
    training: tuple[tuple[str, bool], ...]
    test: tuple[tuple[str, bool], ...]


def _field(text_field: str, label_field: str = "label") -> Callable[[dict[str, Any]], Iterable[tuple[str, bool]]]:
    def extract(row: dict[str, Any]) -> Iterable[tuple[str, bool]]:
        yield str(row[text_field]), bool(row[label_field])

    return extract


def _jack(row: dict[str, Any]) -> Iterable[tuple[str, bool]]:
    yield str(row["prompt"]), row["type"] == "jailbreak"


def _smooth(row: dict[str, Any]) -> Iterable[tuple[str, bool]]:
    labels = {str(label).upper() for label in row["labels"]}
    yield str(row["text"]), labels != {"BENIGN"}


def _darkknight(row: dict[str, Any]) -> Iterable[tuple[str, bool]]:
    yield str(row["prompt"]), str(row["label"]).casefold() == "malicious"


def _hse(row: dict[str, Any]) -> Iterable[tuple[str, bool]]:
    yield str(row["Malicious prompts"]), True
    yield str(row["Safe prompt DeepSeek"]), False
    yield str(row["Safe prompt Llama"]), False


SPECS = (
    CorpusSpec("wambosec", "wambosec/prompt-injections", "071ee17a60112b7f9f808398156b430aadfaf1d2", "MIT", None, _field("prompt")),
    CorpusSpec("deepset", "deepset/prompt-injections", "4f61ecb038e9c3fb77e21034b22511b523772cdd", "Apache-2.0", None, _field("text"), policy="indirect"),
    CorpusSpec("shomi28", "Shomi28/prompt-injection-dataset", "0146454c8404a347ccc170a0291bcec932252fef", "MIT", None, _field("text")),
    CorpusSpec("jackhhao", "jackhhao/jailbreak-classification", "2f2ceeb39658696fd3f462403562b6eea5306287", "Apache-2.0", None, _jack),
    CorpusSpec("cgoosen_guard", "cgoosen/llm_guard_dataset", "b18903ecf0bd6e95ef6f1cdfb691dae7df2851e4", "Apache-2.0", None, _field("text")),
    CorpusSpec("neuralchemy", "neuralchemy/Prompt-injection-dataset", "7d70432dfcf47a821612cbf9d34e9d9e3ad20e75", "Apache-2.0", "core", _field("text")),
    CorpusSpec("wambosec_subtle", "wambosec/prompt-injections-subtle", "cd789a6e362aa72624d7f835c5270c8c3bdaf524", "MIT", None, _field("prompt")),
    CorpusSpec("jcanode", "jcanode/safeguard-prompt-injection", "61fbe3588450fa9b47ac1176ca7b5d2cc932344c", "Apache-2.0", None, _field("text")),
    CorpusSpec("rikka_multilingual", "rikka-snow/prompt-injection-multilingual", "f1ad1f3dd44581f53a4c67e96a9dde2fb419ee5b", "MIT", None, _field("text"), policy="indirect"),
    CorpusSpec("beratcmn_turkish", "beratcmn/turkish-prompt-injections", "c40c38f8ca632052fbfec19e90fab31fce33eda1", "Apache-2.0", None, _field("text"), policy="indirect"),
    CorpusSpec("s_labs", "S-Labs/prompt-injection-dataset", "002a9dd18514abd021869823d6b0429b38606d99", "MIT", None, _field("text")),
    CorpusSpec("cgoosen_combined", "cgoosen/prompt_injection_combined", "483296fde129d392d73077ad0c5d1175087cd9aa", "MIT", None, _field("text"), None, "secret"),
    CorpusSpec("smooth_3", "Smooth-3/llm-prompt-injection-attacks", "dd47798b64ebf0e833ecdbff6b1d73be3e440581", "Apache-2.0", None, _smooth, "validation"),
    CorpusSpec("darkknight25", "darkknight25/Prompt_Injection_Benign_Prompt_Dataset", "a0fc54fb563468a7fd64a9412718ce7cdb366666", "MIT", None, _darkknight, None),
    CorpusSpec("hse_llm", "hse-llm/prompt-injections", "6619b5e0f7a907404b8b81df6aa97c2114dd27a1", "MIT", None, _hse, None, "secret"),
)


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def fingerprint(text: str) -> bytes:
    return hashlib.sha256(normalize(text).encode("utf-8")).digest()


def policy_text(text: str, policy: str) -> str:
    if policy not in {"direct", "indirect", "secret"}:
        raise ValueError(f"unsupported guard policy: {policy}")
    return f"[VALENCE_CONTEXT={policy}] {text}"


def _extract(dataset: Any, extractor: Callable[[dict[str, Any]], Iterable[tuple[str, bool]]]) -> list[tuple[str, bool]]:
    rows: list[tuple[str, bool]] = []
    for row in dataset:
        for text, label in extractor(row):
            if text.strip():
                rows.append((text, label))
    return rows


def _deterministic_split(rows: list[tuple[str, bool]]) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    training: list[tuple[str, bool]] = []
    test: list[tuple[str, bool]] = []
    for label in (False, True):
        labelled = sorted((row for row in rows if row[1] is label), key=lambda row: fingerprint(row[0]))
        test_size = max(1, len(labelled) // 5)
        test.extend(labelled[:test_size])
        training.extend(labelled[test_size:])
    return training, test


def load_corpora(cache_dir: Path) -> tuple[Corpus, ...]:
    from datasets import load_dataset

    cache_dir.mkdir(parents=True, exist_ok=True)
    corpora: list[Corpus] = []
    for spec in SPECS:
        if spec.name == "jcanode":
            base = f"https://huggingface.co/datasets/{spec.dataset}/resolve/{spec.revision}"
            loaded = load_dataset(
                "arrow",
                data_files={
                    "train": f"{base}/train/data-00000-of-00001.arrow",
                    "validation": f"{base}/validation/data-00000-of-00001.arrow",
                    "test": f"{base}/test/data-00000-of-00001.arrow",
                },
                cache_dir=str(cache_dir),
            )
        else:
            kwargs = {
                "path": spec.dataset,
                "revision": spec.revision,
                "cache_dir": str(cache_dir),
                "download_mode": "reuse_cache_if_exists",
            }
            if spec.config is not None:
                kwargs["name"] = spec.config
            loaded = load_dataset(**kwargs)
        if spec.test_split is None:
            training, test = _deterministic_split(_extract(loaded["train"], spec.extractor))
        else:
            training = []
            for split in loaded:
                if split != spec.test_split and split != "test":
                    training.extend(_extract(loaded[split], spec.extractor))
            test = _extract(loaded[spec.test_split], spec.extractor)
        corpora.append(Corpus(spec, tuple(training), tuple(test)))
    return tuple(corpora)
