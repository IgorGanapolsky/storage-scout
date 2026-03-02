# AEO Revenue Evidence Dossier (2026-03-02)

## Scope
This dossier evaluates whether the new done-for-you AEO service can produce real revenue with low execution risk.

## Method
- Source priority: official platform docs, regulator docs, large-sample analytics studies.
- Confidence labels:
  - High: official docs or large-scale first-party analytics.
  - Medium: reputable industry surveys and operator studies.
  - Low: unverified market anecdotes.
- Rule: no revenue claim is treated as proven until tied to measurable funnel events.

## Executive Verdict
- Verdict: viable, but only with strict measurement and authority operations.
- What is proven:
  - AI discovery channels are growing and increasingly used for purchase research.
  - Search/answer platforms expose technical levers we can control (crawlability, structured content, transparent attribution).
  - Local buyer trust still depends on reviews, citations, and authority consistency.
- What is not proven yet:
  - Guaranteed ranking or deterministic revenue uplift from schema/content changes alone.
  - Current close-rate and payback period for this specific offer in this specific funnel.

## Evidence Matrix

### 1) AI answer discovery is materially growing (High)
- Adobe Analytics (1 trillion US retail site visits): Generative AI traffic during 2024 holiday season grew 1300% year-over-year, with conversion rates approaching but not yet matching other channels.
  - Source: https://blog.adobe.com/en/publish/2025/02/06/adobe-data-generative-ai-traffic-surges-1300-percent-holiday-shopping-season
- Bain consumer survey summary: 80% of consumers rely on zero-click results in at least 40% of searches; 68% of users who used AI assistants used them for shopping research.
  - Source: https://www.bain.com/insights/winning-in-the-new-era-of-seo/

Interpretation (inference): demand for AI-discoverable answers is real; conversion requires stronger trust signals and intent matching.

### 2) Platform mechanics are controllable and measurable (High)
- OpenAI: OAI-SearchBot can be allowed/disallowed via robots.txt, and traffic can be attributed using `utm_source=chatgpt.com`.
  - Source: https://help.openai.com/en/articles/10500283-web-search-in-chatgpt
- OpenAI: ranking has no guaranteed position controls.
  - Source: https://openai.com/index/introducing-chatgpt-search/
- Perplexity: has separate crawlers (`PerplexityBot`, `Perplexity-User`, etc.); `Perplexity-User` does not honor robots.txt because it fetches user-requested URLs.
  - Source: https://docs.perplexity.ai/guides/bots
- Bing Webmaster Tools launched AI-performance reporting for Copilot and AI Search (clicks, impressions, pages).
  - Source: https://blogs.bing.com/webmaster/may-2025/Bing-Webmaster-Tools-May-2025-Monthly-News

Interpretation (inference): we can instrument an evidence loop instead of guessing.

### 3) Structured answers help but are not a guarantee (High)
- Google Search docs: structured data helps Google understand page content; rich-result eligibility requires compliance and is not guaranteed.
  - Source: https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data
- Google FAQ rich-result policy narrowed broad FAQ eligibility (mostly authoritative/government/health contexts in many regions).
  - Sources:
    - https://developers.google.com/search/docs/appearance/structured-data/faqpage
    - https://developers.google.com/search/blog/2023/08/howto-faq-changes

Interpretation (inference): schema is a required hygiene layer, not a standalone growth hack.

### 4) Authority and trust are hard constraints (High)
- FTC final rule bans fake reviews/testimonials and authorizes civil penalties.
  - Source: https://www.ftc.gov/business-guidance/blog/2024/08/final-rule-fake-reviews-testimonials-what-it-does-doesnt-do
- BrightLocal local consumer survey: trust in reviews remains high, and consumers increasingly use AI tools to evaluate local businesses.
  - Source: https://www.brightlocal.com/research/local-consumer-review-survey/

Interpretation (inference): authority work must be real and policy-safe; shortcuts create legal and platform risk.

### 5) Crawl access from major AI vendors is explicit (High)
- Anthropic documents crawler controls and user-agent behavior for Claude web retrieval.
  - Source: https://support.anthropic.com/en/articles/11165117-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler

Interpretation (inference): crawl policy hygiene should include OpenAI, Perplexity, Anthropic, and Bing/Google ecosystems.

## What This Means for Revenue

### Revenue thesis
The service can make money if it sells execution speed + evidence accountability, not "ranking promises."

### Valid offer positioning
- Promise: "We run your AEO implementation loop end-to-end."
- Non-promise: "Guaranteed rankings/revenue."
- Commercial proof must come from attributable events:
  - qualified sessions from AI sources
  - booked calls
  - paid setup sprint purchases
  - monthly retainer activations

## 30-Day Proof Protocol (Pass/Fail)

### Instrumentation gate (Day 1-3)
Pass criteria:
- GA4 events firing for all funnel CTAs.
- Thank-you event recorded (`intake_submit`).
- UTM capture configured for AI sources (`chatgpt.com`, `perplexity.ai`, `copilot.microsoft.com`).
- Bing Webmaster AI report connected.

Failure criteria:
- Any missing event path from landing -> intake -> thank-you.

### Traffic quality gate (Day 4-14)
Pass criteria:
- >= 100 sessions from attributable AI/answer sources OR >= 20 highly-qualified inbound sessions with >= 90s engagement and >= 2 page views.

Failure criteria:
- AI traffic exists but low-intent bounce dominates without CTA engagement.

### Commercial gate (Day 15-30)
Pass criteria:
- >= 10 qualified leads from funnel submissions or direct inbound replies.
- >= 3 paid setup sprint purchases OR >= 2 retained monthly clients.
- CAC payback <= 45 days on closed clients.

Failure criteria:
- traffic with no closeable pipeline; indicates mismatch in ICP/offer or weak authority proof.

## No-Tech-Debt Guardrails
- Keep machine-readable assets current (`sitemap.xml`, `llms.txt`, JSON-LD blocks).
- Enforce compliance language (no guarantees, explicit consent language, STOP/HELP where SMS implied).
- Reject any testimonial/review workflow that violates FTC review policy.
- Require weekly evidence report before making pricing or channel decisions.

## Unavoidable Manual/External Dependencies
These are the only non-automatable items:
- Account credentials/access grants (GA4, Bing Webmaster, Google Business Profile, directory accounts).
- Legal approvals for policy-sensitive claims.

## Next Iteration Targets
- Expand question-cluster pages for 2-3 highest-margin verticals.
- Add AI-source segmented dashboard rows to weekly report.
- Run monthly evidence audit against pass/fail gates above.
