"""Markdown for assistant replies.

Raw HTML is escaped, not rendered: replies may quote web pages.
"""

from markdown_it import MarkdownIt
from markupsafe import Markup

_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "breaks": True}).enable("table")
_md.validateLink = lambda url: url.lower().startswith(("http://", "https://", "mailto:"))


def render_markdown(text: str) -> Markup:
    html = _md.render(text or "")
    # Links open in a new tab and never pass the panel's address to other sites.
    html = html.replace("<a href=", '<a target="_blank" rel="noopener noreferrer" href=')
    return Markup(html)
