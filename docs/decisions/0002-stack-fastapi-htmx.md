# 0002 · Stack: FastAPI + server-rendered HTML (Jinja + HTMX) — 2026-11-02

**Context.** Stage 0: choose the web panel stack. 2–5 users, one assistant developer; the owner does not write code and reviews against checklists. Hosting — Railway (decision 0001). Needed: forms, tables and a chat with a streaming response.

**Decision.**
- Backend and pages — one Python service: FastAPI, HTML rendered on the server (Jinja), interactivity via HTMX; chat streams over SSE.
- Complex screens later — targeted JS on top of the same endpoints, no separate frontend application.
- Nightly jobs — the same Python code, a separate scheduled `worker` service (see 0003).
- Database — Postgres on Railway.

**Why.**
- Shortest path to a working panel: one codebase, one build, no CORS.
- Same language as the Visited bot — tooling the owner knows.
- The skill scripts (`make_letter.py` etc.) are already Python — called directly.
- There is a way out: if the panel outgrows HTMX, a separate frontend can be added on top of the same API without rewriting the backend.

**Rejected.**
- B. Python API + separate frontend (Next.js) — better for a "rich" UI, but two codebases, CORS, two builds and deploys; overkill for an MVP for 2–5 people.
- C. All TypeScript (Next.js) — one service, but a different language from Visited and from the skill scripts.
