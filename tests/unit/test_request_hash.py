from app.api.schemas import PaymentCreateRequest
from app.services.payments import request_hash

BASE = {
    "amount": "100.50",
    "currency": "RUB",
    "description": "x",
    "metadata": {"a": 1, "b": 2},
    "webhook_url": "http://hook.test/w",
}


def hash_of(**patch: object) -> str:
    return request_hash(PaymentCreateRequest.model_validate(BASE | patch))


def test_equivalent_bodies_hash_equally() -> None:
    assert hash_of(amount="100.5") == hash_of()
    assert hash_of(metadata={"b": 2, "a": 1}) == hash_of()


def test_any_change_changes_hash() -> None:
    assert hash_of(amount="100.51") != hash_of()
    assert hash_of(description="y") != hash_of()
