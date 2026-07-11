from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


CONTACT = re.compile(r"(?:https?://\S+|www\.\S+|[\w.+-]+@[\w.-]+|\+?[\d][\d ()-]{6,}\d)", re.IGNORECASE)
NON_WORD = re.compile(r"[^a-z0-9\s]")
SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class EngineDecision:
    fraud_score: float
    intercepted: bool
    evidence: tuple[str, ...]


class CodexFraudEngine:
    """Train-only domain history and clone evidence for a calibrated fraud scorer."""

    def __init__(self, *, strictness_exponent: float = 2.0, min_fraud_support: int = 3, clone_similarity: float = 0.95) -> None:
        if strictness_exponent <= 0 or min_fraud_support <= 0 or not 0 < clone_similarity <= 1:
            raise ValueError("invalid engine limits")
        self.k = strictness_exponent
        self.min_fraud_support = min_fraud_support
        self.clone_similarity = clone_similarity
        self.domain_registry: dict[str, dict[str, int]] = defaultdict(lambda: {"fraud_count": 0, "legit_count": 0})
        self.deterministic_blocklist: set[str] = set()
        self.legitimate_signatures: dict[str, list[tuple[str, frozenset[str]]]] = defaultdict(list)

    @staticmethod
    def normalized_tokens(text: str) -> list[str]:
        normalized = SPACE.sub(" ", NON_WORD.sub(" ", CONTACT.sub(" ", text.casefold())))
        return [token for token in normalized.split() if len(token) > 1]

    @classmethod
    def shingle_set(cls, text: str, width: int = 3) -> frozenset[str]:
        tokens = cls.normalized_tokens(text)
        if len(tokens) < width:
            return frozenset(tokens)
        return frozenset(" ".join(tokens[index:index + width]) for index in range(len(tokens) - width + 1))

    @staticmethod
    def _bucket(shingles: frozenset[str]) -> str:
        sample = "\x1f".join(sorted(shingles)[:32]).encode("utf-8")
        return hashlib.sha256(sample).hexdigest()[:16]

    @staticmethod
    def _domain(record: dict[str, Any], key: str) -> str:
        value = str(record.get(key) or "").strip().casefold()
        return value if value and value != "unknown" else ""

    def train_stateful_layers(self, training_records: list[dict[str, Any]]) -> None:
        for record in training_records:
            label = bool(record.get("label", record.get("fraudulent", False)))
            domains = {self._domain(record, "posting_domain"), self._domain(record, "company_domain")}
            for domain in domains - {""}:
                self.domain_registry[domain]["fraud_count" if label else "legit_count"] += 1
            text = str(record.get("description_text", record.get("description", "")) or "")
            posting_domain = self._domain(record, "posting_domain")
            if not label and text and posting_domain:
                shingles = self.shingle_set(text)
                if shingles:
                    self.legitimate_signatures[self._bucket(shingles)].append((posting_domain, shingles))
        self.deterministic_blocklist = {
            domain for domain, counts in self.domain_registry.items()
            if counts["fraud_count"] >= self.min_fraud_support and counts["legit_count"] == 0
        }

    def clone_evidence(self, record: dict[str, Any]) -> tuple[float, tuple[str, ...]]:
        text = str(record.get("description_text", record.get("description", "")) or "")
        posting_domain = self._domain(record, "posting_domain")
        shingles = self.shingle_set(text)
        if not shingles or not posting_domain:
            return 0.0, ()
        candidates = self.legitimate_signatures.get(self._bucket(shingles), [])
        best = 0.0
        for clean_domain, clean_shingles in candidates:
            union = len(shingles | clean_shingles)
            similarity = len(shingles & clean_shingles) / union if union else 0.0
            if clean_domain != posting_domain:
                best = max(best, similarity)
        return best, ("CLONE_DOMAIN_MISMATCH",) if best >= self.clone_similarity else ()

    def evaluate_pipeline(self, record: dict[str, Any], *, tfidf_probability: float, verifier_probability: float, external_probability: float = 0.0) -> EngineDecision:
        posting_domain = self._domain(record, "posting_domain")
        company_domain = self._domain(record, "company_domain")
        evidence: list[str] = []
        if {posting_domain, company_domain} & self.deterministic_blocklist:
            evidence.append("TRAIN_ONLY_DOMAIN_BLOCKLIST")
            return EngineDecision(1.0, True, tuple(evidence))
        clone_score, clone_evidence = self.clone_evidence(record)
        evidence.extend(clone_evidence)
        external_present = bool(posting_domain or company_domain)
        weights = (0.55, 0.30, 0.10, 0.05) if external_present else (0.65, 0.30, 0.05, 0.0)
        score = sum(weight * max(0.0, min(1.0, value)) ** self.k for weight, value in zip(weights, (tfidf_probability, verifier_probability, clone_score, external_probability), strict=True))
        return EngineDecision(round(score, 6), False, tuple(evidence))
