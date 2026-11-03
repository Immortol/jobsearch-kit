"""Email-link login (decision 0005)."""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import auth
from app.config import get_settings
from app.db import get_db
from app.email import EmailError, EmailSender, get_email_sender, login_email
from app.models import User
from app.security import normalize_email
from app.web import render

log = logging.getLogger(__name__)
router = APIRouter()


def _looks_like_email(value: str) -> bool:
    local, _, domain = value.partition("@")
    return bool(local) and "." in domain and len(value) <= 320 and " " not in value


@router.get("/login")
def login_form(request: Request, user: User | None = Depends(auth.optional_user)):
    if user:
        return RedirectResponse("/panel", status_code=303)
    return render(request, "login.html")


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(""),
    db: Session = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
):
    email = normalize_email(email)
    if not _looks_like_email(email):
        return render(request, "login.html", email=email, error="bad_email", status_code=400)

    # Same answer whether or not the address is invited, so the form reveals nothing.
    if auth.is_allowed(db, email) and \
            auth.recent_link_count(db, email) < get_settings().login_links_per_hour:
        token = auth.create_login_token(db, email)
        link = f"{get_settings().app_base_url}/auth?token={token}"
        try:
            sender.send(login_email(email, link))
        except EmailError:
            log.exception("login email failed")
            db.rollback()
            return render(request, "login.html", email=email, error="send_failed",
                          status_code=503)
    return render(request, "check_email.html", email=email)


@router.get("/auth")
def auth_confirm(request: Request, token: str = "", db: Session = Depends(get_db)):
    # Only shows a button: mail scanners that prefetch links must not use the token up.
    if not token or auth.find_valid_token(db, token) is None:
        return render(request, "link_invalid.html", status_code=400)
    return render(request, "auth_confirm.html", token=token)


@router.post("/auth")
def auth_submit(request: Request, token: str = Form(""), db: Session = Depends(get_db)):
    user = auth.consume_token(db, token) if token else None
    if user is None:
        db.commit()  # keep the token marked as used even when access was revoked meanwhile
        return render(request, "link_invalid.html", status_code=400)
    sid = auth.create_session(db, user)
    target = "/panel" if user.api_key else "/settings/key"
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie(
        auth.SESSION_COOKIE, sid,
        max_age=get_settings().session_days * 86400,
        httponly=True, secure=get_settings().secure_cookies, samesite="lax", path="/",
    )
    return resp


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    auth.end_session(db, request.cookies.get(auth.SESSION_COOKIE))
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE, path="/")
    return resp
