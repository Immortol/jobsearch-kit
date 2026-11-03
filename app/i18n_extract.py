"""Collects every string passed to _() in templates and Python code.

Used by the test that keeps the catalogs complete:
    python -m app.i18n_extract ru     # prints strings missing from app/locales/ru.json
"""

import ast
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, nodes

from app.i18n import load_catalog

APP_DIR = Path(__file__).parent


def template_strings() -> set[str]:
    env = Environment(loader=FileSystemLoader(APP_DIR / "templates"))
    found: set[str] = set()
    for name in env.list_templates():
        source = env.loader.get_source(env, name)[0]
        tree = env.parse(source)
        # Jinja's own extract_from_ast skips calls with keyword arguments, so walk the tree.
        for call in tree.find_all(nodes.Call):
            if (isinstance(call.node, nodes.Name) and call.node.name == "_" and call.args
                    and isinstance(call.args[0], nodes.Const)
                    and isinstance(call.args[0].value, str)):
                found.add(call.args[0].value)
    return found


def python_strings() -> set[str]:
    found: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


def all_strings() -> set[str]:
    return template_strings() | python_strings()


def missing(locale: str) -> list[str]:
    catalog = load_catalog(locale)
    return sorted(s for s in all_strings() if s not in catalog)


if __name__ == "__main__":
    import json
    print(json.dumps(missing(sys.argv[1] if len(sys.argv) > 1 else "ru"), ensure_ascii=False,
                     indent=1))
