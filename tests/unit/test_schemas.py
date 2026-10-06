import pytest
from pydantic import ValidationError

from app.api.schemas import PaymentCreateRequest, PaymentResponse
from tests.factories import make_payment

VALID = {
    "amount": "1500.00",
    "currency": "RUB",
    "description": "Order 1042",
    "webhook_url": "http://hook.test/webhook",
}


@pytest.mark.parametrize(
    "patch",
    [
        {"amount": "0"},
        {"amount": "1.001"},
        {"amount": "abc"},
        {"currency": "GBP"},
        {"description": ""},
        {"webhook_url": "ftp://hook.test/"},
        {"metadata": {"blob": "x" * 5000}},
        {"unexpected": 1},
    ],
)
def test_invalid_payload_is_rejected(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PaymentCreateRequest.model_validate(VALID | patch)


def test_amount_is_serialized_as_string() -> None:
    payload = PaymentCreateRequest.model_validate(VALID).model_dump(mode="json")
    assert payload["amount"] == "1500.00"


def test_response_is_built_from_orm_object() -> None:
    payment = make_payment(metadata_={"order_id": "1042"})
    body = PaymentResponse.model_validate(payment).model_dump(mode="json")
    assert (body["payment_id"], body["metadata"]) == (str(payment.id), {"order_id": "1042"})
