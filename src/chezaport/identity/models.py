"""SQLAlchemy models for the optional identity module."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from chezaport.core.database import Base


class User(Base):
    """Persisted identity record used by password authentication."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('viewer', 'operator', 'admin')", name="ck_users_role_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    identifier: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="viewer", server_default="viewer"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
