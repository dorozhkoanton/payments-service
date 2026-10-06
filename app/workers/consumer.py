import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog
from faststream import AckPolicy, FastStream
from faststream.exceptions import NackMessage, RejectMessage
from faststream.rabbit import RabbitBroker
from faststream.rabbit import RabbitMessage as RabbitMessageType
from faststream.rabbit.annotations import RabbitMessage
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.domain.events import PaymentCreatedEvent
from app.domain.exceptions import NonRetryableError, RetryableError
from app.integrations.gateway import FakePaymentGateway
from app.integrations.webhooks import WebhookSender, create_http_client
from app.logging import configure_logging
from app.messaging.broker import Publisher, create_broker
from app.messaging.retry import DeadLetter, RetryScheduler, current_attempt, decide
from app.messaging.topology import PAYMENTS_EXCHANGE, PAYMENTS_NEW_QUEUE, declare_topology
from app.services.processing import PaymentProcessor

log = structlog.get_logger(__name__)

NACK_PAUSE_SECONDS = 1.0


class Processor(Protocol):
    async def process(self, payment_id: uuid.UUID) -> None: ...


class Retrier(Protocol):
    async def schedule(
        self, message: RabbitMessageType, *, attempt: int, error: BaseException
    ) -> None: ...


@dataclass
class Deps:
    processor: Processor
    retry: Retrier
    engine: AsyncEngine | None = None
    http: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self.http is not None:
            await self.http.aclose()
        if self.engine is not None:
            await self.engine.dispose()


async def handle(
    event: PaymentCreatedEvent,
    message: RabbitMessageType,
    deps: Deps,
    retry_delays_ms: Sequence[int],
) -> None:
    attempt = current_attempt(message.headers)
    with structlog.contextvars.bound_contextvars(
        payment_id=str(event.payment_id), event_id=str(event.event_id), attempt=attempt
    ):
        try:
            await deps.processor.process(event.payment_id)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            trace = None if isinstance(exc, RetryableError | NonRetryableError) else exc
            decision = decide(attempt, exc, retry_delays_ms)
            if isinstance(decision, DeadLetter):
                log.error("moved_to_dlq", reason=decision.reason, error=error, exc_info=trace)
                raise RejectMessage(requeue=False) from exc
            try:
                await deps.retry.schedule(message, attempt=attempt, error=exc)
            except Exception:
                log.exception("retry_schedule_failed", error=error)
                await asyncio.sleep(NACK_PAUSE_SECONDS)  # avoid a hot loop
                raise NackMessage(requeue=True) from None
            log.warning(
                "retry_scheduled",
                routing_key=decision.routing_key,
                delay_ms=decision.delay_ms,
                error=error,
                exc_info=trace,
            )


DepsFactory = Callable[[RabbitBroker], Awaitable[Deps]]


def build_consumer(settings: Settings, deps_factory: DepsFactory) -> FastStream:
    broker = create_broker(settings.rabbitmq_url, prefetch=settings.consumer_prefetch)
    app = FastStream(broker)
    state: dict[str, Deps] = {}

    @app.on_startup
    async def startup() -> None:
        await broker.connect()
        await declare_topology(broker, settings.retry_delays_ms)
        state["deps"] = await deps_factory(broker)

    @app.after_shutdown
    async def shutdown() -> None:
        if (deps := state.pop("deps", None)) is not None:
            await deps.aclose()

    @broker.subscriber(PAYMENTS_NEW_QUEUE, PAYMENTS_EXCHANGE, ack_policy=AckPolicy.REJECT_ON_ERROR)
    async def on_payment_created(event: PaymentCreatedEvent, message: RabbitMessage) -> None:
        await handle(event, message, state["deps"], settings.retry_delays_ms)

    return app


async def build_deps(settings: Settings, broker: RabbitBroker) -> Deps:
    engine = create_engine(settings.database_url)
    http = create_http_client(settings.webhook_connect_timeout, settings.webhook_read_timeout)
    gateway = FakePaymentGateway(
        settings.gateway_min_delay, settings.gateway_max_delay, settings.gateway_success_rate
    )
    processor = PaymentProcessor(create_session_factory(engine), gateway, WebhookSender(http))
    return Deps(processor, RetryScheduler(Publisher(broker)), engine=engine, http=http)


def create_app() -> FastStream:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    return build_consumer(settings, lambda broker: build_deps(settings, broker))
