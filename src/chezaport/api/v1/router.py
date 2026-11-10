"""Version 1 public API router.

Feature routers are registered here as the sports domain is implemented.
Keeping the version boundary explicit allows the existing foundation routes
and future public contracts to evolve without breaking clients.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["API v1"])
