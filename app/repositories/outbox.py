from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent
from app.domain.enums import OutboxStatus

MAX_ERROR_LENGTH = 1000


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, event: OutboxEvent) -> None:
        self._session.add(event)

    async def lock_pending_batch(self, limit: int) -> list[OutboxEvent]:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.PENDING)
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.scalars(stmt)).all())

    @staticmethod
    def mark_published(event: OutboxEvent, at: datetime) -> None:
        event.status = OutboxStatus.PUBLISHED
        event.published_at = at

    @staticmethod
    def record_failure(event: OutboxEvent, error: str) -> None:
        event.attempts += 1
        event.last_error = error[:MAX_ERROR_LENGTH]
