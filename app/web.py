"""Template rendering helpers."""

import hashlib
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import object_session

from app.auth import is_owner_email
from app.chat import spend as user_spend
from app.config import get_settings
from app.i18n import gettext
from app.markdown import render_markdown
from app.models import User

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["_"] = gettext
templates.env.filters["markdown"] = render_markdown


def money(value: object) -> str:
    """$0.012 for small sums (a single reply), $1.23 otherwise."""
    amount = Decimal(str(value or 0))
    if amount and amount < Decimal("0.1"):
        return f"${amount:.3f}"
    return f"${amount:.2f}"


templates.env.filters["money"] = money

STATIC_DIR = Path(__file__).parent / "static"


@lru_cache
def static_url(name: str) -> str:
    """`/static/<name>?v=<content hash>`: browsers pick up a new version right after a deploy."""
    digest = hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:10]
    return f"/static/{name}?v={digest}"


templates.env.globals["static"] = static_url


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def render(request: Request, template: str, user: User | None = None, status_code: int = 200,
           **ctx: object):
    spend = None
    if user is not None and (db := object_session(user)) is not None:
        spend = user_spend(db, user)
    context = {
        "user": user,
        "spend": spend,
        "is_owner": bool(user and is_owner_email(user.email)),
        "lang": get_settings().ui_locale,
        **ctx,
    }
    return templates.TemplateResponse(request, template, context, status_code=status_code)
