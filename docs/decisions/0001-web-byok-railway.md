# 0001 · Web panel, BYOK, Railway — 2026-11-02

**Context.** The skills kit for the Claude app works, but setup is complicated, and the Pro tier requires a Mac. The long-term goal is a full job-search panel.

**Decision.**
- A web application (not a Telegram bot): a full panel is needed long term.
- Every user pays for the API themselves with their own key (BYOK). Alexander pays for the first tester (separate workspace with a limit).
- First users — 2–5 friends.
- Hosting — Railway, a separate project (the Visited bot is already there, in its own project).
- Development happens in this repository: one stage = one branch = one chat, decisions in `docs/decisions/`.
- Skills are the single source for both the web app and the Claude-app kit.

**Rejected.** Telegram bot as the main interface (less work, but not a panel); in-app payments (too early for 2–5 people); Gmail OAuth (Google verification, paid security audit).
