"""Typed errors shared by provider adapters and ingestion services."""


class ProviderError(Exception):
    """Base exception for provider integration failures."""


class ProviderConfigurationError(ProviderError):
    """The adapter is missing valid configuration or credentials."""


class ProviderUnavailableError(ProviderError):
    """The provider is temporarily unavailable or returned a server error."""


class ProviderRateLimitError(ProviderError):
    """The provider rejected a request because its rate limit was reached."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
