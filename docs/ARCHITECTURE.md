# Architecture

> Status: **approved 2026-11-02** (stage 0). Key decisions: `docs/decisions/0002-stack-fastapi-htmx.md`, `docs/decisions/0003-scanner-inside-worker.md`, `docs/decisions/0009-agent-messages-api.md`, `docs/decisions/0010-setup-questionnaire-cv-files.md`, `docs/decisions/0011-vacancy-feed-tracker.md`.

## Principles
1. **Simple and cheap to run**: 2–5 users, one assistant developer. As few services as possible.
2. **Skills are the single source of behaviour.** The web app does not rewrite the logic from `skills/`; it executes it.
3. **BYOK**: every Claude call uses the user's key; the spend is visible in their Anthropic console.
4. **A person's data is theirs**: export and deletion at the push of a button from day one (GDPR).

## Stack — option A chosen (decision 0002)

The comparison the decision was based on:

| | **A. Python: FastAPI + server-rendered HTML (Jinja + HTMX)** ✅ | B. Python API + separate frontend (Next.js) | C. All TypeScript (Next.js) |
|---|---|---|---|
| Services | 1 web + background jobs | 2 | 1 |
| Language | one — Python, like Visited | two | one, but not the one Visited uses |
| Streaming chat | yes (SSE) | yes | yes |
| "Rich" panel later | medium: HTMX covers forms, tables, chat; complex screens — targeted JS | best | best |
| Speed to MVP | fastest | slower (two codebases, CORS, build) | medium |
| Risk | a frontend framework may be needed as the UI grows — gradual transition | more moving parts | less familiar to Alexander |

**Chosen: A.** The shortest path to a working panel and the same language as Visited. If the panel outgrows HTMX, a separate frontend can be added on top of the same API without rewriting the backend.

## Layout
```
Railway project "jobsearch-kit"
├─ web        FastAPI: panel, chat (replies in a thread pool, polled), questionnaire, tracker,
│             Gmail connection (OAuth). Runs as a single process (decision 0009)
├─ worker     same code + Node in the image, nightly cron — one sequential chain:
│             scanner (career-ops v1.32.0 + presieve from skills/jobsearch-scanner/assets)
│             → presieve → assessment (Batch) → packages → digest   (decision 0003)
└─ postgres   users, rules, vacancies, tracker, jobs, chat history
```
Only Python code writes to the database; the scanner hands its output to the worker.

- **Login**: email link or 6-digit code from the same email, invite-only. No passwords (decisions 0005, 0007).
- **Email we send**: Resend on `mail.almoti.com`, outbound only — sign-in codes, invitations, digest (decision 0004).
- **User's Gmail**: connected via Google OAuth (read, drafts, labels — never send). Job alerts and employer replies are read from it; application drafts go into its Drafts (decision 0008).
- **User API key**: stored encrypted (encryption key in an environment variable), never written to logs (decision 0005).
- **UI language**: English in code, translations in `app/locales/` (decision 0006).
- **Models**: Haiku — bulk vacancy assessment and email parsing; Sonnet — documents, interviews, review. User rules are cached; Batch API at night (−50%).
- **Files** (CVs, PDF letters, uploads): generated on the server, stored in Postgres (`user_files`, decision 0010). CV: structured content from the agent → DOCX (our template) → PDF via LibreOffice.
- **Vacancies** (decision 0011): a feed of cards at `/vacancies`; each card is a hidden chat (`chats.kind = "card"`) with the `jobsearch-vacancy` skill and the rules in the cached system prompt, and only its own messages. Letter and adapted CV: DOCX → PDF like the master CV, attached to the vacancy.
- **Tracker**: `/tracker`, the same vacancies as a table (status changes in place, CSV export); export to Google Sheets via a service account (no user OAuth), stage 4b. A status "reply" / "interview" / "offer" opens the vacancy's story chat (`chats.kind = "story"`).

## Skills on the web (decision 0009)
The skills are written for the Claude app: "Rules/ in the project", Artifact, Gmail connector, scheduling. On the web an agent on the Messages API executes them (`app/agent.py`):
- **System prompt** = a short platform adapter + the catalog of skills enabled in the panel (name and description). Claude loads the skill it needs with `load_skill` and its `references/` with `read_skill_file`.
- **Agent tools** (ours): `read_rules` / `write_rules` (user rules in the DB; changes logged in `CHANGELOG.md`); `offer_choices` (answer buttons); `questionnaire_prefill` / `questionnaire_answers` (the skill's questionnaire page, served at `/questionnaire` with a storage shim); `save_cv` / `read_cv`; `list_files` / `read_file`; in cards and stories `vacancy_update`, `find_vacancy`, `make_letter`, `save_vacancy_cv`; later `list_new_vacancies`, `gmail_*`. Anthropic server tools: `web_search`, `web_fetch`.
- **Platform adapter**: "in this environment 'project/Rules' = the read_rules/write_rules tools; what is not available yet is skipped". The `SKILL.md` files stay unchanged so the Claude-app kit keeps working.
- **Enabled skills** are listed in `app/skills.py` (`ENABLED_SKILLS`): each stage turns on the skills whose tools exist.
- **Cost**: every call's `usage` is priced (`app/pricing.py`) and stored; the panel always shows the spend this month and in total.

## Open questions (resolved in their stages)
- ~~Messages API + own tools vs Skills API (stage 2)~~ — Messages API, decision 0009.
- ~~File storage: Railway bucket vs Postgres (stage 3)~~ — Postgres for now, decision 0010; revisit in stage 4.
