"""Invitations page, owner only (decision 0005)."""

import logging

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth
from app.db import get_db
from app.email import EmailError, EmailSender, get_email_sender, invite_email
from app.models import Invite, User
from app.routes.login import _looks_like_email
from app.security import normalize_email
from app.web import is_htmx, render

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


def _page(request: Request, db: Session, owner: User, status_code: int = 200, **ctx):
    invites = list(db.scalars(select(Invite).order_by(Invite.created_at)))
    joined = set(db.scalars(select(User.email)))
    name = "_invites.html" if is_htmx(request) else "invites.html"
    return render(request, name, user=owner, invites=invites, joined=joined,
                  status_code=status_code, **ctx)


@router.get("/invites")
def invites(request: Request, owner: User = Depends(auth.require_owner),
            db: Session = Depends(get_db)):
    return _page(request, db, owner)


@router.post("/invites")
def invite_add(request: Request, email: str = Form(""),
               owner: User = Depends(auth.require_owner), db: Session = Depends(get_db),
               sender: EmailSender = Depends(get_email_sender)):
    email = normalize_email(email)
    if not _looks_like_email(email):
        return _page(request, db, owner, 400, status="bad_email", target=email)
    if auth.is_owner_email(email) or db.get(Invite, email):
        return _page(request, db, owner, status="exists", target=email)
    db.add(Invite(email=email, invited_by=owner.email))
    db.flush()
    try:
        sender.send(invite_email(email))
    except EmailError:
        log.exception("invite email failed")
        return _page(request, db, owner, status="added_no_email", target=email)
    return _page(request, db, owner, status="added", target=email)


@router.post("/invites/revoke")
def invite_revoke(request: Request, email: str = Form(""),
                  owner: User = Depends(auth.require_owner), db: Session = Depends(get_db)):
    email = normalize_email(email)
    invite = db.get(Invite, email)
    if invite is not None:
        db.delete(invite)
        auth.delete_user_everything(db, email)
        db.flush()
    return _page(request, db, owner, status="revoked", target=email)
