"""The person's documents: generated CVs and uploaded files (decision 0010)."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.files import (
    MAX_UPLOAD_BYTES, UploadError, get_file, latest_cv, list_files, read_upload, save_file,
)
from app.models import User
from app.web import render

router = APIRouter(prefix="/files")



@router.get("")
def files_page(request: Request, error: str = "", user: User = Depends(require_user),
               db: Session = Depends(get_db)):
    files = list_files(db, user)
    by_id = {f.id: f for f in files}
    cv = latest_cv(db, user)
    current = [by_id[i] for i in ((cv.pdf_id, cv.docx_id) if cv else ()) if i in by_id]
    return render(request, "files.html", user=user, cv=cv, current=current,
                  generated=[f for f in files if f.kind in ("cv_docx", "cv_pdf")
                             and f not in current],
                  vacancy_docs=sum(1 for f in files if f.vacancy_id is not None),
                  uploads=[f for f in files if f.kind == "upload"], error=error)


@router.post("")
async def upload(request: Request, file: UploadFile = File(...), in_package: str = Form(""),
                 user: User = Depends(require_user), db: Session = Depends(get_db)):
    """A document of the person's own, usually one that goes into every package."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        content_type, text = read_upload(file.filename or "", data, images=True)
    except UploadError as exc:
        db.rollback()
        return RedirectResponse(f"/files?error={exc.code}", status_code=303)
    f = save_file(db, user, kind="upload", filename=file.filename or "file",
                  content_type=content_type, data=data, text=text)
    f.in_package = bool(in_package)
    return RedirectResponse("/files#attachments", status_code=303)


@router.post("/{file_id}/package")
def toggle_package(file_id: int, in_package: str = Form(""),
                   user: User = Depends(require_user), db: Session = Depends(get_db)):
    f = get_file(db, user, file_id)
    if f is not None and f.kind == "upload":
        f.in_package = in_package == "1"
    return RedirectResponse("/files#attachments", status_code=303)


@router.post("/{file_id}/delete")
def delete_upload(file_id: int, user: User = Depends(require_user),
                  db: Session = Depends(get_db)):
    f = get_file(db, user, file_id)
    if f is not None and f.kind == "upload":
        db.delete(f)
    return RedirectResponse("/files#attachments", status_code=303)


@router.get("/{file_id}")
def download(file_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    f = get_file(db, user, file_id)
    if f is None:
        return Response("Not found", status_code=404)
    disposition = f"attachment; filename*=UTF-8''{quote(f.filename)}"
    return Response(f.data, media_type=f.content_type,
                    headers={"Content-Disposition": disposition, "Cache-Control": "no-store"})
