# 0007 · Sign-in code in addition to the email link — 2026-11-06

**Context.** Live check of stage 1 on an iPhone: the sign-in link worked, but ~20 seconds later the panel asked to sign in again — twice. The link from the email opens in whatever browser the mail app chooses (often an in-app browser or a different one than where the panel is open); each browser keeps its own cookies, so the session lands in the wrong one. Same for "read mail on the phone, use the panel on the laptop".

**Decision.** Supplements 0005.
- The login email carries a **6-digit code** as well as the link. The code is also in the subject, so iPhone/Mac offer to fill it in from Mail.
- The "check your email" page has a code field; the code signs in **in the browser where it is typed**.
- Code and link belong to one login request: using either uses up both. Same 15-minute validity.
- Brute force: the code is stored hashed (salted with the request's token hash); every wrong code counts against all open requests of that address, and after 5 wrong codes they stop working. With at most 5 requests per hour that is ≤25 guesses per hour out of 1,000,000.
- The page recommends the code over the link.

**Why.** Works in any browser and across devices; no new dependencies; the same pattern Slack, Notion and Claude use.

**Rejected.**
- Link only, with an instruction for iPhone users — every new user would hit it once and get confused.
- Passkeys — best UX in the long run, but more code and a harder recovery story for 2–5 people. Possible later.
