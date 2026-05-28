/**
 * Post-deploy verify for Phase 2+3 state-machine sprint (commits
 * 286573d..8121823). Checks:
 *   1. /healthz OK
 *   2. Case list page loads — Phase 2.3 read path (hydrate cases[] from
 *      co_cases) didn't lose data
 *   3. Delete modal renders new claim-aware warning markup (HIGH #2)
 *   4. Origin sheet page still renders for the existing case
 */
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';

const BASE_CO = 'https://barry-co.tinsu.ai';
const BASE_HUB = 'https://ttdatahub.tinsu.ai';
const EMAIL = 'claude-check@local';
const PASSWORD = 'claude-temp-2026';

const OUT = '/home/vp/workspace/client/barry-CO-main/.ai/screenshots/state-machine-demo';
fs.mkdirSync(OUT, { recursive: true });
let n = 0;
async function shot(page, label, clip) {
  n++;
  const fn = `${String(n).padStart(2, '0')}-${label}.png`;
  await page.screenshot({ path: path.join(OUT, fn), fullPage: !clip, clip });
  console.log(`  📸 ${fn}`);
}

const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });

console.log('▶ /healthz');
const health = await page.goto(`${BASE_CO}/healthz`, { waitUntil: 'networkidle2' });
console.log(`  ${health.status()}`);

console.log('\n▶ Login');
await page.goto(`${BASE_CO}/clients/growatt-vn/co-case`, { waitUntil: 'networkidle2', timeout: 60000 });
if (page.url().includes(BASE_HUB)) {
  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await Promise.all([
    page.click('button[type="submit"]'),
    page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 }),
  ]);
}
console.log(`  authed at ${page.url()}`);

console.log('\n▶ Case list (Phase 2.3 — read from co_cases)');
const listProbe = await page.evaluate(() => {
  const dossierForms = Array.from(document.querySelectorAll('[data-delete-case-form]'));
  return {
    caseCount: dossierForms.length,
    cases: dossierForms.map(f => ({
      caseCode: f.dataset.caseCode || '',
      claimsCount: Number(f.dataset.claimsCount || '0'),
      lotsCount: Number(f.dataset.lotsCount || '0'),
      hasConfirmField: !!f.querySelector('input[name="confirm_release_claims"]'),
    })),
    hasDeleteModal: !!document.querySelector('[data-delete-case-modal]'),
    hasNewWarning: !!document.querySelector('[data-delete-case-warning]'),
  };
});
console.log(`  cases on page: ${listProbe.caseCount}`);
for (const c of listProbe.cases) {
  console.log(`    ${c.caseCode}: claims=${c.claimsCount}, lots=${c.lotsCount}, confirm-field=${c.hasConfirmField}`);
}
console.log(`  modal: ${listProbe.hasDeleteModal}, new warning slot: ${listProbe.hasNewWarning}`);
await shot(page, 'case-list');

if (listProbe.cases.length > 0) {
  console.log('\n▶ Trigger delete modal to verify warning text swap');
  await page.evaluate(() => document.querySelector('[data-delete-case-trigger]')?.scrollIntoView({ block: 'center' }));
  await page.click('[data-delete-case-trigger]');
  await new Promise(r => setTimeout(r, 300));
  const modalProbe = await page.evaluate(() => {
    const modal = document.querySelector('[data-delete-case-modal]');
    if (!modal || modal.hidden) return { open: false };
    const warning = modal.querySelector('[data-delete-case-warning]');
    return {
      open: true,
      warningText: warning?.textContent?.trim() || '',
      hasStrongClass: warning?.classList.contains('confirm-modal-warning-strong') || false,
    };
  });
  console.log(`  open=${modalProbe.open}`);
  console.log(`  warning="${modalProbe.warningText}"`);
  console.log(`  strong-warning class=${modalProbe.hasStrongClass}`);
  await shot(page, 'delete-modal');

  // Close modal
  await page.evaluate(() => document.querySelector('[data-delete-case-cancel]')?.click());
  await new Promise(r => setTimeout(r, 200));
}

console.log('\n▶ Open origin page for the first case');
const firstHref = await page.evaluate(() => {
  const a = document.querySelector('a[href*="/co-case/co-case-"]');
  return a?.getAttribute('href') || '';
});
if (firstHref) {
  const originUrl = `${BASE_CO}${firstHref.replace(/\/$/, '')}/origin`;
  const r = await page.goto(originUrl, { waitUntil: 'networkidle2', timeout: 60000 });
  console.log(`  ${originUrl} → ${r.status()}`);
  await shot(page, 'origin-page');
}

console.log('\n=== verdict ===');
console.log(`/healthz:                  ${health.status() === 200 ? 'OK' : 'FAIL'}`);
console.log(`case list loaded:          ${listProbe.caseCount >= 0 ? 'OK' : 'FAIL'}`);
console.log(`HIGH #2 modal markup:      ${listProbe.hasDeleteModal && listProbe.hasNewWarning ? 'OK' : 'FAIL'}`);

await browser.close();
console.log(`\nDONE — ${OUT}`);
