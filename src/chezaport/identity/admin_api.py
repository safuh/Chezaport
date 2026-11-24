"""Administrative user-management API; authorization is supplied by the host."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User


async def _session(request: Request):
    factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(_session)]
router = APIRouter(prefix="/admin/users", tags=["administration"])
_bearer = HTTPBearer(auto_error=False)


async def _require_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> None:
    validator: Callable[[str], Awaitable[bool]] | None = getattr(
        request.app.state, "admin_token_validator", None
    )
    if validator is None:
        raise HTTPException(
            status_code=503, detail="Administrator authentication is not configured"
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer access token required")
    if not await validator(credentials.credentials):
        raise HTTPException(status_code=403, detail="Administrator access required")


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    identifier: str
    role: str


class UserPage(BaseModel):
    items: list[UserRead]
    total: int
    limit: int
    offset: int


class RoleUpdate(BaseModel):
    role: str = Field(pattern="^(viewer|operator|admin)$")


@router.get("", response_model=UserPage, dependencies=[Depends(_require_admin)])
async def list_users(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserPage:
    total = await session.scalar(select(func.count()).select_from(User))
    result = await session.scalars(
        select(User).order_by(User.created_at.desc(), User.id).limit(limit).offset(offset)
    )
    return UserPage(
        items=[UserRead.model_validate(user) for user in result.all()],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.patch("/{user_id}/role", response_model=UserRead, dependencies=[Depends(_require_admin)])
async def update_user_role(user_id: str, body: RoleUpdate, session: SessionDep) -> UserRead:
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "admin" and body.role != "admin":
        locked_admins = await session.scalars(
            select(User.id).where(User.role == "admin").with_for_update()
        )
        if len(locked_admins.all()) <= 1:
            raise HTTPException(status_code=409, detail="Cannot demote the last administrator")
    user.role = body.role
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)
