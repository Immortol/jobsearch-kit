# Jobsearch-Kit

A Claude-based job-search system: questionnaire → CV → vacancies → application packages → interviews → growth.
Built from a real job search (Germany, PM, 2026) and generalised for any country and profession.

> People who will use the system have a separate guide (Google Doc, RU and EN). This README is for whoever maintains the kit.
> Installation for a user: each skill is a separate ZIP (`dist/*.zip`), Customize → Skills → "+" → "Create skill" → "Upload a skill". Update: delete the old skill and upload the new ZIP.

## What it consists of

| Skill | What it does | Status |
|---|---|---|
| `jobsearch-setup` | Introduction and questionnaire → master CV → personal rules → tracker → chats → schedule | v0.4 |
| `jobsearch-vacancy` | Vacancy link → application method → assessment → letter/CV → package → tracker | v0.1 |
| `jobsearch-digest` | Nightly digest: email, new vacancies, packages, "Today's priorities" | v0.1 |
| `jobsearch-interview` | Interview card, mock interview, debrief afterwards | v0.1 |
| `jobsearch-review` | Weekly review: funnel, reach, what to change | v0.1 |
| `jobsearch-scanner` | Pro: career-ops scanner on a Mac — one-command install, settings from the rules, nightly run | v0.1 |
| `jobsearch-growth` | The cheapest and least obvious ways to fix what is blocking hiring | v0.1 |

The skills are identical for everyone. Only the **person's rules** differ — the files `jobsearch-setup` creates in their project:

```
Rules/  (file names are fixed; content is in the person's language)
  00_Setup_Status  — where we are in setup, what to come back to later
  01_Facts         — facts about the person and achievements they are ready to defend
  02_Documents     — how to write CVs and letters for them
  03_Strategy      — what to look for, how to assess, priorities (broad by default)
  04_Processes     — who does what and when (chats, digest, review)
  Market_<code>    — market package for their country/countries
  CHANGELOG        — history of rule changes
```
## Tiers

- **Lite** — a Claude project + skills + a tracker in Google Sheets. Vacancies from links and from portal job alerts.
- **Standard** — plus a nightly digest, Gmail labels and drafts, weekly review. Recommended start.
- **Pro** — plus a vacancy scanner on a Mac (`jobsearch-scanner`: career-ops, one command in Terminal, nightly run).

## Principles shared by all skills

1. **Truth only.** Documents contain only what the person said and is ready to defend in an interview.
2. **Never send anything on the person's behalf.** Drafts only.
3. **Gently.** Small portions, no jargon; "don't know / skip / later" is always a valid answer. Value first, settings later.
4. **Broad by default.** Geography and role types are narrowed only by the person's explicit word, not by the model's guess.
5. **The person's rules live in their project, not in the skills.** Skills are shared, rules are personal.

## Market packages

They live in `jobsearch-setup/references/markets/`. `jobsearch-setup` builds a new package for a country/profession by research, following `_template.md` and the procedure in `research.md`. Good packages are added to the library after a pilot, so the next person from the same country gets a ready one.

## Versions

- **v1.1 (2026-10-28) — Pro tier:** `jobsearch-scanner` (career-ops v1.32.0, universal presieve, launchd + wake-up); the digest reads the scanner file; the review monitors its health. hh.ru — via saved-search email alerts: the public API has been closed since 04.2026.
- **v1.0 (2026-10-28) — first pilot version:** all 6 skills (`jobsearch-digest` and `jobsearch-review` v0.1), RU/EN guide. Pro tier (scanner) — manual, with the author, for now.
- v0.5 (2026-10-28) — `jobsearch-vacancy` (with a PDF letter generator and a "one page" check) and `jobsearch-interview`. With them a Lite-tier pilot can start.
- v0.4 (2026-10-28) — market packages IL, RU, REMOTE (from sources, awaiting pilots); role inserts: developer, designer, PM; skill `jobsearch-growth` v0.1.
- v0.3 (2026-10-27) — large consent-based questionnaire as a page (can return, answers are saved, works on a phone), prefill from CV, number-check questions tailored to the person. Alternative — questionnaire in chat.
- v0.2 (2026-10-27) — after the first dry run: start with a simple "shall we begin?", the person sends their CV themselves, never search Drive/memory without asking, one question per message in the first session, "how I understood you" — 4 lines max.
- v0.1 (2026-10-27) — `jobsearch-setup`, DE package.
