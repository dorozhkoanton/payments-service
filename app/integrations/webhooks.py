import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel

from app.db.models import Payment
from app.domain.exceptions import WebhookDeliveryError

WEBHOOK_NAMESPACE = uuid.UUID("6f1b6a8e-2c3d-4f5a-9b7c-1d2e3f4a5b6c")


class WebhookPayload(BaseModel):
    event_id: uuid.UUID
    event_type: str
    payment_id: uuid.UUID
    status: str
    amount: Decimal
    currency: str
    metadata: dict[str, Any]
    processed_at: datetime | None


def build_payload(payment: Payment) -> WebhookPayload:
    return WebhookPayload(
        event_id=uuid.uuid5(WEBHOOK_NAMESPACE, f"{payment.id}:{payment.status}"),
        event_type=f"payment.{payment.status}",
        payment_id=payment.id,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        metadata=payment.metadata_,
        processed_at=payment.processed_at,
    )


class WebhookSender:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def send(self, payment: Payment) -> None:
        payload = build_payload(payment)
        try:
            response = await self._client.post(
                payment.webhook_url,
                content=payload.model_dump_json(),
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Event-Id": str(payload.event_id),
                },
            )
        except httpx.TransportError as exc:
            raise WebhookDeliveryError(type(exc).__name__) from exc
        if not response.is_success:
            raise WebhookDeliveryError(f"HTTP {response.status_code}")


def create_http_client(connect_timeout: float, read_timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
        follow_redirects=False,
    )
