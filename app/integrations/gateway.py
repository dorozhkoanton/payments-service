import asyncio
import random
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.domain.enums import PaymentStatus


@dataclass(frozen=True)
class GatewayResult:
    status: PaymentStatus
    reason: str | None = None


class PaymentGateway(Protocol):
    # payment_id is the gateway idempotency key
    async def charge(
        self, payment_id: uuid.UUID, amount: Decimal, currency: str
    ) -> GatewayResult: ...


class FakePaymentGateway:
    def __init__(
        self,
        min_delay: float,
        max_delay: float,
        success_rate: float,
        rng: random.Random | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._min, self._max, self._rate = min_delay, max_delay, success_rate
        self._rng = rng or random.Random()  # noqa: S311
        self._sleep = sleep

    async def charge(self, payment_id: uuid.UUID, amount: Decimal, currency: str) -> GatewayResult:
        await self._sleep(self._rng.uniform(self._min, self._max))
        if self._rng.random() < self._rate:
            return GatewayResult(PaymentStatus.SUCCEEDED)
        return GatewayResult(PaymentStatus.FAILED, reason="declined_by_issuer")
