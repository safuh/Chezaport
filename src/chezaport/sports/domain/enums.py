"""Stable domain enumerations shared by sports modules.

These values describe the internal domain vocabulary. Provider-specific status
strings must be translated into these values by integration adapters rather
than leaking into the domain or public API.
"""

from enum import StrEnum


class SportCode(StrEnum):
    """Supported sport identifiers; additional sports can be added without
    changing the surrounding domain architecture.
    """

    FOOTBALL = "football"


class FixtureStatus(StrEnum):
    """Normalized lifecycle state for a sporting fixture."""

    SCHEDULED = "scheduled"
    LIVE = "live"
    HALFTIME = "halftime"
    FINISHED = "finished"
    POSTPONED = "postponed"
    SUSPENDED = "suspended"
    ABANDONED = "abandoned"
    CANCELLED = "cancelled"
