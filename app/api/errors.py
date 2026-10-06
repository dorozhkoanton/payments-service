from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    DomainError,
    IdempotencyKeyMissingError,
    IdempotencyKeyReusedError,
    PaymentNotFoundError,
    UnauthorizedError,
)

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    IdempotencyKeyMissingError: 400,
    UnauthorizedError: 401,
    PaymentNotFoundError: 404,
    IdempotencyKeyReusedError: 422,
}


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error = exc if isinstance(exc, DomainError) else DomainError()
    return JSONResponse(
        {"detail": error.detail, "code": error.code},
        status_code=STATUS_BY_ERROR.get(type(error), 400),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
