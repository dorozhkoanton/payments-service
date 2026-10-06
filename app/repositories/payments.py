import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment
from app.domain.enums import PaymentStatus

MAX_ERROR_LENGTH = 1000


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_if_absent(self, **values: Any) -> Payment | None:
        stmt = (
            pg_insert(Payment)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(Payment)
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        return await self._session.get(Payment, payment_id, populate_existing=True)

    async def get_by_idempotency_key(self, key: str) -> Payment | None:
        stmt = select(Payment).where(Payment.idempotency_key == key)
        return (await self._session.scalars(stmt)).one_or_none()

    async def finalize(
        self, payment_id: uuid.UUID, status: PaymentStatus, processed_at: datetime
    ) -> Payment | None:
        # compare-and-set returns None if the payment is already finalized
        stmt = (
            update(Payment)
            .where(Payment.id == payment_id, Payment.status == PaymentStatus.PENDING)
            .values(status=status, processed_at=processed_at)
            .returning(Payment)
        )
        return (await self._session.scalars(stmt)).one_or_none()

    async def mark_webhook_delivered(self, payment_id: uuid.UUID, at: datetime) -> None:
        await self._session.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(webhook_delivered_at=at, webhook_attempts=Payment.webhook_attempts + 1)
            .execution_options(synchronize_session=False)
        )

    async def record_webhook_failure(self, payment_id: uuid.UUID, error: str) -> None:
        await self._session.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(
                webhook_attempts=Payment.webhook_attempts + 1,
                webhook_last_error=error[:MAX_ERROR_LENGTH],
            )
            .execution_options(synchronize_session=False)
        )
