# 0004 · Email: Resend on the `mail.almoti.com` subdomain — 2026-11-03

> Inbound part superseded by 0008 (users connect their Gmail). Resend remains for outbound email.

**Context.** Stage 1 needs outbound email (login links, invitations). Stage 5 will need inbound email: each user gets an address to forward job alerts and employer replies to. Any provider needs our own domain for DKIM/SPF, otherwise mail to iCloud/Gmail lands in spam. Alexander owns `almoti.com`.

**Decision.**
- Provider — **Resend**, free plan to start.
- Sending and (later) receiving domain — the subdomain **`mail.almoti.com`**. Sender: `Jobsearch Kit <login@mail.almoti.com>`.
- All email code sits behind one module (`app/email.py`) with a small sender interface. In development (`APP_ENV=dev`) emails are printed to the console instead of sent.
- The Resend API key lives only in the Railway variable `RESEND_API_KEY`; Alexander sets it himself.
- The web panel stays on Railway's default `*.up.railway.app` address for now (custom domain — backlog).

**Why.**
- The free plan (3,000 emails/month, 100/day, inbound included, up to 3 domains) covers the MVP: ~5 users × (digest + ~10 job alerts) ≈ 55 emails/day.
- A subdomain does not touch any records already on `almoti.com` (e.g. personal mail on the root domain).
- One module means switching providers is about half a day of work.

**Rejected.**
- Postmark — best deliverability, but inbound requires the Pro plan ($16.50/month); free Developer plan is 100 emails/month.
- Mailgun — heavier API, short log retention on the free plan.

**Watch.** Inbound and outbound share the 100/day quota. If forwarded job alerts approach it in stage 5 — Resend Pro or Postmark Pro.
