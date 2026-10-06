import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    AliasChoices,
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    UrlConstraints,
    field_validator,
)

from app.domain.enums import Currency, PaymentStatus

Amount = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]
WebhookUrl = Annotated[
    AnyUrl, UrlConstraints(max_length=2048, allowed_schemes=["http", "https"], host_required=True)
]
MAX_METADATA_BYTES = 4096


class PaymentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Amount
    currency: Currency
    description: str = Field(min_length=1, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: WebhookUrl

    @field_validator("metadata")
    @classmethod
    def _limit_metadata_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_METADATA_BYTES:
            raise ValueError("metadata must not exceed 4 KB in JSON")
        return value


class PaymentAcceptedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: UUID = Field(validation_alias=AliasChoices("id", "payment_id"))
    status: PaymentStatus
    created_at: datetime


class PaymentResponse(PaymentAcceptedResponse):
    amount: Decimal
    currency: Currency
    description: str
    # metadata_ goes first because Payment.metadata is SQLAlchemy MetaData
    metadata: dict[str, Any] = Field(validation_alias=AliasChoices("metadata_", "metadata"))
    idempotency_key: str
    webhook_url: str
    processed_at: datetime | None
