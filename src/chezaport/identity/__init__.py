"""Optional database-backed identity persistence."""

from .authorization import create_admin_token_validator, create_sync_operator_token_validator
from .composition import create_sqlalchemy_auth_application
from .models import User
from .refresh_tokens import RefreshToken, SqlAlchemyRefreshTokenStore
from .repository import UserCredentialRepository
from .roles import set_user_role

__all__ = [
    "RefreshToken",
    "SqlAlchemyRefreshTokenStore",
    "User",
    "UserCredentialRepository",
    "create_admin_token_validator",
    "create_sqlalchemy_auth_application",
    "create_sync_operator_token_validator",
    "set_user_role",
]
