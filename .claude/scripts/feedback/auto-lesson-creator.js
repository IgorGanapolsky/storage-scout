#!/usr/bin/env node
/**
 * Auto Lesson Creator
 * Automatically generates lessons from negative feedback to prevent future mistakes
 */

const fs = require('fs');
const path = require('path');

const FEEDBACK_LOG = path.join(__dirname, '../../memory/feedback/feedback-log.jsonl');
const LESSONS_DIR = path.join(__dirname, '../../memory/lessons');
const LESSONS_LEARNED_FILE = path.join(__dirname, '../../memory/lessons-learned.md');

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function loadFeedback() {
  if (!fs.existsSync(FEEDBACK_LOG)) {
    return [];
  }

  const content = fs.readFileSync(FEEDBACK_LOG, 'utf8');
  return content
    .split('\n')
    .filter(line => line.trim())
    .map(line => JSON.parse(line));
}

function generateLesson(feedback) {
  const domain = feedback.richContext?.domain || 'general';
  const category = feedback.richContext?.outcomeCategory || 'general-error';
  const context = feedback.context;

  // Determine severity based on outcome category
  const severityMap = {
    'hallucination': 'critical',
    'factual-error': 'high',
    'insufficient-depth': 'medium',
    'inefficiency': 'low',
    'general-error': 'medium'
  };
  const severity = severityMap[category] || 'medium';

  // Generate prevention strategy based on domain and category
  const preventionStrategies = {
    'hallucination': 'Always verify facts before stating them. If unsure, say "I believe" or "I think" instead of stating definitively.',
    'factual-error': 'Double-check technical details. Read documentation or source code before making claims.',
    'insufficient-depth': 'Ask clarifying questions if requirements are unclear. Provide comprehensive solutions.',
    'inefficiency': 'Plan before coding. Consider edge cases upfront.',
    'general-error': 'Review the context carefully before responding.'
  };

  const lesson = {
    id: `lesson_${feedback.id}`,
    feedbackId: feedback.id,
    createdAt: new Date().toISOString(),
    domain: domain,
    category: category,
    severity: severity,
    title: `${domain.charAt(0).toUpperCase() + domain.slice(1)}: ${category.replace(/-/g, ' ')}`,
    whatWentWrong: context,
    prevention: preventionStrategies[category] || preventionStrategies['general-error'],
    tags: feedback.tags || []
  };

  return lesson;
}

function saveLesson(lesson) {
  ensureDir(LESSONS_DIR);

  const filename = `${lesson.id}.json`;
  const filepath = path.join(LESSONS_DIR, filename);

  fs.writeFileSync(filepath, JSON.stringify(lesson, null, 2));
  console.log(`📝 Lesson created: ${filepath}`);

  return filepath;
}

function consolidateLessons() {
  ensureDir(LESSONS_DIR);

  const lessonFiles = fs.readdirSync(LESSONS_DIR).filter(f => f.endsWith('.json'));

  if (lessonFiles.length === 0) {
    console.log('No lessons to consolidate.');
    return;
  }

  const lessons = lessonFiles.map(f => {
    const content = fs.readFileSync(path.join(LESSONS_DIR, f), 'utf8');
    return JSON.parse(content);
  });

  // Sort by severity and date
  const severityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
  lessons.sort((a, b) => {
    const severityDiff = severityOrder[a.severity] - severityOrder[b.severity];
    if (severityDiff !== 0) return severityDiff;
    return new Date(b.createdAt) - new Date(a.createdAt);
  });

  // Generate markdown
  let markdown = `# Lessons Learned

> Auto-generated from RLHF feedback. Injected at session start.

Last updated: ${new Date().toISOString()}

---

`;

  // Group by severity
  const bySeverity = {};
  lessons.forEach(l => {
    if (!bySeverity[l.severity]) bySeverity[l.severity] = [];
    bySeverity[l.severity].push(l);
  });

  for (const severity of ['critical', 'high', 'medium', 'low']) {
    if (!bySeverity[severity] || bySeverity[severity].length === 0) continue;

    const emoji = { critical: '🚨', high: '⚠️', medium: '📋', low: 'ℹ️' }[severity];
    markdown += `## ${emoji} ${severity.charAt(0).toUpperCase() + severity.slice(1)} Priority\n\n`;

    bySeverity[severity].forEach(lesson => {
      markdown += `### ${lesson.title}\n\n`;
      markdown += `**What went wrong:** ${lesson.whatWentWrong}\n\n`;
      markdown += `**Prevention:** ${lesson.prevention}\n\n`;
      markdown += `*Domain: ${lesson.domain} | Tags: ${lesson.tags.join(', ') || 'none'}*\n\n`;
      markdown += `---\n\n`;
    });
  }

  // Add summary stats
  markdown += `## 📊 Summary\n\n`;
  markdown += `- Total lessons: ${lessons.length}\n`;
  markdown += `- Critical: ${bySeverity.critical?.length || 0}\n`;
  markdown += `- High: ${bySeverity.high?.length || 0}\n`;
  markdown += `- Medium: ${bySeverity.medium?.length || 0}\n`;
  markdown += `- Low: ${bySeverity.low?.length || 0}\n`;

  ensureDir(path.dirname(LESSONS_LEARNED_FILE));
  fs.writeFileSync(LESSONS_LEARNED_FILE, markdown);
  console.log(`📚 Lessons consolidated: ${LESSONS_LEARNED_FILE}`);
}

function processNewFeedback() {
  const feedback = loadFeedback();
  const negativeFeedback = feedback.filter(f => f.reward < 0);

  // Load existing lessons to avoid duplicates
  ensureDir(LESSONS_DIR);
  const existingLessons = new Set(
    fs.readdirSync(LESSONS_DIR)
      .filter(f => f.endsWith('.json'))
      .map(f => {
        const content = fs.readFileSync(path.join(LESSONS_DIR, f), 'utf8');
        return JSON.parse(content).feedbackId;
      })
  );

  let newLessonsCount = 0;

  negativeFeedback.forEach(fb => {
    if (!existingLessons.has(fb.id)) {
      const lesson = generateLesson(fb);
      saveLesson(lesson);
      newLessonsCount++;
    }
  });

  if (newLessonsCount > 0) {
    console.log(`\n✅ Created ${newLessonsCount} new lesson(s)`);
    consolidateLessons();
  } else {
    console.log('No new lessons to create.');
  }
}

// CLI interface
const args = process.argv.slice(2);
const command = args[0];

if (command === 'process') {
  processNewFeedback();
} else if (command === 'consolidate') {
  consolidateLessons();
} else {
  console.log(`
Auto Lesson Creator

Usage:
  node auto-lesson-creator.js process      # Process new negative feedback into lessons
  node auto-lesson-creator.js consolidate  # Consolidate all lessons into markdown
  `);
}

module.exports = { processNewFeedback, consolidateLessons };
