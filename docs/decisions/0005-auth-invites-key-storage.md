# 0005 · Login, invitations and API key storage — 2026-11-03

**Context.** Stage 1: 2–5 invited users log in without passwords and store their Anthropic API key. Alexander must be able to invite people himself without touching code.

**Decision.**
- **Invite-only.** Only addresses on the invite list (plus the owner, `OWNER_EMAIL` variable) can log in. The owner manages the list on the panel's "Invitations" page; adding an address sends an invitation email with the panel address. Revoking access deletes the account and all its data (with a confirmation).
- **Email link login.** A random single-use token, stored only as a SHA-256 hash, valid 15 minutes, at most 5 links per address per hour. The link opens a page with a "Sign in" button (POST), so mail scanners that prefetch links cannot use it up. The login form gives the same answer whether or not the address is invited.
- **Sessions** are random IDs stored hashed in the database, in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie for 30 days. POST requests from another origin are rejected.
- **API key.** Checked with a free `GET /v1/models` request before saving. Encrypted in the app with Fernet (`cryptography`); the encryption key(s) live only in `APP_ENCRYPTION_KEY` (comma-separated for rotation). The panel shows only the last 4 characters. Request logs contain method and path only, never bodies or query strings.
- **Rules** are stored as documents with the same file names as `Rules/` in the skills (`01_Facts.md`, `Market_DE.md`, …), so stage 2's `read_rules`/`write_rules` map onto the skills one to one.
- **GDPR from day one:** "download my data" (JSON) and "delete my account" buttons.

**Why.**
- Login is ~100 lines of our own code; auth libraries are built around passwords and add more than they save.
- Encryption in the app (not `pgcrypto`) means the encryption key never reaches the database or its backups.
- Hashed tokens and sessions: a database leak does not let anyone log in.

**Rejected.**
- Invite list as a Railway variable — Alexander would edit variables and wait for a redeploy for every friend.
- Open sign-up — not needed for 2–5 people and invites abuse.
- Passwords / OAuth — more to build and support, nothing gained at this scale.
