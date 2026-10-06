import asyncio
import logging
from typing import Any

from faststream.rabbit import RabbitBroker, RabbitExchange
from faststream.rabbit.schemas import Channel

APP_ID = "payments-service"
PUBLISH_TIMEOUT = 5.0


def create_broker(url: str, *, prefetch: int | None = None) -> RabbitBroker:
    return RabbitBroker(
        url,
        default_channel=Channel(
            prefetch_count=prefetch,
            publisher_confirms=True,
            on_return_raises=True,
        ),
        app_id=APP_ID,
        logger=logging.getLogger("faststream.rabbit"),
    )


class Publisher:
    def __init__(self, broker: RabbitBroker, timeout: float = PUBLISH_TIMEOUT) -> None:
        self._broker = broker
        self._timeout = timeout

    async def publish(
        self,
        body: dict[str, Any] | bytes,
        *,
        exchange: RabbitExchange,
        routing_key: str,
        message_id: str,
        correlation_id: str,
        headers: dict[str, Any] | None = None,
    ) -> None:
        # covers the whole call because a robust channel waits for reconnect
        async with asyncio.timeout(self._timeout):
            await self._broker.publish(
                body,
                exchange=exchange,
                routing_key=routing_key,
                message_id=message_id,
                correlation_id=correlation_id,
                headers=headers or {},
                persist=True,
                mandatory=True,
                content_type="application/json",
            )
