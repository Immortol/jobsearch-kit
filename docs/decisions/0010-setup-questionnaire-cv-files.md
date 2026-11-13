# 0010 · Setup in the panel: questionnaire page, CV files, file storage — 2026-11-10

Resolves the open question of ARCHITECTURE.md "File storage: Railway bucket vs Postgres".

**Context.**
- Stage 3: a new user goes through setup (skill `jobsearch-setup`, meetings 1–2 and the rules) in the panel and downloads a master CV.
- The skill offers a questionnaire page (`assets/questionnaire.html`) that, in the Claude app, saves answers through the artifact database (`window.claude.use("db")`, documents `intake/prefill` and `intake/answers`).
- The skill delivers the CV as a Google Doc or a .docx plus a PDF. Google Drive is not connected to the panel yet.
- 2–5 users; a CV is tens of kilobytes.
- Stage 2 is not accepted yet (no API key available); stage 3 is built on top of it.

**Decision.**
- **Questionnaire:** the panel serves `assets/questionnaire.html` unchanged at `/questionnaire`, plus a small script (`app/static/questionnaire-db.js`) that provides the same `window.claude.use("db")` interface backed by our endpoints. Answers and prefill are stored per user in Postgres. The page gets its own Content-Security-Policy allowing exactly its inline script and style (by hash). The agent writes the prefill and reads the answers with tools (`questionnaire_prefill`, `questionnaire_answers`).
- **CV:** the agent passes the CV *content* as structured data to the `save_cv` tool; the server renders a DOCX with our single-column, ATS-friendly template (python-docx) and converts that same DOCX to PDF with LibreOffice (headless). DOCX is the editable format until Google Drive is connected. Each save is a new version; the agent can read the latest one back (`read_cv`). Photo: not in this stage (backlog).
- **File storage:** files live in Postgres (`user_files`, bytes in the row): uploads and generated CVs. They are part of the data export (as a list) and are deleted with the account.
- **Uploads:** a paperclip in the chat composer accepts PDF, DOCX and TXT up to 5 MB. A PDF is sent to Claude as a document (Claude reads text and layout); for DOCX and TXT the server extracts the text.
- **Choice buttons:** the agent tool `offer_choices` shows 2–4 answer buttons under its message (the skill asks for choices "with buttons, if available"); a tap sends that answer as the person's message.
- **Setup entry:** a "Setup" card on the panel starts or continues a setup chat; progress is kept in `00_Setup_Status.md`, as in the skill.
- **Scope:** meetings 1–2 and rules 01–04. The tracker, schedule, scanner, Gmail and "project chats" are not in the panel yet; the adapter tells the agent to note them in the status as "later".

**Why.**
- One source of questions for both product versions; the skill's page already handles partial answers, skipping, phones and versioning.
- Our template guarantees the layout rules of `cv-builder.md` (one column, standard headings, selectable text) whatever the model writes; DOCX and PDF never diverge because the PDF is made from the DOCX.
- Postgres: no extra service, backups and deletion come with the database; the volume is tiny.

**Rejected.**
- **A native questionnaire form:** questions duplicated in code, drifting away from the skill.
- **HTML → PDF (WeasyPrint) and a separate DOCX:** two templates that diverge. LibreOffice costs ~400 MB of image size and a slower build, acceptable.
- **The model writing the document itself (code execution):** layout would differ every time; no container on our side.
- **Railway bucket now:** revisit when files grow (stage 4, application packages).
