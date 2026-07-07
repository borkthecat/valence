
from __future__ import annotations

import asyncio

import observability
import stage3_hydrator as s3
import stage4_razor_reranker as s4
import stage5_cognitive_verifier as s5
import stream_worker
from message_broker import InMemoryMessageBroker


def test_stage3_distribution() -> None:
    generator = s3.FuzzDataGenerator(seed=7)
    profiles = generator.generate(2000)
    assert len(profiles) == 2000
    assert generator.report.unauthorized_channels > 0
    assert generator.report.negative_ages > 0
    assert generator.report.era_anomalies > 0
    assert generator.report.complex_profiles > 0
    assert any(profile["age"] in {0.0, 120.0, 80.1} for profile in profiles)
    assert any(str(profile["colorway"]).strip() != profile["colorway"] for profile in profiles)
    for profile in profiles:
        assert set(profile.keys()) == {
            "id",
            "age",
            "anniversary",
            "channel",
            "colorway",
            "era_year",
        }


def test_stage3_scale_and_determinism() -> None:
    report = s3._run_scale_validation()
    assert report.profiles == 2_000_000
    assert report.windows == 20
    assert report.winners > 0


def test_stage4_verification() -> None:
    s4._run_verification()


def test_stage4_determinism() -> None:
    batch = s4._sample_batch()
    context = s4._fixed_test_context()
    first = [c.id for c in s4.RazorReranker().rerank(batch, context).selected]
    second = [c.id for c in s4.RazorReranker().rerank(batch, context).selected]
    assert first == second


def test_stage4_quality_validation() -> None:
    report = s4.run_quality_validation(batches=1_000, batch_size=s4.MAX_BATCH_SIZE)
    assert report.top1_accuracy >= 0.995
    assert report.top5_recall >= 1.0


def test_stage5_json_healer() -> None:
    s5._run_healer_checks()


def test_observability_schema() -> None:
    record = observability.build_record(
        "gateway-proxy",
        "pii_redaction_complete",
        trace_id="val_tx_1",
        stage=2,
        metrics={"redacted_fields_count": 3},
    )
    assert set(record.keys()) == {"timestamp", "level", "component", "trace_id", "context"}
    assert record["context"]["metrics"]["redacted_fields_count"] == 3


def test_stage5_concurrent_simulation() -> None:
    verified, dropped = asyncio.run(s5._run_concurrent_sim())
    assert verified + dropped == 20
    assert dropped >= 6


def test_stage5_mock_provider_scale() -> None:
    asyncio.run(s5._run_mock_scale_check(500))


def test_message_broker_stub_round_trip() -> None:
    async def scenario() -> None:
        broker: InMemoryMessageBroker[str] = InMemoryMessageBroker()
        await broker.publish("stage3.to.stage4", "candidate-batch")
        subscriber = broker.subscribe("stage3.to.stage4")
        assert await anext(subscriber) == "candidate-batch"

    asyncio.run(scenario())


def test_stream_worker_enterprise_profile_processing() -> None:
    records = [
        {
            "candidate_id": f"sku-{index}",
            "age": 24 + index,
            "retail_channel": "direct" if index % 2 == 0 else "brand-direct",
            "era": "1500",
            "raw_score": 95.0 if index == 0 else 80.0,
        }
        for index in range(8)
    ]
    pool = stream_worker.process_profile_batch(records)
    assert len(pool) == 5
    assert pool[0]["id"] == "sku-0"
