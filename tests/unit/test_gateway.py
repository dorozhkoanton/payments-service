import random
import uuid
from decimal import Decimal

from app.domain.enums import PaymentStatus
from app.integrations.gateway import FakePaymentGateway


async def test_success_share_and_delay_bounds() -> None:
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    gateway = FakePaymentGateway(2, 5, 0.9, rng=random.Random(42), sleep=fake_sleep)
    results = [await gateway.charge(uuid.uuid4(), Decimal("1"), "RUB") for _ in range(10_000)]

    share = sum(r.status is PaymentStatus.SUCCEEDED for r in results) / len(results)
    assert 0.89 <= share <= 0.91
    assert all(2 <= delay <= 5 for delay in delays)
