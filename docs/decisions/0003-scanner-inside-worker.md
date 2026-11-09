# 0003 · The career-ops scanner is a step of the nightly chain inside the worker — 2026-11-02

**Context.** In the draft architecture the scanner (Node: career-ops v1.32.0 + our presieve) was a separate Railway service with its own cron, and the `worker` (Python) another service with its own cron. Assessment must start only after the scanner has finished, and coupling them "by schedule" is fragile: if the scanner runs late or fails, the worker silently assesses yesterday's data. The owner left this choice to the assistant.

**Decision.**
- No separate `scanner` service. Node and career-ops are installed in the `worker` image.
- The nightly chain is one sequential job in the `worker`: scanner (Node child process) → presieve → assessment (Batch) → packages → digest.
- The scanner writes its output to a file/stdout; the worker reads it and stores it in Postgres (only Python code writes to the DB — one schema, one place for migrations).
- Each step logs its outcome; a scanner failure does not break the chain — the digest honestly reports "the scanner did not run", and everything else (job alerts) is still processed.

**Why.**
- Step order is guaranteed by code, not by aligned schedules.
- One service fewer: cheaper on Railway, fewer places to break.
- Only Python touches the DB — no second Postgres client and no duplicated schema in Node.

**Rejected.**
- A separate `scanner` service with its own cron — fragile time-based coupling, an extra service, DB writes from two languages.
- Rewriting the scanner in Python — loses compatibility with career-ops and with the Claude-app kit.

**When implemented.** Stage 5.
