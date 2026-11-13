"""Read-only access to the skills in `skills/` for the agent (decision 0009).

The skills are the single source of behaviour (ARCHITECTURE.md). The agent sees the catalog of the
skills enabled in the panel, loads a skill's SKILL.md when it needs it, and reads its other text
files (references, script docstrings) on demand.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

# Skills the panel can run so far. The others need tools that come in later stages
# (tracker/letters/Gmail — stage 4, night jobs — stage 5, interviews and reviews — stage 6).
ENABLED_SKILLS = ("jobsearch-setup", "jobsearch-vacancy")

TEXT_SUFFIXES = {".md", ".py", ".mjs", ".json", ".sh", ".txt"}
MAX_FILE_CHARS = 60_000


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str          # SKILL.md without the frontmatter
    path: Path

    def files(self) -> list[str]:
        """Other text files of the skill, as paths relative to its folder."""
        return sorted(
            str(p.relative_to(self.path)) for p in self.path.rglob("*")
            if p.is_file() and p.name != "SKILL.md" and p.suffix in TEXT_SUFFIXES
        )


def skills_dir() -> Path:
    return Path(os.environ.get("SKILLS_DIR") or DEFAULT_SKILLS_DIR)


def parse_skill_md(text: str) -> tuple[dict[str, str], str]:
    """Splits the YAML-like frontmatter (simple `key: value` lines) from the body."""
    meta: dict[str, str] = {}
    if not text.startswith("---"):
        return meta, text
    _, head, body = text.split("---", 2)
    for line in head.strip().splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, body.lstrip("\n")


@lru_cache
def load_skill(name: str) -> Skill | None:
    if name not in ENABLED_SKILLS:
        return None
    path = skills_dir() / name
    md = path / "SKILL.md"
    if not md.is_file():
        return None
    meta, body = parse_skill_md(md.read_text(encoding="utf-8"))
    return Skill(name=meta.get("name", name), description=meta.get("description", ""),
                 body=body, path=path)


def catalog() -> list[Skill]:
    return [s for s in (load_skill(n) for n in ENABLED_SKILLS) if s is not None]


def read_skill_file(name: str, relative: str) -> str | None:
    """A text file inside the skill's folder; None for anything outside it or not text."""
    skill = load_skill(name)
    if skill is None:
        return None
    root = skill.path.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file() \
            or target.suffix not in TEXT_SUFFIXES:
        return None
    return target.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
