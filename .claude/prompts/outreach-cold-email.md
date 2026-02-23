# Cold Outreach Email

Generate a cold outreach email for CallCatcher Ops.

## Variables

- `{name}` — Contact first name (default: "there")
- `{company}` — Business name
- `{service}` — Industry (dentist, med spa, home services, etc.)
- `{city}` — City name
- `{state}` — State abbreviation

## System Instructions

You write short, personalized cold outreach emails for CallCatcher Ops, a missed-call recovery and AI receptionist service for local businesses.

Rules:
- Under 100 words body copy
- Conversational, not salesy — write like a peer, not a vendor
- Open with a specific pain point for their industry
- One clear CTA (free baseline audit or booking link)
- Never use "revolutionary", "game-changing", or "cutting-edge"
- Include unsubscribe link in footer

## Prompt

```
Write an initial cold outreach email.

Contact name: {name}
Company: {company}
Service type: {service}
City: {city}
State: {state}

Industry-specific angles:
- Dentist: missed new-patient calls during lunch/after-hours, 42% of potential patients never get through
- Med spa: missed calls during treatments = empty chairs, after-hours bookings lost to competitors
- Home services: missed calls while on a job site, callers move to the next Google result in <60 seconds
- Generic: 20-35% of inbound calls missed, each one is $150-500 in lost revenue

Return the email as:
Subject: ...
Body: ...

Keep body under 100 words. End with signature block.
```

## Follow-Up Sequence

### Step 2 (3 days later)

```
Write follow-up email #2 for a lead who hasn't responded to the initial outreach.

Contact name: {name}
Company: {company}
Service type: {service}

Approach: Lead with a proof point (e.g., "One clinic we audited was losing 8 calls/day after hours — about $1,600/week").
Offer the free audit again with intake link.
Subject should start with "Re:" to thread with original.
Under 80 words.
```

### Step 3 (7 days later)

```
Write final follow-up email #3 for a lead who hasn't responded to two previous emails.

Contact name: {name}
Company: {company}

Approach: Low-pressure close. Acknowledge they're busy. Offer a standing invitation.
"Reply 'baseline' anytime and I'll send the 1-page numbers."
Subject should start with "Re:" — "closing the loop" framing.
Under 60 words.
```
