import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Payment
from app.domain.enums import PaymentStatus
from app.domain.exceptions import PaymentNotFoundError, WebhookDeliveryError
from app.integrations.gateway import PaymentGateway
from app.repositories.payments import PaymentRepository

log = structlog.get_logger(__name__)


class WebhookNotifier(Protocol):
    async def send(self, payment: Payment) -> None: ...


def utcnow() -> datetime:
    return datetime.now(UTC)


class PaymentProcessor:
    def __init__(
        self,
        sf: async_sessionmaker[AsyncSession],
        gateway: PaymentGateway,
        webhooks: WebhookNotifier,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sf, self._gateway, self._webhooks, self._clock = sf, gateway, webhooks, clock

    async def process(self, payment_id: uuid.UUID) -> None:
        payment = await self._load(payment_id)
        if payment.status == PaymentStatus.PENDING:
            payment = await self._charge(payment)
        else:
            log.info("charge_skipped", status=payment.status)
        if payment.webhook_delivered_at is None:
            await self._notify(payment)

    async def _load(self, payment_id: uuid.UUID) -> Payment:
        async with self._sf() as session:
            payment = await PaymentRepository(session).get(payment_id)
        if payment is None:
            raise PaymentNotFoundError()
        return payment

    async def _charge(self, payment: Payment) -> Payment:
        result = await self._gateway.charge(payment.id, payment.amount, payment.currency)
        async with self._sf() as session, session.begin():
            updated = await PaymentRepository(session).finalize(
                payment.id, result.status, self._clock()
            )
        if updated is None:
            return await self._load(payment.id)
        log.info("payment_processed", status=updated.status, reason=result.reason)
        return updated

    async def _notify(self, payment: Payment) -> None:
        try:
            await self._webhooks.send(payment)
        except WebhookDeliveryError as exc:
            async with self._sf() as session, session.begin():
                await PaymentRepository(session).record_webhook_failure(payment.id, str(exc))
            raise
        async with self._sf() as session, session.begin():
            await PaymentRepository(session).mark_webhook_delivered(payment.id, self._clock())
        log.info("webhook_delivered", status=payment.status)
