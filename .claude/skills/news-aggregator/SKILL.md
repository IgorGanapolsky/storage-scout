# News Aggregator

Aggregates real-time news from multiple sources for market intelligence, tracking product launches, and monitoring mentions.

## Triggers

- User says "news", "trending", "what's happening", "check HN"
- User mentions "hacker news", "product hunt", "github trending"
- `/news` or `/news-aggregator` command

## Instructions

### Supported Sources

1. **Hacker News** - Tech/startup news, Show HN posts
2. **GitHub Trending** - Popular repositories
3. **Product Hunt** - New product launches
4. **Reddit** - Subreddit monitoring (r/SideProject, r/Automate, r/Entrepreneur)

### Usage

```bash
python3 scripts/fetch_news.py --source hackernews --limit 20 --keyword "automation,github actions"
python3 scripts/fetch_news.py --source producthunt --limit 10 --keyword "gumroad,automation"
python3 scripts/fetch_news.py --source all --limit 5
```

### Keyword Expansion Protocol

Automatically expand user queries:
- "automation" → "automation,workflow,cron,scheduler,github actions,zapier,n8n"
- "rental" → "rental,rent,lease,peer-to-peer,sharing economy"
- "arbitrage" → "arbitrage,spread,profit,flip,resell"

### Output Format

```markdown
## 📰 News Digest - {DATE}

### 🔥 Hacker News
1. [Title](url) - {score} points, {comments} comments
   > Brief summary relevant to your interests

### 🚀 Product Hunt
1. [Product Name](url) - {upvotes} upvotes
   > Description + relevance to your business

### 📊 GitHub Trending
1. [repo/name](url) - ⭐ {stars} (+{today})
   > Why this matters for automation
```

### Track Our Posts

Monitor specific posts by ID:
- HN Post: `item?id=46865237`
- Check score, comments, rank every 15 minutes

### GitHub Action

```yaml
name: News Aggregator
on:
  schedule:
    - cron: '0 8 * * *'  # Daily at 8am
  workflow_dispatch:

jobs:
  aggregate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Fetch News
        run: |
          python3 scripts/fetch_news.py --source all --limit 10 \
            --keyword "automation,github actions,gumroad" \
            --output reports/news_$(date +%Y%m%d).md
      - name: Commit Report
        run: |
          git add reports/
          git commit -m "chore: daily news $(date +%Y-%m-%d)" || true
          git push
```

## Best Practices

- Run daily digest at consistent time
- Track competitor product launches on Product Hunt
- Monitor Show HN for similar products
- Save reports for trend analysis
