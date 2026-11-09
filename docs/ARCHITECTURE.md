# Architecture

> Status: **approved 2026-11-02** (stage 0). Key decisions: `docs/decisions/0002-stack-fastapi-htmx.md`, `docs/decisions/0003-scanner-inside-worker.md`.

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
├─ web        FastAPI: panel, chat (SSE), questionnaire, tracker, Gmail connection (OAuth)
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
- **Files** (CVs, PDF letters): generated on the server, stored in Railway object storage.
- **Tracker**: a table in the panel; export to Google Sheets via a service account (no user OAuth), stage 4.

## Skills on the web
The skills are written for the Claude app: "Rules/ in the project", Artifact, Gmail connector, scheduling. On the web an agent on the Messages API executes them:
- **System prompt** = `SKILL.md` (+ the needed `references/` on demand via a `read_skill_file` tool).
- **Agent tools** (ours): `read_rules` / `write_rules` (user rules in the DB), `tracker_*`, `make_letter_pdf`, `make_cv`, `list_new_vacancies`, `gmail_*` (search/read the user's mail, create drafts, labels — via their OAuth token). Anthropic server tools: `web_search`, `web_fetch`.
- **Platform adapter**: a short shared prompt block: "in this environment 'project/Rules' = the read_rules/write_rules tools; scheduling is done by the worker; email = gmail_*". The `SKILL.md` files themselves change minimally so the Claude-app kit keeps working.
- Alternative — Anthropic's Skills API (upload skills as is, run in a code container). To be checked in stage 2: if it supports the tools we need and is cheaper to maintain — use it.

## Open questions (resolved in their stages)
- Messages API + own tools vs Skills API (stage 2).
- File storage: Railway bucket vs Postgres (stage 3).
