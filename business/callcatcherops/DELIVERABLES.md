# Deliverables (Auto-Generated)

## Live Assets
- Domain: callcatcherops.com
- Email: hello@callcatcherops.com
- DMARC: p=none (monitoring)

## Site
- GitHub Pages repo: https://github.com/IgorGanapolsky/callcatcherops-site
- Custom domain configured: callcatcherops.com

## DNS Records (Cloudflare)
- MX @ -> in1-smtp.messagingengine.com (priority 10)
- MX @ -> in2-smtp.messagingengine.com (priority 20)
- TXT @ -> v=spf1 include:spf.messagingengine.com ?all
- CNAME fm1._domainkey -> fm1.callcatcherops.com.dkim.fmhosted.com
- CNAME fm2._domainkey -> fm2.callcatcherops.com.dkim.fmhosted.com
- CNAME fm3._domainkey -> fm3.callcatcherops.com.dkim.fmhosted.com
- TXT _dmarc -> v=DMARC1; p=none; rua=mailto:dmarc@callcatcherops.com
- CNAME @ -> igorganapolsky.github.io (GitHub Pages)
- CNAME www -> igorganapolsky.github.io

## Outreach Engine
- Config: autonomy/config.callcatcherops.json
- Sample leads: autonomy/data/leads_callcatcherops.csv

## Next Activations
- Add Fastmail aliases: sales@, support@, ops@.
- Add inbox forwarding rules if desired.
- Add lead list (200+ local businesses).
