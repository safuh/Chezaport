"""Serve the bundled first-party sports dashboard."""

from importlib.resources import files

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse, name="sports_dashboard")
async def sports_dashboard() -> HTMLResponse:
    """Serve the same-origin dashboard; data remains sourced from the API."""
    page = files("chezaport.web").joinpath("index.html").read_text(encoding="utf-8")
    return HTMLResponse(page)
