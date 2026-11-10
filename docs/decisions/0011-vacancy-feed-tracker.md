# 0011 · Vacancies: one feed of cards, the tracker, vacancy stories — 2026-11-10

**Context.**
- In acceptance of stages 2–3 the owner pointed out that "one chat per vacancy" does not scale: a search means hundreds or thousands of vacancies.
- The wanted flow: one place where vacancies are dropped in; each gets an assessment and, for 4–5, the documents; a tracker of the vacancies something happened with; a separate conversation only once a vacancy has a story (a reply, an interview).
- Each assessment must not resend the conversation about other vacancies to Claude.
- The tracker was already planned as a table in the panel (ARCHITECTURE.md), stage 4.

**Decision.**
- **Vacancies feed** (`/vacancies`): one input ("paste a link or the text; several links at once are fine") and a feed of **cards**, newest first, with search (company, role, city, text) and filters (4–5, in progress, not a fit, all). One link = one card; pasting a link that is already in the feed opens the existing card instead.
- **A card is isolated.** Under the hood each card is its own hidden chat (`chats.kind = "card"`) with the `jobsearch-vacancy` skill and the person's rules in the system prompt (cached), and only that card's messages. Follow-up questions are asked on the card page and stay about that vacancy.
- **Documents** follow the skill: made automatically for 4–5; for 3 and below a button "make documents anyway". Cover letter: the skill's letter JSON (`scripts/make_letter.py` format) rendered by the server as DOCX and converted to PDF (same pipeline as the CV, decision 0010). Adapted CV: same CV template, stored with the vacancy (the master CV is used as is when it fits). Files are attached to the vacancy.
- **Tracker** (`/tracker`): a table of the same vacancies: date, company, role, score, status, next step, city. By default it shows the vacancies with documents or a later status; a filter shows all. Status changes in place. CSV export.
- **Vacancy story**: when the status becomes "reply" or "interview" (by the person in the tracker; from Gmail in stage 5), or with a button, the vacancy gets its own chat (`chats.kind = "story"`) that starts with the card's summary and documents in its context. It is listed in "My chats".
- **Stage 4 is split**: 4a — feed, cards, documents, tracker, stories; 4b — Gmail connection and drafts (decision 0008), Google Sheets export.

**Why.**
- A feed of cards keeps the "one place" feel without ambiguity: in one free-form chat, "make the documents" would leave the assistant guessing which vacancy is meant (errors, more tokens).
- Reusing chats for cards keeps one engine: background replies, progress, costs, attachments.
- The skill and rules in the cached system prompt save a tool round trip per card and are read at the cache price.
- Letter as DOCX → PDF: no second renderer (Chromium) in the image, and the letter becomes editable in Word.

**Rejected.**
- **One chat for all vacancies with the whole history sent each time:** cost grows with every vacancy; context mixes vacancies.
- **One free-form chat with only the latest message sent:** follow-ups lose their vacancy.
- **A chat per vacancy** (stage 2 behaviour): a thousand chats.
- **The skill's HTML letter rendered with Chromium (Playwright):** +300 MB image, a second document pipeline.
