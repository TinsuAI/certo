/**
 * Verify Load BOM (POST /origin/sheet/{code}/calculate) works after DH
 * restart. Hits the Johnson case-4e9f5a3b1e9c origin page and triggers
 * the calculate endpoint for MAS1230-39 from within the authed page
 * context so we get a real user session.
 */
import puppeteer from 'puppeteer';

const BASE_CO = 'http://127.0.0.1:8001';
const DH_BASE = 'http://127.0.0.1:8754';
const EMAIL = 'admin@data-hub.local';
const PASSWORD = 'admin123';

const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });

async function login() {
  await page.goto(`${BASE_CO}/clients`, { waitUntil: 'networkidle2', timeout: 60000 });
  if (page.url().startsWith(DH_BASE)) {
    await page.type('input[name="email"]', EMAIL);
    await page.type('input[name="password"]', PASSWORD);
    await Promise.all([page.click('button[type="submit"]'), page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 })]);
  }
}

console.log('▶ login');
await login();
await page.goto(`${BASE_CO}/clients/johnson-vn/co-case/co-case-4e9f5a3b1e9c/origin`, { waitUntil: 'networkidle2', timeout: 60000 });
if (page.url().startsWith(DH_BASE)) {
  // SSO re-prompt
  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await Promise.all([page.click('button[type="submit"]'), page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 })]);
}
console.log('  at', page.url());

console.log('\n▶ POST /calculate for MAS1230-39');
const probe = await page.evaluate(async () => {
  const r = await fetch('/clients/johnson-vn/co-case/co-case-4e9f5a3b1e9c/origin/sheet/MAS1230-39/calculate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  const text = await r.text();
  return { status: r.status, len: text.length, head: text.slice(0, 300) };
});
console.log(`  HTTP ${probe.status}`);
console.log(`  body length: ${probe.len}`);
if (probe.status !== 200) console.log(`  excerpt: ${probe.head}`);

await browser.close();
console.log(probe.status === 200 ? '\n✓ Load BOM works' : `\n✗ still failing (${probe.status})`);
process.exit(probe.status === 200 ? 0 : 1);
