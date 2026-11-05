"""Template rendering helpers."""

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.auth import is_owner_email
from app.config import get_settings
from app.i18n import gettext
from app.models import User

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["_"] = gettext


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def render(request: Request, template: str, user: User | None = None, status_code: int = 200,
           **ctx: object):
    context = {
        "user": user,
        "is_owner": bool(user and is_owner_email(user.email)),
        "lang": get_settings().ui_locale,
        **ctx,
    }
    return templates.TemplateResponse(request, template, context, status_code=status_code)
