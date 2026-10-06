import pytest
from pydantic import ValidationError

from tests.factories import make_settings


def test_retry_delays_grow_exponentially() -> None:
    assert make_settings().retry_delays_ms == [2000, 4000]
    assert make_settings(retry_max_attempts=4).retry_delays_ms == [2000, 4000, 8000]


@pytest.mark.parametrize(
    "overrides",
    [
        {"gateway_min_delay": 6, "gateway_max_delay": 5},
        {"gateway_success_rate": 1.5},
        {"retry_max_attempts": 0},
        {"api_key": ""},
    ],
)
def test_invalid_config_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)
