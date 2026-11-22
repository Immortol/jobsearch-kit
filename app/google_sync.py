"""What the panel does in the person's Google account (decision 0012): the Jobsearch folder, a
folder per vacancy with its package, the tracker sheet, Gmail drafts with the package attached."""

import logging
import threading
import time
from collections.abc import Callable
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app import vacancies as vac
from app.db import get_sessionmaker
from app.google import FOLDER, SPREADSHEET, Google, GoogleError, get_google
from app.models import GoogleAccount, User, Vacancy, utcnow
from app.security import decrypt_secret

log = logging.getLogger("app.google")

ROOT_NAME = "Jobsearch"
APPLICATIONS_NAME = "Applications"
SHEET_NAME = "Jobsearch — tracker"
TRACKER_HEADER = ["Date", "Company", "Role", "Location", "Salary", "Score", "Status",
                  "Next step", "How to apply", "Deadline", "Link", "Notes"]
SHEET_NOTE = "Updated by the Jobsearch Kit panel. Edits here are overwritten: change things in the panel."
SYNC_DELAY = 3.0  # seconds: several changes in a row make one sheet update


def account(db: Session, user: User) -> GoogleAccount | None:
    return db.get(GoogleAccount, user.id)


def _token(g: Google, acc: GoogleAccount) -> str:
    return g.access_token(decrypt_secret(acc.encrypted_refresh_token))


def _fail(db: Session, acc: GoogleAccount, exc: GoogleError) -> None:
    acc.last_error = ("revoked" if exc.revoked else str(exc))[:300]
    db.flush()
    log.warning("Google sync failed for user %s: %s", acc.user_id, exc)


def ensure_layout(db: Session, g: Google, acc: GoogleAccount, token: str) -> None:
    """Jobsearch/ with Applications/ and the tracker sheet; recreated if the person deleted them."""
    if not g.exists(token, acc.root_folder_id):
        acc.root_folder_id = g.create_file(token, ROOT_NAME, FOLDER)
        acc.applications_folder_id = acc.sheet_id = None
    if not g.exists(token, acc.applications_folder_id):
        acc.applications_folder_id = g.create_file(token, APPLICATIONS_NAME, FOLDER,
                                                   acc.root_folder_id)
    if not g.exists(token, acc.sheet_id):
        acc.sheet_id = g.create_file(token, SHEET_NAME, SPREADSHEET, acc.root_folder_id)
    db.flush()


def folder_name(v: Vacancy) -> str:
    return " – ".join(x for x in (v.company, v.role) if x)[:150] or f"Vacancy {v.id}"


def sync_package(db: Session, user: User, v: Vacancy, g: Google | None = None) -> bool:
    """Puts the vacancy's package into Jobsearch/Applications/<Company – Role>/."""
    acc = account(db, user)
    files = vac.package_files(db, user, v)
    if acc is None or not files:
        return False
    g = g or get_google()
    try:
        token = _token(g, acc)
        ensure_layout(db, g, acc, token)
        if not g.exists(token, v.drive_folder_id):
            v.drive_folder_id = g.create_file(token, folder_name(v), FOLDER,
                                              acc.applications_folder_id)
        present = g.children(token, v.drive_folder_id)
        for f in files:
            g.upload(token, v.drive_folder_id, f.filename, f.content_type, f.data,
                     file_id=present.get(f.filename))
        acc.last_error = None
        db.flush()
        return True
    except GoogleError as exc:
        _fail(db, acc, exc)
        return False


def tracker_rows(db: Session, user: User) -> list[list]:
    rows: list[list] = [[SHEET_NOTE], TRACKER_HEADER]
    for v in vac.list_vacancies(db, user, flt="all", limit=100_000):
        rows.append([v.created_at.date().isoformat(), v.company, v.role, v.location, v.salary,
                     v.score or "", v.status, v.next_step, v.apply_how, v.deadline, v.url or "",
                     v.notes[:2000]])
    return rows


def sync_tracker(db: Session, user: User, g: Google | None = None) -> bool:
    acc = account(db, user)
    if acc is None:
        return False
    g = g or get_google()
    try:
        token = _token(g, acc)
        ensure_layout(db, g, acc, token)
        g.write_sheet(token, acc.sheet_id, tracker_rows(db, user))
        acc.synced_at, acc.last_error = utcnow(), None
        db.flush()
        return True
    except GoogleError as exc:
        _fail(db, acc, exc)
        return False


# --- background updates --------------------------------------------------------------------

def _default_submit(fn: Callable[[], None]) -> None:
    from app.chat import get_runner
    get_runner().submit(fn)


submit: Callable[[Callable[[], None]], None] = _default_submit
_pending: dict[int, float] = {}
_pending_lock = threading.Lock()


def tracker_changed(db: Session, user: User) -> None:
    """Schedules a sheet update a few seconds from now (after the caller's commit)."""
    if account(db, user) is None:
        return
    user_id = user.id
    with _pending_lock:
        _pending[user_id] = time.monotonic()

    def job() -> None:
        if SYNC_DELAY:
            time.sleep(SYNC_DELAY)
        with _pending_lock:
            started = _pending.get(user_id)
            if started is None or time.monotonic() - started < SYNC_DELAY:
                return  # a newer change will run its own update
            _pending.pop(user_id, None)
        with get_sessionmaker()() as s:
            u = s.get(User, user_id)
            if u is not None:
                sync_tracker(s, u)
                s.commit()

    submit(job)


def package_changed(user_id: int, vacancy_id: int) -> None:
    def job() -> None:
        with get_sessionmaker()() as s:
            u, v = s.get(User, user_id), s.get(Vacancy, vacancy_id)
            if u is not None and v is not None and account(s, u) is not None:
                sync_package(s, u, v)
                s.commit()
    submit(job)


# --- Gmail drafts ------------------------------------------------------------------------------

def create_draft(db: Session, user: User, v: Vacancy, to: str, subject: str, body: str,
                 attach: bool = True, g: Google | None = None) -> str:
    """Creates a draft in the person's Gmail; returns a link to it. Never sends."""
    acc = account(db, user)
    if acc is None:
        raise GoogleError("not connected")
    msg = EmailMessage()
    if to:
        msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attach:
        for f in vac.package_files(db, user, v):
            maintype, _, subtype = f.content_type.partition("/")
            msg.add_attachment(f.data, maintype=maintype, subtype=subtype or "octet-stream",
                               filename=f.filename)
    g = g or get_google()
    try:
        draft = g.create_draft(_token(g, acc), msg)
    except GoogleError as exc:
        _fail(db, acc, exc)
        raise
    message_id = (draft.get("message") or {}).get("id", "")
    v.draft_url = f"https://mail.google.com/mail/u/0/#drafts?compose={message_id}"
    db.flush()
    return v.draft_url
