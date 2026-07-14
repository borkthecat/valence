"""Offset-safe GLiNER export helpers for Label Studio PII review."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from typing import Any, Protocol


LOGGER = logging.getLogger(__name__)

# These expressions remove Markdown delimiters only when they act as syntax.
# They deliberately preserve punctuation inside values such as email addresses,
# phone numbers, API keys, and snake_case usernames.
_FENCED_CODE = re.compile(r"(?m)^\s*(`{3,}|~{3,}).*$\n?")
_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_BLOCKQUOTE = re.compile(r"(?m)^\s{0,3}>\s?")
_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-+*]|\d+[.)])\s+")
_HORIZONTAL_RULE = re.compile(r"(?m)^\s{0,3}(?:[-*_]\s*){3,}$\n?")
_INLINE_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_INLINE_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BOLD_OR_STRIKE = re.compile(r"(?<!\\)(?:\*\*|__|~~)(.+?)(?<!\\)(?:\*\*|__|~~)")
_ITALIC = re.compile(r"(?<!\w)(?:\*|_)([^*_\n]+?)(?:\*|_)(?!\w)")
_ESCAPED_MARKDOWN = re.compile(r"\\([`*_{}\[\]<>#+.!-])")
_WHITESPACE = re.compile(r"\s+")


class Predictor(Protocol):
    def predict_entities(self, text: str, labels: list[str], *, threshold: float, flat_ner: bool) -> Iterable[dict[str, Any]]: ...


DEFAULT_LABELS = ["person", "email", "phone number", "address", "api key", "password", "social security number", "credit card number"]
LABEL_MAP = {
    "PERSON": "PERSON_NAME",
    "PERSON_NAME": "PERSON_NAME",
    "EMAIL": "EMAIL",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE": "PHONE",
    "PHONE_NUMBER": "PHONE",
    "ADDRESS": "ADDRESS",
    "API_KEY": "API_KEY",
    "PASSWORD": "PASSWORD",
    "SOCIAL_SECURITY_NUMBER": "SSN",
    "SSN": "SSN",
    "CREDIT_CARD_NUMBER": "CREDIT_CARD",
    "CREDIT_CARD": "CREDIT_CARD",
}


def clean_text(raw_text: str) -> str:
    """Remove common Markdown syntax and collapse all whitespace deterministically.

    The result is intentionally a single line. Run inference and export offsets
    only against this returned string; offsets from raw Markdown are unusable.
    """
    if not isinstance(raw_text, str):
        raise TypeError("raw_text must be a string")
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    text = _FENCED_CODE.sub("", text)
    text = _HORIZONTAL_RULE.sub("", text)
    text = _HEADING.sub("", text)
    text = _BLOCKQUOTE.sub("", text)
    text = _LIST_MARKER.sub("", text)
    text = _INLINE_IMAGE.sub(r"\1", text)
    text = _INLINE_LINK.sub(r"\1", text)
    text = _BOLD_OR_STRIKE.sub(r"\1", text)
    text = _ITALIC.sub(r"\1", text)
    text = _ESCAPED_MARKDOWN.sub(r"\1", text)
    return _WHITESPACE.sub(" ", text).strip()


def _label(value: object) -> str:
    normalized = str(value).upper().replace("-", "_").replace(" ", "_")
    return LABEL_MAP.get(normalized, normalized)


def validated_results(cleaned: str, entities: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert valid GLiNER entities to Label Studio result blocks.

    Invalid or mismatched spans are logged and excluded. The assertion is caught
    per entity so one model defect cannot invalidate a complete review batch.
    """
    results: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for entity in entities:
        try:
            start = entity["start"]
            end = entity["end"]
            model_text = entity["text"]
            if not isinstance(start, int) or not isinstance(end, int) or not isinstance(model_text, str):
                raise ValueError("missing typed start, end, or text")
            if not 0 <= start < end <= len(cleaned):
                raise ValueError(f"out-of-range offsets start={start} end={end} length={len(cleaned)}")
            # Do not normalize either side of this comparison. Exact character
            # equality is the contract that makes Label Studio offsets safe.
            assert cleaned[start:end] == model_text, (
                f"offset mismatch expected={model_text!r} actual={cleaned[start:end]!r} "
                f"start={start} end={end}"
            )
        except (AssertionError, KeyError, TypeError, ValueError) as error:
            LOGGER.error("discarding GLiNER span: %s", error)
            continue
        label = _label(entity.get("label", ""))
        key = (start, end, label)
        if key in seen:
            continue
        seen.add(key)
        score = entity.get("score", 0.0)
        results.append({
            "id": uuid.uuid4().hex,
            "from_name": "pii",
            "to_name": "text",
            "type": "labels",
            "value": {"start": start, "end": end, "text": model_text, "labels": [label]},
            "score": float(score),
        })
    return sorted(results, key=lambda result: (result["value"]["start"], result["value"]["end"], result["value"]["labels"][0]))


def label_studio_task(source_id: str, raw_text: str, predictor: Predictor, labels: list[str], threshold: float, model_version: str) -> dict[str, Any]:
    """Normalize, infer, validate, and produce one Label Studio task."""
    cleaned = clean_text(raw_text)
    entities = predictor.predict_entities(cleaned, labels, threshold=threshold, flat_ner=True)
    return {
        "data": {"source_id": source_id, "text": cleaned},
        "predictions": [{"model_version": model_version, "result": validated_results(cleaned, entities)}],
    }
