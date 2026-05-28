/**
 * Comprehensive screenshots of the Bảng kê C/O (origin tab) after redesign.
 * Captures multiple sheets in different states (draft / locked / with BOM diff)
 * + the cost-buildup expanded view + mobile width.
 */
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';

const BASE_CO = 'http://127.0.0.1:8001';
const CLIENT_ID = process.env.CLIENT_ID || 'growatt-vn';
const CASE_ID = process.env.CASE_ID || 'co-case-be691b9dceec';
const LABEL = process.env.LABEL || 'after';

const OUT = '/home/vp/workspace/client/barry-CO-main/.ai/screenshots/bang-ke-redesign';
fs.mkdirSync(OUT, { recursive: true });

const wait = (ms) => new Promise(r => setTimeout(r, ms));

const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
await page.setCookie({ name: 'co_theme', value: 'dark', domain: '127.0.0.1', path: '/', expires: -1, httpOnly: false, secure: false });

async function snap(label, opts = {}) {
  await page.screenshot({ path: path.join(OUT, `${LABEL}-${label}.png`), fullPage: !!opts.fullPage });
  console.log(`📸 ${LABEL}-${label}.png ${opts.fullPage ? '(full)' : ''}`);
}

// --- Desktop dark, default first sheet ---
await page.setViewport({ width: 1440, height: 900 });
await page.goto(`${BASE_CO}/clients/${CLIENT_ID}/co-case/${CASE_ID}/origin`, { waitUntil: 'networkidle2' });
await wait(500);
// clear localStorage so column defaults take effect
await page.evaluate(() => {
  window.localStorage.removeItem('barryCo.origin.hiddenColumns');
  window.localStorage.removeItem('barryCo.origin.hiddenColumns.v2');
});
await page.reload({ waitUntil: 'networkidle2' });
await wait(600);

await snap('01-dark-default-viewport');
await snap('01-dark-default-fullpage', { fullPage: true });

// --- Click second sheet tab if exists (often locked) ---
const tabs = await page.$$('[data-origin-sheet-tab]');
console.log(`tabs found: ${tabs.length}`);
if (tabs.length >= 2) {
  await tabs[1].click();
  await wait(400);
  await snap('02-dark-sheet2-viewport');
}
if (tabs.length >= 3) {
  await tabs[2].click();
  await wait(400);
  await snap('03-dark-sheet3-viewport');
}

// --- Find a locked sheet by scanning all tabs ---
const tabInfo = await page.evaluate(() =>
  Array.from(document.querySelectorAll('[data-origin-sheet-tab]')).map((t, i) => ({
    i, code: t.dataset.productCode, status: t.querySelector('small')?.textContent || ''
  }))
);
console.log('tab states:', JSON.stringify(tabInfo, null, 2));
const lockedIdx = tabInfo.findIndex(t => t.status.includes('Đã chốt') || t.status.includes('locked'));
if (lockedIdx >= 0) {
  (await page.$$('[data-origin-sheet-tab]'))[lockedIdx].click();
  await wait(500);
  await snap(`04-dark-locked-sheet-viewport`);
  await snap(`04-dark-locked-sheet-fullpage`, { fullPage: true });
}

// --- Expand cost-buildup on visible sheet ---
const cb = await page.$('.origin-sheet-panel-active .cost-buildup-block summary');
if (cb) {
  await cb.click();
  await wait(300);
  await snap('05-dark-cost-buildup-open');
}

// --- Mobile viewport ---
await page.setViewport({ width: 414, height: 900 });
await wait(300);
await snap('06-dark-mobile-viewport');

// --- Light mode ---
await page.setCookie({ name: 'co_theme', value: 'light', domain: '127.0.0.1', path: '/', expires: -1, httpOnly: false, secure: false });
await page.setViewport({ width: 1440, height: 900 });
await page.reload({ waitUntil: 'networkidle2' });
await wait(600);
await snap('07-light-default-viewport');
await snap('07-light-default-fullpage', { fullPage: true });

await browser.close();
console.log('done');
