/**
 * Time Load BOM on demo (https://barry-co.tinsu.ai) — comparable to
 * scripts/time_load_bom.mjs but against the deployed instance. Reports
 * 3 sequential POSTs so the warm-cache effect of the in-process
 * snapshot cache is visible.
 */
import puppeteer from 'puppeteer';

const BASE_CO = 'https://barry-co.tinsu.ai';
const BASE_HUB = 'https://ttdatahub.tinsu.ai';
const EMAIL = 'claude-check@local';
const PASSWORD = 'claude-temp-2026';

const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });

await page.goto(`${BASE_CO}/clients/growatt-vn/co-case`, { waitUntil: 'networkidle2', timeout: 60000 });
if (page.url().includes(BASE_HUB)) {
  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await Promise.all([page.click('button[type="submit"]'), page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 })]);
}
console.log('authed at', page.url());

const refs = await page.evaluate(() =>
  Array.from(document.querySelectorAll('a[href*="/co-case/co-case-"]'))
    .map(a => a.getAttribute('href'))
    .filter((v, i, arr) => arr.indexOf(v) === i)
);
if (!refs.length) {
  console.log('No cases on growatt-vn — cannot time /calculate.');
  await browser.close();
  process.exit(0);
}

// Pick the first case with at least one product code
let targetCase = '';
let targetProduct = '';
for (const href of refs) {
  const originUrl = `${BASE_CO}${href.replace(/\/$/, '')}/origin`;
  const r = await page.goto(originUrl, { waitUntil: 'networkidle2', timeout: 60000 });
  if (r.status() !== 200) continue;
  const products = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.origin-sheet-product-line strong')).map(el => el.textContent.trim())
  );
  if (products.length) {
    targetCase = href.split('/').filter(Boolean).pop();
    targetProduct = products[0];
    break;
  }
}

if (!targetProduct) {
  console.log('No case had a product to /calculate against — abort.');
  await browser.close();
  process.exit(0);
}
console.log(`target: ${targetCase} / ${targetProduct}`);

for (let i = 0; i < 3; i++) {
  const r = await page.evaluate(async (caseId, code) => {
    const t0 = performance.now();
    const r = await fetch(`/clients/growatt-vn/co-case/${caseId}/origin/sheet/${encodeURIComponent(code)}/calculate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    });
    const text = await r.text();
    return { status: r.status, ms: Math.round(performance.now() - t0), bytes: text.length };
  }, targetCase, targetProduct);
  console.log(`run ${i+1}: ${r.status} ${r.ms}ms ${r.bytes}B`);
}
await browser.close();
