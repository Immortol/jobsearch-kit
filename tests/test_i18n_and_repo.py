import re
import subprocess
from pathlib import Path

from app.i18n import load_catalog
from app.i18n_extract import all_strings, missing

ROOT = Path(__file__).resolve().parent.parent
CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def test_every_ui_string_has_a_russian_translation():
    assert missing("ru") == []


def test_catalog_has_no_stale_entries():
    assert sorted(set(load_catalog("ru")) - all_strings()) == []


def test_translations_keep_placeholders():
    for source, target in load_catalog("ru").items():
        assert set(re.findall(r"\{\w+\}", source)) == set(re.findall(r"\{\w+\}", target)), source


def test_no_cyrillic_outside_skills_and_catalogs():
    """Repository rule (CLAUDE.md): English everywhere except skills/, UI catalogs and *.ru.md."""
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    offenders = []
    for f in files:
        if f.startswith("skills/") or f.startswith("app/locales/") or f.endswith(".ru.md"):
            continue
        path = ROOT / f
        if not path.is_file() or path.suffix in {".png", ".jpg", ".zip", ".pdf", ".ico"}:
            continue
        if path.name == "htmx.min.js":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if CYRILLIC.search(text):
            offenders.append(f)
    # Tests may use Cyrillic sample data (it's user content, not repository text).
    offenders = [f for f in offenders if not f.startswith("tests/")]
    assert offenders == []
