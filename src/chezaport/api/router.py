"""Top-level API router.

Legacy foundation routes remain mounted at the existing API prefix. New
product-facing endpoints are grouped under the explicit /v1 version boundary.
"""

from fastapi import APIRouter

from .auth import router as auth_router
from .health import router as health_router
from .v1.router import router as v1_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(v1_router)
