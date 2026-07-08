from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from datetime import UTC, datetime
from collections.abc import Iterable
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from redis.asyncio import Redis

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
_RICH_KEYS = frozenset({"entity_type", "title", "description", "attributes", "signals", "images", "links"})
_HEX_DIGITS = frozenset("0123456789abcdef")


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
    for key in ("entity_type", "title", "description", "attributes", "signals", "images", "links"):
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
    links = profile.get("links")
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
        valid_digests = {
            str(image.get("sha256", "")).lower()
            for image in images
            if _valid_image_evidence(image)
        }
        score += min(len(valid_digests), 4) * 0.0625
    if isinstance(links, list):
        valid_links = {str(link.get("url", "")) for link in links if _valid_link_evidence(link)}
        score += min(len(valid_links), 2) * 0.05
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


def _valid_link_evidence(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    url = str(value.get("url", ""))
    source = str(value.get("source", "")).strip()
    digest = value.get("sha256")
    return (
        url.startswith("https://")
        and bool(source)
        and (
            digest is None
            or (
                isinstance(digest, str)
                and len(digest) == 64
                and all(char in "0123456789abcdefABCDEF" for char in digest)
            )
        )
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


def _parse_envelope(raw: bytes) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("message must contain an object data field")
    for field in ("message_id", "batch_fingerprint"):
        value = payload.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(char not in _HEX_DIGITS for char in value):
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    if not isinstance(payload.get("tenant_id"), str) or not isinstance(payload.get("batch_id"), str):
        raise ValueError("tenant_id and batch_id must be strings")
    batch_size = payload.get("batch_size")
    profile_index = payload.get("profile_index")
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 50_000:
        raise ValueError("batch_size is out of range")
    if not isinstance(profile_index, int) or not 0 <= profile_index < batch_size:
        raise ValueError("profile_index is out of range")
    return payload


def _digest_key(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"valence:{prefix}:{digest}"


async def _publish_dlq(
    producer: AIOKafkaProducer,
    topic: str,
    raw: bytes,
    reason: str,
    source: dict[str, Any],
) -> None:
    record = {
        "failed_at": datetime.now(UTC).isoformat(),
        "reason": reason,
        "source": source,
        "payload": raw.decode("utf-8", errors="replace"),
    }
    await producer.send_and_wait(topic, json.dumps(record, separators=(",", ":")).encode("utf-8"))


async def _stage_envelope(redis: Redis, payload: dict[str, Any], ttl: int) -> tuple[str, bool]:
    message_id = str(payload["message_id"])
    if await redis.exists(_digest_key("processed", message_id)):
        return "", False
    identity = f'{payload["tenant_id"]}\0{payload["batch_id"]}\0{payload["batch_fingerprint"]}'
    staging_key = _digest_key("staging", identity)
    await redis.hset(staging_key, str(payload["profile_index"]), json.dumps(payload, separators=(",", ":")))
    await redis.expire(staging_key, ttl)
    complete = await redis.hlen(staging_key) == int(payload["batch_size"])
    return staging_key, complete


async def _process_staged_batch(
    redis: Redis,
    producer: AIOKafkaProducer,
    staging_key: str,
    settings: Any,
) -> None:
    lock_key = staging_key.replace(":staging:", ":lock:")
    if not await redis.set(lock_key, "1", ex=300, nx=True):
        return
    try:
        values = await redis.hvals(staging_key)
        payloads = sorted(
            (json.loads(value) for value in values),
            key=lambda item: int(item["profile_index"]),
        )
        try:
            pool = process_profile_batch(payload["data"] for payload in payloads)
        except Exception as error:
            for payload in payloads:
                await _publish_dlq(
                    producer,
                    settings.kafka_dlq_topic,
                    json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                    f"processing_failed:{type(error).__name__}",
                    {"topic": settings.kafka_ingest_topic},
                )
            pool = []
            logger.error("batch moved to DLQ error=%s", type(error).__name__)
        transaction = redis.pipeline(transaction=True)
        for payload in payloads:
            transaction.set(
                _digest_key("processed", str(payload["message_id"])),
                "1",
                ex=settings.idempotency_ttl_seconds,
            )
        transaction.delete(staging_key)
        await transaction.execute()
        logger.info(
            "processed batch %s records=%s stage5_pool=%s",
            payloads[0]["batch_id"],
            len(payloads),
            len(pool),
        )
    finally:
        await redis.delete(lock_key)


async def run_worker_loop() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    consumer = AIOKafkaConsumer(
        settings.kafka_ingest_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await redis.ping()
    await producer.start()
    await consumer.start()
    logger.info("Valence stream worker connected to Kafka")
    try:
        while True:
            records = await consumer.getmany(timeout_ms=1000, max_records=1000)
            if not records:
                continue
            completed_staging: set[str] = set()
            for messages in records.values():
                for msg in messages:
                    source = {"topic": msg.topic, "partition": msg.partition, "offset": msg.offset}
                    try:
                        payload = _parse_envelope(msg.value)
                        staging_key, complete = await _stage_envelope(
                            redis, payload, settings.idempotency_ttl_seconds
                        )
                        if complete:
                            completed_staging.add(staging_key)
                    except Exception as error:
                        await _publish_dlq(
                            producer,
                            settings.kafka_dlq_topic,
                            msg.value,
                            f"invalid_message:{type(error).__name__}",
                            source,
                        )
            for staging_key in completed_staging:
                await _process_staged_batch(redis, producer, staging_key, settings)
            await consumer.commit()
    finally:
        await consumer.stop()
        await producer.stop()
        await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker_loop())
