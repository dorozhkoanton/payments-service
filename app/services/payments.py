import hashlib
import json
import uuid
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.schemas import PaymentCreateRequest
from app.db.models import OutboxEvent, Payment
from app.domain.events import PaymentCreatedEvent
from app.domain.exceptions import IdempotencyKeyReusedError, PaymentNotFoundError
from app.messaging.topology import PAYMENTS_NEW_RK
from app.repositories.outbox import OutboxRepository
from app.repositories.payments import PaymentRepository

log = structlog.get_logger(__name__)


def request_hash(cmd: PaymentCreateRequest) -> str:
    data = cmd.model_dump(mode="json")
    data["amount"] = str(cmd.amount.quantize(Decimal("0.01")))
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def payment_created_event(payment: Payment) -> OutboxEvent:
    event = PaymentCreatedEvent(
        event_id=uuid.uuid7(), payment_id=payment.id, occurred_at=payment.created_at
    )
    return OutboxEvent(
        id=event.event_id,
        event_type=event.event_type,
        routing_key=PAYMENTS_NEW_RK,
        payload=event.model_dump(mode="json"),
    )


async def create_payment(
    sf: async_sessionmaker[AsyncSession], cmd: PaymentCreateRequest, idempotency_key: str
) -> Payment:
    body_hash = request_hash(cmd)
    async with sf() as session, session.begin():
        payments = PaymentRepository(session)
        payment = await payments.insert_if_absent(
            id=uuid.uuid7(),
            amount=cmd.amount,
            currency=cmd.currency,
            description=cmd.description,
            metadata_=cmd.metadata,
            webhook_url=str(cmd.webhook_url),
            idempotency_key=idempotency_key,
            request_hash=body_hash,
        )
        created = payment is not None
        if payment is not None:
            OutboxRepository(session).add(payment_created_event(payment))
        else:
            # the conflicting transaction is already committed
            payment = await payments.get_by_idempotency_key(idempotency_key)

    if payment is None:
        raise RuntimeError("idempotency conflict without an existing payment")
    if created:
        log.info("payment_created", payment_id=str(payment.id))
    elif payment.request_hash != body_hash:
        raise IdempotencyKeyReusedError()
    return payment


async def get_payment(sf: async_sessionmaker[AsyncSession], payment_id: uuid.UUID) -> Payment:
    async with sf() as session:
        payment = await PaymentRepository(session).get(payment_id)
    if payment is None:
        raise PaymentNotFoundError()
    return payment
