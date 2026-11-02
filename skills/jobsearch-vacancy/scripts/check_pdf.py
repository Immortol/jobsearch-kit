#!/usr/bin/env python3
"""python3 check_pdf.py file.pdf — печатает число страниц (pages=N). Письмо должно быть ровно на одной странице."""
import re, sys
try:
    from pypdf import PdfReader
    n = len(PdfReader(sys.argv[1]).pages)
except Exception:
    data = open(sys.argv[1], "rb").read()
    n = len(re.findall(rb"/Type\s*/Page(?!s)", data))
print(f"pages={n}")
sys.exit(0 if n == 1 else 2)
