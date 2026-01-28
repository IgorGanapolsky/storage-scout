# YouTube Video Review Skill

## Purpose
Extract actionable business insights from YouTube videos when users share URLs or transcripts. Focus on implementation steps, not just summaries.

## Trigger Conditions
- User shares a YouTube URL (youtube.com/watch, youtu.be)
- User pastes video transcript or summary
- User asks "how do we leverage this" or "what can we learn from this"
- User mentions reviewing a video for business insights

## Workflow

### 1. Content Acquisition
Since YouTube cannot be directly fetched, request one of:
- User-provided transcript (from YouTube's transcript feature)
- User-provided summary or key points
- Screenshot of video content
- Third-party transcript service output

### 2. Analysis Framework
Extract insights in this structure:

```markdown
## Video Summary
[1-2 sentence overview]

## Key Takeaways
1. [Actionable insight #1]
2. [Actionable insight #2]
3. [Actionable insight #3]

## Implementation for [User's Business]
### Quick Wins (This Week)
- [ ] Step 1
- [ ] Step 2

### Medium-Term (This Month)
- [ ] Step 1
- [ ] Step 2

### Strategic (This Quarter)
- [ ] Step 1
- [ ] Step 2

## Tools/Resources Mentioned
- Tool 1: [What it does] - [URL if available]
- Tool 2: [What it does] - [URL if available]

## Warnings/Gotchas
- [Any risks or caveats mentioned]
```

### 3. Business Context Mapping
Always map insights to the user's specific context:
- **Storage Scout**: Storage arbitrage, Flutter app, GitHub automation
- **AI Automation**: Claude Code workflows, agent patterns
- **SaaS/Product**: Feature development, user acquisition

## Example Analysis

**Input**: Nate Herk's "Clawdbot vs Claude Code" video

**Output**:
```markdown
## Video Summary
Comparison of Clawdbot (autonomous AI agent) vs Claude Code for developer productivity.
Claude Code wins for coding; Clawdbot wins for ambient assistant tasks.

## Key Takeaways
1. Claude Code provides 10-30% coding speedup with proper prompts
2. Autonomous agents need strict security isolation (separate VPS, limited API keys)
3. Start with read-only access, graduate to write access after trust is established

## Implementation for Storage Scout
### Quick Wins (This Week)
- [ ] Create Claude Code playbook with standard prompts for Flutter/Dart
- [ ] Document project context in CLAUDE.md (already done!)
- [ ] Set up budget alerts on Anthropic API usage

### Medium-Term (This Month)
- [ ] Build CLI workflow for "storage market audit" (fetch prices → analyze → report)
- [ ] Add automated security scan to CI pipeline

### Strategic (This Quarter)
- [ ] Evaluate Clawdbot for ambient tasks (email triage, calendar management)
- [ ] Build "Storage Scout as a Service" for other arbitrageurs
```

## Integration Points

### With RLHF System
After analysis, prompt for feedback:
```
Was this analysis helpful for your business?
👍 = actionable insights
👎 = too generic or missed the point
```

### With Session State
Save analysis to `.claude/RALPH_STATE.md` for continuity:
```markdown
## Last Video Analyzed
- URL: [youtube link]
- Date: [timestamp]
- Key Action: [most important next step]
```

## Commands

### Trigger Skill
```
/youtube-review [URL or "analyze the video I just shared"]
```

### Export Analysis
Analysis can be exported to:
- GitHub Issue (for tracking implementation)
- Notion page (via API)
- Markdown file in `docs/insights/`

## Limitations
- Cannot directly fetch YouTube content (use transcripts)
- Cannot verify video claims (user should fact-check)
- Analysis quality depends on transcript quality

## Tags
- `video-analysis`
- `business-insights`
- `content-review`
- `competitive-intelligence`
