"""Optional GLiNER-backed exact-span PII classifier for the gateway adapter."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Protocol

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

MODEL_ID = os.environ.get("PII_MODEL_ID", "urchade/gliner_multi_pii-v1")
MODEL_DEVICE = os.environ.get("PII_CLASSIFIER_DEVICE", "cpu").strip().lower()
DEFAULT_THRESHOLD = float(os.environ.get("PII_MODEL_THRESHOLD", "0.35"))
LABELS = (
    "person", "organization", "phone number", "mobile phone number", "landline phone number",
    "address", "street address", "city", "state", "country", "postal code", "coordinate",
    "passport number", "email", "email address", "credit card number", "social security number",
    "date of birth", "date", "time", "ip address", "api key", "access token", "password",
    "username", "bank account number", "routing number", "iban", "swift bic", "cvv",
    "driver's license number", "tax identification number", "medical record number",
    "health insurance number", "identity card number", "national id number", "license plate number",
    "device identifier", "employee id", "customer id", "unique identifier", "vehicle identification number",
)
LABEL_MAP = {
    "PERSON": "PERSON_NAME", "ORGANIZATION": "COMPANY_NAME", "PHONE_NUMBER": "PHONE_NUMBER",
    "MOBILE_PHONE_NUMBER": "PHONE_NUMBER", "LANDLINE_PHONE_NUMBER": "PHONE_NUMBER",
    "EMAIL": "EMAIL", "EMAIL_ADDRESS": "EMAIL", "SOCIAL_SECURITY_NUMBER": "SSN",
    "CREDIT_CARD_NUMBER": "CREDIT_CARD_NUMBER", "IP_ADDRESS": "IP_ADDRESS",
    "POSTAL_CODE": "POSTCODE", "API_KEY": "API_KEY", "ACCESS_TOKEN": "ACCESS_TOKEN",
    "USERNAME": "USER_NAME", "BANK_ACCOUNT_NUMBER": "ACCOUNT_NUMBER", "ROUTING_NUMBER": "BANK_ROUTING_NUMBER",
    "DRIVERS_LICENSE_NUMBER": "CERTIFICATE_LICENSE_NUMBER", "TAX_IDENTIFICATION_NUMBER": "TAX_ID",
    "HEALTH_INSURANCE_NUMBER": "HEALTH_PLAN_BENEFICIARY_NUMBER", "IDENTITY_CARD_NUMBER": "NATIONAL_ID",
    "LICENSE_PLATE_NUMBER": "LICENSE_PLATE", "VEHICLE_IDENTIFICATION_NUMBER": "VEHICLE_IDENTIFIER",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClassifyRequest(StrictModel):
    text: str = Field(max_length=1_000_000)


class Span(StrictModel):
    label: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    score: float = Field(ge=0, le=1)


class ClassifyResponse(StrictModel):
    spans: tuple[Span, ...]


class Predictor(Protocol):
    def predict(self, text: str) -> list[dict[str, Any]]: ...


class GlinerPredictor:
    def __init__(
        self,
        model_id: str = MODEL_ID,
        threshold: float = DEFAULT_THRESHOLD,
        device: str = MODEL_DEVICE,
    ) -> None:
        if not 0 <= threshold <= 1:
            raise ValueError("PII_MODEL_THRESHOLD must be between 0 and 1")
        if device not in {"cpu", "cuda"}:
            raise ValueError("PII_CLASSIFIER_DEVICE must be cpu or cuda")
        from gliner import GLiNER
        self.model = GLiNER.from_pretrained(model_id, map_location=device)
        self.threshold = threshold
        self.device = device

    def predict(self, text: str) -> list[dict[str, Any]]:
        return list(self.model.predict_entities(text, LABELS, threshold=self.threshold, flat_ner=True))


@lru_cache(maxsize=1)
def configured_predictor() -> GlinerPredictor:
    return GlinerPredictor()


def _canonical_label(label: str) -> str:
    normalized = label.upper().replace("'", "").replace("-", "_").replace(" ", "_")
    return LABEL_MAP.get(normalized, normalized)


def create_app(predictor: Predictor | None = None, api_key: str | None = None) -> FastAPI:
    app = FastAPI(title="Valence PII classifier", docs_url=None, redoc_url=None)
    expected_key = api_key if api_key is not None else os.environ.get("PII_CLASSIFIER_API_KEY")

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "model": MODEL_ID, "device": MODEL_DEVICE}

    @app.post("/v1/classify", response_model=ClassifyResponse)
    def classify(request: ClassifyRequest, authorization: str | None = Header(default=None)) -> ClassifyResponse:
        if expected_key is not None and authorization != f"Bearer {expected_key}":
            raise HTTPException(status_code=401, detail="invalid classifier credential")
        active = predictor if predictor is not None else configured_predictor()
        unique: dict[tuple[int, int, str], Span] = {}
        for item in active.predict(request.text):
            start, end = int(item["start"]), int(item["end"])
            if start < 0 or end > len(request.text) or start >= end:
                continue
            span = Span(
                label=_canonical_label(str(item["label"])),
                start=start,
                end=end,
                score=float(item["score"]),
            )
            key = (span.start, span.end, span.label)
            if key not in unique or span.score > unique[key].score:
                unique[key] = span
        return ClassifyResponse(spans=tuple(sorted(unique.values(), key=lambda item: (item.start, item.end, item.label))))

    return app


app = create_app()
