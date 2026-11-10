"""Storage of the questionnaire page's documents (`intake/prefill`, `intake/answers`)."""

from sqlalchemy.orm import Session

from app.models import Questionnaire, User, utcnow


def get_questionnaire(db: Session, user: User) -> Questionnaire | None:
    return db.get(Questionnaire, user.id)


def set_document(db: Session, user: User, name: str, data: dict) -> None:
    if name not in ("prefill", "answers"):
        raise ValueError(name)
    q = get_questionnaire(db, user)
    if q is None:
        q = Questionnaire(user_id=user.id)
        db.add(q)
    setattr(q, name, data)
    q.updated_at = utcnow()
    db.flush()
