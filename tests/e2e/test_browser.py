"""End-to-end checks in a real browser (Chromium via Playwright) against the running app.

Claude is simulated, so these runs are free; they catch what unit tests cannot: scripts, CSP,
polling, scrolling, buttons, file inputs and the phone layout. Skipped when Playwright or its
Chromium is not installed (CI installs both).
"""

import re
import socket
import threading
import time

import pytest
import uvicorn

from app import chat as chats
from app.anthropic_keys import KeyCheck, get_key_checker
from app.claude import get_claude_client
from app.email import MemorySender, get_email_sender
from app.main import app
from tests.conftest import OWNER, last_code

playwright_api = pytest.importorskip("playwright.sync_api")

KEY = "sk-ant-api03-" + "e" * 60 + "E2Ex"
PHONE = {"width": 390, "height": 844}


# --- the app, served for the browser -----------------------------------------------------------

class ThreadedRunner:
    """Replies run in the background, as in production, so the page really polls them."""

    def __init__(self):
        self.threads: list[threading.Thread] = []

    def submit(self, fn):
        t = threading.Thread(target=fn, daemon=True)
        t.start()
        self.threads.append(t)

    def join(self):
        for t in self.threads:
            t.join(timeout=30)


def last_user_text(params) -> str:
    content = params["messages"][-1]["content"]
    return " ".join(b.get("text", "") for b in content if b.get("type") == "text")


class ScriptedClaude:
    """Answers like the assistant would, slowly enough for the page to show progress."""

    usage = {"input_tokens": 2000, "output_tokens": 200}

    def _reply(self, on_event, text, extra=None, stop="end_turn"):
        for word in text.split(" "):
            on_event("text", word + " ")
            time.sleep(0.05)
        content = ([{"type": "text", "text": text}] if text else []) + (extra or [])
        return {"model": "claude-sonnet-5-5", "content": content, "stop_reason": stop,
                "usage": self.usage}

    def _tools(self, *calls):
        return {"model": "claude-sonnet-5-5", "stop_reason": "tool_use", "usage": self.usage,
                "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": args}
                            for i, (name, args) in enumerate(calls)]}

    def create(self, api_key, params, on_event):
        system = " ".join(b["text"] for b in params["system"])
        msgs = params["messages"]
        assistant_turns = sum(1 for m in msgs if m["role"] == "assistant")
        last = last_user_text(params)
        time.sleep(0.5)
        if "This conversation is a vacancy card" in system:
            company = "Acme" if "acme" in str(msgs[0]).lower() else "Beta"
            if assistant_turns == 0:
                on_event("tool", "web_fetch")
                return self._tools(("vacancy_update", {
                    "company": company, "role": "Project Manager", "location": "München",
                    "score": 4 if company == "Acme" else 2,
                    "status": "assessed",
                    "summary": f"**4/5** · {company} · PM\nПочему: задачи совпадают"}))
            if msgs[-1]["role"] == "user" and last:
                time.sleep(3)  # a slow follow-up: the page must not jump while it runs
                return self._reply(on_event, f"Про зарплату в {company}: не указана.")
            return self._reply(on_event, f"Оценка {company} готова.")
        after_tool = msgs[-1]["content"][-1].get("type") == "tool_result"
        if after_tool and "questionnaire" in str(msgs[-2]["content"]):
            return self._reply(on_event, "Анкета: [Открыть анкету](/questionnaire)")
        if "Я заполнил анкету" in last:
            return self._reply(on_event, "Прочитал анкету.")
        if "Да, давай" in last:
            return self._tools(("questionnaire_prefill", {
                "lang": "ru", "name": "Анна", "values": {"a1": "Project Manager"}}))
        return self._reply(on_event, "Привет! Сегодня сделаем резюме.", extra=[
            {"type": "tool_use", "id": "c1", "name": "offer_choices",
             "input": {"question": "Начнём?", "options": ["Да, давай", "Не сейчас"]}}],
            stop="tool_use")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server():
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not srv.started:
        if time.time() > deadline:
            raise RuntimeError("the app did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    try:
        pw = playwright_api.sync_playwright().start()
        b = pw.chromium.launch()
    except Exception as exc:  # Chromium not installed
        pytest.skip(f"Chromium is not available: {exc}")
    yield b
    b.close()
    pw.stop()


@pytest.fixture
def env():
    """Fakes for e-mail, key check, Claude and the reply runner."""
    outbox, runner = MemorySender(), ThreadedRunner()
    app.dependency_overrides[get_email_sender] = lambda: outbox
    app.dependency_overrides[get_key_checker] = lambda: (lambda key: KeyCheck.OK)
    app.dependency_overrides[get_claude_client] = lambda: ScriptedClaude()
    app.dependency_overrides[chats.get_runner] = lambda: runner
    yield outbox
    runner.join()
    app.dependency_overrides.clear()


class Page:
    """A browser tab that records console errors and failed page scripts."""

    def __init__(self, browser, base, viewport=None):
        self.ctx = browser.new_context(viewport=viewport or {"width": 1200, "height": 900},
                                       accept_downloads=True)
        self.page = self.ctx.new_page()
        self.base = base
        self.errors: list[str] = []
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error"
                     and "favicon" not in m.text and "404" not in m.text else None)
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def go(self, path):
        self.page.goto(self.base + path)
        return self.page

    def close(self):
        self.ctx.close()


@pytest.fixture
def tab(browser, server):
    pages = []

    def make(viewport=None):
        p = Page(browser, server, viewport)
        pages.append(p)
        return p
    yield make
    for p in pages:
        p.close()


def sign_in(tab_obj, outbox, email=OWNER):
    page = tab_obj.go("/login")
    page.fill("input[name=email]", email)
    page.click("form[action='/login'] button[type=submit]")
    page.wait_for_selector("input[name=code]")
    page.fill("input[name=code]", last_code(outbox))
    page.click("form[action='/auth/code'] button[type=submit]")
    page.wait_for_url(re.compile(r".*/(panel|settings/key).*"))
    page = tab_obj.go("/settings/key")
    page.fill("input[name=api_key]", KEY)
    page.click("form[action='/settings/key'] button[type=submit]")
    page.wait_for_selector("text=…E2Ex")
    return page


# --- scenarios ---------------------------------------------------------------------------------

def test_sign_in_and_every_page_fits_a_phone(tab, env):
    t = tab(PHONE)
    page = sign_in(t, env)
    assert "Ключ …E2Ex" in page.inner_text("#spend")
    for path in ("/panel", "/vacancies", "/tracker", "/chats", "/files", "/rules", "/account",
                 "/settings/google"):
        page = t.go(path)
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 1, f"{path} scrolls sideways by {overflow}px on a phone"
    assert t.errors == []


def test_vacancy_cards_follow_up_and_no_jumping(tab, env):
    t = tab({"width": 390, "height": 600})  # a phone: the card page is longer than the screen
    sign_in(t, env)
    page = t.go("/vacancies")
    page.fill("textarea[name=text]", "https://jobs.example/acme https://jobs.example/beta")
    page.click("form[data-paste] button[type=submit]")
    page.wait_for_selector("text=Добавлено: 2")
    page.wait_for_selector(".vcard:has-text('Acme · Project Manager') >> text=Оценена",
                           timeout=15000)
    page.wait_for_selector(".vcard:has-text('Beta · Project Manager') >> text=Оценена",
                           timeout=15000)

    page.click("text=Acme · Project Manager")
    page.wait_for_selector("text=Оценка и вопросы")
    assert page.evaluate("window.scrollY") == 0, "a card page must open at its top"

    page.fill("textarea[name=message]", "а что с зарплатой?")
    page.click("form[data-composer] button[type=submit]")
    page.wait_for_selector(".msg.assistant.running")
    assert page.evaluate("document.documentElement.scrollHeight > window.innerHeight + 200")
    # While the reply runs, the person scrolls up to read: the page must stay there.
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(2500)
    assert page.evaluate("window.scrollY") == 0, "the running reply pulled the page down"
    page.wait_for_selector("text=Про зарплату в Acme: не указана.", timeout=15000)

    page = t.go("/vacancies?q=beta+manager")
    assert page.locator(".vcard").count() == 1 and "Beta" in page.inner_text(".vcard")
    page = t.go("/tracker?f=all")
    assert page.locator(".trow").count() == 2
    assert t.errors == []


def test_setup_buttons_and_questionnaire_done(tab, env):
    t = tab()
    sign_in(t, env)
    page = t.go("/panel")
    page.click("form[action='/setup'] button[type=submit]")
    page.wait_for_selector("button.choice:has-text('Да, давай')", timeout=15000)
    assert "Начнём?" in page.inner_text("#thread")
    page.click("button.choice:has-text('Да, давай')")
    page.wait_for_selector("text=Открыть анкету", timeout=15000)
    assert page.locator("button.choice").count() == 0
    chat_url = page.url

    page.click("text=Открыть анкету")
    page.wait_for_selector(".jsk-bar")
    field = page.locator("textarea, input[type=text]").first
    field.fill("Project Manager, IT")
    page.click("form[data-jsk-done] button")
    page.wait_for_url(chat_url, timeout=15000)
    page.wait_for_selector("text=Прочитал анкету.", timeout=15000)
    assert "Я заполнил анкету" in page.inner_text("#thread")
    assert t.errors == [], t.errors


def test_documents_take_several_files_at_once(tab, env, tmp_path):
    t = tab()
    sign_in(t, env)
    files = []
    for name in ("Zeugnis.pdf", "Diplom.pdf"):
        f = tmp_path / name
        f.write_bytes(b"%PDF-1.4 " + name.encode())
        files.append(str(f))
    page = t.go("/files")
    page.set_input_files("form[action='/files'] input[type=file]", files)
    assert "+1" in page.inner_text("form[action='/files'] [data-attach-name]")
    page.click("form[action='/files'] button[type=submit]")
    page.wait_for_selector("text=Diplom.pdf")
    assert page.locator("ul.attachments li").count() == 2
    assert t.errors == []
