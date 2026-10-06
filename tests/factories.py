import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.config import Settings
from app.db.models import Payment


def payment_values(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "amount": Decimal("100.00"),
        "currency": "RUB",
        "description": "test",
        "metadata_": {},
        "webhook_url": "http://hook.test/webhook",
        "idempotency_key": uuid.uuid4().hex,
        "request_hash": "0" * 64,
    }
    return values | overrides


def make_payment(**overrides: Any) -> Payment:
    now = datetime.now(UTC)
    defaults = payment_values(status="succeeded", created_at=now, processed_at=now)
    return Payment(**(defaults | overrides))


def make_settings(**overrides: Any) -> Settings:
    required = {
        "database_url": "postgresql+asyncpg://unused/db",
        "rabbitmq_url": "amqp://unused",
        "api_key": "test-key",
    }
    return Settings(**(required | overrides), _env_file=None)
