import asyncio
import contextlib
import signal
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from aio_pika.exceptions import AMQPConnectionError, ChannelInvalidStateError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models import OutboxEvent
from app.db.session import create_engine, create_session_factory
from app.logging import configure_logging
from app.messaging.broker import Publisher, create_broker
from app.messaging.topology import PAYMENTS_EXCHANGE, declare_topology
from app.repositories.outbox import OutboxRepository

log = structlog.get_logger("app.workers.outbox_relay")

# broker down aborts the batch with backoff, other errors only skip the row
CONNECTION_ERRORS = (AMQPConnectionError, ChannelInvalidStateError, ConnectionError, TimeoutError)
MAX_BACKOFF_SECONDS = 30.0


@dataclass(frozen=True)
class BatchResult:
    fetched: int
    published: int
    broker_down: bool


def correlation_id(event: OutboxEvent) -> str:
    return str(event.payload.get("payment_id") or event.id)


async def relay_once(
    sf: async_sessionmaker[AsyncSession], publisher: Publisher, batch_size: int
) -> BatchResult:
    published, broker_down = 0, False
    async with sf() as session, session.begin():
        events = await OutboxRepository(session).lock_pending_batch(batch_size)
        for event in events:
            context = {"event_id": str(event.id), "payment_id": correlation_id(event)}
            try:
                await publisher.publish(
                    event.payload,
                    exchange=PAYMENTS_EXCHANGE,
                    routing_key=event.routing_key,
                    message_id=str(event.id),
                    correlation_id=correlation_id(event),
                )
            except CONNECTION_ERRORS as exc:
                OutboxRepository.record_failure(event, repr(exc))
                log.warning("outbox_broker_unavailable", error=repr(exc), **context)
                broker_down = True
                break
            except Exception as exc:
                OutboxRepository.record_failure(event, repr(exc))
                log.exception("outbox_publish_failed", **context)
                continue
            OutboxRepository.mark_published(event, datetime.now(UTC))
            log.info("outbox_published", **context)
            published += 1
    return BatchResult(len(events), published, broker_down)


async def sleep_or_stop(stop: asyncio.Event, delay: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), delay)


async def run(
    sf: async_sessionmaker[AsyncSession],
    publisher: Publisher,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    backoff = 1.0
    while not stop.is_set():
        try:
            result = await relay_once(sf, publisher, settings.outbox_batch_size)
        except Exception:
            log.exception("outbox_batch_failed")
            failed, fetched = True, 0
        else:
            failed, fetched = result.broker_down, result.fetched
        if failed:
            await sleep_or_stop(stop, backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue
        backoff = 1.0
        if fetched < settings.outbox_batch_size:
            await sleep_or_stop(stop, settings.outbox_poll_interval)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    engine = create_engine(settings.database_url)
    broker = create_broker(settings.rabbitmq_url)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await broker.connect()
        await declare_topology(broker, settings.retry_delays_ms)
        log.info("outbox_relay_started")
        await run(create_session_factory(engine), Publisher(broker), settings, stop)
    finally:
        await broker.stop()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        log.exception("outbox_relay_crashed")
        sys.exit(1)
