"""Chat with the assistant (decision 0009)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import chat as chats
from app.auth import require_user
from app.claude import ClaudeClient, get_claude_client
from app.db import get_db
from app.models import Chat, ChatMessage, User
from app.web import is_htmx, render

router = APIRouter(prefix="/chats")


def _message_view(m: ChatMessage) -> dict:
    """What a message template needs, with live progress for a running reply."""
    view = {"m": m, "text": m.text, "label": None, "cost": m.cost_usd,
            "error_message": chats.failure_message(m.error)}
    live = chats.LIVE.get(m.id) if m.status == "running" else None
    if live is not None:
        view["text"], view["label"], view["cost"] = live.snapshot()
    return view


def _composer_error(request: Request, user: User, error: str, status: int):
    return render(request, "_composer_note.html", user=user, error=error, status_code=status)


@router.get("")
def chat_list(request: Request, user: User = Depends(require_user)):
    return render(request, "chats.html", user=user, chats=user.chats)


@router.post("")
def chat_create(request: Request, message: str = Form(""), user: User = Depends(require_user),
                db: Session = Depends(get_db), client: ClaudeClient = Depends(get_claude_client),
                runner: chats.Runner = Depends(chats.get_runner)):
    text = message.strip()
    if user.api_key is None:
        return render(request, "chats.html", user=user, chats=user.chats, error="no_key",
                      status_code=400)
    if not text or len(text) > chats.MAX_MESSAGE_CHARS:
        return render(request, "chats.html", user=user, chats=user.chats, error="bad_message",
                      status_code=400)
    chat = Chat(user=user)
    db.add(chat)
    reply = chats.start_reply(db, user, chat, text)
    runner.submit(chats.reply_job(reply.id, client))
    return RedirectResponse(f"/chats/{chat.id}", status_code=303)


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
                  messages=[_message_view(m) for m in chat.messages],
                  running=chats.is_running(chat))


@router.post("/{chat_id}/messages")
def chat_send(request: Request, chat_id: int, message: str = Form(""),
              user: User = Depends(require_user), db: Session = Depends(get_db),
              client: ClaudeClient = Depends(get_claude_client),
              runner: chats.Runner = Depends(chats.get_runner)):
    chat = _owned_chat(db, user, chat_id)
    if chat is None:
        return render(request, "not_found.html", user=user, status_code=404)
    text = message.strip()
    if user.api_key is None:
        return _composer_error(request, user, "no_key", 400)
    if not text or len(text) > chats.MAX_MESSAGE_CHARS:
        return _composer_error(request, user, "bad_message", 400)
    if chats.is_running(chat):
        return _composer_error(request, user, "busy", 409)
    reply = chats.start_reply(db, user, chat, text)
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
