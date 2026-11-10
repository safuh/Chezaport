"""Tests for transient provider retry behavior."""

import pytest

from chezaport.sports.integrations.errors import (
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from chezaport.sports.integrations.retry import retry_provider_call


async def test_retries_transient_failure_with_exponential_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ProviderUnavailableError("temporarily unavailable")
        return "ok"

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    result = await retry_provider_call(operation, sleep=fake_sleep)

    assert result == "ok"
    assert attempts == 3
    assert delays == [0.5, 1.0]


async def test_rate_limit_retry_after_takes_precedence() -> None:
    attempts = 0
    delays: list[float] = []

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ProviderRateLimitError("slow down", retry_after_seconds=12.0)
        return "ok"

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    result = await retry_provider_call(operation, sleep=fake_sleep)

    assert result == "ok"
    assert delays == [12.0]


async def test_does_not_retry_configuration_errors() -> None:
    attempts = 0
    delays: list[float] = []

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise ProviderConfigurationError("missing API token")

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    with pytest.raises(ProviderConfigurationError, match="missing API token"):
        await retry_provider_call(operation, sleep=fake_sleep)

    assert attempts == 1
    assert delays == []


async def test_raises_after_maximum_attempts() -> None:
    attempts = 0
    delays: list[float] = []

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise ProviderUnavailableError("provider unavailable")

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    with pytest.raises(ProviderUnavailableError, match="provider unavailable"):
        await retry_provider_call(
            operation,
            max_attempts=3,
            base_delay_seconds=1.0,
            max_delay_seconds=1.5,
            sleep=fake_sleep,
        )

    assert attempts == 3
    assert delays == [1.0, 1.5]


def test_rejects_invalid_retry_configuration() -> None:
    async def operation() -> str:
        return "unused"

    with pytest.raises(ValueError, match="max_attempts"):
        await retry_provider_call(operation, max_attempts=0)
