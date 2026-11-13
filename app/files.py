"""User files in Postgres: uploads and generated documents (decision 0010)."""

import io
import re
import zipfile

from docx import Document
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserFile, User

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 60_000

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT = "text/plain"
UPLOAD_TYPES = {".pdf": PDF, ".docx": DOCX, ".txt": TXT, ".md": TXT}


class UploadError(Exception):
    """`code` is shown to the person through the translation catalog."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def safe_filename(name: str) -> str:
    base = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", "_", (name or "").strip())[-120:].strip(" .")
    return base or "file"


def _docx_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(p for p in parts if p.strip())


def read_upload(filename: str, data: bytes) -> tuple[str, str | None]:
    """Checks an upload and returns (content type, extracted text; None for PDFs)."""
    if not data:
        raise UploadError("empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError("too_big")
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    content_type = UPLOAD_TYPES.get(suffix)
    if content_type is None:
        raise UploadError("type")
    if content_type == PDF:
        if not data.startswith(b"%PDF"):
            raise UploadError("broken")
        return PDF, None
    if content_type == DOCX:
        try:
            text = _docx_text(data)
        except (zipfile.BadZipFile, KeyError, ValueError):
            raise UploadError("broken") from None
    else:
        text = data.decode("utf-8", errors="replace")
    if not text.strip():
        raise UploadError("empty")
    return content_type, text[:MAX_TEXT_CHARS]


def save_file(db: Session, user: User, *, kind: str, filename: str, content_type: str,
              data: bytes, text: str | None = None) -> UserFile:
    f = UserFile(user_id=user.id, kind=kind, filename=safe_filename(filename),
                 content_type=content_type, size=len(data), data=data, text=text)
    db.add(f)
    db.flush()
    return f


def get_file(db: Session, user: User, file_id: int) -> UserFile | None:
    f = db.get(UserFile, file_id)
    return f if f is not None and f.user_id == user.id else None


def list_files(db: Session, user: User) -> list[UserFile]:
    return list(db.scalars(select(UserFile).where(UserFile.user_id == user.id)
                           .order_by(UserFile.id.desc())))
