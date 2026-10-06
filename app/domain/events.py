from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PaymentCreatedEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID
    event_type: Literal["payment.created"] = "payment.created"
    payment_id: UUID
    occurred_at: datetime
    version: Literal[1] = 1
