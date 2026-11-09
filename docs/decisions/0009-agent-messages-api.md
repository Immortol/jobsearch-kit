# 0009 · The "brain": skills on the Messages API with our own tools — 2026-11-09

Resolves the open question of ARCHITECTURE.md "Messages API + own tools vs Skills API".

**Context.**
- Stage 2: a person writes "here is a vacancy <link>" in the panel's chat and gets an assessment according to their rules, paid from their own API key (BYOK, decision 0001).
- The skills in `skills/` are the single source of behaviour and must keep working in the Claude-app kit.
- Rules live in our database (decision 0005).
- The owner wants every user to see, at all times, how many dollars they have already spent.

**Decision.**
- **Messages API with our own tool loop.** The system prompt is a short platform adapter plus the catalog of skills enabled in the panel (name + description). Claude loads a skill with `load_skill`, reads its files with `read_skill_file`, reads and writes the person's rules with `read_rules` / `write_rules`, and uses Anthropic's server tools `web_search` and `web_fetch`. The `SKILL.md` files are not changed.
- **Skill choice by the model**, like in the Claude app: one chat, the model picks the skill from the descriptions. Enabled in stage 2: `jobsearch-vacancy` only; the adapter tells Claude which tools do not exist yet (tracker, files, Gmail) so it skips those steps.
- **Model:** Claude Sonnet 5.5 (`AGENT_MODEL` variable). Haiku stays for bulk night assessment (stage 5). No model choice in the UI for now (backlog).
- **Rules from chat:** `write_rules` may change rules when the person asks or a skill says so; every change is logged automatically in `CHANGELOG.md` and is visible on the Rules page.
- **Replies run in the background** in a thread pool inside the web process; the page polls the reply once a second (htmx) and shows the text and the current step as they come. Closing the tab does not lose the reply. A reply interrupted by a restart is marked as such. One reply at a time per chat.
- **Wallet protection:** at most 15 API calls per reply, 5 web searches and 5 page fetches per call; prompt caching of the system prompt and of the conversation.
- **History:** chats and messages in Postgres; each reply stores its full API exchange (tool calls and results), so the next message sends the whole conversation. "New chat" starts fresh.
- **Spend counter:** every API call's cost is computed from the `usage` the API returns (prices in `app/pricing.py`) and stored as a separate usage record. The header of every page shows "spent this month · in total"; each reply shows its own cost. Deleting a chat does not lower the counter; deleting the account removes everything.
- **Errors** are explained in plain words: rejected key, billing (no credit or the workspace limit reached), rate limits, Anthropic unavailable.

**Why.**
- Rules are in our database and the agent needs our tools; on the Messages API they are plain functions in our code.
- BYOK: nothing has to be uploaded or synced into each user's Anthropic account; any valid key works at once.
- `web_fetch` costs only its tokens; no container hours.
- Polling instead of a server-sent event stream: no extra JS library (the CSP allows only our own scripts), survives reloads and flaky mobile networks; at 2–5 users the load is negligible. Text still appears as it is written.
- Our own counter: the exact figure is only available from Anthropic's Usage & Cost API, which needs an organization admin key that our users do not have. The estimate uses the same token counts Anthropic bills.

**Rejected.**
- **Skills API** (skills uploaded to Anthropic, run in a code-execution container): custom skills are scoped to the workspace of the key, so they would have to be uploaded into every user's account and re-uploaded after every edit; the container has no network access; the docs do not confirm mixing it with our own tools (our rules); not covered by zero data retention. Gives nothing for an assessment without files. May be reconsidered for document generation if it becomes simpler than our server scripts (stage 4).
- **Managed Agents** (agent hosted by Anthropic): an extra $0.08 per session-hour, an agent to create in every user's account, less control. Overkill for 2–5 people.
- **A separate worker service for replies:** a queue and a second service for 2–5 people. The thread pool requires the web service to run as a single process; revisit if it grows.

**Consequences.**
- The web service must run as one process (one Railway replica, no `--workers`), because live progress is kept in memory.
- Prices in `app/pricing.py` are updated by hand when Anthropic changes them.
