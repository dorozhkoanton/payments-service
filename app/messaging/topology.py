from collections.abc import Sequence

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

PAYMENTS_EXCHANGE = RabbitExchange("payments", type=ExchangeType.DIRECT, durable=True)
RETRY_EXCHANGE = RabbitExchange("payments.retry", type=ExchangeType.DIRECT, durable=True)
DLX_EXCHANGE = RabbitExchange("payments.dlx", type=ExchangeType.DIRECT, durable=True)

PAYMENTS_NEW_RK = "payments.new"
DLQ_RK = "payments.new.dlq"

PAYMENTS_NEW_QUEUE = RabbitQueue(
    "payments.new",
    durable=True,
    routing_key=PAYMENTS_NEW_RK,
    arguments={"x-dead-letter-exchange": DLX_EXCHANGE.name, "x-dead-letter-routing-key": DLQ_RK},
)
DLQ_QUEUE = RabbitQueue("payments.new.dlq", durable=True, routing_key=DLQ_RK)


def retry_routing_key(attempt: int) -> str:
    return f"payments.new.retry.{attempt}"


def retry_queues(delays_ms: Sequence[int]) -> list[RabbitQueue]:
    # one queue per delay because per-message TTL blocks behind unexpired messages
    return [
        RabbitQueue(
            retry_routing_key(n),
            durable=True,
            routing_key=retry_routing_key(n),
            arguments={
                "x-message-ttl": delay,
                "x-dead-letter-exchange": PAYMENTS_EXCHANGE.name,
                "x-dead-letter-routing-key": PAYMENTS_NEW_RK,
            },
        )
        for n, delay in enumerate(delays_ms, start=1)
    ]


async def declare_topology(broker: RabbitBroker, delays_ms: Sequence[int]) -> None:
    payments = await broker.declare_exchange(PAYMENTS_EXCHANGE)
    retry = await broker.declare_exchange(RETRY_EXCHANGE)
    dlx = await broker.declare_exchange(DLX_EXCHANGE)
    bindings = [(PAYMENTS_NEW_QUEUE, payments, PAYMENTS_NEW_RK), (DLQ_QUEUE, dlx, DLQ_RK)]
    bindings += [(queue, retry, queue.name) for queue in retry_queues(delays_ms)]
    for queue, exchange, routing_key in bindings:
        declared = await broker.declare_queue(queue)
        await declared.bind(exchange=exchange, routing_key=routing_key)
