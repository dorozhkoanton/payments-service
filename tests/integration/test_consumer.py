import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
from faststream.rabbit import RabbitBroker

from app.domain.events import PaymentCreatedEvent
from app.domain.exceptions import WebhookDeliveryError
from app.messaging.broker import Publisher
from app.messaging.retry import RetryScheduler
from app.messaging.topology import DLQ_QUEUE, PAYMENTS_EXCHANGE, PAYMENTS_NEW_RK
from app.workers.consumer import Deps, build_consumer
from tests.factories import make_settings
from tests.integration.conftest import TEST_RETRY_DELAYS_MS
from tests.integration.rabbit import wait_for_message


class FailingProcessor:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def process(self, payment_id: uuid.UUID) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise WebhookDeliveryError("HTTP 500")


StartConsumer = Callable[[FailingProcessor], Awaitable[None]]


@pytest.fixture
async def start_consumer(rabbitmq_url: str, broker: RabbitBroker) -> AsyncIterator[StartConsumer]:
    settings = make_settings(rabbitmq_url=rabbitmq_url, retry_base_delay_ms=TEST_RETRY_DELAYS_MS[0])
    apps = []

    async def start(processor: FailingProcessor) -> None:
        async def deps_factory(consumer_broker: RabbitBroker) -> Deps:
            return Deps(processor=processor, retry=RetryScheduler(Publisher(consumer_broker)))

        app = build_consumer(settings, deps_factory)
        await app.start()
        apps.append(app)

    yield start
    for app in apps:
        await app.stop()


async def publish(broker: RabbitBroker, body: dict[str, object] | None = None) -> str:
    event = PaymentCreatedEvent(
        event_id=uuid.uuid7(), payment_id=uuid.uuid7(), occurred_at=datetime.now(UTC)
    )
    await Publisher(broker).publish(
        body if body is not None else event.model_dump(mode="json"),
        exchange=PAYMENTS_EXCHANGE,
        routing_key=PAYMENTS_NEW_RK,
        message_id=str(event.event_id),
        correlation_id=str(event.payment_id),
    )
    return str(event.event_id)


async def test_message_is_retried_until_success(
    broker: RabbitBroker, start_consumer: StartConsumer
) -> None:
    processor = FailingProcessor(failures=1)
    await start_consumer(processor)
    await publish(broker)

    async with asyncio.timeout(5):
        while processor.calls < 2:  # noqa: ASYNC110
            await asyncio.sleep(0.05)
    await asyncio.sleep(0.5)

    assert processor.calls == 2
    assert await (await broker.declare_queue(DLQ_QUEUE)).get(fail=False) is None


async def test_message_goes_to_dlq_after_three_attempts(
    broker: RabbitBroker, start_consumer: StartConsumer
) -> None:
    processor = FailingProcessor(failures=100)
    await start_consumer(processor)
    message_id = await publish(broker)

    dead = await wait_for_message(await broker.declare_queue(DLQ_QUEUE))

    assert processor.calls == 3
    assert (dead.message_id, dead.headers["x-retry-count"]) == (message_id, 2)
    await dead.ack()


async def test_invalid_message_goes_to_dlq(
    broker: RabbitBroker, start_consumer: StartConsumer
) -> None:
    processor = FailingProcessor(failures=0)
    await start_consumer(processor)
    message_id = await publish(broker, body={"not": "an event"})

    dead = await wait_for_message(await broker.declare_queue(DLQ_QUEUE))

    assert dead.message_id == message_id
    assert processor.calls == 0
