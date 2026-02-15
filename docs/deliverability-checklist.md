# Email Deliverability Checklist — callcatcherops.com

> Last audited: 2026-02-14

## Current DNS Status

### ✅ MX Records (OK)
```
10 in1-smtp.messagingengine.com
20 in2-smtp.messagingengine.com
```
Fastmail MX is correctly configured.

### ⚠️ SPF Record (NEEDS FIX)
**Current:**
```
"v=spf1 include:spf.messagingengine.com ?all"
```
**Problem:** `?all` is a **neutral** qualifier — inbox providers treat it as "no opinion" which is almost as bad as no SPF at all. Gmail and Outlook may soft-fail your emails.

**Fix:** Change `?all` → `-all` (hard fail):
```
"v=spf1 include:spf.messagingengine.com -all"
```

**How to fix:**
1. Log into [Cloudflare Dashboard](https://dash.cloudflare.com) → callcatcherops.com → DNS → Records
2. Find the TXT record for `callcatcherops.com` with content starting `v=spf1`
3. Edit it to: `v=spf1 include:spf.messagingengine.com -all`
4. Save

> Note: The wrangler OAuth token lacks `dns_records:write` scope. To fix via API, create a Cloudflare API Token with DNS edit permissions at https://dash.cloudflare.com/profile/api-tokens.

### ✅ DKIM Records (OK)
```
fm1._domainkey → v=DKIM1; k=rsa; p=MIIBIjAN... (active key)
fm2._domainkey → v=DKIM1; k=rsa; p=             (rotated/blank — normal)
fm3._domainkey → v=DKIM1; k=rsa; p=             (rotated/blank — normal)
```
Fastmail DKIM is correctly configured. `fm1` is the active signing key; `fm2`/`fm3` are blank per Fastmail's DKIM rotation best practice.

### ⚠️ DMARC Record (NEEDS HARDENING)
**Current:**
```
"v=DMARC1; p=none; rua=mailto:dmarc@callcatcherops.com"
```
**Problem:** `p=none` means **no enforcement** — spoofed emails from your domain are still delivered.

**Phased fix:**
1. **Now (after fixing SPF):** Keep `p=none` for 2 weeks to collect reports
2. **After 2 weeks:** Change to `p=quarantine; pct=100; rua=mailto:dmarc@callcatcherops.com`
3. **After 30 days clean:** Change to `p=reject; rua=mailto:dmarc@callcatcherops.com`

**Recommended final DMARC:**
```
"v=DMARC1; p=quarantine; rua=mailto:dmarc@callcatcherops.com; adkim=r; aspf=r"
```

---

## Cold Outreach Protection

### 🛡️ Buy a Secondary Domain
**Do NOT send cold outreach from callcatcherops.com.** If recipients mark cold emails as spam, your main domain's reputation tanks — affecting ALL emails (invoices, support, transactional).

**Recommendation:**
- Register `callcatcherops.co` or `getcallcatcher.com` (~$10/yr)
- Set up SPF/DKIM/DMARC on the secondary domain
- Use the secondary domain exclusively for cold outreach
- Forward replies to your main inbox

### 📧 Cold Email Platform
Use a dedicated platform with built-in warmup, deliverability monitoring, and send limits:

| Platform | Price | Key Features |
|----------|-------|-------------|
| **Instantly.ai** | $30/mo | Unlimited warmup, send rotation, analytics |
| **Woodpecker** | $29/mo | A/B testing, auto follow-ups, bounce detection |
| **Smartlead** | $39/mo | Unlimited mailboxes, warmup, IP rotation |

These platforms gradually warm up your secondary domain's sending reputation over 2-4 weeks before scaling volume.

---

## Action Items

- [ ] Fix SPF: change `?all` → `-all` in Cloudflare DNS
- [ ] Monitor DMARC reports at dmarc@callcatcherops.com for 2 weeks
- [ ] Harden DMARC: change `p=none` → `p=quarantine` after clean report period
- [ ] Register secondary domain for cold outreach
- [ ] Set up cold email platform (Instantly.ai recommended)
- [ ] Create Cloudflare API Token with DNS edit perms for future automation
