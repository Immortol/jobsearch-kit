"""UI translations. Strings are written in English in code and templates; catalogs map them to other
languages (decision 0006). A missing translation falls back to the English source string."""

import json
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

LOCALES_DIR = Path(__file__).parent / "locales"


@lru_cache
def load_catalog(locale: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{locale}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def gettext(message: str, **params: object) -> str:
    text = load_catalog(get_settings().ui_locale).get(message, message)
    return text.format(**params) if params else text


_ = gettext
