from typing import Any

import pytest

from app.domain.exceptions import PaymentNotFoundError, WebhookDeliveryError
from app.messaging.retry import DeadLetter, Retry, RetryScheduler, current_attempt, decide
from app.messaging.topology import RETRY_EXCHANGE

DELAYS = [2000, 4000]


@pytest.mark.parametrize(
    ("attempt", "error", "expected"),
    [
        (1, WebhookDeliveryError("HTTP 500"), Retry("payments.new.retry.1", 2000)),
        (2, WebhookDeliveryError("HTTP 500"), Retry("payments.new.retry.2", 4000)),
        (3, WebhookDeliveryError("HTTP 500"), DeadLetter("attempts_exhausted")),
        (1, RuntimeError("db is down"), Retry("payments.new.retry.1", 2000)),
        (1, PaymentNotFoundError(), DeadLetter("non_retryable")),
    ],
)
def test_decide(attempt: int, error: Exception, expected: Retry | DeadLetter) -> None:
    assert decide(attempt, error, DELAYS) == expected


def test_current_attempt() -> None:
    assert current_attempt({}) == 1
    assert current_attempt({"x-retry-count": 2}) == 3


class StubMessage:
    def __init__(self) -> None:
        self.headers = {"trace": "t-1", "x-death": [{"reason": "expired"}]}
        self.body, self.message_id, self.correlation_id = b"{}", "m-1", "c-1"


class SpyPublisher:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def publish(self, body: bytes, **kwargs: Any) -> None:
        self.calls.append(kwargs)


async def test_scheduler_republishes_to_retry_queue() -> None:
    publisher = SpyPublisher()

    await RetryScheduler(publisher).schedule(
        StubMessage(),
        attempt=2,
        error=WebhookDeliveryError("HTTP 500"),
    )

    [call] = publisher.calls
    assert (call["exchange"], call["routing_key"]) == (RETRY_EXCHANGE, "payments.new.retry.2")
    assert call["headers"] == {
        "trace": "t-1",
        "x-retry-count": 2,
        "x-last-error": "WebhookDeliveryError: HTTP 500",
    }
