# Missed-Call Audit Report Copy

Generate copy for the 1-page missed-call audit deliverable sent to prospects.

## Prompt — Full Report

```
Write the copy sections for a 1-page missed-call audit report.

Business: {company}
Industry: {service}
City: {city}
Calls attempted: {calls_attempted}
Calls answered: {calls_answered}
Voicemails reached: {voicemails}
Estimated missed calls/week: {missed_per_week}
Estimated revenue loss/month: {revenue_loss}

Sections needed:

1. HEADLINE (under 10 words, lead with their revenue loss number)

2. EXECUTIVE SUMMARY (2-3 sentences)
   - State the finding plainly
   - Quantify the gap
   - No selling — just the data

3. WHAT WE FOUND (bullet points)
   - Call disposition breakdown
   - Response time observations
   - After-hours coverage gaps

4. WHAT THIS COSTS YOU (1 paragraph)
   - Monthly/annual revenue impact using their average ticket price
   - Compare to industry benchmarks (dentist avg ticket: $350, med spa: $250, HVAC: $450)

5. RECOMMENDED NEXT STEP (1 sentence)
   - Single clear action: "Book a 15-minute call to see the fix in action"
   - No feature lists, no pricing, no pressure

Tone: Factual, consultant-grade. Like a report from an analyst, not a sales deck.
```

## Prompt — Email Delivering the Report

```
Write a short email (under 80 words) delivering the completed audit report.

Contact name: {name}
Company: {company}
Key finding: {key_finding}

Structure:
- 1-line opener referencing the audit
- The key number (e.g., "You're missing ~12 calls/week, roughly $4,200/month")
- Link to the report
- 1-line soft CTA

No hard sell. The report does the selling.
```
