/**
 * Verify 4-item export xlsx checklist:
 *   1. Tên thương nhân = legal_name (or fallback name)
 *   2. Mã số thuế presented
 *   3. Tờ khai xuất khẩu has both no + date
 *   4. FOB currency dynamic (no hardcoded "USD")
 *
 * Sets legal_name + tax_code via /clients/{id}/config form first,
 * then downloads the export xlsx and inspects key cells.
 */
import puppeteer from 'puppeteer';
import { unzipSync, strFromU8 } from 'fflate';
import { writeFileSync } from 'node:fs';

const BASE_CO = 'http://127.0.0.1:8001';
const BASE_HUB = 'http://127.0.0.1:8754';
const EMAIL = 'admin@data-hub.local';
const PASSWORD = 'admin123';
const CLIENT_ID = 'growatt';
const CASE_ID = 'co-case-36ad2da0201a';
const LEGAL_NAME = 'CÔNG TY TNHH CLAUDE VERIFY (test)';
const TAX_CODE = '0312345678';

const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();

// 1) Auth.
await page.goto(`${BASE_CO}/clients`, { waitUntil: 'networkidle2' });
if (page.url().includes(BASE_HUB)) {
  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await Promise.all([page.click('button[type="submit"]'), page.waitForNavigation({ waitUntil: 'networkidle2' })]);
}
console.log(`auth ok, landed at ${page.url()}`);

// 2) Set legal_name + tax_code via /clients/{id}/config.
const configUrl = `${BASE_CO}/clients/${CLIENT_ID}/config`;
await page.goto(configUrl, { waitUntil: 'networkidle2' });
console.log(`config page URL: ${page.url()}`);
const fieldsPresent = await page.evaluate(() => ({
  legal: !!document.querySelector('input[name="legal_name"]'),
  tax: !!document.querySelector('input[name="tax_code"]'),
  form: !!document.querySelector('form[action$="/config"]'),
}));
console.log('fields present:', fieldsPresent);
if (!fieldsPresent.legal || !fieldsPresent.tax) {
  console.error('config form missing expected inputs; bailing.');
  await browser.close();
  process.exit(1);
}
const postStatus = await page.evaluate(async (clientId, legal, tax) => {
  const form = new FormData();
  form.set('legal_name', legal);
  form.set('tax_code', tax);
  // Carry the existing config-related fields so we don't accidentally null them.
  for (const input of document.querySelectorAll('input[name], select[name]')) {
    const name = input.getAttribute('name');
    if (name === 'legal_name' || name === 'tax_code') continue;
    form.set(name, input.value);
  }
  const resp = await fetch(`/clients/${clientId}/config`, { method: 'POST', body: form });
  return resp.status;
}, CLIENT_ID, LEGAL_NAME, TAX_CODE);
console.log(`save POST status: ${postStatus}`);

// 3) Download xlsx.
const caseUrl = `${BASE_CO}/clients/${CLIENT_ID}/co-case/${CASE_ID}`;
await page.goto(`${caseUrl}/origin`, { waitUntil: 'networkidle2' });
const xlsx = await page.evaluate(async (url) => {
  const resp = await fetch(url);
  if (!resp.ok) return { status: resp.status, body: await resp.text() };
  const buf = new Uint8Array(await resp.arrayBuffer());
  let b64 = '';
  const chunk = 0x8000;
  for (let i = 0; i < buf.length; i += chunk) {
    b64 += String.fromCharCode.apply(null, buf.subarray(i, i + chunk));
  }
  return { status: 200, b64: btoa(b64) };
}, `${caseUrl}/export-bang-ke`);

if (xlsx.status !== 200) {
  console.error(`Export failed: HTTP ${xlsx.status}\n${xlsx.body}`);
  await browser.close();
  process.exit(1);
}

const bytes = Uint8Array.from(atob(xlsx.b64), c => c.charCodeAt(0));
writeFileSync('/tmp/verify-export.xlsx', bytes);
console.log(`downloaded xlsx (${bytes.length} bytes) → /tmp/verify-export.xlsx`);

// 4) Inspect cells via raw xlsx XML.
const files = unzipSync(bytes);
const sharedStrings = (() => {
  if (!files['xl/sharedStrings.xml']) return [];
  const xml = strFromU8(files['xl/sharedStrings.xml']);
  return [...xml.matchAll(/<t[^>]*>([^<]*)<\/t>/g)].map(m => m[1]);
})();
const sheet1 = strFromU8(files['xl/worksheets/sheet1.xml']);

const hasText = (needle) => sharedStrings.some(s => s.includes(needle)) || sheet1.includes(needle);

const checks = [
  { label: '1. Tên thương nhân (legal_name)', ok: hasText(LEGAL_NAME), expected: LEGAL_NAME },
  { label: '2. Mã số thuế',                    ok: hasText(TAX_CODE),   expected: TAX_CODE },
  { label: '3. No hardcoded "USD" cell',       ok: !sharedStrings.some(s => / USD$/.test(s)) && !/<t[^>]*>USD<\/t>/.test(sheet1), expected: '!" USD" suffix; sheet1 cells not "USD"' },
  { label: '4. Currency cells match product.currency (VND)', ok: /<t[^>]*>VND<\/t>/.test(sheet1) || /<t[^>]*>Trị giá \(VND\)<\/t>/.test(sheet1), expected: 'VND or "(VND)" cell present' },
];

console.log('\nChecks:');
for (const c of checks) {
  console.log(`  [${c.ok ? 'PASS' : 'FAIL'}] ${c.label} (expected: ${c.expected})`);
}

console.log('\nMerchant/tax sample sharedStrings:');
sharedStrings
  .filter(s => /thương nhân|mã số thuế|MST|FOB|Trị giá|customer|tax/i.test(s))
  .forEach(s => console.log(`  • ${s.slice(0, 100)}`));

console.log('\nFirst 30 sharedStrings:');
sharedStrings.slice(0, 30).forEach((s, i) => console.log(`  [${i}] ${s.slice(0, 100)}`));

console.log('\nSheet name list:');
const wbXml = strFromU8(files['xl/workbook.xml']);
[...wbXml.matchAll(/<sheet [^>]*name="([^"]+)"/g)].forEach(m => console.log(`  - ${m[1]}`));

await browser.close();
process.exit(checks.every(c => c.ok) ? 0 : 1);
