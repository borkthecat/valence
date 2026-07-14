"""Local transformer NER endpoint compatible with Valence's PII classifier client.

Run this only on an approved internal network. The gateway merges this independent
PERSON detector with GLiNER and retains its fail-closed detector semantics.
"""

from __future__ import annotations

import os
from numbers import Real
from functools import lru_cache
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from transformers import pipeline


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=16_384)


class Span(BaseModel):
    label: Literal["PERSON_NAME"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    score: float = Field(ge=0, le=1)


class ClassifyResponse(BaseModel):
    spans: list[Span]


MODEL_NAME = os.environ.get("SECONDARY_NER_MODEL", "dslim/bert-base-NER")
API_KEY = os.environ.get("SECONDARY_NER_API_KEY")
app = FastAPI(title="Valence secondary NER", version="1")


@lru_cache(maxsize=1)
def model():
    return pipeline("token-classification", model=MODEL_NAME, aggregation_strategy="simple")


def require_key(authorization: str | None) -> None:
    if API_KEY is None:
        return
    if authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="invalid authorization")


@app.post("/v1/classify", response_model=ClassifyResponse)
def classify(request: ClassifyRequest, authorization: str | None = Header(default=None)) -> ClassifyResponse:
    require_key(authorization)
    spans = []
    for entity in model()(request.text):
        if str(entity.get("entity_group", "")).upper() != "PER":
            continue
        start, end = entity.get("start"), entity.get("end")
        score = entity.get("score")
        if not isinstance(start, int) or not isinstance(end, int) or not isinstance(score, Real):
            continue
        if 0 <= start < end <= len(request.text):
            spans.append(Span(label="PERSON_NAME", start=start, end=end, score=float(score)))
    return ClassifyResponse(spans=spans)
