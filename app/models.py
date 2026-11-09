"""Database models."""

from datetime import UTC, datetime

from decimal import Decimal

from sqlalchemy import (
    JSON, DateTime, ForeignKey, Index, LargeBinary, Numeric, String, Text, UniqueConstraint,
)
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
    chats: Mapped[list["Chat"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Chat.updated_at.desc()",
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


class Chat(Base):
    """A conversation with the assistant (decision 0009)."""

    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="chats")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ChatMessage.id",
    )


class ChatMessage(Base):
    """One message in a chat.

    `text` is what the panel shows. `api_messages` is what was exchanged with the Claude API for
    this message, in API format: for a user message, the user turn; for an assistant reply, every
    assistant turn and tool result of that reply. Concatenated in order, they are the history
    sent with the next request.
    """

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # "user" or "assistant"
    text: Mapped[str] = mapped_column(Text, default="")
    api_messages: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="done")  # running, done, error
    error: Mapped[str | None] = mapped_column(String(32))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chat: Mapped[Chat] = relationship(back_populates="messages")


class UsageRecord(Base):
    """Cost of one Claude API call made with the user's key. Kept when a chat is deleted, so the
    spend shown in the panel never goes down; removed only with the account."""

    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_records_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32), default="chat")
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
