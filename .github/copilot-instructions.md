# GitHub Copilot Instructions for CallCatcher Ops

This repository is focused on one business: CallCatcher Ops.

## Product Context
- Offer: missed-call recovery + appointment booking automation for local service businesses
- Revenue path: landing page -> intake -> audit/build -> managed growth
- Primary code areas:
  - `docs/callcatcherops/` (public website + intake)
  - `autonomy/` (outreach engine, dry-run default)
  - `business/callcatcherops/` (offers, pricing, scripts)

## Non-Negotiable Rules
- Never add or commit secrets, API keys, tokens, or PII.
- Keep outreach dry-run by default unless explicitly configured by the user.
- Preserve a clean CTA flow and valid public URLs.
- Prefer small, auditable Python scripts and minimal dependencies.

## Coding Priorities
1. Revenue conversion (CTA clarity, booking flow, payment flow)
2. Reliability (no broken pages/scripts, safe defaults)
3. Measurement (analytics events and attributable outcomes)

## Python Standards
- Keep functions small and explicit.
- Validate external inputs.
- Avoid hidden side effects.
- Run `ruff check autonomy/ --select E,F,W --ignore E501` before merge.

## Website Standards
- Keep metadata accurate (title, description, canonical, OG).
- Keep sitemap/robots/llms files aligned to live URLs.
- Avoid placeholder CTAs in production-facing pages.
