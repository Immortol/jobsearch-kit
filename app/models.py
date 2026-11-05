"""Database models."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Invite(Base):
    __tablename__ = "invites"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    invited_by: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    api_key: Mapped["ApiKey | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    rule_files: Mapped[list["RuleFile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True,
        order_by="RuleFile.name",
    )


class LoginToken(Base):
    """Single-use email login link. Keyed by email (not user) so it works before the first login."""

    __tablename__ = "login_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # 6-digit code from the same email, for signing in from another browser/device (0007).
    code_hash: Mapped[str | None] = mapped_column(String(64))
    code_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class ApiKey(Base):
    __tablename__ = "api_keys"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary)
    last4: Mapped[str] = mapped_column(String(4))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="api_key")


class RuleFile(Base):
    """One personal rules document, named like the files in Rules/ of the skills kit."""

    __tablename__ = "rule_files"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="rule_files")
