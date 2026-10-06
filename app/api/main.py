from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.v1 import payments
from app.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_engine(app.state.settings.database_url)
    app.state.session_factory = create_session_factory(engine)
    yield
    await engine.dispose()


def build_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Payments Service", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    register_exception_handlers(app)
    app.include_router(payments.router)
    return app


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    return build_app(settings)
