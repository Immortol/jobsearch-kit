# 0012 · Google connection in stage 4b: drafts with the package, Drive folders, tracker sheet — 2026-11-11

Builds on 0008 (connect the user's Gmail) and 0011 (vacancy feed). Replaces the ARCHITECTURE.md line "export to Google Sheets via a service account".

**Context.**
- 0008 chose a per-user Google OAuth connection for Gmail drafts (stage 4) and reading mail (stage 5).
- The owner wants each application package as a folder he can upload in one go (0011 addendum: ZIP download) and the tracker as a Google spreadsheet.
- Once each user has a Google connection anyway, a service account for Sheets is an extra moving part: the sheet would live in someone else's Drive and have to be shared.
- The panel's address becomes `https://jobsearch.almoti.com` (the owner's domain) before the Google client is registered, because the redirect URI is part of that registration.

**Decision.**
- **One Google connection per user**, made in the panel (`/settings/google`), with the Google Cloud project owned by Alexander. Scopes in stage 4b: `gmail.compose` (create drafts), `drive.file` (only files and folders the panel creates), `openid email` (to show which account is connected). `gmail.readonly` and `gmail.labels` (0008) are requested only in stage 5, when reading mail starts — least privilege until then; Google asks once more at that point.
- **Drafts with the package attached**: the agent tool `gmail_draft` creates a draft in the person's Gmail with the letter text and the package files attached (letter PDF, CV PDF, files marked "in every package"). It never sends; there is no send scope.
- **Drive folders**: `Jobsearch/Applications/<Company – Role>/` in the person's own Drive, filled with the same package files after the card's documents are made, and on demand ("update the folder"). With Google Drive for desktop it is a folder on the computer.
- **Tracker sheet**: a spreadsheet "Jobsearch — tracker" in `Jobsearch/`, rewritten from the panel a few seconds after any change of the vacancies. One-way: the panel is the source; edits made in the sheet are overwritten (the sheet says so in its first row).
- **Google calls**: plain HTTPS calls (OAuth, Gmail, Drive, Sheets REST APIs) through one small client; the refresh token is stored encrypted like the API key; "disconnect" revokes it at Google and deletes it; account deletion does the same. Failures are logged and shown on the settings page; they never block the card itself.
- **Data use**: in stage 4b the panel reads nothing from Gmail and only its own files from Drive. Google's Limited Use and AI terms are checked again before stage 5 sends mail content to Claude.

**Why.**
- Drafts with attachments make applying by email two clicks: check, Send. Uploading to a portal stays "open the folder, select all".
- `drive.file` is a non-sensitive scope and sees nothing but the panel's own files.
- One-way sync avoids conflicts between two sources of truth at a size (one person, ≤ thousands of rows) where rewriting the sheet is cheap.
- No Google client libraries: four REST calls, easy to test with a mocked transport.

**Rejected.**
- **Service account for Sheets**: the sheet would not be the person's own and must be shared; a second credential to manage.
- **Two-way sync with the sheet**: conflicts, polling for changes; revisit if people really edit the sheet.
- **Full Drive scope** to place folders anywhere: sensitive, unnecessary.
- **Asking for `gmail.readonly` now**: not used before stage 5.
