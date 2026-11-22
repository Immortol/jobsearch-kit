"""Cover letter files: the skill's letter JSON → DOCX (our template) → PDF via LibreOffice.

The input is the format documented in `skills/jobsearch-vacancy/scripts/make_letter.py`, so the
skill reads the same in the Claude app and in the panel (decision 0011). Photo: not supported yet.
"""

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from app.cv import FONT, CvError, _clean

INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x33, 0x33, 0x33)

LETTER_SCHEMA = {
    "type": "object",
    "properties": {
        "lang": {"type": "string", "description": "Language code of the letter"},
        "file_name": {"type": "string",
                      "description": "Without extension, e.g. Muster_Anschreiben or Muster_Letter"},
        "sender": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "role": {"type": "string"},
                "lines": {"type": "array", "items": {"type": "string"},
                          "description": "Contact lines, e.g. phone | email, address"},
            },
            "required": ["name"],
        },
        "recipient": {"type": "array", "items": {"type": "string"}},
        "date": {"type": "string", "description": "e.g. München, 28.10.2026"},
        "subject": {"type": "string"},
        "salutation": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}},
        "closing": {"type": "string"},
        "signature": {"type": "string"},
        "enclosures": {"type": "string"},
        "font_pt": {"type": "number", "description": "10.5–11.5"},
    },
    "required": ["lang", "sender", "date", "subject", "salutation", "paragraphs", "closing"],
}


def validate(data: dict) -> dict:
    if not isinstance(data, dict):
        raise CvError("The letter must be an object.")
    sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
    letter = {
        "lang": _clean(data.get("lang"), 10),
        "file_name": _clean(data.get("file_name"), 120),
        "sender": {
            "name": _clean(sender.get("name"), 120),
            "role": _clean(sender.get("role"), 160),
            "lines": [_clean(x, 200) for x in (sender.get("lines") or [])[:4] if _clean(x)],
        },
        "recipient": [_clean(x, 200) for x in (data.get("recipient") or [])[:6] if _clean(x)],
        "paragraphs": [_clean(p, 3000) for p in (data.get("paragraphs") or [])[:8] if _clean(p)],
    }
    for key in ("date", "subject", "salutation", "closing", "signature", "enclosures"):
        letter[key] = _clean(data.get(key), 300)
    try:
        pt = float(data.get("font_pt") or 11)
    except (TypeError, ValueError):
        pt = 11.0
    letter["font_pt"] = min(11.5, max(10.5, pt))
    if not letter["sender"]["name"] or not letter["paragraphs"]:
        raise CvError("A letter needs the sender's name and at least one paragraph.")
    return letter


def _para(doc, text="", *, size=11.0, bold=False, color=INK, after=0.0, before=0.0, align=None):
    p = doc.add_paragraph()
    fmt = p.paragraph_format
    fmt.space_before, fmt.space_after = Pt(before), Pt(after)
    if align is not None:
        p.alignment = align
    if text:
        run = p.add_run(text)
        run.font.size, run.bold = Pt(size), bold
        run.font.color.rgb = color
    return p


def _rule_below(paragraph) -> None:
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in (("w:val", "single"), ("w:sz", "10"), ("w:space", "6"),
                       ("w:color", "1A1A1A")):
        bottom.set(qn(key), value)
    borders.append(bottom)
    paragraph._p.get_or_add_pPr().append(borders)


def render_docx(letter: dict) -> bytes:
    pt = letter["font_pt"]
    doc = Document()
    section = doc.sections[0]
    section.page_height, section.page_width = Mm(297), Mm(210)
    section.top_margin, section.bottom_margin = Mm(16), Mm(14)
    section.left_margin = section.right_margin = Mm(18)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = FONT, Pt(pt)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.paragraph_format.line_spacing = 1.2
    doc.core_properties.author = letter["sender"]["name"]
    doc.core_properties.title = letter["subject"]
    if letter["lang"]:
        doc.core_properties.language = letter["lang"]

    s = letter["sender"]
    _para(doc, s["name"], size=20, bold=True)
    if s["role"]:
        _para(doc, s["role"], size=11, bold=True, color=MUTED, before=2)
    last = None
    for line in s["lines"]:
        last = _para(doc, line, size=9, color=MUTED, before=1)
    _rule_below(last if last is not None else doc.paragraphs[-1])
    _para(doc, after=8)

    for i, line in enumerate(letter["recipient"]):
        _para(doc, line, size=pt - 0.5, after=8 if i == len(letter["recipient"]) - 1 else 0)
    _para(doc, letter["date"], size=pt, align=WD_ALIGN_PARAGRAPH.RIGHT, after=12)
    _para(doc, letter["subject"], size=pt, bold=True, after=12)
    _para(doc, letter["salutation"], size=pt, after=8)
    for p in letter["paragraphs"]:
        _para(doc, p, size=pt, after=8)
    _para(doc, letter["closing"] or "Kind regards", size=pt, before=4, after=20)
    _para(doc, letter["signature"] or s["name"], size=pt)
    if letter["enclosures"]:
        _para(doc, letter["enclosures"], size=pt - 1, color=MUTED, before=12)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def file_base(letter: dict) -> str:
    from app.cv import file_base as cv_file_base
    surname = (letter["sender"]["name"].split() or ["Letter"])[-1]
    return cv_file_base({"file_name": letter["file_name"] or f"{surname}_Letter"})
