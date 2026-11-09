"""Account page: data export and deletion (GDPR from day one)."""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app import auth
from app.auth import require_user
from app.chat import spend
from app.db import get_db
from app.models import User, utcnow
from app.rules import list_rules
from app.web import render

router = APIRouter(prefix="/account")


@router.get("")
def account(request: Request, user: User = Depends(require_user)):
    return render(request, "account.html", user=user)


def export_data(db: Session, user: User) -> dict:
    key = user.api_key
    spent = spend(db, user)
    return {
        "exported_at": utcnow().isoformat(),
        "email": user.email,
        "created_at": user.created_at.isoformat(),
        "api_key": None if key is None else {
            "last4": key.last4, "verified_at": key.verified_at.isoformat(),
            "note": "The key itself is not exported.",
        },
        "spend_usd": {"this_month": str(spent.month), "total": str(spent.total)},
        "chats": [
            {"title": c.title, "created_at": c.created_at.isoformat(), "messages": [
                {"role": m.role, "text": m.text, "created_at": m.created_at.isoformat(),
                 "cost_usd": str(m.cost_usd)} for m in c.messages
            ]} for c in user.chats
        ],
        "rules": [
            {"name": r.name, "content": r.content, "updated_at": r.updated_at.isoformat()}
            for r in list_rules(db, user)
        ],
    }


@router.get("/export")
def account_export(user: User = Depends(require_user), db: Session = Depends(get_db)):
    body = json.dumps(export_data(db, user), ensure_ascii=False, indent=2)
    return Response(
        body, media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="jobsearch-kit-export.json"'},
    )


@router.post("/delete")
def account_delete(request: Request, confirm: str = Form(""),
                   user: User = Depends(require_user), db: Session = Depends(get_db)):
    if confirm != "yes":
        return render(request, "account.html", user=user, error="confirm", status_code=400)
    auth.delete_user_everything(db, user.email)
    resp = RedirectResponse("/login?deleted=1", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE, path="/")
    return resp
