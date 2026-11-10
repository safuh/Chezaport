"""Bounded retry policy for transient sports-provider failures."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from chezaport.sports.integrations.errors import (
    ProviderRateLimitError,
    ProviderUnavailableError,
)

T = TypeVar("T")
Sleep = Callable[[float], Awaitable[None]]
Operation = Callable[[], Awaitable[T]]


async def retry_provider_call(
    operation: Operation[T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 8.0,
    sleep: Sleep = asyncio.sleep,
) -> T:
    """Retry transient provider failures with exponential backoff.

    Provider-supplied Retry-After values take precedence over the calculated
    backoff. Configuration/authentication errors and all unrelated exceptions
    are deliberately allowed to propagate without a retry.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if base_delay_seconds < 0 or max_delay_seconds < 0:
        raise ValueError("retry delays must not be negative")

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except (ProviderUnavailableError, ProviderRateLimitError) as exc:
            if attempt == max_attempts:
                raise

            if (
                isinstance(exc, ProviderRateLimitError)
                and exc.retry_after_seconds is not None
            ):
                delay = max(0.0, exc.retry_after_seconds)
            else:
                delay = min(
                    base_delay_seconds * (2 ** (attempt - 1)),
                    max_delay_seconds,
                )
            await sleep(delay)

    raise RuntimeError("unreachable retry state")
