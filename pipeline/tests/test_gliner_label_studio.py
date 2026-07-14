from __future__ import annotations

from gliner_label_studio import clean_text, label_studio_task, validated_results


class FakeGliner:
    def predict_entities(self, text: str, labels: list[str], *, threshold: float, flat_ner: bool):
        assert text == "Contact Ada Lovelace at ada@example.test today."
        return [
            {"start": 8, "end": 20, "text": "Ada Lovelace", "label": "person", "score": 0.95},
            {"start": 24, "end": 40, "text": "wrong-text", "label": "email", "score": 0.8},
        ]


def test_clean_text_removes_markdown_without_corrupting_pii_values() -> None:
    raw = "### Contact **Ada Lovelace**" + chr(10) + chr(10) + "- email: ada_lovelace@example.test"
    assert clean_text(raw) == "Contact Ada Lovelace email: ada_lovelace@example.test"


def test_validated_results_discards_mismatched_offsets_and_generates_ids() -> None:
    clean = "Contact Ada Lovelace at ada@example.test today."
    results = validated_results(clean, FakeGliner().predict_entities(clean, [], threshold=0.3, flat_ner=True))
    assert len(results) == 1
    assert results[0]["id"]
    assert results[0]["value"]["text"] == clean[8:20]
    assert results[0]["value"]["labels"] == ["PERSON_NAME"]


def test_label_studio_task_infers_against_exported_text() -> None:
    task = label_studio_task("case-1", "## Contact **Ada Lovelace** at ada@example.test today.", FakeGliner(), ["person"], 0.3, "fake")
    assert task["data"]["text"] == "Contact Ada Lovelace at ada@example.test today."
    assert task["predictions"][0]["result"][0]["value"]["text"] == "Ada Lovelace"
