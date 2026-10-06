import asyncio

from aio_pika.abc import AbstractIncomingMessage, AbstractQueue


async def wait_for_message(queue: AbstractQueue) -> AbstractIncomingMessage:
    async with asyncio.timeout(5):
        while (message := await queue.get(fail=False)) is None:  # noqa: ASYNC110
            await asyncio.sleep(0.05)
    return message
