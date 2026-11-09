"""Main panel and API key settings."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.anthropic_keys import KeyCheck, KeyChecker, get_key_checker, looks_like_api_key
from app.auth import optional_user, require_user
from app.db import get_db
from app.models import ApiKey, User, utcnow
from app.rules import list_rules
from app.security import encrypt_secret
from app.web import is_htmx, render

router = APIRouter()


@router.get("/")
def root(user: User | None = Depends(optional_user)):
    return RedirectResponse("/panel" if user else "/login", status_code=303)


@router.get("/panel")
def panel(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return render(request, "panel.html", user=user, rules_count=len(list_rules(db, user)))


def _key_page(request: Request, user: User, status: str | None = None, status_code: int = 200):
    name = "_key_card.html" if is_htmx(request) else "key.html"
    return render(request, name, user=user, status=status, status_code=status_code)


@router.get("/settings/key")
def key_form(request: Request, user: User = Depends(require_user)):
    return _key_page(request, user)


@router.post("/settings/key")
def key_save(
    request: Request,
    api_key: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    checker: KeyChecker = Depends(get_key_checker),
):
    api_key = api_key.strip()
    if not looks_like_api_key(api_key):
        return _key_page(request, user, "bad_format", 400)
    result = checker(api_key)
    if result is KeyCheck.INVALID:
        return _key_page(request, user, "invalid", 400)
    if result is KeyCheck.UNAVAILABLE:
        return _key_page(request, user, "unavailable", 503)

    row = user.api_key or ApiKey(user_id=user.id)
    row.encrypted_key = encrypt_secret(api_key)
    row.last4 = api_key[-4:]
    row.verified_at = utcnow()
    db.add(row)
    db.flush()
    db.refresh(user)
    return _key_page(request, user, "saved")


@router.post("/settings/key/delete")
def key_delete(request: Request, user: User = Depends(require_user),
               db: Session = Depends(get_db)):
    if user.api_key:
        db.delete(user.api_key)
        db.flush()
        db.refresh(user)
    return _key_page(request, user, "deleted")
