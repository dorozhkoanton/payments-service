from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    rabbitmq_url: str
    api_key: SecretStr = Field(min_length=1)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    gateway_min_delay: float = Field(2.0, ge=0)
    gateway_max_delay: float = Field(5.0, ge=0)
    gateway_success_rate: float = Field(0.9, ge=0, le=1)

    webhook_connect_timeout: float = Field(3.0, gt=0)
    webhook_read_timeout: float = Field(5.0, gt=0)

    retry_max_attempts: int = Field(3, ge=1)
    retry_base_delay_ms: int = Field(2000, gt=0)
    retry_multiplier: float = Field(2.0, ge=1)

    consumer_prefetch: int = Field(10, ge=1)
    outbox_batch_size: int = Field(100, ge=1)
    outbox_poll_interval: float = Field(0.5, gt=0)

    @model_validator(mode="after")
    def _check_gateway_delays(self) -> Self:
        if self.gateway_min_delay > self.gateway_max_delay:
            raise ValueError("GATEWAY_MIN_DELAY must not exceed GATEWAY_MAX_DELAY")
        return self

    @property
    def retry_delays_ms(self) -> list[int]:
        return [
            round(self.retry_base_delay_ms * self.retry_multiplier**i)
            for i in range(self.retry_max_attempts - 1)
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
