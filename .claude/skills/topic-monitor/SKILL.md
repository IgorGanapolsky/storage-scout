# Topic Monitor

Automated monitoring system that transforms Claude from reactive to proactive by tracking topics of interest and sending intelligent alerts.

## Triggers

- User says "monitor", "track", "alert me", "watch for"
- User mentions "storage arbitrage", "tool rental", "gumroad", "competitor"
- `/topic-monitor` command

## Instructions

When the user wants to monitor topics for business opportunities:

### 1. Configure Topics

Create/update `data/topic_monitor/config.json`:

```json
{
  "topics": [
    {
      "name": "storage-arbitrage",
      "query": "storage arbitrage OR storage rental profit",
      "keywords": ["neighbor.com", "self-storage", "RV storage", "spread"],
      "frequency": "daily",
      "importance_threshold": "medium",
      "alert_channel": "ntfy"
    },
    {
      "name": "tool-rental-market",
      "query": "tool rental business OR power tool rental",
      "keywords": ["2quip", "rentmyequipment", "peer rental"],
      "frequency": "daily",
      "importance_threshold": "medium",
      "alert_channel": "ntfy"
    },
    {
      "name": "gumroad-automation",
      "query": "github actions automation gumroad",
      "keywords": ["workflow", "free tier", "cron"],
      "frequency": "daily",
      "importance_threshold": "high",
      "alert_channel": "ntfy"
    }
  ],
  "ntfy_topic": "$NTFY_TOPIC"
}
```

### 2. Importance Scoring

Assign priority based on:
- **HIGH**: Breaking news, major price changes (>10%), product releases, competitor launches
- **MEDIUM**: Related updates, community discussions, market trends
- **LOW**: Duplicates, tangential content, low-quality sources

### 3. Alert via ntfy.sh

```bash
curl -d "🔔 Topic Alert: $TOPIC_NAME

$SUMMARY

Source: $URL
Importance: $LEVEL" \
  -H "Title: Topic Monitor Alert" \
  -H "Priority: $PRIORITY" \
  "https://ntfy.sh/$NTFY_TOPIC"
```

### 4. GitHub Action for Scheduled Monitoring

Create `.github/workflows/topic-monitor.yml`:

```yaml
name: Topic Monitor
on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:

jobs:
  monitor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Topic Monitor
        env:
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
        run: python3 scripts/topic_monitor.py
```

## Best Practices

- Start with medium importance thresholds
- Use specific keywords with negative filters
- Review weekly digests to identify patterns
- Adjust scoring based on false positive rate
