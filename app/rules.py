"""Personal rules storage. File names follow Rules/ of the skills kit, so the stage 2 agent tools
read_rules / write_rules map onto the skills one to one."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RuleFile, User

STANDARD_NAMES = [
    "00_Setup_Status.md",
    "01_Facts.md",
    "02_Documents.md",
    "03_Strategy.md",
    "04_Processes.md",
    "Market_DE.md",
    "Growth_Plan.md",
    "CHANGELOG.md",
]

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}\.md$")
MAX_CONTENT = 200_000


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


def list_rules(db: Session, user: User) -> list[RuleFile]:
    return list(db.scalars(
        select(RuleFile).where(RuleFile.user_id == user.id).order_by(RuleFile.name)
    ))


def read_rule(db: Session, user: User, name: str) -> RuleFile | None:
    return db.scalar(select(RuleFile).where(RuleFile.user_id == user.id, RuleFile.name == name))


def write_rule(db: Session, user: User, name: str, content: str) -> RuleFile:
    if not valid_name(name):
        raise ValueError("invalid rule file name")
    if len(content) > MAX_CONTENT:
        raise ValueError("rule file too large")
    content = content.replace("\r\n", "\n")
    row = read_rule(db, user, name)
    if row is None:
        row = RuleFile(user_id=user.id, name=name, content=content)
        db.add(row)
    else:
        row.content = content
    db.flush()
    return row


def delete_rule(db: Session, user: User, name: str) -> bool:
    row = read_rule(db, user, name)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
