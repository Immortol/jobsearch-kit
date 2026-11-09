"""Login links, sessions and access rules (decision 0005)."""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Invite, LoginToken, User, UserSession
from app.security import hash_token, new_token, normalize_email

SESSION_COOKIE = "jsk_session"


class NotAuthenticated(Exception):
    pass


class NotOwner(Exception):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def is_owner_email(email: str) -> bool:
    owner = get_settings().owner_email
    return bool(owner) and normalize_email(email) == owner


def is_allowed(db: Session, email: str) -> bool:
    email = normalize_email(email)
    return is_owner_email(email) or db.get(Invite, email) is not None


def recent_link_count(db: Session, email: str) -> int:
    since = now() - timedelta(hours=1)
    return db.scalar(
        select(func.count()).select_from(LoginToken)
        .where(LoginToken.email == email, LoginToken.created_at >= since)
    ) or 0


MAX_CODE_ATTEMPTS = 5


def _code_hash(token_hash: str, code: str) -> str:
    # Salted with the token's own hash, so equal codes in different emails hash differently.
    return hash_token(f"{token_hash}:{code}")


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code if ch.isdigit())


def create_login_token(db: Session, email: str) -> tuple[str, str]:
    """Returns (link token, 6-digit code). Both sign in once; using either uses up both."""
    token = new_token()
    code = f"{secrets.randbelow(10**6):06d}"
    token_hash = hash_token(token)
    db.add(LoginToken(
        email=email,
        token_hash=token_hash,
        code_hash=_code_hash(token_hash, code),
        expires_at=now() + timedelta(minutes=get_settings().login_token_ttl_minutes),
    ))
    db.flush()
    return token, code


def _is_valid(row: LoginToken | None) -> bool:
    return row is not None and row.used_at is None and row.expires_at > now()


def find_valid_token(db: Session, token: str) -> LoginToken | None:
    row = db.scalar(select(LoginToken).where(LoginToken.token_hash == hash_token(token)))
    return row if _is_valid(row) else None


def consume_token(db: Session, token: str) -> User | None:
    """Marks the token used and returns the (possibly new) user, or None if not allowed."""
    row = find_valid_token(db, token)
    if row is None:
        return None
    return _consume(db, row)


def consume_code(db: Session, email: str, code: str) -> User | None:
    """Signs in with the code from the email. Every wrong code counts against all of the
    address's open links; after MAX_CODE_ATTEMPTS wrong codes they stop working."""
    email = normalize_email(email)
    code = normalize_code(code)
    rows = [r for r in db.scalars(
        select(LoginToken).where(LoginToken.email == email, LoginToken.used_at.is_(None))
    ) if _is_valid(r) and r.code_hash]
    if len(code) == 6:
        for row in rows:
            if secrets.compare_digest(row.code_hash, _code_hash(row.token_hash, code)):
                return _consume(db, row)
    for row in rows:
        row.code_attempts += 1
        if row.code_attempts >= MAX_CODE_ATTEMPTS:
            row.used_at = now()
    db.flush()
    return None


def _consume(db: Session, row: LoginToken) -> User | None:
    row.used_at = now()
    if not is_allowed(db, row.email):
        return None
    user = db.scalar(select(User).where(User.email == row.email))
    if user is None:
        user = User(email=row.email)
        db.add(user)
    user.last_login_at = now()
    db.flush()
    return user


def create_session(db: Session, user: User) -> str:
    sid = new_token()
    db.add(UserSession(
        user_id=user.id,
        session_hash=hash_token(sid),
        expires_at=now() + timedelta(days=get_settings().session_days),
    ))
    db.flush()
    return sid


def end_session(db: Session, sid: str | None) -> None:
    if sid:
        db.execute(delete(UserSession).where(UserSession.session_hash == hash_token(sid)))


def user_from_request(request: Request, db: Session) -> User | None:
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    s = db.scalar(select(UserSession).where(UserSession.session_hash == hash_token(sid)))
    if s is None or s.expires_at <= now():
        return None
    return s.user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    return user_from_request(request, db)


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_request(request, db)
    if user is None:
        raise NotAuthenticated()
    return user


def require_owner(user: User = Depends(require_user)) -> User:
    if not is_owner_email(user.email):
        raise NotOwner()
    return user


def delete_user_everything(db: Session, email: str) -> None:
    """Removes the account and all its data. Sessions, key and rules go via ON DELETE CASCADE."""
    email = normalize_email(email)
    db.execute(delete(User).where(User.email == email))
    db.execute(delete(LoginToken).where(LoginToken.email == email))
