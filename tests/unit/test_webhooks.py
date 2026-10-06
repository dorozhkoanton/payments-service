import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from app.domain.exceptions import WebhookDeliveryError
from app.integrations.webhooks import WebhookSender, build_payload, create_http_client
from tests.factories import make_payment

URL = "http://hook.test/webhook"


@pytest.fixture
async def sender() -> AsyncIterator[WebhookSender]:
    async with create_http_client(connect_timeout=3, read_timeout=5) as client:
        yield WebhookSender(client)


async def test_payload_is_posted(sender: WebhookSender, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(URL).mock(return_value=httpx.Response(204))
    payment = make_payment(webhook_url=URL)

    await sender.send(payment)

    request = route.calls.last.request
    body = json.loads(request.content)
    assert (body["payment_id"], body["status"], body["amount"]) == (
        str(payment.id),
        "succeeded",
        "100.00",
    )
    assert request.headers["X-Webhook-Event-Id"] == body["event_id"]


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.Response(500),
        httpx.Response(302),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("down"),
    ],
)
async def test_failures_raise(
    sender: WebhookSender, respx_mock: respx.MockRouter, outcome: httpx.Response | Exception
) -> None:
    route = respx_mock.post(URL)
    if isinstance(outcome, httpx.Response):
        route.mock(return_value=outcome)
    else:
        route.mock(side_effect=outcome)
    with pytest.raises(WebhookDeliveryError):
        await sender.send(make_payment(webhook_url=URL))


def test_event_id_is_stable() -> None:
    payment = make_payment()
    assert build_payload(payment).event_id == build_payload(payment).event_id
