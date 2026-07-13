from fastapi.testclient import TestClient

from pii_classifier_service import create_app


class FakePredictor:
    def predict(self, text: str) -> list[dict]:
        assert text == "Contact Alice at alice@example.com"
        return [
            {"label": "person", "start": 8, "end": 13, "score": 0.9},
            {"label": "email address", "start": 17, "end": 34, "score": 0.99},
        ]


def test_classifier_contract_and_authentication() -> None:
    client = TestClient(create_app(FakePredictor(), "secret-classifier-key"))
    payload = {"text": "Contact Alice at alice@example.com"}
    assert client.post("/v1/classify", json=payload).status_code == 401
    response = client.post(
        "/v1/classify", json=payload,
        headers={"authorization": "Bearer secret-classifier-key"},
    )
    assert response.status_code == 200
    assert response.json() == {"spans": [
        {"label": "PERSON_NAME", "start": 8, "end": 13, "score": 0.9},
        {"label": "EMAIL", "start": 17, "end": 34, "score": 0.99},
    ]}


def test_health_exposes_configured_runtime() -> None:
    response = TestClient(create_app(FakePredictor(), "secret-classifier-key")).get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["model"]
    assert response.json()["device"] in {"cpu", "cuda"}
