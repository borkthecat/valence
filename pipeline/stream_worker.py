from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from aiokafka import AIOKafkaConsumer

from config import get_settings
from stage3_hydrator import batched
from stage4_razor_reranker import (
    MAX_BATCH_SIZE,
    InsufficientEligibleCandidatesError,
    RazorReranker,
    _default_context,
    result_to_stage5_pool,
)

logger = logging.getLogger("ValenceStreamWorker")


def enterprise_profile_to_stage4(profile: dict[str, Any]) -> dict[str, Any]:
    era = profile["era"]
    era_year = int(era) if isinstance(era, int | float) else _parse_era(str(era))
    raw_score = float(profile.get("raw_score", 0.0))
    return {
        "id": str(profile["candidate_id"]),
        "age": float(profile["age"]),
        "anniversary": raw_score >= 90.0,
        "channel": str(profile["retail_channel"]),
        "colorway": str(profile.get("colorway", get_settings().target_colorway)),
        "era_year": era_year,
    }


def _parse_era(value: str) -> int:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 4:
        return int(digits[:4])
    if len(digits) == 2:
        return int(f"20{digits}")
    return get_settings().target_era


def process_profile_batch(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    engine = RazorReranker()
    context = _default_context()
    stage4_records = [enterprise_profile_to_stage4(record) for record in records]
    pools: list[dict[str, Any]] = []
    for batch in batched(stage4_records, MAX_BATCH_SIZE):
        if len(batch) < 5:
            continue
        try:
            result = engine.rerank(batch, context)
        except InsufficientEligibleCandidatesError:
            continue
        pools.extend(result_to_stage5_pool(result))
    return pools


async def run_worker_loop() -> None:
    settings = get_settings()
    consumer = AIOKafkaConsumer(
        settings.kafka_ingest_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    logger.info("Valence stream worker connected to Kafka")
    try:
        while True:
            records = await consumer.getmany(timeout_ms=1000, max_records=1000)
            if not records:
                continue
            batches: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for messages in records.values():
                for msg in messages:
                    payload = json.loads(msg.value.decode("utf-8"))
                    batches[str(payload["batch_id"])].append(payload["data"])
            for batch_id, batch_records in batches.items():
                pool = process_profile_batch(batch_records)
                logger.info("processed batch %s records=%s stage5_pool=%s", batch_id, len(batch_records), len(pool))
            await consumer.commit()
    finally:
        await consumer.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker_loop())
