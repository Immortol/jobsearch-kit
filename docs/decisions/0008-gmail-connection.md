# 0008 · Connect the user's Gmail instead of a forwarding address — 2026-11-09

Supersedes the "Gmail OAuth" rejection in 0001 and the inbound part of 0004.

**Context.**
- All first users are on Gmail (pilot countries: Israel and Russia).
- Recruiters distrust unfamiliar domains; applications must keep going out from the person's own `firstname.lastname@gmail.com`. (The forwarding address of 0004 would never have been visible to recruiters, but it could not put drafts into the person's own mailbox or see employer replies.)
- The main value of the product is the morning digest with ready application packages (confirmed by Alexander). The best "last step" is a draft waiting in the person's own Gmail: check it, press Send.
- New fact: Google does not require app verification for apps for personal use with fewer than 100 users; users click through an "unverified app" warning instead. The paid security assessment applies only when verifying restricted scopes. The earlier rejection assumed verification was unavoidable.
- The skills for the Claude app already work through Gmail (reading alerts, labels, drafts), so the web version needs fewer adapter changes.

**Decision.**
- Each user connects their Gmail to the panel with Google OAuth (Google Cloud project owned by Alexander).
- Scopes: `gmail.readonly` (job alerts, employer replies), `gmail.compose` (drafts), `gmail.labels` (labels). **No `gmail.send`**: the panel cannot send anything on the person's behalf, by construction.
- The app stays unverified, published as "In production" (not "Testing": test-mode authorizations expire every 7 days), for fewer than 100 users. To be confirmed in practice when built.
- The code reads only what it needs (messages from known job-alert senders and replies to tracked applications), even though the scope allows the whole mailbox. The panel says so plainly on the connect screen.
- OAuth refresh tokens are stored encrypted like API keys (Fernet, `APP_ENCRYPTION_KEY`); "disconnect Gmail" revokes and deletes the token; account deletion does the same.
- Google API Services User Data Policy (Limited Use) applies: Gmail data is used only for the person's own features. Check the policy's AI-related terms before the first Gmail data goes to the Claude API (stage 4).
- Resend stays for outbound only (sign-in codes, invitations, digest). No inbound email for now.
- When: drafts in Gmail — stage 4; reading job alerts and replies — stage 5.

**Why.** Zero setup for the user beyond one connect click; employer replies update the tracker; drafts sit in the person's own mailbox and go out from their own address; reuses how the skills already work.

**Rejected.**
- Forwarding address (0004) — invisible to recruiters, but every user sets up filters, replies bypass the tracker, drafts have to be copied by hand. Kept in the backlog for users not on Gmail or if Google changes its rules.
- Verified app with a security assessment — not needed below 100 users; revisit only if the panel grows past that.
- `gmail.send` scope — contradicts the "drafts only" principle.

**Risks.** The "unverified app" warning may scare people — the connect screen explains it beforehand. Google may tighten rules for unverified apps — fallback is the forwarding address. Holding read access to friends' mailboxes is a responsibility: tokens encrypted, never logged, revocable from the panel and from the Google account.
