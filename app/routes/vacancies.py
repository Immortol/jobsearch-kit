"""The vacancies feed, card pages and the tracker (decision 0011)."""

import csv
import io
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app import chat as chats
from app import google_sync
from app import vacancies as vac
from app.auth import require_user
from app.claude import ClaudeClient, get_claude_client
from app.db import get_db
from app.models import VACANCY_STATUSES, User, Vacancy
from app.routes.chat import _message_view
from app.files import latest_cv
from app.web import render

router = APIRouter()

MAX_PASTE_CHARS = 30_000


def _(message: str) -> str:
    """Marks a string for the UI catalog; templates translate it."""
    return message


STATUS_LABELS = {
    "new": _("Assessing"),
    "assessed": _("Assessed"),
    "prepared": _("Documents ready"),
    "applied": _("Applied"),
    "reply": _("Reply"),
    "interview": _("Interview"),
    "offer": _("Offer"),
    "rejected": _("Rejected"),
    "not_fit": _("Not a fit"),
    "closed": _("Closed"),
}
FILTER_LABELS = {
    "all": _("All"),
    "good": _("4–5"),
    "progress": _("In progress"),
    "not_fit": _("Not a fit"),
}
DOCUMENT_LABELS = {
    "letter_pdf": _("Cover letter, PDF"),
    "letter_docx": _("Cover letter, Word"),
    "vcv_pdf": _("CV for this vacancy, PDF"),
    "vcv_docx": _("CV for this vacancy, Word"),
}


SCORE_LINE = re.compile(r"^\W*[1-5]\s*/\s*5\b")


def card_summary(text: str) -> str:
    """The assessment without its first line when that line repeats the card's header
    ("4/5 · Company · Role · …")."""
    lines = (text or "").strip().splitlines()
    if lines and SCORE_LINE.match(lines[0]):
        lines = lines[1:]
    return "\n".join(lines).strip()


def card_view(db: Session, v: Vacancy) -> dict:
    """What a card needs: its thread state, the latest answer, documents."""
    chat = vac.card_chat(db, v)
    messages = chat.messages if chat is not None else []
    for m in messages:
        chats.refresh_orphan(db, m)
    running = next((m for m in messages if m.status == "running"), None)
    last = next((m for m in reversed(messages) if m.role == "assistant"), None)
    live = chats.LIVE.get(running.id) if running is not None else None
    label = live.snapshot()[1] if live is not None else None
    docs = vac.latest_documents(db, v)
    return {
        "v": v, "chat": chat, "running": running is not None, "label": label,
        "title": vac.display_title(v), "status_label": STATUS_LABELS.get(v.status, v.status),
        "summary": card_summary(v.summary or (last.text if last is not None else "")),
        "error": chats.failure_message(last.error) if last is not None and
        last.status == "error" else None,
        "documents": [(DOCUMENT_LABELS[k], docs[k]) for k in DOCUMENT_LABELS if k in docs],
        "has_vacancy_cv": "vcv_pdf" in docs or "vcv_docx" in docs,
        "has_package": "letter_pdf" in docs or "vcv_pdf" in docs,
        "story": vac.story_chat(db, v),
    }


@router.get("/vacancies")
def feed(request: Request, q: str = "", f: str = "all", page: int = 0, added: int = 0,
         repeat: int = 0, user: User = Depends(require_user), db: Session = Depends(get_db)):
    f = f if f in vac.FILTERS else "all"
    page = max(0, page)
    rows = vac.list_vacancies(db, user, q=q, flt=f, offset=page * vac.PAGE_SIZE,
                              limit=vac.PAGE_SIZE + 1)
    return render(request, "vacancies.html", user=user, q=q, f=f, page=page,
                  cards=[card_view(db, v) for v in rows[:vac.PAGE_SIZE]],
                  more=len(rows) > vac.PAGE_SIZE, filters=FILTER_LABELS, added=added,
                  repeat=repeat, total=vac.count_vacancies(db, user))


@router.post("/vacancies")
def paste(request: Request, text: str = Form(""), user: User = Depends(require_user),
          db: Session = Depends(get_db), client: ClaudeClient = Depends(get_claude_client),
          runner: chats.Runner = Depends(chats.get_runner)):
    text = text.strip()[:MAX_PASTE_CHARS]
    if user.api_key is None:
        return RedirectResponse("/settings/key", status_code=303)
    if not text:
        return RedirectResponse("/vacancies", status_code=303)
    added = vac.add_from_paste(db, user, text)
    started = []
    for a in added:
        if a.message_text is not None:
            chat = vac.card_chat(db, a.vacancy)
            started.append(chats.start_reply(db, user, chat, a.message_text))
    for reply in started:
        runner.submit(chats.reply_job(reply.id, client))
    repeats = [a.vacancy for a in added if a.message_text is None]
    if len(added) == 1 and repeats:
        return RedirectResponse(f"/vacancies/{repeats[0].id}?repeat=1", status_code=303)
    return RedirectResponse(f"/vacancies?added={len(started)}&repeat={len(repeats)}",
                            status_code=303)


@router.get("/vacancies/{vacancy_id}/card")
def card_fragment(request: Request, vacancy_id: int, user: User = Depends(require_user),
                  db: Session = Depends(get_db)):
    v = vac.get_vacancy(db, user, vacancy_id)
    if v is None:
        return Response(status_code=404)
    view = card_view(db, v)
    return render(request, "_vacancy_card.html", user=user, c=view,
                  finished_now=not view["running"])


@router.get("/vacancies/{vacancy_id}")
def card_page(request: Request, vacancy_id: int, repeat: int = 0,
              user: User = Depends(require_user), db: Session = Depends(get_db)):
    v = vac.get_vacancy(db, user, vacancy_id)
    if v is None:
        return render(request, "not_found.html", user=user, status_code=404)
    view = card_view(db, v)
    messages = view["chat"].messages if view["chat"] is not None else []
    return render(request, "vacancy.html", user=user, c=view, repeat=repeat,
                  google=google_sync.account(db, user),
                  messages=[_message_view(m, i == len(messages) - 1)
                            for i, m in enumerate(messages)],
                  statuses=[(s, STATUS_LABELS[s]) for s in VACANCY_STATUSES if s != "new"],
                  master_cv=latest_cv(db, user))


def _back(request: Request, fallback: str) -> str:
    target = request.headers.get("referer") or ""
    host = request.headers.get("host") or ""
    # Only back to a page of the panel itself.
    for prefix in (f"https://{host}/", f"http://{host}/"):
        if target.startswith(prefix):
            return "/" + target[len(prefix):]
    return fallback


@router.get("/vacancies/{vacancy_id}/package.zip")
def package(vacancy_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    v = vac.get_vacancy(db, user, vacancy_id)
    if v is None or not vac.package_files(db, user, v):
        return Response("Not found", status_code=404)
    name, data = vac.build_package(db, user, v)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"',
                             "Cache-Control": "no-store"})


@router.post("/vacancies/{vacancy_id}/drive")
def drive_folder(vacancy_id: int, user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    v = vac.get_vacancy(db, user, vacancy_id)
    if v is None:
        return Response(status_code=404)
    google_sync.sync_package(db, user, v)
    return RedirectResponse(f"/vacancies/{v.id}", status_code=303)


@router.post("/vacancies/{vacancy_id}/status")
def change_status(request: Request, vacancy_id: int, status: str = Form(...),
                  user: User = Depends(require_user), db: Session = Depends(get_db)):
    v = vac.get_vacancy(db, user, vacancy_id)
    if v is None or status not in VACANCY_STATUSES:
        return Response(status_code=404)
    story = vac.set_status(db, user, v, status)
    db.flush()
    google_sync.tracker_changed(db, user)
    if story is not None:
        return RedirectResponse(f"/chats/{story.id}", status_code=303)
    return RedirectResponse(_back(request, f"/vacancies/{v.id}"), status_code=303)


@router.post("/vacancies/{vacancy_id}/story")
def story(vacancy_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    v = vac.get_vacancy(db, user, vacancy_id)
    if v is None:
        return Response(status_code=404)
    chat = vac.open_story(db, user, v)
    return RedirectResponse(f"/chats/{chat.id}", status_code=303)


@router.post("/vacancies/{vacancy_id}/delete")
def delete(vacancy_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    v = vac.get_vacancy(db, user, vacancy_id)
    if v is not None:
        for f in vac.vacancy_files(db, v):
            db.delete(f)
        db.delete(v)
        db.flush()
        google_sync.tracker_changed(db, user)
    return RedirectResponse("/vacancies", status_code=303)


@router.get("/tracker")
def tracker(request: Request, f: str = "progress", q: str = "",
            user: User = Depends(require_user), db: Session = Depends(get_db)):
    f = f if f in vac.FILTERS else "progress"
    rows = vac.list_vacancies(db, user, q=q, flt=f, limit=1000)
    return render(request, "tracker.html", user=user, rows=rows, f=f, q=q,
                  filters=FILTER_LABELS, labels=STATUS_LABELS,
                  statuses=[(s, STATUS_LABELS[s]) for s in VACANCY_STATUSES if s != "new"],
                  title=vac.display_title)


CSV_COLUMNS = ("created", "company", "role", "location", "salary", "score", "status",
               "next_step", "apply_how", "deadline", "link", "notes")


@router.get("/tracker.csv")
def tracker_csv(user: User = Depends(require_user), db: Session = Depends(get_db)):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for v in vac.list_vacancies(db, user, flt="all", limit=100_000):
        writer.writerow([v.created_at.date().isoformat(), v.company, v.role, v.location,
                         v.salary, v.score or "", v.status, v.next_step, v.apply_how,
                         v.deadline, v.url or "", v.notes])
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="tracker.csv"'})
