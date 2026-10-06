from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_idempotency_key, get_session_factory, require_api_key
from app.api.schemas import PaymentAcceptedResponse, PaymentCreateRequest, PaymentResponse
from app.db.models import Payment
from app.services.payments import create_payment, get_payment

router = APIRouter(prefix="/api/v1", tags=["payments"], dependencies=[Depends(require_api_key)])
SessionFactory = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


@router.post(
    "/payments", status_code=status.HTTP_202_ACCEPTED, response_model=PaymentAcceptedResponse
)
async def create_payment_endpoint(
    body: PaymentCreateRequest,
    idempotency_key: Annotated[str, Depends(get_idempotency_key)],
    sf: SessionFactory,
) -> Payment:
    return await create_payment(sf, body, idempotency_key)


@router.get("/payments/{payment_id}", response_model=PaymentResponse)
async def get_payment_endpoint(payment_id: UUID, sf: SessionFactory) -> Payment:
    return await get_payment(sf, payment_id)
