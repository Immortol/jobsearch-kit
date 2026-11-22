"""The person's documents: generated CVs and uploaded files (decision 0010)."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app import chat as chats
from app import cv
from app.auth import require_user
from app.claude import ClaudeClient, get_claude_client
from app.db import get_db
from app.files import (
    DOCX, PDF,
    MAX_UPLOAD_BYTES, UploadError, get_file, latest_cv, list_files, read_upload, save_file,
)
from app.i18n import gettext as _
from app.models import CvVersion, User
from app.routes.chat import _start_chat
from app.web import render

router = APIRouter(prefix="/files")
MAX_FILES_PER_UPLOAD = 10



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
async def upload(request: Request, file: list[UploadFile] = File(...),
                 in_package: str = Form(""), user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    """Documents of the person's own, usually ones that go into every package. Several files
    at once are fine; if one of them is refused, none is saved and the error names the reason."""
    for upload_file in file[:MAX_FILES_PER_UPLOAD]:
        data = await upload_file.read(MAX_UPLOAD_BYTES + 1)
        try:
            content_type, text = read_upload(upload_file.filename or "", data, images=True)
        except UploadError as exc:
            db.rollback()
            return RedirectResponse(f"/files?error={exc.code}", status_code=303)
        f = save_file(db, user, kind="upload", filename=upload_file.filename or "file",
                      content_type=content_type, data=data, text=text)
        f.in_package = bool(in_package)
    return RedirectResponse("/files#attachments", status_code=303)


@router.post("/cv")
async def upload_cv(file: UploadFile = File(...), user: User = Depends(require_user),
                    db: Session = Depends(get_db)):
    """The person's own file becomes the master CV as it is (PDF, or Word converted to PDF)."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    name = file.filename or "CV"
    try:
        content_type, text = read_upload(name, data)
        if content_type not in (PDF, DOCX):
            raise UploadError("type")
        if content_type == PDF:
            text = cv.pdf_text(data)
            if not text.strip():
                raise UploadError("scan")  # a scanned CV: recruiting systems cannot read it
            pdf, docx_file = data, None
        else:
            docx_file = save_file(db, user, kind="cv_docx", filename=name,
                                  content_type=DOCX, data=data)
            pdf = cv.docx_to_pdf(data)
    except UploadError as exc:
        db.rollback()
        return RedirectResponse(f"/files?error={exc.code}", status_code=303)
    except cv.CvError:
        db.rollback()
        return RedirectResponse("/files?error=broken", status_code=303)
    pdf_name = name.rsplit(".", 1)[0] + ".pdf"
    pdf_file = save_file(db, user, kind="cv_pdf", filename=pdf_name, content_type=PDF, data=pdf)
    db.add(CvVersion(
        user_id=user.id, pages=cv.pdf_pages(pdf), pdf_id=pdf_file.id,
        docx_id=docx_file.id if docx_file is not None else None,
        content={"uploaded": True, "file_name": name, "text": (text or "")[:60_000]}))
    return RedirectResponse("/files", status_code=303)


@router.post("/cv/edit")
def edit_cv(user: User = Depends(require_user), db: Session = Depends(get_db),
            client: ClaudeClient = Depends(get_claude_client),
            runner: chats.Runner = Depends(chats.get_runner)):
    """Opens a chat about changing the master CV."""
    if user.api_key is None:
        return RedirectResponse("/settings/key", status_code=303)
    return _start_chat(db, user, _("I want to change my master CV"), None, client, runner)


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
