import asyncio
import uuid
from typing import Any

from aio_pika.exceptions import AMQPConnectionError
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import OutboxEvent
from app.messaging.broker import Publisher
from app.messaging.topology import PAYMENTS_NEW_QUEUE
from app.repositories.outbox import OutboxRepository
from app.workers.outbox_relay import relay_once
from tests.integration.rabbit import wait_for_message

SessionFactory = async_sessionmaker[AsyncSession]


async def add_event(sf: SessionFactory, routing_key: str = "payments.new") -> uuid.UUID:
    event_id = uuid.uuid7()
    async with sf() as s, s.begin():
        OutboxRepository(s).add(
            OutboxEvent(
                id=event_id,
                event_type="payment.created",
                routing_key=routing_key,
                payload={"event_id": str(event_id), "payment_id": str(uuid.uuid7())},
            )
        )
    return event_id


async def load(sf: SessionFactory, event_id: uuid.UUID) -> OutboxEvent:
    async with sf() as s:
        event = await s.get(OutboxEvent, event_id)
    assert event is not None
    return event


class DownPublisher:
    async def publish(self, *args: Any, **kwargs: Any) -> None:
        raise AMQPConnectionError("broker is down")


class RecordingPublisher:
    def __init__(self) -> None:
        self.message_ids: list[str] = []

    async def publish(self, body: Any, *, message_id: str, **kwargs: Any) -> None:
        await asyncio.sleep(0.01)
        self.message_ids.append(message_id)


async def test_pending_event_is_published(
    session_factory: SessionFactory, broker: RabbitBroker
) -> None:
    event_id = await add_event(session_factory)

    result = await relay_once(session_factory, Publisher(broker), batch_size=10)

    message = await wait_for_message(await broker.declare_queue(PAYMENTS_NEW_QUEUE))
    assert result.published == 1
    assert message.message_id == str(event_id)
    assert (await load(session_factory, event_id)).status == "published"
    await message.ack()


async def test_events_stay_pending_while_broker_is_down(session_factory: SessionFactory) -> None:
    first, second = await add_event(session_factory), await add_event(session_factory)

    result = await relay_once(session_factory, DownPublisher(), batch_size=10)

    assert result.broker_down
    stuck = await load(session_factory, first)
    assert (stuck.status, stuck.attempts) == ("pending", 1)
    assert (await load(session_factory, second)).attempts == 0


async def test_unroutable_event_is_skipped(
    session_factory: SessionFactory, broker: RabbitBroker
) -> None:
    broken, good = await add_event(session_factory, "nowhere"), await add_event(session_factory)

    result = await relay_once(session_factory, Publisher(broker), batch_size=10)

    assert (result.fetched, result.published) == (2, 1)
    assert (await load(session_factory, broken)).status == "pending"
    assert (await load(session_factory, good)).status == "published"
    await (await wait_for_message(await broker.declare_queue(PAYMENTS_NEW_QUEUE))).ack()


async def test_parallel_relays_publish_each_event_once(session_factory: SessionFactory) -> None:
    event_ids = {str(await add_event(session_factory)) for _ in range(20)}
    publisher = RecordingPublisher()

    await asyncio.gather(*(relay_once(session_factory, publisher, batch_size=10) for _ in range(2)))

    assert sorted(publisher.message_ids) == sorted(event_ids)
