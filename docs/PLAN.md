# Plan

## Goal
A job-search web panel: questionnaire → truthful CV → vacancies (scanner + job alerts) → assessment → application packages → interviews → weekly review and growth. Runs on the Claude API; every user pays Anthropic directly with their own key (BYOK).

## MVP scope
- 2–5 users, friends of the owner. The first tester runs on Alexander's key (separate workspace in the Anthropic console with a monthly limit).
- Not in the MVP: in-app payments, Gmail access (a forwarding address instead), mobile app, hh.ru directly (API closed since 04.2026 — job alerts only).
- API cost target: $10–20 / user / month (Haiku for bulk assessment, Sonnet for documents, Batch API at night, rules caching). Hosting: Railway, separate project, €5–20 / month.

## Stages
Statuses: `done` · `in progress` · `next` · `later`.

| # | Stage | What Alexander checks (acceptance) | Status |
|---|---|---|---|
| 0 | Repository, CLAUDE.md, plan, architecture (draft), skills in repo, ZIP build | architecture approved ("go" on `ARCHITECTURE.md`); ZIPs from `dist/` match kit v1.1 | done |
| 1 | Skeleton: service on Railway, Postgres, email-link login, API key storage (encrypted), user rules | logs in via a link from an email, enters a key, sees an empty panel | next |
| 2 | "Brain": skills-based agent via the API + chat in the panel | writes "here is a vacancy <link>" in chat → gets an assessment per their rules | later |
| 3 | Questionnaire and CV: questionnaire in the panel, rules from answers, master CV (DOCX/PDF) | goes through setup as a new user, downloads the CV | later |
| 4 | Vacancies: application package (PDF letter), tracker in the panel (+ export to Google Sheets) | one real package; a row in the tracker | later |
| 5 | Night: career-ops scanner on the server, forwarding address for job alerts, assessment (Batch), morning digest by email and in the panel | digest arrives three mornings in a row | later |
| 6 | Interviews, weekly review, growth | interview card, mock interview, weekly review | later |
| 7 | Pilot with the tester | a week of use without intervention | later |

## Backlog
- In-app payments (option B) — once there are 10–20 happy users.
- Gmail OAuth (requires Google verification) — only if forwarding turns out insufficient.
- Confirmation of the IL/RU market packages after pilots.
- Custom domain for the panel (e.g. `app.almoti.com`) instead of `*.up.railway.app`.
- `build_kit.sh`: version number in the bundle archive name and its inner folder (`Jobsearch-Kit-v1.1/`, as in the v1.1 release); currently `Jobsearch-Kit/`.
