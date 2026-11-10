"""Vacancies: the feed of cards, the tracker and vacancy stories (decision 0011)."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.i18n import gettext
from app.models import (
    STORY_STATUSES, VACANCY_STATUSES, Chat, ChatMessage, UserFile, User, Vacancy, utcnow,
)

def _(message: str) -> str:
    """Marks a string for the UI catalog; translated when used."""
    return message


URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
TRACKING_PARAMS = re.compile(
    r"^(utm_.*|gclid|fbclid|mc_[ce]id|trk|trkInfo|refId|trackingId|ref|referrer|src|source|"
    r"campaign|lipi|originalSubdomain|eBP|from)$", re.I)
MAX_LINKS_PER_PASTE = 10
PAGE_SIZE = 20

# Feed filters → statuses.
IN_PROGRESS = ("prepared", "applied", "reply", "interview", "offer")
FILTERS = {
    "all": None,
    "good": "good",          # score 4–5
    "progress": IN_PROGRESS,
    "not_fit": ("not_fit", "rejected", "closed"),
}
TRACKER_DEFAULT = IN_PROGRESS


def extract_urls(text: str) -> list[str]:
    seen, urls = set(), []
    for raw in URL_RE.findall(text or ""):
        url = raw.rstrip(".,;:!?")
        key = url_key(url)
        if key not in seen:
            seen.add(key)
            urls.append(url)
    return urls[:MAX_LINKS_PER_PASTE]


def url_key(url: str) -> str:
    """The same vacancy behind different links: no tracking parameters, fragment, "www.",
    trailing slash or letter case in the host."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not TRACKING_PARAMS.match(k)))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, query, ""))[:2000]


def card_chat(db: Session, vacancy: Vacancy) -> Chat | None:
    return db.scalar(select(Chat).where(Chat.vacancy_id == vacancy.id, Chat.kind == "card"))


def story_chat(db: Session, vacancy: Vacancy) -> Chat | None:
    return db.scalar(select(Chat).where(Chat.vacancy_id == vacancy.id, Chat.kind == "story"))


def get_vacancy(db: Session, user: User, vacancy_id: int) -> Vacancy | None:
    v = db.get(Vacancy, vacancy_id)
    return v if v is not None and v.user_id == user.id else None


def find_by_url(db: Session, user: User, url: str) -> Vacancy | None:
    return db.scalar(select(Vacancy).where(Vacancy.user_id == user.id,
                                           Vacancy.url_key == url_key(url)).limit(1))


@dataclass
class Added:
    vacancy: Vacancy
    message_text: str | None  # what to send to the card's assistant; None = a repeat, not sent


def add_from_paste(db: Session, user: User, text: str) -> list[Added]:
    """Turns a paste into cards: one per link, or one for a pasted ad. Repeats of a link already
    in the feed are returned as they are."""
    text = text.strip()
    urls = extract_urls(text)
    added: list[Added] = []
    if not urls:
        v = Vacancy(user_id=user.id, source_text=text)
        db.add(v)
        added.append(Added(v, text))
    for url in urls:
        existing = find_by_url(db, user, url)
        if existing is not None:
            added.append(Added(existing, None))
            continue
        v = Vacancy(user_id=user.id, url=url[:2000], url_key=url_key(url))
        db.add(v)
        # With one link the whole paste goes to the assistant (it may carry a note or the ad).
        added.append(Added(v, text if len(urls) == 1 else url))
    db.flush()
    for a in added:
        if a.message_text is not None:
            db.add(Chat(user=user, kind="card", vacancy_id=a.vacancy.id,
                        title=a.vacancy.url or ""))
    db.flush()
    return added


def display_title(v: Vacancy) -> str:
    title = " · ".join(x for x in (v.company, v.role) if x)
    if title:
        return title
    if v.url:
        return urlsplit(v.url).netloc.removeprefix("www.")
    return (v.source_text or "")[:60]


def set_status(db: Session, user: User, v: Vacancy, status: str) -> Chat | None:
    """Changes the status; a status with a story ("reply", "interview", "offer") opens the
    vacancy's story chat. Returns the story chat when it was just created."""
    if status not in VACANCY_STATUSES:
        raise ValueError(status)
    v.status = status
    v.updated_at = utcnow()
    if status in STORY_STATUSES and story_chat(db, v) is None:
        return open_story(db, user, v)
    return None


STORY_INTRO = _("This is the story of the vacancy {title}. Write here what happens: replies, "
                 "interview invitations, questions. I know the assessment and the documents.")


def open_story(db: Session, user: User, v: Vacancy) -> Chat:
    existing = story_chat(db, v)
    if existing is not None:
        return existing
    chat = Chat(user=user, kind="story", vacancy_id=v.id, title=display_title(v))
    db.add(chat)
    # A greeting written by the panel (no API call); it is not sent to Claude.
    db.add(ChatMessage(chat=chat, role="assistant", status="done", api_messages=[],
                       text=gettext(STORY_INTRO, title=display_title(v))))
    db.flush()
    return chat


def vacancy_files(db: Session, v: Vacancy) -> list[UserFile]:
    return list(db.scalars(select(UserFile).where(UserFile.vacancy_id == v.id)
                           .order_by(UserFile.id.desc())))


def latest_documents(db: Session, v: Vacancy) -> dict[str, UserFile]:
    """The newest file of each kind (letter_pdf, letter_docx, vcv_pdf, vcv_docx)."""
    out: dict[str, UserFile] = {}
    for f in vacancy_files(db, v):
        out.setdefault(f.kind, f)
    return out


def list_vacancies(db: Session, user: User, *, q: str = "", flt: str = "all",
                   statuses: tuple[str, ...] | None = None, offset: int = 0,
                   limit: int = PAGE_SIZE) -> list[Vacancy]:
    stmt = select(Vacancy).where(Vacancy.user_id == user.id)
    if q.strip():
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(or_(Vacancy.company.ilike(like), Vacancy.role.ilike(like),
                              Vacancy.location.ilike(like), Vacancy.url.ilike(like),
                              Vacancy.summary.ilike(like), Vacancy.notes.ilike(like)))
    kind = FILTERS.get(flt) if statuses is None else statuses
    if kind == "good":
        stmt = stmt.where(Vacancy.score >= 4)
    elif kind:
        stmt = stmt.where(Vacancy.status.in_(kind))
    return list(db.scalars(stmt.order_by(Vacancy.created_at.desc(), Vacancy.id.desc())
                           .offset(offset).limit(limit)))


def count_vacancies(db: Session, user: User) -> int:
    return db.scalar(select(func.count()).select_from(Vacancy)
                     .where(Vacancy.user_id == user.id)) or 0


def find_similar(db: Session, user: User, query: str, exclude_id: int | None) -> list[Vacancy]:
    words = [w for w in re.split(r"\W+", query or "") if len(w) > 2][:5]
    if not words:
        return []
    stmt = select(Vacancy).where(Vacancy.user_id == user.id)
    if exclude_id:
        stmt = stmt.where(Vacancy.id != exclude_id)
    for w in words:
        like = f"%{w}%"
        stmt = stmt.where(or_(Vacancy.company.ilike(like), Vacancy.role.ilike(like),
                              Vacancy.url.ilike(like)))
    return list(db.scalars(stmt.order_by(Vacancy.id.desc()).limit(10)))
