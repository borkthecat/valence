from __future__ import annotations

import asyncio
import json
import logging
import math
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
_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_RICH_KEYS = frozenset({"entity_type", "title", "description", "attributes", "signals", "images"})


def enterprise_profile_to_stage4(profile: dict[str, Any]) -> dict[str, Any]:
    era = profile["era"]
    era_year = int(era) if isinstance(era, int | float) else _parse_era(str(era))
    raw_score = float(profile.get("raw_score", 0.0))
    attributes = profile.get("attributes")
    colorway = profile.get("colorway")
    if colorway is None and isinstance(attributes, dict):
        colorway = attributes.get("colorway")
    record = {
        "id": str(profile["candidate_id"]),
        "age": float(profile["age"]),
        "anniversary": bool(profile.get("anniversary", False)),
        "channel": str(profile["retail_channel"]),
        "colorway": str(colorway if colorway is not None else get_settings().target_colorway),
        "era_year": era_year,
        "source_relevance_score": raw_score / 100.0,
    }
    for key in ("entity_type", "title", "description", "attributes", "signals", "images"):
        if key in profile:
            record[key] = profile[key]
    evidence_quality = evidence_quality_score(profile)
    if evidence_quality is not None:
        record["evidence_quality_score"] = evidence_quality
    return record


def evidence_quality_score(profile: dict[str, Any]) -> float | None:
    if not any(key in profile for key in _RICH_KEYS):
        return None
    score = 0.0
    title = str(profile.get("title", "")).strip()
    description = str(profile.get("description", "")).strip()
    attributes = profile.get("attributes")
    signals = profile.get("signals")
    images = profile.get("images")
    if profile.get("entity_type"):
        score += 0.05
    if len(title) >= 8:
        score += 0.15
    if len(description) >= 40:
        score += 0.15
    if isinstance(attributes, dict):
        score += min(len(attributes), 4) * 0.0625
    if isinstance(signals, dict):
        finite_signals = sum(
            1
            for value in signals.values()
            if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(float(value))
        )
        score += min(finite_signals, 3) * (0.20 / 3)
    if isinstance(images, list):
        valid_images = sum(1 for image in images if _valid_image_evidence(image))
        score += min(valid_images, 2) * 0.125
    return round(min(score, 1.0), 3)


def _valid_image_evidence(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    url = str(value.get("url", ""))
    digest = str(value.get("sha256", ""))
    mime_type = str(value.get("mime_type", ""))
    return (
        url.startswith("https://")
        and len(digest) == 64
        and all(char in "0123456789abcdefABCDEF" for char in digest)
        and mime_type in _IMAGE_MIME_TYPES
    )


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
