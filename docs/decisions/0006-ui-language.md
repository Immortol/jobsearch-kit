# 0006 · Interface language: English in code, Russian via a catalog — 2026-11-03

**Context.** The panel is Russian-only for now, but the repository must contain no Russian outside the skills and translation catalogs. More languages may follow.

**Decision.**
- All UI strings in templates and code are written in English and wrapped in `_()`.
- Translations live in `app/locales/<lang>.json` (English string → translation). The active language is the `UI_LOCALE` variable, default `ru`. A missing translation falls back to English.
- A test fails if any `_()` string has no `ru` translation.

**Why.** Simplest thing that works: no gettext compile step, the catalog is one readable file, adding a language is adding one file.

**Rejected.** gettext/Babel `.po` files — standard, but an extra toolchain and compile step for a few dozen strings; worth revisiting if plurals or many languages appear.
