"""Application entry point: `uvicorn app.main:app`."""

import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.auth import NotAuthenticated, NotOwner
from app.config import get_settings
from app.db import get_engine
from app.routes import account, admin, chat, login, panel, rules
from app.web import is_htmx, render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")),
              name="static")
    for r in (login.router, panel.router, chat.router, rules.router, account.router,
              admin.router):
        app.include_router(r)

    @app.middleware("http")
    async def guard_and_log(request: Request, call_next):
        started = time.monotonic()
        # Reject cross-site form posts. Browsers always send Origin on POST; compare its host
        # with the Host the request arrived at (works behind Railway's proxy without config).
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                log.warning("blocked cross-origin %s %s (origin=%s host=%s)", request.method,
                            request.url.path, origin, request.headers.get("host"))
                return PlainTextResponse("Forbidden", status_code=403)
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Not "no-referrer": with it browsers send "Origin: null" on form posts, which the check
        # above rejects. "same-origin" still never leaks URLs (login tokens) to other sites.
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        # Method and path only: query strings (login tokens) and bodies (API keys) never hit logs.
        log.info("%s %s %s %.0fms", request.method, request.url.path, response.status_code,
                 (time.monotonic() - started) * 1000)
        return response

    @app.exception_handler(NotAuthenticated)
    async def _not_authenticated(request: Request, exc: NotAuthenticated):
        if is_htmx(request):
            return PlainTextResponse("", status_code=401, headers={"HX-Redirect": "/login"})
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(NotOwner)
    async def _not_owner(request: Request, exc: NotOwner):
        return render(request, "not_found.html", status_code=404)

    @app.get("/healthz")
    def healthz():
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return JSONResponse({"ok": True})

    if not get_settings().app_encryption_key:
        log.error("APP_ENCRYPTION_KEY is not set: saving API keys will fail")
    return app


app = create_app()
