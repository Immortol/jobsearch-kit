"""The questionnaire page of the setup skill, backed by our database (decision 0010)."""

import base64
import hashlib
import re
from functools import lru_cache

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app import skills
from app.auth import require_user
from app.db import get_db
from app.intake import get_questionnaire, set_document
from app.models import User

router = APIRouter(prefix="/questionnaire")

ASSET = ("jobsearch-setup", "assets/questionnaire.html")
SHIM = '<script src="/static/questionnaire-db.js"></script>\n'
MAX_ANSWERS_BYTES = 200_000


@lru_cache
def page() -> tuple[str, str]:
    """The skill's page as served, and its Content-Security-Policy.

    Served unchanged except: our storage shim is loaded first, and the Google Fonts links are
    removed (no requests to Google from the panel; the page has system-font fallbacks).
    """
    html = (skills.skills_dir() / ASSET[0] / ASSET[1]).read_text(encoding="utf-8")
    html = re.sub(r'<link[^>]+(fonts\.googleapis\.com|fonts\.gstatic\.com)[^>]*>\n?', "", html)
    html = html.replace("<script>", SHIM + "<script>", 1)
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


@router.get("")
def questionnaire_page(user: User = Depends(require_user)):
    html, csp = page()
    return HTMLResponse(html, headers={"Content-Security-Policy": csp,
                                       "Cache-Control": "no-store"})


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
