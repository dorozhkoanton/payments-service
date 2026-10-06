import asyncio
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.schemas import PaymentCreateRequest
from app.db.base import Base
from app.db.models import OutboxEvent, Payment
from app.domain.exceptions import IdempotencyKeyReusedError
from app.services import payments as payments_service
from app.services.payments import create_payment

SessionFactory = async_sessionmaker[AsyncSession]


def make_cmd(**overrides: object) -> PaymentCreateRequest:
    base = {
        "amount": "100.50",
        "currency": "RUB",
        "description": "test",
        "webhook_url": "http://hook.test/webhook",
    }
    return PaymentCreateRequest.model_validate(base | overrides)


async def count(sf: SessionFactory, model: type[Base]) -> int:
    async with sf() as s:
        return int(await s.scalar(select(func.count()).select_from(model)) or 0)


async def test_payment_and_event_are_saved_together(session_factory: SessionFactory) -> None:
    payment = await create_payment(session_factory, make_cmd(), "key-1")

    async with session_factory() as s:
        [event] = (await s.scalars(select(OutboxEvent))).all()
    assert payment.status == "pending"
    assert (event.status, event.routing_key) == ("pending", "payments.new")
    assert event.payload["payment_id"] == str(payment.id)


async def test_replay_returns_same_payment(session_factory: SessionFactory) -> None:
    first = await create_payment(session_factory, make_cmd(), "key-2")
    again = await create_payment(session_factory, make_cmd(amount="100.5"), "key-2")
    assert again.id == first.id
    assert await count(session_factory, OutboxEvent) == 1


async def test_same_key_with_other_body_is_rejected(session_factory: SessionFactory) -> None:
    await create_payment(session_factory, make_cmd(), "key-3")
    with pytest.raises(IdempotencyKeyReusedError):
        await create_payment(session_factory, make_cmd(amount="200.00"), "key-3")


async def test_concurrent_requests_create_one_payment(session_factory: SessionFactory) -> None:
    results = await asyncio.gather(
        *(create_payment(session_factory, make_cmd(), "key-4") for _ in range(10))
    )
    assert len({payment.id for payment in results}) == 1
    assert await count(session_factory, Payment) == 1
    assert await count(session_factory, OutboxEvent) == 1


async def test_failed_outbox_insert_rolls_back_payment(
    session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_event = payments_service.payment_created_event

    def invalid_event(payment: Payment) -> Any:
        event = real_event(payment)
        event.status = "bogus"
        return event

    monkeypatch.setattr(payments_service, "payment_created_event", invalid_event)
    with pytest.raises(IntegrityError):
        await create_payment(session_factory, make_cmd(), "key-5")
    assert await count(session_factory, Payment) == 0
