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
  const csvRows = results
    .filter(r => r !== null)
    .map(r => {
      const spread = calculateSpread(r.price);
      return `${date},33071,${r.facility},${r.price},${CONFIG.defaultP2PRate * 4},${spread.toFixed(2)},false,auto-scraped`;
    })
    .join('\n');

  if (!csvRows) {
    console.log('No data to sync');
    return;
  }

  // This would use the GitHub API to append to storage_spreads.csv
  // For now, just log what would be synced
  console.log('Would sync:');
  console.log(csvRows);
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
