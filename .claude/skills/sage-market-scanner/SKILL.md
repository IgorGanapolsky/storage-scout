# SAGE Market Scanner

24/7 autonomous market scanning with SAGE-inspired feedback loop for intelligent opportunity detection. Based on Google's SAGE research (Steerable Agentic Data Generation for Deep Search with Execution Feedback).

## Triggers

- User says "scan market", "find opportunities", "check listings"
- User mentions "arbitrage", "clearance", "deals"
- `/sage-scan` or `/market-scanner` command

## Instructions

### Core Concept

SAGE principles applied to market scanning:
1. **Execution feedback** - Track what actually converts, not just what looks good
2. **When to search again** - Only deep-search when initial results look promising
3. **When to stop** - Don't waste resources on low-probability listings
4. **Reason across sources** - Combine platform, timing, and pricing signals

### Quick Start

```bash
# Run a market scan
python3 agents/sage_feedback_loop.py

# Record an inquiry
python3 agents/sage_feedback_loop.py inquiry <listing_id> <platform> <inquiry_type>

# Record a conversion
python3 agents/sage_feedback_loop.py conversion <listing_id> <platform> <revenue>

# Get insights
python3 agents/sage_feedback_loop.py insights

# Retrain weights from conversion data
python3 agents/sage_feedback_loop.py retrain
```

### Supported Platforms

| Platform | Type | Status |
|----------|------|--------|
| Facebook Marketplace | Tool rentals | ✅ Active |
| Craigslist | Tool rentals | ✅ Active |
| 2Quip | Tool rentals | ✅ Active |
| Neighbor.com | Storage arbitrage | ✅ Active |
| Nextdoor | Local leads | ✅ Active |
| Yoodlize | P2P rentals | ✅ Active |

### SAGE Weights System

The scanner learns from conversions using Thompson Sampling-style updates:

```json
{
  "platform_weights": {
    "facebook": 1.2,      // Higher = better conversion
    "craigslist": 0.8,
    "neighbor": 1.1
  },
  "category_weights": {
    "pressure_washer": 1.3,
    "tile_saw": 1.1
  },
  "timing_weights": {
    "saturday": 1.4,      // Weekends convert better
    "monday": 0.9
  }
}
```

### Scoring a Listing

```python
score = loop.get_listing_score(
    platform="facebook",
    category="pressure_washer",
    daily_price=35.0
)
# Returns: {
#   "score": 0.72,
#   "should_list": True,
#   "needs_deep_search": False
# }
```

### GitHub Action (24/7 Scanning)

Already configured in `.github/workflows/sage-market-scanner.yml`:
- Runs every 4 hours
- Supports standard/deep/retrain modes
- Auto-commits weight updates

### Notification Channels

- **ntfy.sh**: Real-time push alerts for high-value opportunities
- **GitHub Issues**: Auto-created for opportunities above threshold
- **RALPH_STATE.md**: Session continuity tracking

## Publishing to ClawHub

This skill follows the Agent Skill convention and can be published:

```bash
npx clawhub@latest publish sage-market-scanner
```

## Best Practices

1. **Record ALL conversions** - Even failed ones inform the model
2. **Review insights weekly** - Adjust strategy based on data
3. **Retrain monthly** - Or after 50+ new events
4. **Trust the weights** - They reflect actual market behavior
