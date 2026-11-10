"""The questionnaire page of the setup skill, backed by our database (decision 0010)."""

import base64
import hashlib
import re
from functools import lru_cache

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from markupsafe import escape
from sqlalchemy.orm import Session

from app import chat as chats
from app import skills
from app.auth import require_user
from app.claude import ClaudeClient, get_claude_client
from app.db import get_db
from app.intake import get_questionnaire, set_document
from app.i18n import gettext as _
from app.models import Chat, User
from app.web import static_url

router = APIRouter(prefix="/questionnaire")

ASSET = ("jobsearch-setup", "assets/questionnaire.html")
BAR_MARKER = "<!--panel-bar-->"
BAR = BAR_MARKER  # replaced per request with the translated bar
MAX_ANSWERS_BYTES = 200_000


@lru_cache
def page() -> tuple[str, str]:
    """The skill's page as served, and its Content-Security-Policy.

    Served unchanged except: our storage shim and the panel's bar ("back to chat", "done") are
    added, and the Google Fonts links are removed (no requests to Google from the panel; the page
    has system-font fallbacks).
    """
    html = (skills.skills_dir() / ASSET[0] / ASSET[1]).read_text(encoding="utf-8")
    html = re.sub(r'<link[^>]+(fonts\.googleapis\.com|fonts\.gstatic\.com)[^>]*>\n?', "", html)
    shim = (f'<link rel="stylesheet" href="{static_url("questionnaire-bar.css")}">\n'
            f'<script src="{static_url("questionnaire-db.js")}"></script>\n')
    html = html.replace("<script>", shim + "<script>", 1)
    html = html.rstrip() + "\n" + BAR + "\n"
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
    hashes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode() + "'"
        for s in scripts
    )
    csp = ("default-src 'self'; img-src 'self' data:; "
           # The page sets a few style attributes from its own script.
           "style-src 'self' 'unsafe-inline'; "
           f"script-src 'self' {hashes}; connect-src 'self'; "
           "frame-ancestors 'none'; form-action 'self'")
    return html, csp


def bar_html() -> str:
    """The panel's bar under the page: back to the chat, and "done" (decision 0010)."""
    return (
        '<nav class="jsk-bar" aria-label="panel">'
        f'<a class="jsk-back" href="/questionnaire/back">← {escape(_("Back to the chat"))}</a>'
        '<form method="post" action="/questionnaire/done" data-jsk-done>'
        f'<button type="submit">{escape(_("Done, tell the assistant"))}</button></form>'
        '</nav>'
    )


@router.get("")
def questionnaire_page(user: User = Depends(require_user)):
    html, csp = page()
    return HTMLResponse(html.replace(BAR_MARKER, bar_html()),
                        headers={"Content-Security-Policy": csp, "Cache-Control": "no-store"})


def _questionnaire_chat(db: Session, user: User):
    q = get_questionnaire(db, user)
    return chats.get_chat(db, user, q.chat_id) if q is not None and q.chat_id else None


@router.get("/back")
def back_to_chat(user: User = Depends(require_user), db: Session = Depends(get_db)):
    chat = _questionnaire_chat(db, user)
    return RedirectResponse(f"/chats/{chat.id}" if chat else "/chats", status_code=303)


@router.post("/done")
def questionnaire_done(user: User = Depends(require_user), db: Session = Depends(get_db),
                       client: ClaudeClient = Depends(get_claude_client),
                       runner: chats.Runner = Depends(chats.get_runner)):
    """Returns to the chat the questionnaire came from and tells the assistant it is filled in."""
    if user.api_key is None:
        return RedirectResponse("/settings/key", status_code=303)
    text = _("I filled in the questionnaire")
    chat = _questionnaire_chat(db, user)
    if chat is None:
        chat = Chat(user=user)
        db.add(chat)
    elif chats.is_running(chat):
        return RedirectResponse(f"/chats/{chat.id}", status_code=303)
    reply = chats.start_reply(db, user, chat, text)
    runner.submit(chats.reply_job(reply.id, client))
    return RedirectResponse(f"/chats/{chat.id}", status_code=303)


@router.get("/data/{name}")
def read_document(name: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if name not in ("prefill", "answers"):
        return JSONResponse({"error": "not found"}, status_code=404)
    q = get_questionnaire(db, user)
    data = getattr(q, name) if q is not None else None
    return {"exists": data is not None, "data": data}


@router.put("/data/answers")
def write_answers(request: Request, payload: dict = Body(...),
                  user: User = Depends(require_user), db: Session = Depends(get_db)):
    length = request.headers.get("content-length") or "0"
    if not length.isdigit() or int(length) > MAX_ANSWERS_BYTES:
        return JSONResponse({"error": "too large"}, status_code=413)
    if not isinstance(payload.get("values", {}), dict):
        return JSONResponse({"error": "bad data"}, status_code=400)
    set_document(db, user, "answers", payload)
    return {"ok": True}
