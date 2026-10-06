import pytest
from faststream.rabbit import RabbitBroker

from app.messaging.broker import Publisher
from app.messaging.topology import (
    DLQ_QUEUE,
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
    PAYMENTS_NEW_RK,
    RETRY_EXCHANGE,
    retry_routing_key,
)
from tests.integration.rabbit import wait_for_message


def death_reason(headers: dict[str, object]) -> object:
    [death] = headers["x-death"]
    return death["reason"]


@pytest.mark.parametrize("attempt", [1, 2])
async def test_retry_queue_returns_message_after_ttl(broker: RabbitBroker, attempt: int) -> None:
    main = await broker.declare_queue(PAYMENTS_NEW_QUEUE)
    await Publisher(broker).publish(
        {"n": attempt},
        exchange=RETRY_EXCHANGE,
        routing_key=retry_routing_key(attempt),
        message_id="m-1",
        correlation_id="c-1",
    )

    assert await main.get(fail=False) is None
    message = await wait_for_message(main)

    assert death_reason(message.headers) == "expired"
    await message.ack()


async def test_rejected_message_goes_to_dlq(broker: RabbitBroker) -> None:
    await Publisher(broker).publish(
        {"n": 1},
        exchange=PAYMENTS_EXCHANGE,
        routing_key=PAYMENTS_NEW_RK,
        message_id="m-2",
        correlation_id="c-2",
    )
    await (await wait_for_message(await broker.declare_queue(PAYMENTS_NEW_QUEUE))).reject()

    dead = await wait_for_message(await broker.declare_queue(DLQ_QUEUE))

    assert (dead.message_id, death_reason(dead.headers)) == ("m-2", "rejected")
    await dead.ack()
