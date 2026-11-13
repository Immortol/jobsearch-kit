"""Connecting the person's Google account (decisions 0008, 0012)."""

import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import google_sync
from app.auth import require_user
from app.config import get_settings
from app.db import get_db
from app.google import SCOPES, GoogleError, configured, email_from_id_token, get_google
from app.models import GoogleAccount, User
from app.security import decrypt_secret, encrypt_secret
from app.web import render

router = APIRouter()
STATE_COOKIE = "g_state"


def _drive_url(file_id: str | None, kind: str) -> str | None:
    if not file_id:
        return None
    if kind == "sheet":
        return f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
    return f"https://drive.google.com/drive/folders/{file_id}"


@router.get("/settings/google")
def settings_page(request: Request, connected: int = 0, error: str = "",
                  user: User = Depends(require_user), db: Session = Depends(get_db)):
    acc = google_sync.account(db, user)
    return render(request, "google.html", user=user, acc=acc, available=configured(),
                  connected=connected, error=error,
                  folder_url=_drive_url(acc.root_folder_id if acc else None, "folder"),
                  sheet_url=_drive_url(acc.sheet_id if acc else None, "sheet"))


@router.get("/google/connect")
def connect(user: User = Depends(require_user)):
    if not configured():
        return RedirectResponse("/settings/google", status_code=303)
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(get_google().auth_url(state), status_code=303)
    resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax",
                    secure=get_settings().secure_cookies, path="/google")
    return resp


@router.get("/google/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "",
             user: User = Depends(require_user), db: Session = Depends(get_db)):
    expected = request.cookies.get(STATE_COOKIE)
    if error or not code or not expected or not secrets.compare_digest(state, expected):
        return _back("cancelled" if error else "state")
    g = get_google()
    try:
        tokens = g.exchange(code)
    except GoogleError:
        return _back("exchange")
    granted = set(str(tokens.get("scope", "")).split())
    refresh = tokens.get("refresh_token")
    if not refresh:
        return _back("exchange")
    if not {s for s in SCOPES if s.startswith("https://")} <= granted:
        g.revoke(refresh)
        return _back("scopes")  # the person unticked Gmail or Drive on Google's screen
    acc = google_sync.account(db, user)
    if acc is not None:
        g.revoke(decrypt_secret(acc.encrypted_refresh_token))
        db.delete(acc)
        db.flush()
    acc = GoogleAccount(user_id=user.id, email=email_from_id_token(tokens.get("id_token")),
                        encrypted_refresh_token=encrypt_secret(refresh),
                        scopes=" ".join(sorted(granted)))
    db.add(acc)
    db.flush()
    google_sync.sync_tracker(db, user, g)
    resp = RedirectResponse("/settings/google?connected=1", status_code=303)
    resp.delete_cookie(STATE_COOKIE, path="/google")
    return resp


def _back(error: str) -> RedirectResponse:
    resp = RedirectResponse(f"/settings/google?error={error}", status_code=303)
    resp.delete_cookie(STATE_COOKIE, path="/google")
    return resp


@router.post("/google/disconnect")
def disconnect(user: User = Depends(require_user), db: Session = Depends(get_db)):
    acc = google_sync.account(db, user)
    if acc is not None:
        get_google().revoke(decrypt_secret(acc.encrypted_refresh_token))
        db.delete(acc)
    return RedirectResponse("/settings/google", status_code=303)


@router.post("/google/sync")
def sync_now(user: User = Depends(require_user), db: Session = Depends(get_db)):
    google_sync.sync_tracker(db, user)
    return RedirectResponse("/settings/google", status_code=303)
