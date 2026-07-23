from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_review_environment_is_localhost_only_and_persistent() -> None:
    compose = (ROOT / "docker-compose.review.yml").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "start_hybrid_review_env.ps1").read_text(encoding="utf-8")

    assert "127.0.0.1:8081:8080" in compose
    assert ".valence-data/label-studio" in compose
    assert "LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED: \"false\"" in compose
    assert "pii-tasks-reviewer_a.json" in launcher
    assert "curl.exe --fail" in launcher
    assert "docker compose -f docker-compose.review.yml up -d" in launcher
