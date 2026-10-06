from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from alembic import command
from alembic.config import Config
from faststream.rabbit import RabbitBroker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.rabbitmq import RabbitMqContainer

from app.api.deps import get_session_factory
from app.api.main import build_app
from app.db.session import create_session_factory
from app.messaging.broker import create_broker
from app.messaging.topology import DLQ_QUEUE, PAYMENTS_NEW_QUEUE, declare_topology, retry_queues
from tests.factories import make_settings

TEST_API_KEY = "test-key"
# same delays in all tests because queue arguments can't change
TEST_RETRY_DELAYS_MS = [100, 200]


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:18-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(cfg, "head")
        yield url


@pytest.fixture(scope="session")
def rabbitmq_url() -> Iterator[str]:
    with RabbitMqContainer("rabbitmq:4.3-management") as rmq:
        host, port = rmq.get_container_host_ip(), rmq.get_exposed_port(5672)
        yield f"amqp://{rmq.username}:{rmq.password}@{host}:{port}/"


@pytest.fixture
async def session_factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # NullPool because connections are bound to the test event loop
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE payments, outbox"))
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def broker(rabbitmq_url: str) -> AsyncIterator[RabbitBroker]:
    broker = create_broker(rabbitmq_url)
    await broker.connect()
    await declare_topology(broker, TEST_RETRY_DELAYS_MS)
    for queue in (PAYMENTS_NEW_QUEUE, DLQ_QUEUE, *retry_queues(TEST_RETRY_DELAYS_MS)):
        await (await broker.declare_queue(queue)).purge()
    yield broker
    await broker.stop()


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    api = build_app(make_settings(api_key=TEST_API_KEY))
    api.dependency_overrides[get_session_factory] = lambda: session_factory
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as http:
        yield http
