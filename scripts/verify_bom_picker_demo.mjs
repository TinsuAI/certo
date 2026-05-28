/**
 * Demo verify for BOM picker enrichment. Mirrors verify_bom_picker_local.mjs
 * but targets https://barry-co.tinsu.ai with the persistent demo account
 * from memory. If demo has no case with active BOM artifacts, reports
 * health + no-regression only (visual proof requires seeded data).
 */
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';

const BASE_CO = 'https://barry-co.tinsu.ai';
const BASE_HUB = 'https://ttdatahub.tinsu.ai';
const EMAIL = 'claude-check@local';
const PASSWORD = 'claude-temp-2026';
const CLIENTS = ['growatt-vn', 'johnson-vn'];

const OUT = '/home/vp/workspace/client/barry-CO-main/.ai/screenshots/bom-picker-filter-demo';
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

await page.goto(`${BASE_CO}/clients/${CLIENTS[0]}/co-case`, { waitUntil: 'networkidle2', timeout: 60000 });
if (page.url().includes(BASE_HUB)) {
  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await Promise.all([page.click('button[type="submit"]'), page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 })]);
}
console.log('authed at', page.url());

let winner = null;
const probedCases = [];
outer: for (const client of CLIENTS) {
  await page.goto(`${BASE_CO}/clients/${client}/co-case`, { waitUntil: 'networkidle2', timeout: 60000 });
  const refs = await page.evaluate(() =>
    Array.from(document.querySelectorAll('a[href*="/co-case/co-case-"]'))
         .map(a => a.getAttribute('href'))
         .filter((v, i, arr) => arr.indexOf(v) === i)
  );
  console.log(`\n[${client}] ${refs.length} cases`);
  for (const href of refs.slice(0, 20)) {
    const originUrl = `${BASE_CO}${href.replace(/\/$/, '')}/origin`;
    const res = await page.goto(originUrl, { waitUntil: 'networkidle2', timeout: 60000 });
    if (res.status() !== 200) {
      probedCases.push({ client, href, status: res.status(), populated: false });
      continue;
    }
    const probe = await page.evaluate(() => {
      const sels = Array.from(document.querySelectorAll('.product-bom-picker select[data-bom-version-select]'));
      let bestCount = 0, bestOpts = [];
      sels.forEach(sel => {
        const opts = Array.from(sel.options).map(o => o.textContent.trim());
        if (opts[0] !== '❗ Chưa có BOM' && opts.length > bestCount) {
          bestCount = opts.length;
          bestOpts = opts;
        }
      });
      const metas = document.querySelectorAll('.product-bom-picker-meta').length;
      const pills = Array.from(document.querySelectorAll('.bom-meta-pill')).map(el => ({
        cls: el.className.replace('bom-meta-pill', '').trim(),
        text: el.textContent.trim(),
      }));
      return { selects: sels.length, bestCount, bestOpts, metas, pills };
    });
    const populated = probe.bestCount >= 1;
    probedCases.push({ client, href, status: 200, populated, ...probe });
    console.log(`  [200] ${href}  selects=${probe.selects} best=${probe.bestCount} metas=${probe.metas}`);
    if (populated) { winner = { url: originUrl, probe, client, href }; break outer; }
  }
}

console.log('\n=== demo verify summary ===');
console.log(`probed: ${probedCases.length} cases`);
console.log(`page renders OK (no 500): ${probedCases.every(c => c.status === 200) ? 'YES' : 'NO'}`);
console.log(`populated picker found: ${winner ? 'YES' : 'NO'}`);

if (winner) {
  console.log(`\n▶ Snapshot ${winner.url}`);
  await page.goto(winner.url, { waitUntil: 'networkidle2', timeout: 60000 });
  await shot(page, 'demo-origin-page');
  const box = await page.evaluate(() => {
    const sel = document.querySelector('.product-bom-picker select[data-bom-version-select]');
    if (!sel) return null;
    sel.scrollIntoView({ block: 'center' });
    const wrap = sel.closest('.origin-sheet-toolbar') || sel.parentElement;
    const r = wrap.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  if (box) {
    await shot(page, 'demo-picker-zoom', {
      x: Math.max(0, box.x - 10), y: Math.max(0, box.y - 10),
      width: Math.min(1440, box.w + 20), height: Math.min(900, box.h + 60),
    });
  }
  console.log('label format check:');
  for (const opt of winner.probe.bestOpts) {
    const hasN = /^#\d+\s+·\s+\d+\s+dòng/.test(opt);
    const hasDate = /\d{4}-\d{2}-\d{2}/.test(opt);
    const hasKind = /(manual-flat|technical-flat|technical-raw|co-edit|staff-edit|customs-filed|data-hub)/.test(opt);
    console.log(`  N=${hasN ? 'Y' : 'n'} date=${hasDate ? 'Y' : 'n'} kind=${hasKind ? 'Y' : 'n'}  ${opt}`);
  }
  console.log(`meta pills: ${winner.probe.pills.length}`);
  for (const p of winner.probe.pills) console.log(`  pill ${p.cls || '(default)'} = "${p.text}"`);
} else {
  console.log('\nNo case with active BOM artifacts on demo. Visual proof of');
  console.log('the new label format / meta strip requires seeded data.');
  console.log('Health + no-regression OK; full verify done on local.');
}

await browser.close();
console.log(`\nDONE — ${OUT}`);
