"""Viewing and editing personal rules files. Filled for real in stage 3; editable by hand now."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app import rules as rules_store
from app.auth import require_user
from app.db import get_db
from app.models import User
from app.web import is_htmx, render

router = APIRouter(prefix="/rules")


@router.get("")
def rules_list(request: Request, user: User = Depends(require_user),
               db: Session = Depends(get_db)):
    return render(request, "rules.html", user=user, files=rules_store.list_rules(db, user),
                  suggestions=rules_store.STANDARD_NAMES)


@router.post("")
def rules_create(request: Request, name: str = Form(""), user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    name = name.strip()
    if not rules_store.valid_name(name):
        return render(request, "rules.html", user=user, files=rules_store.list_rules(db, user),
                      suggestions=rules_store.STANDARD_NAMES, error="bad_name", name=name,
                      status_code=400)
    if rules_store.read_rule(db, user, name) is None:
        rules_store.write_rule(db, user, name, "")
    return RedirectResponse(f"/rules/{name}", status_code=303)


@router.get("/{name}")
def rule_view(request: Request, name: str, user: User = Depends(require_user),
              db: Session = Depends(get_db)):
    row = rules_store.read_rule(db, user, name)
    if row is None:
        return render(request, "not_found.html", user=user, status_code=404)
    return render(request, "rule_edit.html", user=user, file=row)


@router.post("/{name}")
def rule_save(request: Request, name: str, content: str = Form(""),
              user: User = Depends(require_user), db: Session = Depends(get_db)):
    if rules_store.read_rule(db, user, name) is None:
        return render(request, "not_found.html", user=user, status_code=404)
    try:
        row = rules_store.write_rule(db, user, name, content)
    except ValueError:
        return render(request, "_save_status.html", status="too_large", status_code=400)
    if is_htmx(request):
        return render(request, "_save_status.html", status="saved", file=row)
    return RedirectResponse(f"/rules/{name}", status_code=303)


@router.post("/{name}/delete")
def rule_delete(request: Request, name: str, user: User = Depends(require_user),
                db: Session = Depends(get_db)):
    rules_store.delete_rule(db, user, name)
    if is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": "/rules"})
    return RedirectResponse("/rules", status_code=303)
