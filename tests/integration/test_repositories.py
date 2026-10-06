import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import OutboxEvent
from app.domain.enums import PaymentStatus
from app.repositories.outbox import OutboxRepository
from app.repositories.payments import PaymentRepository
from tests.factories import payment_values

SessionFactory = async_sessionmaker[AsyncSession]


async def test_duplicate_idempotency_key_is_not_inserted(session_factory: SessionFactory) -> None:
    async with session_factory() as s, s.begin():
        first = await PaymentRepository(s).insert_if_absent(**payment_values(idempotency_key="k"))
    async with session_factory() as s, s.begin():
        again = await PaymentRepository(s).insert_if_absent(**payment_values(idempotency_key="k"))
    assert first is not None
    assert again is None


async def test_finalize_is_compare_and_set(session_factory: SessionFactory) -> None:
    values = payment_values()
    async with session_factory() as s, s.begin():
        await PaymentRepository(s).insert_if_absent(**values)
    now = datetime.now(UTC)

    async with session_factory() as s, s.begin():
        first = await PaymentRepository(s).finalize(values["id"], PaymentStatus.SUCCEEDED, now)
    async with session_factory() as s, s.begin():
        second = await PaymentRepository(s).finalize(values["id"], PaymentStatus.FAILED, now)

    assert first is not None and first.status == "succeeded"
    assert second is None


async def test_skip_locked_batches_do_not_overlap(session_factory: SessionFactory) -> None:
    async with session_factory() as s, s.begin():
        for _ in range(10):
            OutboxRepository(s).add(
                OutboxEvent(
                    id=uuid.uuid7(),
                    event_type="payment.created",
                    routing_key="payments.new",
                    payload={},
                )
            )

    async with session_factory() as s1, s1.begin(), session_factory() as s2, s2.begin():
        first = await OutboxRepository(s1).lock_pending_batch(5)
        second = await OutboxRepository(s2).lock_pending_batch(5)

    assert len(first) == len(second) == 5
    assert {e.id for e in first}.isdisjoint({e.id for e in second})
