#!/usr/bin/env node
/**
 * Autonomous Storage Price Scout
 * Uses Vercel's agent-browser to scrape storage prices
 * and automatically log them to GitHub
 */

const { execSync } = require('child_process');
const https = require('https');

// Configuration
const CONFIG = {
  zipCodes: ['33071', '33076'],
  ghToken: process.env.GITHUB_TOKEN,
  ghUser: 'IgorGanapolsky',
  ghRepo: 'storage-scout',
  ntfyTopic: 'igor_storage_alerts',
  defaultP2PRate: 65, // Average Neighbor.com 5x5 rate
  highPriorityThreshold: 120,
};

// Target storage facilities with their search URLs
const FACILITIES = [
  {
    name: 'Public Storage',
    url: 'https://www.publicstorage.com/self-storage-fl-coral-springs/10x20-storage-units',
    priceSelector: '.price',
  },
  {
    name: 'Extra Space Storage',
    url: 'https://www.extraspace.com/storage/facilities/us/florida/coral_springs/',
    priceSelector: '.unit-price',
  },
  {
    name: 'CubeSmart',
    url: 'https://www.cubesmart.com/florida-self-storage/coral-springs-self-storage.html',
    priceSelector: '.price',
  },
];

function agentBrowser(command) {
  try {
    const result = execSync(`npx agent-browser ${command}`, {
      encoding: 'utf8',
      timeout: 30000,
      cwd: process.cwd(),
    });
    return result.trim();
  } catch (error) {
    console.error(`Browser command failed: ${command}`, error.message);
    return null;
  }
}

async function scrapeFacility(facility) {
  console.log(`\n🔍 Scraping ${facility.name}...`);

  try {
    // Open the page
    agentBrowser(`open "${facility.url}"`);

    // Wait for content to load
    await new Promise(r => setTimeout(r, 3000));

    // Get accessibility snapshot
    const snapshot = agentBrowser('snapshot');

    // Take screenshot for debugging
    agentBrowser(`screenshot "${facility.name.replace(/\s+/g, '_')}.png"`);

    // Extract prices from snapshot (look for dollar amounts)
    const priceMatches = snapshot?.match(/\$(\d+(?:\.\d{2})?)/g) || [];
    const prices = priceMatches
      .map(p => parseFloat(p.replace('$', '')))
      .filter(p => p >= 100 && p <= 600); // Reasonable 10x20 price range

    agentBrowser('close');

    if (prices.length > 0) {
      const lowestPrice = Math.min(...prices);
      console.log(`  ✓ Found ${prices.length} prices, lowest: $${lowestPrice}`);
      return {
        facility: facility.name,
        price: lowestPrice,
        allPrices: prices,
        timestamp: new Date().toISOString(),
      };
    } else {
      console.log(`  ⚠ No prices found`);
      return null;
    }
  } catch (error) {
    console.error(`  ✗ Error scraping ${facility.name}:`, error.message);
    agentBrowser('close');
    return null;
  }
}

function calculateSpread(price10x20, p2pRate = CONFIG.defaultP2PRate) {
  const revenue = p2pRate * 4;
  const insurance = 12;
  return revenue - price10x20 - insurance;
}

async function syncToGitHub(results) {
  if (!CONFIG.ghToken) {
    console.log('\n⚠ No GITHUB_TOKEN - skipping sync');
    return;
  }

  console.log('\n📤 Syncing to GitHub...');

  const date = new Date().toISOString().split('T')[0];
  const newRows = results
    .filter(r => r !== null)
    .map(r => {
      const spread = calculateSpread(r.price);
      return `${date},33071,${r.facility},${r.price},${CONFIG.defaultP2PRate * 4},${spread.toFixed(2)},false,auto-scraped`;
    })
    .join('\n');

  if (!newRows) {
    console.log('No data to sync');
    return;
  }

  const filePath = 'storage_spreads.csv';
  const apiUrl = `https://api.github.com/repos/${CONFIG.ghUser}/${CONFIG.ghRepo}/contents/${filePath}`;

  try {
    // Get current file content and SHA
    const getResponse = await fetch(apiUrl, {
      headers: {
        'Authorization': `Bearer ${CONFIG.ghToken}`,
        'Accept': 'application/vnd.github.v3+json',
      },
    });

    let existingContent = '';
    let sha = null;

    if (getResponse.ok) {
      const data = await getResponse.json();
      existingContent = Buffer.from(data.content, 'base64').toString('utf8');
      sha = data.sha;
    } else if (getResponse.status === 404) {
      // File doesn't exist, create with header
      existingContent = 'date,zip,facility,commercial_price,p2p_revenue,spread,high_priority,source\n';
    } else {
      throw new Error(`GitHub API error: ${getResponse.status}`);
    }

    // Append new rows
    const updatedContent = existingContent.trimEnd() + '\n' + newRows + '\n';

    // Update file
    const putBody = {
      message: `Auto-scout: ${date} - ${results.filter(r => r).length} facilities`,
      content: Buffer.from(updatedContent).toString('base64'),
      branch: 'main',
    };
    if (sha) putBody.sha = sha;

    const putResponse = await fetch(apiUrl, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${CONFIG.ghToken}`,
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(putBody),
    });

    if (putResponse.ok) {
      console.log(`✓ Synced ${results.filter(r => r).length} entries to GitHub`);
    } else {
      const errorData = await putResponse.json();
      throw new Error(`GitHub PUT failed: ${errorData.message}`);
    }
  } catch (error) {
    console.error('GitHub sync failed:', error.message);
  }
}

async function sendAlerts(results) {
  const highPriority = results
    .filter(r => r !== null)
    .filter(r => calculateSpread(r.price) >= CONFIG.highPriorityThreshold);

  if (highPriority.length === 0) {
    console.log('\n📱 No high-priority deals found');
    return;
  }

  console.log(`\n🚨 ${highPriority.length} HIGH PRIORITY DEALS FOUND!`);

  for (const deal of highPriority) {
    const spread = calculateSpread(deal.price);
    const message = `🔥 ${deal.facility}: $${deal.price}/mo = $${spread.toFixed(0)} spread!`;
    console.log(`  ${message}`);

    // Send ntfy notification
    try {
      const req = https.request({
        hostname: 'ntfy.sh',
        path: `/${CONFIG.ntfyTopic}`,
        method: 'POST',
        headers: {
          'Title': 'Storage Deal Alert',
          'Priority': 'high',
          'Tags': 'moneybag,rotating_light',
        },
      });
      req.write(message);
      req.end();
    } catch (e) {
      console.error('Failed to send notification:', e.message);
    }
  }
}

async function runScout() {
  console.log('🤖 Autonomous Storage Scout Starting...');
  console.log(`Target: Coral Springs FL (${CONFIG.zipCodes.join(', ')})`);
  console.log(`Threshold: $${CONFIG.highPriorityThreshold}/mo spread\n`);

  const results = [];

  for (const facility of FACILITIES) {
    const result = await scrapeFacility(facility);
    results.push(result);

    // Be polite - wait between requests
    await new Promise(r => setTimeout(r, 2000));
  }

  // Summary
  console.log('\n📊 RESULTS SUMMARY');
  console.log('='.repeat(50));

  for (const result of results) {
    if (result) {
      const spread = calculateSpread(result.price);
      const priority = spread >= CONFIG.highPriorityThreshold ? '🔥 HIGH' : '  ';
      console.log(`${priority} ${result.facility}: $${result.price}/mo → $${spread.toFixed(0)} spread`);
    }
  }

  // Sync and alert
  await syncToGitHub(results);
  await sendAlerts(results);

  console.log('\n✅ Scout complete!');
}

// Run if called directly
if (require.main === module) {
  runScout().catch(console.error);
}

module.exports = { runScout, scrapeFacility, calculateSpread };
