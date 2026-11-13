"""Chats: storing messages, running a reply in the background, live progress (decision 0009).

A reply runs in a worker thread of the web process, so it continues when the person closes the tab.
While it runs, its streamed text and current step live in memory (`LIVE`); the panel polls them
every second. When it ends, the result is saved to the database and the live entry is dropped.
"""

import base64
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import Progress, build_history, run_reply
from app.claude import ClaudeClient, ClaudeFailure
from app.config import get_settings
from app.db import get_sessionmaker
from app.files import PDF, get_file
from app.models import Chat, ChatMessage, UsageRecord, User, UserFile, utcnow
from app.security import decrypt_secret


def _(message: str) -> str:
    """Marks a string for the UI catalog; it is translated later, when the panel renders it."""
    return message

log = logging.getLogger("app.chat")

MAX_MESSAGE_CHARS = 20_000
TITLE_CHARS = 60

ERROR_INTERRUPTED = "interrupted"  # the server restarted while the reply was running
ERROR_NO_KEY = "no_key"
ERROR_INTERNAL = "internal"


# --- live progress ---------------------------------------------------------------------------

@dataclass
class LiveReply(Progress):
    text_parts: list[str] = field(default_factory=list)
    label: str = _("Thinking")
    cost: Decimal = Decimal(0)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def text(self, delta: str) -> None:
        with self.lock:
            self.text_parts.append(delta)

    def status(self, label: str) -> None:
        self.label = label

    def call_done(self, model: str, usage: dict, cost: Decimal) -> None:
        self.cost += cost

    def snapshot(self) -> tuple[str, str, Decimal]:
        with self.lock:
            return "".join(self.text_parts).strip(), self.label, self.cost


LIVE: dict[int, LiveReply] = {}


# --- running replies ---------------------------------------------------------------------------

class Runner:
    """Where replies run. The app uses a thread pool; tests run them inline."""

    def submit(self, fn: Callable[[], None]) -> None:
        raise NotImplementedError


class ThreadRunner(Runner):
    def __init__(self, workers: int):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="reply")

    def submit(self, fn: Callable[[], None]) -> None:
        self.pool.submit(fn)


@lru_cache
def get_runner() -> Runner:
    return ThreadRunner(get_settings().agent_workers)


def chat_title(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= TITLE_CHARS else one_line[:TITLE_CHARS - 1] + "…"


def is_running(chat: Chat) -> bool:
    return any(m.status == "running" for m in chat.messages)


def start_reply(db: Session, user: User, chat: Chat, text: str,
                attachment: UserFile | None = None) -> ChatMessage:
    """Saves the user's message and a running assistant message (committed, so the worker sees
    them). Returns the assistant message; the caller submits `reply_job` to the runner."""
    if not chat.title:
        chat.title = chat_title(text or (attachment.filename if attachment else ""))
    chat.updated_at = utcnow()
    content: list[dict] = []
    if attachment is not None:
        content.append({"type": "user_file", "file_id": attachment.id})
    if text:
        content.append({"type": "text", "text": text})
    db.add(ChatMessage(chat=chat, role="user", text=text,
                       file_id=attachment.id if attachment else None,
                       api_messages=[{"role": "user", "content": content}]))
    reply = ChatMessage(chat=chat, role="assistant", status="running")
    db.add(reply)
    db.commit()
    LIVE[reply.id] = LiveReply()
    return reply


def _record_usage(user_id: int, model: str, usage: dict, cost: Decimal) -> None:
    # Own session and commit: the spend is recorded even if the reply fails later.
    with get_sessionmaker()() as s:
        s.add(UsageRecord(user_id=user_id, model=model, purpose="chat", usage=usage,
                          cost_usd=cost))
        s.commit()


class _RecordingProgress(Progress):
    def __init__(self, live: LiveReply, user_id: int):
        self.live, self.user_id = live, user_id

    def text(self, delta: str) -> None:
        self.live.text(delta)

    def status(self, label: str) -> None:
        self.live.status(label)

    def call_done(self, model: str, usage: dict, cost: Decimal) -> None:
        self.live.call_done(model, usage, cost)
        _record_usage(self.user_id, model, usage, cost)


def reply_job(message_id: int, client: ClaudeClient) -> Callable[[], None]:
    def job() -> None:
        live = LIVE.setdefault(message_id, LiveReply())
        try:
            _run(message_id, client, live)
        except Exception:
            log.exception("reply %s failed", message_id)
            _finish_with_error(message_id, ERROR_INTERNAL)
        finally:
            LIVE.pop(message_id, None)
    return job


def _run(message_id: int, client: ClaudeClient, live: LiveReply) -> None:
    with get_sessionmaker()() as db:
        reply = db.get(ChatMessage, message_id)
        if reply is None or reply.status != "running":
            return
        chat = reply.chat
        user = chat.user
        if user.api_key is None:
            reply.status, reply.error, reply.finished_at = "error", ERROR_NO_KEY, utcnow()
            db.commit()
            return
        earlier = [m.api_messages for m in chat.messages
                   if m.id < reply.id and m.api_messages]
        result = run_reply(
            client=client, api_key=decrypt_secret(user.api_key.encrypted_key),
            model=get_settings().agent_model, db=db, user=user,
            history=build_history(earlier, lambda fid: file_block(db, user, fid)),
            progress=_RecordingProgress(live, user.id), chat_id=chat.id,
        )
        reply.choices = result.choices
        reply.text = result.text
        reply.api_messages = result.api_messages
        reply.cost_usd = result.cost
        reply.finished_at = utcnow()
        if result.error is not None:
            reply.status, reply.error = "error", result.error.value
        else:
            reply.status = "done"
            reply.error = "step_limit" if result.hit_step_limit else None
        chat.updated_at = utcnow()
        db.commit()


def file_block(db: Session, user: User, file_id: int) -> dict:
    """An attached file as the API sees it: a PDF document, or the extracted text."""
    f = get_file(db, user, file_id)
    if f is None:
        return {"type": "text", "text": "(an attached file that no longer exists)"}
    if f.content_type == PDF:
        return {"type": "document", "title": f.filename,
                "source": {"type": "base64", "media_type": PDF,
                           "data": base64.b64encode(f.data).decode()}}
    return {"type": "text",
            "text": f"Attached file «{f.filename}» (file id {f.id}):\n\n{f.text or ''}"}


def _finish_with_error(message_id: int, error: str) -> None:
    with get_sessionmaker()() as db:
        reply = db.get(ChatMessage, message_id)
        if reply is not None and reply.status == "running":
            reply.status, reply.error, reply.finished_at = "error", error, utcnow()
            db.commit()


def refresh_orphan(db: Session, message: ChatMessage) -> None:
    """A running message with no live entry belongs to a server that restarted mid-reply."""
    if message.status == "running" and message.id not in LIVE:
        db.refresh(message)
        if message.status == "running" and message.id not in LIVE:
            message.status, message.error, message.finished_at = \
                "error", ERROR_INTERRUPTED, utcnow()
            db.flush()


# --- reading -----------------------------------------------------------------------------------

def get_chat(db: Session, user: User, chat_id: int) -> Chat | None:
    chat = db.get(Chat, chat_id)
    return chat if chat is not None and chat.user_id == user.id else None


def failure_message(error: str | None) -> str | None:
    """English source strings, translated in the template."""
    return {
        ClaudeFailure.INVALID_KEY.value:
            _("Anthropic rejected your API key. Check it in the API key section."),
        ClaudeFailure.NO_PERMISSION.value:
            _("Your API key is not allowed to use this model. Check the key's workspace in the "
            "Anthropic console."),
        ClaudeFailure.BILLING.value:
            _("Anthropic refused the request because of billing: the balance is empty or the "
            "monthly limit is reached. Top up or raise the limit in the Anthropic console."),
        ClaudeFailure.RATE_LIMIT.value:
            _("Too many requests to Anthropic right now. Please try again in a minute."),
        ClaudeFailure.UNAVAILABLE.value:
            _("Anthropic is not responding right now. Please try again in a few minutes."),
        ClaudeFailure.TOO_LARGE.value:
            _("This chat has become too long. Start a new chat."),
        ClaudeFailure.OTHER.value:
            _("Something went wrong while asking Claude. Please try again."),
        ERROR_INTERRUPTED:
            _("The reply was interrupted by a server restart. Please send it again."),
        ERROR_NO_KEY: _("Add your Anthropic API key first."),
        ERROR_INTERNAL: _("Something went wrong on our side. Please try again."),
        "step_limit": _("The assistant stopped after too many steps, to protect your balance. "
                      "Ask it to continue if needed."),
    }.get(error or "")


# --- spend ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Spend:
    month: Decimal
    total: Decimal


def spend(db: Session, user: User, now: datetime | None = None) -> Spend:
    now = now or utcnow()
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    month_end = datetime(now.year + now.month // 12, now.month % 12 + 1, 1, tzinfo=UTC)
    total, month = db.execute(
        select(
            func.coalesce(func.sum(UsageRecord.cost_usd), 0),
            func.coalesce(func.sum(UsageRecord.cost_usd).filter(
                UsageRecord.created_at >= month_start, UsageRecord.created_at < month_end), 0),
        ).where(UsageRecord.user_id == user.id)
    ).one()
    return Spend(month=Decimal(month), total=Decimal(total))
