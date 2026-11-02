#!/usr/bin/env python3
"""Генератор сопроводительного письма (Jobsearch-Kit).

Использование:
    python3 make_letter.py letter.json out.html
    node render.mjs out.html out.pdf
    python3 check_pdf.py out.pdf          # должно быть: pages=1

letter.json:
{
  "lang": "de",                                   # язык письма (атрибут lang)
  "sender": {
    "name": "Maria Muster",
    "role": "UX/UI Designer",                     # необязательно
    "lines": ["+49 170 0000000 | maria@example.com", "Musterstraße 1 | 80331 München"],
    "photo": "/path/to/photo.jpg"                 # необязательно; только если принято на рынке и человек согласен
  },
  "recipient": ["Firma GmbH", "Frau Beispiel", "Straße 1", "12345 Stadt"],   # необязательно; во многих рынках не нужен
  "date": "München, 28.10.2026",
  "subject": "Bewerbung als UX/UI Designerin (Kennziffer 123)",
  "salutation": "Sehr geehrte Frau Beispiel,",
  "paragraphs": ["...", "...", "..."],            # обычный текст; переносы строк внутри абзаца не нужны
  "closing": "Mit freundlichen Grüßen",
  "signature": "Maria Muster",                    # по умолчанию = sender.name
  "enclosures": "Anlagen: Lebenslauf, Zeugnisse", # необязательно
  "font_pt": 11                                   # 10.5–11.5; уменьшай на 0.5, только если не влезает в страницу
}
Текст экранируется автоматически — HTML в полях не нужен.
"""
import base64, html, json, mimetypes, os, sys

def esc(s):
    return html.escape(str(s), quote=True)

def main(src, out):
    d = json.load(open(src, encoding="utf-8"))
    s = d.get("sender", {})
    pt = float(d.get("font_pt", 11))
    photo = ""
    if s.get("photo") and os.path.exists(s["photo"]):
        mime = mimetypes.guess_type(s["photo"])[0] or "image/jpeg"
        b64 = base64.b64encode(open(s["photo"], "rb").read()).decode()
        photo = f'<img class="photo" src="data:{mime};base64,{b64}" alt="">'
    lines = "<br>".join(esc(x) for x in s.get("lines", []))
    rec = d.get("recipient") or []
    rec_html = f'<div class="rec">{"<br>".join(esc(x) for x in rec)}</div>' if rec else ""
    paras = "".join(f'<p class="b">{esc(p)}</p>' for p in d["paragraphs"])
    enc = f'<p class="enc">{esc(d["enclosures"])}</p>' if d.get("enclosures") else ""
    role = f'<div class="role">{esc(s["role"])}</div>' if s.get("role") else ""
    doc = f"""<!doctype html><html lang="{esc(d.get('lang','en'))}"><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 16mm 18mm 14mm 18mm; }}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:"Calibri","Carlito","Helvetica Neue",Arial,sans-serif;font-size:{pt}pt;line-height:1.45;color:#1a1a1a;}}
.head{{display:flex;gap:14pt;align-items:flex-start;border-bottom:1.4pt solid #1a1a1a;padding-bottom:8pt;margin-bottom:14pt;}}
.head .txt{{flex:1;}}
.name{{font-size:20pt;font-weight:700;letter-spacing:-0.3pt;line-height:1.1;}}
.role{{font-size:11pt;font-weight:600;color:#333;margin-top:2pt;}}
.contact{{font-size:9pt;color:#333;margin-top:5pt;line-height:1.5;}}
.photo{{width:70pt;height:70pt;border-radius:50%;object-fit:cover;flex:0 0 auto;}}
.rec{{margin-bottom:12pt;font-size:{pt-0.5}pt;}}
.date{{text-align:right;margin:4pt 0 14pt;}}
.subject{{font-weight:700;margin-bottom:14pt;line-height:1.35;}}
p.b{{margin-bottom:9pt;}}
.closing{{margin-top:12pt;}}
.sig{{margin-top:20pt;}}
.enc{{margin-top:12pt;font-size:{pt-1}pt;color:#333;}}
</style></head><body>
<div class="head"><div class="txt"><div class="name">{esc(s.get('name',''))}</div>{role}<div class="contact">{lines}</div></div>{photo}</div>
{rec_html}<div class="date">{esc(d['date'])}</div>
<div class="subject">{esc(d['subject'])}</div>
<p class="b">{esc(d['salutation'])}</p>{paras}
<p class="b closing">{esc(d.get('closing','Kind regards'))}</p>
<p class="b sig">{esc(d.get('signature', s.get('name','')))}</p>{enc}
</body></html>"""
    open(out, "w", encoding="utf-8").write(doc)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(1)
    main(sys.argv[1], sys.argv[2])
