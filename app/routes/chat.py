"""Chat with the assistant (decision 0009)."""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import chat as chats
from app.auth import require_user
from app.claude import ClaudeClient, get_claude_client
from app.db import get_db
from app.files import MAX_UPLOAD_BYTES, UploadError, read_upload, save_file
from app.i18n import gettext as _
from app.models import Chat, ChatMessage, User, UserFile
from app.rules import read_rule
from app.web import is_htmx, render

router = APIRouter(prefix="/chats")
setup_router = APIRouter()

SETUP_STATUS = "00_Setup_Status.md"
MAX_UPLOAD_READ = MAX_UPLOAD_BYTES + 1  # one byte over the limit, to detect "too big"


async def _attachment(db: Session, user: User, file: UploadFile | None) -> UserFile | None:
    """Stores an uploaded file; raises UploadError with a code for the message."""
    if file is None or not file.filename:
        return None
    data = await file.read(MAX_UPLOAD_READ)
    content_type, text = read_upload(file.filename, data)
    return save_file(db, user, kind="upload", filename=file.filename,
                     content_type=content_type, data=data, text=text)



def _message_view(m: ChatMessage, is_last: bool = True) -> dict:
    """What a message template needs, with live progress for a running reply."""
    view = {"m": m, "text": m.text, "label": None, "cost": m.cost_usd,
            "error_message": chats.failure_message(m.error), "is_last": is_last,
            "file_name": m.file.filename if m.file is not None else None}
    live = chats.LIVE.get(m.id) if m.status == "running" else None
    if live is not None:
        view["text"], view["label"], view["cost"] = live.snapshot()
    return view


def _check(user: User, text: str, has_file: bool) -> str | None:
    if user.api_key is None:
        return "no_key"
    if (not text and not has_file) or len(text) > chats.MAX_MESSAGE_CHARS:
        return "bad_message"
    return None


def _composer_error(request: Request, user: User, error: str, status: int):
    return render(request, "_composer_note.html", user=user, error=error, status_code=status)


@router.get("")
def chat_list(request: Request, user: User = Depends(require_user)):
    return render(request, "chats.html", user=user, chats=user.chats)


@router.post("")
async def chat_create(request: Request, message: str = Form(""),
                      file: UploadFile | None = File(None),
                      user: User = Depends(require_user), db: Session = Depends(get_db),
                      client: ClaudeClient = Depends(get_claude_client),
                      runner: chats.Runner = Depends(chats.get_runner)):
    text = message.strip()
    error = _check(user, text, bool(file and file.filename))
    attachment = None
    if error is None:
        try:
            attachment = await _attachment(db, user, file)
        except UploadError as exc:
            error = "file_" + exc.code
    if error is not None:
        db.rollback()
        return render(request, "chats.html", user=user, chats=user.chats, error=error,
                      status_code=400)
    return _start_chat(db, user, text, attachment, client, runner)


def _start_chat(db: Session, user: User, text: str, attachment: UserFile | None,
                client: ClaudeClient, runner: chats.Runner) -> RedirectResponse:
    chat = Chat(user=user)
    db.add(chat)
    reply = chats.start_reply(db, user, chat, text, attachment)
    runner.submit(chats.reply_job(reply.id, client))
    return RedirectResponse(f"/chats/{chat.id}", status_code=303)


@setup_router.post("/setup")
def setup_start(request: Request, user: User = Depends(require_user),
                db: Session = Depends(get_db), client: ClaudeClient = Depends(get_claude_client),
                runner: chats.Runner = Depends(chats.get_runner)):
    """Starts a setup meeting: a new chat whose first message asks for setup (decision 0010)."""
    if user.api_key is None:
        return RedirectResponse("/settings/key", status_code=303)
    started = read_rule(db, user, SETUP_STATUS) is not None
    text = _("Let's continue the setup.") if started else \
        _("I want to set up my job search.")
    return _start_chat(db, user, text, None, client, runner)


def _owned_chat(db: Session, user: User, chat_id: int) -> Chat | None:
    chat = chats.get_chat(db, user, chat_id)
    if chat is not None:
        for m in chat.messages:
            chats.refresh_orphan(db, m)
    return chat


@router.get("/{chat_id}")
def chat_view(request: Request, chat_id: int, user: User = Depends(require_user),
              db: Session = Depends(get_db)):
    chat = _owned_chat(db, user, chat_id)
    if chat is None:
        return render(request, "not_found.html", user=user, status_code=404)
    return render(request, "chat.html", user=user, chat=chat,
                  messages=[_message_view(m, i == len(chat.messages) - 1)
                            for i, m in enumerate(chat.messages)],
                  running=chats.is_running(chat))


@router.post("/{chat_id}/messages")
async def chat_send(request: Request, chat_id: int, message: str = Form(""),
                    file: UploadFile | None = File(None),
                    user: User = Depends(require_user), db: Session = Depends(get_db),
                    client: ClaudeClient = Depends(get_claude_client),
                    runner: chats.Runner = Depends(chats.get_runner)):
    chat = _owned_chat(db, user, chat_id)
    if chat is None:
        return render(request, "not_found.html", user=user, status_code=404)
    text = message.strip()
    error = _check(user, text, bool(file and file.filename))
    if error is None and chats.is_running(chat):
        return _composer_error(request, user, "busy", 409)
    attachment = None
    if error is None:
        try:
            attachment = await _attachment(db, user, file)
        except UploadError as exc:
            error = "file_" + exc.code
    if error is not None:
        return _composer_error(request, user, error, 400)
    reply = chats.start_reply(db, user, chat, text, attachment)
    user_message = chat.messages[-2]
    runner.submit(chats.reply_job(reply.id, client))
    if not is_htmx(request):
        return RedirectResponse(f"/chats/{chat.id}", status_code=303)
    db.refresh(reply)
    return render(request, "_new_messages.html", user=user, chat=chat,
                  messages=[_message_view(user_message), _message_view(reply)])


@router.get("/{chat_id}/messages/{message_id}")
def message_poll(request: Request, chat_id: int, message_id: int,
                 user: User = Depends(require_user), db: Session = Depends(get_db)):
    chat = chats.get_chat(db, user, chat_id)
    message = db.get(ChatMessage, message_id)
    if chat is None or message is None or message.chat_id != chat.id:
        return render(request, "not_found.html", user=user, status_code=404)
    chats.refresh_orphan(db, message)
    return render(request, "_message.html", user=user, chat=chat, v=_message_view(message),
                  finished_now=message.status != "running")


@router.post("/{chat_id}/delete")
def chat_delete(request: Request, chat_id: int, user: User = Depends(require_user),
                db: Session = Depends(get_db)):
    chat = chats.get_chat(db, user, chat_id)
    if chat is not None:
        db.delete(chat)
        db.flush()
    return RedirectResponse("/chats", status_code=303)
