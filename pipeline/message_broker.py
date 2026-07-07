from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

T = TypeVar("T")


class MessageBroker(Protocol[T]):
    async def publish(self, topic: str, message: T) -> None: ...

    def subscribe(self, topic: str) -> AsyncIterator[T]: ...


@dataclass(slots=True)
class BrokerEnvelope(Generic[T]):
    topic: str
    message: T


class InMemoryMessageBroker(Generic[T]):
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[T]] = {}

    async def publish(self, topic: str, message: T) -> None:
        await self._queue(topic).put(message)

    async def subscribe(self, topic: str) -> AsyncIterator[T]:
        queue = self._queue(topic)
        while True:
            yield await queue.get()

    def _queue(self, topic: str) -> asyncio.Queue[T]:
        queue = self._queues.get(topic)
        if queue is None:
            queue = asyncio.Queue()
            self._queues[topic] = queue
        return queue
