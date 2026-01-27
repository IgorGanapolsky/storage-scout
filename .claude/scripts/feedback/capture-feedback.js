#!/usr/bin/env node
/**
 * RLHF Feedback Capture System
 * Captures thumbs up/down feedback with rich context for learning
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const FEEDBACK_LOG = path.join(__dirname, '../../memory/feedback/feedback-log.jsonl');
const FEEDBACK_SUMMARY = path.join(__dirname, '../../memory/feedback/feedback-summary.json');

// Domain tags for storage-scout project
const DOMAIN_TAGS = {
  'spread': ['spread', 'calculation', 'formula', 'profit', 'arbitrage'],
  'flutter': ['flutter', 'dart', 'widget', 'ui', 'mobile', 'app'],
  'github': ['github', 'git', 'pr', 'push', 'commit', 'branch'],
  'api': ['api', 'http', 'request', 'response', 'endpoint'],
  'testing': ['test', 'spec', 'coverage', 'tdd', 'unit'],
  'csv': ['csv', 'data', 'storage', 'file', 'export'],
  'notification': ['ntfy', 'alert', 'push', 'notification'],
  'validation': ['validate', 'input', 'form', 'error'],
  'security': ['token', 'secret', 'auth', 'credential', 'env'],
  'ci': ['ci', 'action', 'workflow', 'pipeline', 'deploy']
};

// Action type classification
const ACTION_TYPES = {
  'implementation': ['implement', 'add', 'create', 'build', 'write'],
  'fix': ['fix', 'bug', 'error', 'issue', 'resolve'],
  'refactor': ['refactor', 'improve', 'optimize', 'clean'],
  'testing': ['test', 'spec', 'coverage', 'tdd'],
  'documentation': ['doc', 'readme', 'comment', 'explain'],
  'configuration': ['config', 'setup', 'env', 'settings'],
  'git-operations': ['commit', 'push', 'pr', 'merge', 'branch']
};

function generateId() {
  return 'fb_' + crypto.randomBytes(4).toString('hex');
}

function inferDomain(context) {
  const lowerContext = context.toLowerCase();
  for (const [domain, keywords] of Object.entries(DOMAIN_TAGS)) {
    if (keywords.some(kw => lowerContext.includes(kw))) {
      return domain;
    }
  }
  return 'general';
}

function inferActionType(context) {
  const lowerContext = context.toLowerCase();
  for (const [actionType, keywords] of Object.entries(ACTION_TYPES)) {
    if (keywords.some(kw => lowerContext.includes(kw))) {
      return actionType;
    }
  }
  return 'general';
}

function classifyOutcome(feedback, context) {
  const lowerContext = context.toLowerCase();

  if (feedback === 'positive') {
    if (lowerContext.includes('quick') || lowerContext.includes('fast')) return 'quick-success';
    if (lowerContext.includes('thorough') || lowerContext.includes('comprehensive')) return 'deep-success';
    if (lowerContext.includes('creative') || lowerContext.includes('elegant')) return 'creative-success';
    return 'standard-success';
  } else {
    if (lowerContext.includes('wrong') || lowerContext.includes('incorrect')) return 'factual-error';
    if (lowerContext.includes('incomplete') || lowerContext.includes('missing')) return 'insufficient-depth';
    if (lowerContext.includes('hallucinate') || lowerContext.includes('made up')) return 'hallucination';
    if (lowerContext.includes('slow') || lowerContext.includes('took too long')) return 'inefficiency';
    return 'general-error';
  }
}

function extractTags(context) {
  const tags = [];
  const lowerContext = context.toLowerCase();

  // Extract domain tags
  for (const [domain, keywords] of Object.entries(DOMAIN_TAGS)) {
    if (keywords.some(kw => lowerContext.includes(kw))) {
      tags.push(domain);
    }
  }

  // Extract action tags
  for (const [action, keywords] of Object.entries(ACTION_TYPES)) {
    if (keywords.some(kw => lowerContext.includes(kw))) {
      tags.push(action);
    }
  }

  return [...new Set(tags)]; // Remove duplicates
}

function captureFeedback(feedbackType, context, additionalData = {}) {
  const feedback = feedbackType.toLowerCase();
  const isPositive = ['up', 'thumbsup', '👍', '+', 'positive', 'good', 'great'].includes(feedback);
  const isNegative = ['down', 'thumbsdown', '👎', '-', 'negative', 'bad', 'wrong'].includes(feedback);

  if (!isPositive && !isNegative) {
    console.error('Invalid feedback type. Use: up/down, thumbsup/thumbsdown, 👍/👎, +/-');
    process.exit(1);
  }

  const feedbackEntry = {
    id: generateId(),
    timestamp: new Date().toISOString(),
    feedback: isPositive ? 'positive' : 'negative',
    reward: isPositive ? 1 : -1,
    context: context,
    tags: extractTags(context),
    actionType: inferActionType(context),
    richContext: {
      domain: inferDomain(context),
      outcomeCategory: classifyOutcome(isPositive ? 'positive' : 'negative', context),
      filePaths: additionalData.filePaths || [],
      errorType: additionalData.errorType || null
    }
  };

  // Ensure directory exists
  const dir = path.dirname(FEEDBACK_LOG);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  // Append to JSONL log
  fs.appendFileSync(FEEDBACK_LOG, JSON.stringify(feedbackEntry) + '\n');

  // Update summary
  updateSummary(feedbackEntry);

  console.log(`✅ Feedback captured: ${feedbackEntry.id}`);
  console.log(`   Type: ${feedbackEntry.feedback} (reward: ${feedbackEntry.reward})`);
  console.log(`   Domain: ${feedbackEntry.richContext.domain}`);
  console.log(`   Tags: ${feedbackEntry.tags.join(', ')}`);

  return feedbackEntry;
}

function updateSummary(entry) {
  let summary = {
    totalFeedback: 0,
    positive: 0,
    negative: 0,
    byDomain: {},
    byActionType: {},
    recentPatterns: [],
    lastUpdated: null
  };

  if (fs.existsSync(FEEDBACK_SUMMARY)) {
    try {
      summary = JSON.parse(fs.readFileSync(FEEDBACK_SUMMARY, 'utf8'));
    } catch (e) {
      // Use default summary
    }
  }

  summary.totalFeedback++;
  if (entry.reward > 0) {
    summary.positive++;
  } else {
    summary.negative++;
  }

  // Track by domain
  const domain = entry.richContext.domain;
  if (!summary.byDomain[domain]) {
    summary.byDomain[domain] = { positive: 0, negative: 0 };
  }
  if (entry.reward > 0) {
    summary.byDomain[domain].positive++;
  } else {
    summary.byDomain[domain].negative++;
  }

  // Track by action type
  const actionType = entry.actionType;
  if (!summary.byActionType[actionType]) {
    summary.byActionType[actionType] = { positive: 0, negative: 0 };
  }
  if (entry.reward > 0) {
    summary.byActionType[actionType].positive++;
  } else {
    summary.byActionType[actionType].negative++;
  }

  // Track recent patterns (keep last 10)
  summary.recentPatterns.unshift({
    id: entry.id,
    feedback: entry.feedback,
    domain: domain,
    timestamp: entry.timestamp
  });
  summary.recentPatterns = summary.recentPatterns.slice(0, 10);

  summary.lastUpdated = new Date().toISOString();

  fs.writeFileSync(FEEDBACK_SUMMARY, JSON.stringify(summary, null, 2));
}

function showStats() {
  if (!fs.existsSync(FEEDBACK_SUMMARY)) {
    console.log('No feedback recorded yet.');
    return;
  }

  const summary = JSON.parse(fs.readFileSync(FEEDBACK_SUMMARY, 'utf8'));

  console.log('\n📊 RLHF Feedback Statistics\n');
  console.log(`Total Feedback: ${summary.totalFeedback}`);
  console.log(`  👍 Positive: ${summary.positive}`);
  console.log(`  👎 Negative: ${summary.negative}`);
  console.log(`  Success Rate: ${((summary.positive / summary.totalFeedback) * 100).toFixed(1)}%`);

  console.log('\nBy Domain:');
  for (const [domain, stats] of Object.entries(summary.byDomain)) {
    const total = stats.positive + stats.negative;
    const rate = ((stats.positive / total) * 100).toFixed(1);
    console.log(`  ${domain}: ${stats.positive}/${total} (${rate}%)`);
  }

  console.log('\nBy Action Type:');
  for (const [action, stats] of Object.entries(summary.byActionType)) {
    const total = stats.positive + stats.negative;
    const rate = ((stats.positive / total) * 100).toFixed(1);
    console.log(`  ${action}: ${stats.positive}/${total} (${rate}%)`);
  }

  if (summary.recentPatterns.length > 0) {
    console.log('\nRecent Feedback:');
    summary.recentPatterns.slice(0, 5).forEach(p => {
      const emoji = p.feedback === 'positive' ? '👍' : '👎';
      console.log(`  ${emoji} [${p.domain}] ${p.timestamp.split('T')[0]}`);
    });
  }
}

// CLI interface
const args = process.argv.slice(2);
const command = args[0];

if (command === 'stats') {
  showStats();
} else if (command === 'up' || command === 'down' || command === 'thumbsup' || command === 'thumbsdown') {
  const context = args.slice(1).join(' ') || 'No context provided';
  captureFeedback(command, context);
} else if (args.length >= 2) {
  captureFeedback(args[0], args.slice(1).join(' '));
} else {
  console.log(`
RLHF Feedback Capture System

Usage:
  node capture-feedback.js up "Context description"
  node capture-feedback.js down "Context description"
  node capture-feedback.js stats

Examples:
  node capture-feedback.js up "Excellent spread calculation implementation"
  node capture-feedback.js down "Forgot to add tests for edge case"
  node capture-feedback.js stats
  `);
}

module.exports = { captureFeedback, showStats };
