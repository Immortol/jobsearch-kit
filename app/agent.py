"""The "brain": runs the skills from `skills/` on the Messages API with our tools (decision 0009).

One reply = a loop of API calls. Claude sees a platform adapter and the catalog of enabled skills,
loads the skill it needs, reads the user's rules, uses web search / fetch on Anthropic's side and
our tools on ours, until it answers or hits the step limit.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app import rules, skills
from app.claude import ClaudeClient, ClaudeError, ClaudeFailure
from app.models import User, utcnow
from app.pricing import call_cost


def _(message: str) -> str:
    """Marks a string for the UI catalog; it is translated later, when the panel renders it."""
    return message

MAX_STEPS = 15          # API calls per reply: protects the user's wallet from loops
MAX_TOKENS = 8000
MAX_WEB_USES = 5        # per API call, for each of web search and web fetch

ADAPTER = """\
You are the assistant of Jobsearch Kit, a web panel that helps one person look for a job. \
Everything you do follows the person's skills (instructions) and their personal rules.

## How this environment maps onto the skills
The skills were written for the Claude app. Here:
- "Rules/<file>" in the project = the `read_rules` and `write_rules` tools. `read_rules` with no \
names lists the files; read several files in one call.
- WebFetch = the `web_fetch` tool; web search = the `web_search` tool.
- Skill files (references/, scripts/) = the `read_skill_file` tool.
- Not available in the panel yet: the tracker, Google Drive and folders, PDF and DOCX generation, \
Gmail (search, drafts, labels), scheduled tasks, other chats. Skip skill steps that need them \
without comment. If the person asks for documents, a package, the tracker or an email draft, say \
in one line that this will appear in the panel soon, and do what you can in the chat instead.

## Working rules
- Before doing a task that a skill covers, call `load_skill` and follow that skill.
- Reply in the person's language (by default Russian). Be brief, use Markdown.
- Do not narrate tool calls ("let me open the link…"): the panel already shows what you are doing.
- Never invent facts about the person: use only their rules and what they tell you.
- Never send anything on the person's behalf: drafts only.
- Change rules only when the person asks or a skill tells you to, and say what you changed.
"""

UNAVAILABLE_SKILLS_NOTE = (
    "Other skills of the kit (setup questionnaire and CV, scanner, morning digest, interviews, "
    "weekly review, growth) are not in the panel yet. If the person asks for them, say so in one "
    "line and offer what is available."
)

TOOLS: list[dict] = [
    {
        "name": "load_skill",
        "description": "Load a skill's instructions (SKILL.md) and the list of its files. "
                       "Call before doing a task the skill covers.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Skill name"}},
            "required": ["name"],
        },
    },
    {
        "name": "read_skill_file",
        "description": "Read a file of a skill, e.g. references/letter.md.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
                "path": {"type": "string", "description": "Path inside the skill folder"},
            },
            "required": ["skill", "path"],
        },
    },
    {
        "name": "read_rules",
        "description": "Read the person's rules files (Rules/ of the skills). With no names, "
                       "lists the files that exist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "names": {"type": "array", "items": {"type": "string"},
                          "description": "File names, e.g. [\"01_Facts.md\", \"03_Strategy.md\"]"},
            },
        },
    },
    {
        "name": "write_rules",
        "description": "Create or change one rules file. Every change is also logged in "
                       "CHANGELOG.md automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "File name, e.g. 03_Strategy.md"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["replace", "append"],
                         "description": "replace = the whole file becomes `content`; "
                                        "append = `content` is added at the end"},
                "summary": {"type": "string",
                            "description": "One line for CHANGELOG.md, in the person's language"},
            },
            "required": ["name", "content", "mode", "summary"],
        },
    },
    {"type": "web_search_20260318", "name": "web_search", "max_uses": MAX_WEB_USES},
    {"type": "web_fetch_20260318", "name": "web_fetch", "max_uses": MAX_WEB_USES,
     "max_content_tokens": 15000},
]

# What the panel says while a tool runs; strings are translated when rendered.
TOOL_STATUS = {
    "load_skill": _("Reading the instructions"),
    "read_skill_file": _("Reading the instructions"),
    "read_rules": _("Reading your rules"),
    "write_rules": _("Updating your rules"),
    "web_search": _("Searching the web"),
    "web_fetch": _("Opening a page"),
}
STATUS_THINKING = _("Thinking")


def system_prompt(rule_names: list[str], today: date) -> list[dict]:
    catalog = "\n".join(f"- `{s.name}`: {s.description}" for s in skills.catalog())
    static = f"{ADAPTER}\n## Skills available\n{catalog}\n\n{UNAVAILABLE_SKILLS_NOTE}\n"
    existing = ", ".join(rule_names) if rule_names else "none yet (the person has not done setup)"
    dynamic = f"Today is {today.isoformat()}. Rules files of this person: {existing}."
    return [
        {"type": "text", "text": static, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic},
    ]


# --- our tools ---------------------------------------------------------------------------------

class ToolFailed(Exception):
    pass


def _tool_load_skill(db: Session, user: User, args: dict) -> str:
    skill = skills.load_skill(str(args.get("name", "")))
    if skill is None:
        raise ToolFailed("No such skill in the panel.")
    files = "\n".join(f"- {f}" for f in skill.files()) or "(none)"
    return f"{skill.body}\n\n---\nFiles of this skill (read with read_skill_file):\n{files}"


def _tool_read_skill_file(db: Session, user: User, args: dict) -> str:
    text = skills.read_skill_file(str(args.get("skill", "")), str(args.get("path", "")))
    if text is None:
        raise ToolFailed("No such file in this skill.")
    return text


def _tool_read_rules(db: Session, user: User, args: dict) -> str:
    names = args.get("names") or []
    if not isinstance(names, list):
        raise ToolFailed("`names` must be a list.")
    if not names:
        rows = rules.list_rules(db, user)
        if not rows:
            return "The person has no rules files yet."
        return "\n".join(f"- {r.name} ({len(r.content)} characters)" for r in rows)
    parts = []
    for name in names[:12]:
        row = rules.read_rule(db, user, str(name))
        parts.append(f"=== {name} ===\n" + (row.content if row else "(this file does not exist)"))
    return "\n\n".join(parts)


def _tool_write_rules(db: Session, user: User, args: dict) -> str:
    name = str(args.get("name", ""))
    content = str(args.get("content", ""))
    mode = args.get("mode", "replace")
    summary = " ".join(str(args.get("summary", "")).split())[:300] or "—"
    if name == "CHANGELOG.md":
        raise ToolFailed("CHANGELOG.md is written automatically.")
    if mode == "append":
        row = rules.read_rule(db, user, name)
        old = row.content if row else ""
        content = (old.rstrip("\n") + "\n\n" if old.strip() else "") + content
    try:
        rules.write_rule(db, user, name, content)
        log = rules.read_rule(db, user, "CHANGELOG.md")
        line = f"- {utcnow():%Y-%m-%d} · {name}: {summary} (assistant, chat)"
        rules.write_rule(db, user, "CHANGELOG.md",
                         ((log.content.rstrip("\n") + "\n") if log and log.content.strip() else
                          "# CHANGELOG\n\n") + line + "\n")
    except ValueError as exc:
        raise ToolFailed(str(exc)) from None
    return f"Saved {name}."


LOCAL_TOOLS: dict[str, Callable[[Session, User, dict], str]] = {
    "load_skill": _tool_load_skill,
    "read_skill_file": _tool_read_skill_file,
    "read_rules": _tool_read_rules,
    "write_rules": _tool_write_rules,
}


def run_local_tool(db: Session, user: User, block: dict) -> dict:
    fn = LOCAL_TOOLS.get(block.get("name", ""))
    args = block.get("input") if isinstance(block.get("input"), dict) else {}
    result: dict = {"type": "tool_result", "tool_use_id": block["id"]}
    try:
        if fn is None:
            raise ToolFailed("Unknown tool.")
        result["content"] = fn(db, user, args)
    except ToolFailed as exc:
        result["content"] = str(exc)
        result["is_error"] = True
    return result


# --- the loop ----------------------------------------------------------------------------------

@dataclass
class ReplyResult:
    text: str
    api_messages: list[dict]
    cost: Decimal = Decimal(0)
    error: ClaudeFailure | None = None
    hit_step_limit: bool = False
    calls: list[dict] = field(default_factory=list)  # model + usage + cost of every API call


class Progress:
    """Receives live progress; the chat keeps it in memory for the panel to poll."""

    def text(self, delta: str) -> None: ...
    def status(self, label: str) -> None: ...
    def call_done(self, model: str, usage: dict, cost: Decimal) -> None: ...


def build_history(api_messages: list[list[dict]]) -> list[dict]:
    """Joins stored turns into one valid history: consecutive turns of the same role are merged
    (e.g. tool results of a reply cut short, followed by the next user message)."""
    history: list[dict] = []
    for chunk in api_messages:
        for m in chunk:
            content = m["content"] if isinstance(m["content"], list) else \
                [{"type": "text", "text": str(m["content"])}]
            if history and history[-1]["role"] == m["role"]:
                history[-1]["content"] = history[-1]["content"] + content
            else:
                history.append({"role": m["role"], "content": list(content)})
    return history


def _with_cache_breakpoint(messages: list[dict]) -> list[dict]:
    """Caches the conversation up to the last user turn, so the next call of the same reply (and
    the next reply) re-reads it at the cache price."""
    if not messages or messages[-1]["role"] != "user":
        return messages
    last = messages[-1]
    blocks = [dict(b) for b in last["content"]]
    if blocks and blocks[-1].get("type") in ("text", "tool_result"):
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return messages[:-1] + [{"role": "user", "content": blocks}]


def _clean_content(content: list[dict]) -> list[dict]:
    """Assistant content as it must be sent back: without empty text blocks."""
    return [b for b in content if not (b.get("type") == "text" and not b.get("text"))]


def run_reply(*, client: ClaudeClient, api_key: str, model: str, db: Session, user: User,
              history: list[dict], progress: Progress, today: date | None = None) -> ReplyResult:
    system = system_prompt([r.name for r in rules.list_rules(db, user)], today or date.today())
    turn: list[dict] = []
    texts: list[str] = []
    result = ReplyResult(text="", api_messages=turn)

    def on_event(kind: str, value: str) -> None:
        if kind == "text":
            progress.text(value)
        elif kind == "tool":
            progress.status(TOOL_STATUS.get(value, STATUS_THINKING))

    for step in range(MAX_STEPS):
        progress.status(STATUS_THINKING)
        params = {
            "model": model, "max_tokens": MAX_TOKENS, "system": system, "tools": TOOLS,
            "messages": _with_cache_breakpoint(history + turn),
        }
        try:
            msg = client.create(api_key, params, on_event)
        except ClaudeError as exc:
            result.error = exc.failure
            break
        usage = msg.get("usage") or {}
        cost = call_cost(msg.get("model", model), usage)
        result.cost += cost
        result.calls.append({"model": msg.get("model", model), "usage": usage, "cost": cost})
        progress.call_done(msg.get("model", model), usage, cost)

        content = _clean_content(msg.get("content") or [])
        turn.append({"role": "assistant", "content": content})
        new_text = "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        if new_text:
            texts.append(new_text)
            progress.text("\n\n")

        stop = msg.get("stop_reason")
        if stop == "tool_use":
            results = []
            for block in content:
                if block.get("type") == "tool_use":
                    progress.status(TOOL_STATUS.get(block.get("name", ""), STATUS_THINKING))
                    results.append(run_local_tool(db, user, block))
            db.flush()
            turn.append({"role": "user", "content": results})
            continue
        if stop == "pause_turn":  # a long server-tool turn: send it back to let Claude continue
            continue
        break
    else:
        result.hit_step_limit = True

    if result.error is not None:
        # A reply cut by an error may end with unanswered tool calls; do not replay it.
        turn.clear()
    result.text = "\n\n".join(texts)
    return result

