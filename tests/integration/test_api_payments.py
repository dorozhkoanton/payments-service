import uuid

import httpx
import pytest

BODY = {
    "amount": "1500.00",
    "currency": "RUB",
    "description": "Order 1042",
    "metadata": {"order_id": "1042"},
    "webhook_url": "http://hook.test/webhook",
}
URL = "/api/v1/payments"


async def test_create_and_get(client: httpx.AsyncClient) -> None:
    created = await client.post(URL, json=BODY, headers={"Idempotency-Key": "k-1"})

    assert created.status_code == 202
    assert set(created.json()) == {"payment_id", "status", "created_at"}
    payment_id = created.json()["payment_id"]
    payment = (await client.get(f"{URL}/{payment_id}")).json()
    assert (payment["status"], payment["amount"], payment["metadata"]) == (
        "pending",
        "1500.00",
        {"order_id": "1042"},
    )


async def test_replay_returns_same_payment(client: httpx.AsyncClient) -> None:
    first = await client.post(URL, json=BODY, headers={"Idempotency-Key": "k-2"})
    again = await client.post(URL, json=BODY, headers={"Idempotency-Key": "k-2"})
    assert again.status_code == 202
    assert again.json() == first.json()


async def test_reused_key_with_other_body_is_422(client: httpx.AsyncClient) -> None:
    await client.post(URL, json=BODY, headers={"Idempotency-Key": "k-3"})
    r = await client.post(URL, json=BODY | {"amount": "1.00"}, headers={"Idempotency-Key": "k-3"})
    assert (r.status_code, r.json()["code"]) == (422, "idempotency_key_reused")


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 400),
        ({"Idempotency-Key": "has space"}, 400),
        ({"Idempotency-Key": "k-4", "X-API-Key": "wrong"}, 401),
    ],
)
async def test_header_errors(
    client: httpx.AsyncClient, headers: dict[str, str], status: int
) -> None:
    assert (await client.post(URL, json=BODY, headers=headers)).status_code == status


async def test_api_key_is_required(client: httpx.AsyncClient) -> None:
    del client.headers["X-API-Key"]
    assert (await client.get(f"{URL}/{uuid.uuid4()}")).status_code == 401


async def test_invalid_body_is_422(client: httpx.AsyncClient) -> None:
    r = await client.post(URL, json=BODY | {"currency": "GBP"}, headers={"Idempotency-Key": "k-5"})
    assert r.status_code == 422


@pytest.mark.parametrize(("payment_id", "status"), [(str(uuid.uuid4()), 404), ("not-a-uuid", 422)])
async def test_get_errors(client: httpx.AsyncClient, payment_id: str, status: int) -> None:
    assert (await client.get(f"{URL}/{payment_id}")).status_code == status
