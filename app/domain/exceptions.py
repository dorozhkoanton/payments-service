class DomainError(Exception):
    code = "domain_error"
    default_detail = "Domain error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class RetryableError(Exception):
    pass


class NonRetryableError(Exception):
    pass


class UnauthorizedError(DomainError):
    code = "unauthorized"
    default_detail = "Invalid or missing API key"


class IdempotencyKeyMissingError(DomainError):
    code = "idempotency_key_invalid"
    default_detail = "Idempotency-Key header is missing or invalid"


class IdempotencyKeyReusedError(DomainError):
    code = "idempotency_key_reused"
    default_detail = "Idempotency-Key was used with another request body"


class PaymentNotFoundError(DomainError, NonRetryableError):
    code = "payment_not_found"
    default_detail = "Payment not found"


class WebhookDeliveryError(RetryableError):
    pass
