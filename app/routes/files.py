"""The person's documents: generated CVs and uploaded files (decision 0010)."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.files import get_file, list_files
from app.models import CvVersion, User
from app.web import render

router = APIRouter(prefix="/files")


def latest_cv(db: Session, user: User) -> CvVersion | None:
    return db.scalar(select(CvVersion).where(CvVersion.user_id == user.id)
                     .order_by(CvVersion.id.desc()).limit(1))


@router.get("")
def files_page(request: Request, user: User = Depends(require_user),
               db: Session = Depends(get_db)):
    files = list_files(db, user)
    by_id = {f.id: f for f in files}
    cv = latest_cv(db, user)
    current = [by_id[i] for i in ((cv.pdf_id, cv.docx_id) if cv else ()) if i in by_id]
    return render(request, "files.html", user=user, cv=cv, current=current,
                  generated=[f for f in files if f.kind != "upload" and f not in current],
                  uploads=[f for f in files if f.kind == "upload"])


@router.get("/{file_id}")
def download(file_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    f = get_file(db, user, file_id)
    if f is None:
        return Response("Not found", status_code=404)
    disposition = f"attachment; filename*=UTF-8''{quote(f.filename)}"
    return Response(f.data, media_type=f.content_type,
                    headers={"Content-Disposition": disposition, "Cache-Control": "no-store"})
