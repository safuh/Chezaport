"""Provider adapters and normalized ingestion contracts for sports data."""

from chezaport.sports.integrations.capabilities import (
    ProviderCapabilities,
    ProviderResource,
)
from chezaport.sports.integrations.protocols import SportsDataProvider

__all__ = ["ProviderCapabilities", "ProviderResource", "SportsDataProvider"]
