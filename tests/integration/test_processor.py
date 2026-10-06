import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Payment
from app.domain.enums import PaymentStatus
from app.domain.exceptions import PaymentNotFoundError, WebhookDeliveryError
from app.integrations.gateway import GatewayResult
from app.repositories.payments import PaymentRepository
from app.services.processing import PaymentProcessor
from tests.factories import payment_values

SessionFactory = async_sessionmaker[AsyncSession]


class StubGateway:
    def __init__(self, *statuses: PaymentStatus) -> None:
        self.statuses, self.calls = list(statuses), 0

    async def charge(self, payment_id: uuid.UUID, amount: Decimal, currency: str) -> GatewayResult:
        self.calls += 1
        await asyncio.sleep(0.01)
        return GatewayResult(self.statuses[min(self.calls, len(self.statuses)) - 1])


class SpyWebhooks:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[str] = []

    async def send(self, payment: Payment) -> None:
        if self.fail:
            raise WebhookDeliveryError("HTTP 500")
        self.sent.append(payment.status)


async def insert_pending(sf: SessionFactory) -> uuid.UUID:
    values = payment_values()
    async with sf() as s, s.begin():
        await PaymentRepository(s).insert_if_absent(**values)
    return uuid.UUID(str(values["id"]))


async def load(sf: SessionFactory, payment_id: uuid.UUID) -> Payment:
    async with sf() as s:
        payment = await PaymentRepository(s).get(payment_id)
    assert payment is not None
    return payment


async def test_payment_is_finalized_and_notified(session_factory: SessionFactory) -> None:
    pid = await insert_pending(session_factory)
    webhooks = SpyWebhooks()

    await PaymentProcessor(session_factory, StubGateway(PaymentStatus.SUCCEEDED), webhooks).process(
        pid
    )

    payment = await load(session_factory, pid)
    assert webhooks.sent == ["succeeded"]
    assert payment.processed_at is not None
    assert payment.webhook_delivered_at is not None


async def test_repeated_processing_changes_nothing(session_factory: SessionFactory) -> None:
    pid = await insert_pending(session_factory)
    gateway, webhooks = StubGateway(PaymentStatus.SUCCEEDED), SpyWebhooks()
    processor = PaymentProcessor(session_factory, gateway, webhooks)

    await processor.process(pid)
    await processor.process(pid)

    assert (gateway.calls, webhooks.sent) == (1, ["succeeded"])


async def test_retry_after_webhook_failure_skips_gateway(session_factory: SessionFactory) -> None:
    pid = await insert_pending(session_factory)
    gateway = StubGateway(PaymentStatus.FAILED)
    with pytest.raises(WebhookDeliveryError):
        await PaymentProcessor(session_factory, gateway, SpyWebhooks(fail=True)).process(pid)
    assert (await load(session_factory, pid)).status == "failed"

    webhooks = SpyWebhooks()
    await PaymentProcessor(session_factory, gateway, webhooks).process(pid)

    assert (gateway.calls, webhooks.sent) == (1, ["failed"])
    assert (await load(session_factory, pid)).webhook_attempts == 2


async def test_concurrent_deliveries_agree_on_status(session_factory: SessionFactory) -> None:
    pid = await insert_pending(session_factory)
    webhooks = SpyWebhooks()
    processor = PaymentProcessor(
        session_factory, StubGateway(PaymentStatus.SUCCEEDED, PaymentStatus.FAILED), webhooks
    )

    await asyncio.gather(processor.process(pid), processor.process(pid))

    assert len(set(webhooks.sent)) == 1
    assert (await load(session_factory, pid)).status == webhooks.sent[0]


async def test_missing_payment_is_not_retryable(session_factory: SessionFactory) -> None:
    processor = PaymentProcessor(
        session_factory, StubGateway(PaymentStatus.SUCCEEDED), SpyWebhooks()
    )
    with pytest.raises(PaymentNotFoundError):
        await processor.process(uuid.uuid7())
