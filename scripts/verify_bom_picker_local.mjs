/**
 * Local verify for BOM picker enrichment. Iterates over local cases and
 * snaps the first one whose origin page renders a multi-option BOM picker.
 * Local CO dev server runs at 127.0.0.1:8001 (no SSO).
 */
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:8001';
const DH_BASE = 'http://127.0.0.1:8754';
const EMAIL = 'admin@data-hub.local';
const PASSWORD = 'admin123';
const OUT = '/home/vp/workspace/client/barry-CO-main/.ai/screenshots/bom-picker-filter';
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

// log in via DH SSO (local dev)
await page.goto(`${BASE}/clients`, { waitUntil: 'networkidle2', timeout: 60000 });
if (page.url().startsWith(DH_BASE)) {
  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await Promise.all([page.click('button[type="submit"]'), page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 })]);
}
console.log('authed at', page.url());
const clientIds = await page.evaluate(() =>
  Array.from(document.querySelectorAll('a[href*="/clients/"]'))
       .map(a => (a.getAttribute('href') || '').match(/^\/clients\/([^/]+)\/?$/))
       .filter(Boolean).map(m => m[1])
       .filter((v, i, arr) => arr.indexOf(v) === i)
);
console.log('clients:', clientIds);

let winner = null;
outer: for (const client of clientIds) {
  await page.goto(`${BASE}/clients/${client}/co-case`, { waitUntil: 'networkidle2', timeout: 60000 });
  const cases = await page.evaluate(() =>
    Array.from(document.querySelectorAll('a[href*="/co-case/co-case-"]'))
         .map(a => a.getAttribute('href'))
         .filter((v, i, arr) => arr.indexOf(v) === i)
  );
  console.log(`\n[${client}] ${cases.length} cases`);
  for (const href of cases.slice(0, 30)) {
    const originUrl = `${BASE}${href.replace(/\/$/, '')}/origin`;
    const res = await page.goto(originUrl, { waitUntil: 'networkidle2', timeout: 60000 });
    if (res.status() !== 200) continue;
    const probe = await page.evaluate(() => {
      const sels = Array.from(document.querySelectorAll('.product-bom-picker select[data-bom-version-select]'));
      let bestCount = 0, bestOpts = [];
      sels.forEach(sel => {
        if (sel.options.length > bestCount && sel.options[0]?.textContent?.trim() !== '❗ Chưa có BOM') {
          bestCount = sel.options.length;
          bestOpts = Array.from(sel.options).map(o => o.textContent.trim());
        }
      });
      const metas = document.querySelectorAll('.product-bom-picker-meta').length;
      const pills = Array.from(document.querySelectorAll('.bom-meta-pill')).map(el => ({
        cls: el.className.replace('bom-meta-pill', '').trim(),
        text: el.textContent.trim(),
        title: el.getAttribute('title') || '',
      }));
      return { selects: sels.length, bestCount, bestOpts, metas, pills };
    });
    console.log(`  ${href}  selects=${probe.selects} best=${probe.bestCount} metas=${probe.metas} pills=${probe.pills.length}`);
    if (probe.bestCount >= 1 && probe.bestOpts[0] !== '❗ Chưa có BOM') {
      winner = { url: originUrl, probe, client, href };
      console.log(`  ✓ winner`);
      break outer;
    }
  }
}

if (!winner) {
  console.error('\nNo case with a populated BOM picker found.');
  await browser.close();
  process.exit(2);
}

console.log(`\n▶ Snapshot ${winner.url}`);
await page.goto(winner.url, { waitUntil: 'networkidle2', timeout: 60000 });
await shot(page, 'local-origin-page');

const box = await page.evaluate(() => {
  const sel = document.querySelector('.product-bom-picker select[data-bom-version-select]');
  if (!sel) return null;
  sel.scrollIntoView({ block: 'center' });
  const wrap = sel.closest('.origin-sheet-toolbar') || sel.parentElement;
  const r = wrap.getBoundingClientRect();
  return { x: r.x, y: r.y, w: r.width, h: r.height };
});
if (box) {
  await shot(page, 'local-picker-zoom', {
    x: Math.max(0, box.x - 10), y: Math.max(0, box.y - 10),
    width: Math.min(1440, box.w + 20), height: Math.min(900, box.h + 60),
  });
}

// Open the select to capture options dropdown (best effort)
try {
  await page.click('.product-bom-picker select[data-bom-version-select]');
  await new Promise(r => setTimeout(r, 300));
  await shot(page, 'local-picker-open');
} catch (e) {
  console.log('  (could not open native select for screenshot — that is fine)');
}

const labelChecks = winner.probe.bestOpts.map(opt => ({
  text: opt,
  hasN: /^#\d+\s+·\s+\d+\s+dòng/.test(opt),
  hasDate: /\d{4}-\d{2}-\d{2}/.test(opt),
  hasKind: /(manual-flat|technical-flat|technical-raw|co-edit|staff-edit|customs-filed|data-hub)/.test(opt),
}));

console.log('\n=== verdict ===');
console.log(`case:           ${winner.client}${winner.href}`);
console.log(`options:        ${winner.probe.bestCount}`);
console.log(`meta strips:    ${winner.probe.metas}`);
console.log(`meta pills:     ${winner.probe.pills.length}`);
if (winner.probe.pills.length) {
  for (const p of winner.probe.pills) console.log(`  pill ${p.cls || '(default)'} = "${p.text}"  title="${p.title}"`);
}
console.log('label format per option:');
for (const c of labelChecks) {
  console.log(`  N=${c.hasN ? 'Y' : 'n'} date=${c.hasDate ? 'Y' : 'n'} kind=${c.hasKind ? 'Y' : 'n'}  ${c.text}`);
}
await browser.close();
console.log(`\nDONE — ${OUT}`);
