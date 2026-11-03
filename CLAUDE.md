# Jobsearch Kit — instructions for Claude

A job-search web panel built on the Claude API. Users are 2–5 friends of the owner, each with their own Anthropic API key (BYOK). Owner and product lead is Alexander; he does not write code and reviews results against checklists.

## How we work
- **Talk to Alexander in Russian**, briefly. Everything in the repository and on GitHub is in **English**: code, comments, file names, commits, PRs, docs. Exceptions: the skills in `skills/` (Russian product content, shipped to the Claude-app kit as is) and UI translation catalogs (`app/locales/<lang>/`). Docs meant for end users are kept in two versions: `<name>.md` (English) and `<name>.ru.md`. Instructions for Alexander himself go to the Claude project, not to GitHub.
- **Architecture and approach before code.** If a task has more than one reasonable path: options with pros/cons, a recommendation, then wait for Alexander's "go". If unclear — ask, don't guess.
- **One stage — one branch — one chat.** Stages and their status live in `docs/PLAN.md`. When starting: read `docs/PLAN.md` and `docs/ARCHITECTURE.md`, take the first stage with status `next`, create branch `stage-N-<slug>`.
- **Record decisions in `docs/decisions/NNNN-<slug>.md`** (context → decision → why → rejected). Don't reopen a recorded decision without a new reason.
- **End of stage:** tests green → PR into `main` with a plain-language "what to check" checklist (no code) → update status in `docs/PLAN.md`. Alexander merges.
- Don't bloat a stage: anything found outside its scope goes as one line to "Backlog" in `docs/PLAN.md`.

## Never
- Secrets (API keys, tokens) never go into the repository. Railway environment variables only.
- Railway project `laudable-celebration` (the Visited bot) — do not touch. This app has its own project.
- Never send anything on the user's behalf (emails, applications) — drafts only. This is a product principle, see the skills.
- Production deploy (`accept-deploy`, merging into `main`) only after Alexander's explicit "yes".

## Repository map
```
skills/        single source of the "brain": 7 skills (SKILL.md + references/assets/scripts).
               The ZIPs for the Claude-app version are built from them (scripts/build_kit.sh).
docs/PLAN.md   goal, stages, acceptance criteria, backlog
docs/ARCHITECTURE.md   stack and layout (approved in stage 0, decisions 0002–0003)
docs/decisions/        accepted decisions
docs/KIT_README.md     description of the skills kit
app/           server application (from stage 1)
```

## Skills
Edits in `skills/` change both product versions (web and the Claude-app kit). When changing a skill, keep it working in both: references to platform tools go through the "where to store" section / adapter (see `docs/ARCHITECTURE.md`, "Skills on the web"). After editing, run `scripts/build_kit.sh`.

## Commands
(filled in as they appear: run, tests, migrations)
- `scripts/build_kit.sh` — build `dist/*.zip` skills for the Claude app.
