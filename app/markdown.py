"""Markdown for assistant replies.

Raw HTML is escaped, not rendered: replies may quote web pages.
"""

from markdown_it import MarkdownIt
from markupsafe import Markup

_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "breaks": True}).enable("table")


def _allowed_link(url: str) -> bool:
    lower = url.lower()
    if lower.startswith(("http://", "https://", "mailto:")):
        return True
    # Panel pages the agent links to (/questionnaire, /files/12); not protocol-relative "//".
    return url.startswith("/") and not url.startswith("//")


_md.validateLink = _allowed_link


def render_markdown(text: str) -> Markup:
    html = _md.render(text or "")
    # External links open in a new tab and never pass the panel's address to other sites.
    html = html.replace('<a href="http', '<a target="_blank" rel="noopener noreferrer" href="http')
    return Markup(html)
