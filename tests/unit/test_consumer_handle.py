import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from faststream.exceptions import NackMessage, RejectMessage

from app.domain.events import PaymentCreatedEvent
from app.domain.exceptions import PaymentNotFoundError, WebhookDeliveryError
from app.workers import consumer
from app.workers.consumer import Deps, handle

DELAYS = [2000, 4000]
EVENT = PaymentCreatedEvent(
    event_id=uuid.uuid7(), payment_id=uuid.uuid7(), occurred_at=datetime.now(UTC)
)


class StubMessage:
    def __init__(self, headers: dict[str, Any] | None = None) -> None:
        self.headers = headers or {}
        self.body, self.message_id, self.correlation_id = b"{}", "m-1", "c-1"


class StubProcessor:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def process(self, payment_id: uuid.UUID) -> None:
        if self.error is not None:
            raise self.error


class SpyRetry:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.attempts: list[int] = []

    async def schedule(self, message: Any, *, attempt: int, error: BaseException) -> None:
        if self.fail:
            raise ConnectionError("broker is down")
        self.attempts.append(attempt)


def deps(error: Exception | None = None, retry: SpyRetry | None = None) -> Deps:
    return Deps(processor=StubProcessor(error), retry=retry or SpyRetry())


async def test_success_is_acked() -> None:
    retry = SpyRetry()
    await handle(EVENT, StubMessage(), deps(retry=retry), DELAYS)
    assert retry.attempts == []


@pytest.mark.parametrize(("headers", "attempt"), [({}, 1), ({"x-retry-count": 1}, 2)])
async def test_retryable_error_is_scheduled(headers: dict[str, Any], attempt: int) -> None:
    retry = SpyRetry()
    await handle(EVENT, StubMessage(headers), deps(WebhookDeliveryError("HTTP 500"), retry), DELAYS)
    assert retry.attempts == [attempt]


@pytest.mark.parametrize(
    ("error", "headers"),
    [(WebhookDeliveryError("HTTP 500"), {"x-retry-count": 2}), (PaymentNotFoundError(), {})],
)
async def test_exhausted_or_non_retryable_is_rejected(
    error: Exception, headers: dict[str, Any]
) -> None:
    with pytest.raises(RejectMessage):
        await handle(EVENT, StubMessage(headers), deps(error), DELAYS)


async def test_failed_republish_is_nacked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(consumer, "NACK_PAUSE_SECONDS", 0)
    with pytest.raises(NackMessage):
        await handle(
            EVENT,
            StubMessage(),
            deps(WebhookDeliveryError("HTTP 500"), SpyRetry(fail=True)),
            DELAYS,
        )
