from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from faststream.rabbit import RabbitMessage

from app.domain.exceptions import NonRetryableError
from app.messaging.broker import Publisher
from app.messaging.topology import RETRY_EXCHANGE, retry_routing_key

RETRY_HEADER = "x-retry-count"
LAST_ERROR_HEADER = "x-last-error"
BROKER_HEADER_PREFIXES = ("x-death", "x-first-death", "x-last-death")


@dataclass(frozen=True)
class Retry:
    routing_key: str
    delay_ms: int


@dataclass(frozen=True)
class DeadLetter:
    reason: str


def current_attempt(headers: Mapping[str, Any]) -> int:
    try:
        return max(int(headers.get(RETRY_HEADER, 0)), 0) + 1
    except TypeError, ValueError:
        return 1


def decide(attempt: int, error: BaseException, delays_ms: Sequence[int]) -> Retry | DeadLetter:
    if isinstance(error, NonRetryableError):
        return DeadLetter("non_retryable")
    if attempt > len(delays_ms):
        return DeadLetter("attempts_exhausted")
    return Retry(retry_routing_key(attempt), delays_ms[attempt - 1])


class RetryScheduler:
    def __init__(self, publisher: Publisher) -> None:
        self._publisher = publisher

    async def schedule(self, message: RabbitMessage, *, attempt: int, error: BaseException) -> None:
        headers = {
            key: value
            for key, value in message.headers.items()
            if not key.startswith(BROKER_HEADER_PREFIXES)
        }
        headers[RETRY_HEADER] = attempt
        headers[LAST_ERROR_HEADER] = f"{type(error).__name__}: {error}"[:500]
        await self._publisher.publish(
            message.body,
            exchange=RETRY_EXCHANGE,
            routing_key=retry_routing_key(attempt),
            message_id=message.message_id,
            correlation_id=message.correlation_id,
            headers=headers,
        )
