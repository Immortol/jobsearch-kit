"""Master CV files: structured content → DOCX (our template) → PDF via LibreOffice.

Decision 0010.

The template follows `skills/jobsearch-setup/references/cv-builder.md`: one column, no tables or
text boxes, standard section headings in the CV's language, selectable text.
"""

import io
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from pypdf import PdfReader

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_TYPE = "application/pdf"

ACCENT = RGBColor(0x1F, 0x3A, 0x5F)
MUTED = RGBColor(0x55, 0x55, 0x55)
FONT = "Liberation Sans"  # metric-compatible with Arial; installed with LibreOffice in the image

# JSON schema of the `save_cv` tool input. Everything the CV shows comes from here.
_ENTRY = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Role / degree / project name"},
        "organization": {"type": "string", "description": "Company / school"},
        "location": {"type": "string"},
        "dates": {"type": "string", "description": "e.g. 03/2021 – 08/2024 (one format)"},
        "details": {"type": "string", "description": "One line under the title, optional"},
        "bullets": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title"],
}
CV_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string", "description": "Language code of the CV, e.g. de, en, ru"},
        "file_name": {"type": "string",
                      "description": "CV_<Surname>_<Role>_<lang>, without extension"},
        "name": {"type": "string"},
        "headline": {"type": "string", "description": "Target role (not the word 'CV')"},
        "contacts": {"type": "array", "items": {"type": "string"},
                     "description": "City/country, phone, email, LinkedIn, portfolio…"},
        "sections": {
            "type": "array",
            "description": "In display order. Headings in the CV's language "
                           "(e.g. Profil, Berufserfahrung, Ausbildung).",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "text": {"type": "string", "description": "A paragraph (e.g. the profile)"},
                    "entries": {"type": "array", "items": _ENTRY,
                                "description": "Experience, education, projects"},
                    "items": {"type": "array", "items": {"type": "string"},
                              "description": "Simple lines (skills groups, languages, courses)"},
                },
                "required": ["heading"],
            },
        },
        "closing": {"type": "string",
                    "description": "Optional last line, e.g. 'München, 10.11.2026' (DE norm)"},
    },
    "required": ["language", "file_name", "name", "headline", "contacts", "sections"],
}


class CvError(Exception):
    pass


def _clean(value: object, limit: int = 2000) -> str:
    return " ".join(str(value or "").split())[:limit]


def validate(content: dict) -> dict:
    """Keeps only known fields, as trimmed strings; raises CvError when the CV is unusable."""
    if not isinstance(content, dict):
        raise CvError("The CV must be an object.")
    cv = {k: _clean(content.get(k), 200) for k in ("language", "file_name", "name", "headline")}
    cv["contacts"] = [_clean(c, 200) for c in (content.get("contacts") or [])[:8] if _clean(c)]
    cv["closing"] = _clean(content.get("closing"), 200)
    sections = []
    for s in (content.get("sections") or [])[:15]:
        if not isinstance(s, dict) or not _clean(s.get("heading")):
            continue
        entries = []
        for e in (s.get("entries") or [])[:20]:
            if isinstance(e, dict) and _clean(e.get("title")):
                entries.append({
                    **{k: _clean(e.get(k), 300) for k in
                       ("title", "organization", "location", "dates", "details")},
                    "bullets": [_clean(b, 600) for b in (e.get("bullets") or [])[:8] if _clean(b)],
                })
        sections.append({
            "heading": _clean(s.get("heading"), 100),
            "text": _clean(s.get("text"), 1500),
            "entries": entries,
            "items": [_clean(i, 400) for i in (s.get("items") or [])[:30] if _clean(i)],
        })
    cv["sections"] = sections
    if not cv["name"] or not sections:
        raise CvError("A CV needs at least a name and one section.")
    return cv


def file_base(cv: dict) -> str:
    """Safe ASCII file name; falls back to CV_<lang>."""
    raw = cv.get("file_name") or f"CV_{cv.get('language') or 'cv'}"
    ascii_name = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_name).strip("_")[:80]
    return name or "CV"


# --- DOCX --------------------------------------------------------------------------------------

def _bottom_border(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"),
                       ("w:color", "1F3A5F")):
        bottom.set(qn(key), value)
    borders.append(bottom)
    p_pr.append(borders)


def _para(doc, text: str = "", *, size: float = 10, bold: bool = False, color=None,
          before: float = 0, after: float = 2, style: str | None = None):
    p = doc.add_paragraph(style=style)
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    if text:
        run = p.add_run(text)
        run.font.size, run.bold = Pt(size), bold
        if color is not None:
            run.font.color.rgb = color
    return p


def render_docx(cv: dict) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.page_height, section.page_width = Cm(29.7), Cm(21.0)  # A4
    for side in ("left_margin", "right_margin"):
        setattr(section, side, Cm(2.0))
    section.top_margin = section.bottom_margin = Cm(1.6)

    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = FONT, Pt(10)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    doc.core_properties.title = f"{cv['name']} — {cv['headline']}".strip(" —")
    doc.core_properties.author = cv["name"]
    doc.core_properties.comments = ""
    if cv["language"]:
        doc.core_properties.language = cv["language"]

    _para(doc, cv["name"], size=20, bold=True, color=ACCENT, after=0)
    if cv["headline"]:
        _para(doc, cv["headline"], size=12, after=2)
    if cv["contacts"]:
        _para(doc, " · ".join(cv["contacts"]), size=9, color=MUTED, after=6)

    for s in cv["sections"]:
        heading = _para(doc, s["heading"].upper(), size=10.5, bold=True, color=ACCENT,
                        before=8, after=4)
        _bottom_border(heading)
        if s["text"]:
            _para(doc, s["text"], after=4)
        for e in s["entries"]:
            line = _para(doc, after=0, before=3)
            title = line.add_run(e["title"])
            title.bold, title.font.size = True, Pt(10.5)
            org = ", ".join(x for x in (e["organization"], e["location"]) if x)
            if org:
                line.add_run(f" · {org}").font.size = Pt(10.5)
            if e["dates"]:
                _para(doc, e["dates"], size=9, color=MUTED, after=1)
            if e["details"]:
                _para(doc, e["details"], size=9.5, after=1)
            for b in e["bullets"]:
                p = _para(doc, b, after=1, style="List Bullet")
                p.paragraph_format.left_indent = Cm(0.5)
        for item in s["items"]:
            _para(doc, item, after=1)

    if cv["closing"]:
        p = _para(doc, cv["closing"], before=12)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


# --- PDF ---------------------------------------------------------------------------------------

def docx_to_pdf(docx: bytes, timeout: int = 60) -> bytes:
    """Converts with LibreOffice in a throwaway profile (safe to run several at once)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "cv.docx"
        src.write_bytes(docx)
        cmd = ["soffice", f"-env:UserInstallation=file://{tmp}/profile", "--headless",
               "--norestore", "--convert-to", "pdf", "--outdir", tmp, str(src)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CvError(f"PDF conversion failed: {type(exc).__name__}") from None
        pdf = Path(tmp) / "cv.pdf"
        if not pdf.is_file():
            raise CvError("PDF conversion produced no file.")
        return pdf.read_bytes()


def pdf_pages(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


def pdf_text(pdf: bytes, limit: int = 20_000) -> str:
    reader = PdfReader(io.BytesIO(pdf))
    return "\n".join((page.extract_text() or "") for page in reader.pages)[:limit]
