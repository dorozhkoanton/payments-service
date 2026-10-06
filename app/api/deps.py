import re
import secrets
from typing import Annotated, cast

from fastapi import Depends, Header, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.exceptions import IdempotencyKeyMissingError, UnauthorizedError

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
IDEMPOTENCY_KEY_RE = re.compile(r"[\x21-\x7e]{1,255}")


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], request.app.state.session_factory)


async def require_api_key(
    api_key: Annotated[str | None, Security(api_key_header)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    expected = settings.api_key.get_secret_value().encode()
    if api_key is None or not secrets.compare_digest(api_key.encode(), expected):
        raise UnauthorizedError()


async def get_idempotency_key(
    # optional so that a missing header returns 400 instead of 422
    key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if key is None or not IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise IdempotencyKeyMissingError()
    return key
