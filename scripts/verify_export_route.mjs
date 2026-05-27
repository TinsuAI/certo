/**
 * Verify the GET /export-bang-ke 404 bug is fixed AND that the step routes
 * still 404 on invalid step names.
 */
import puppeteer from 'puppeteer';

const BASE_CO = 'http://127.0.0.1:8001';
const BASE_HUB = 'http://127.0.0.1:8754';
const EMAIL = 'admin@data-hub.local';
const PASSWORD = 'admin123';
const CLIENT_ID = 'growatt-vn';
const CASE_ID = 'co-case-be691b9dceec';

const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.goto(`${BASE_CO}/clients`, { waitUntil: 'networkidle2' });
if (page.url().includes(BASE_HUB)) {
  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await Promise.all([page.click('button[type="submit"]'), page.waitForNavigation({ waitUntil: 'networkidle2' })]);
}
// Land on the case page so fetch() runs in same-origin context.
const caseUrl = `${BASE_CO}/clients/${CLIENT_ID}/co-case/${CASE_ID}`;
await page.goto(`${caseUrl}/origin`, { waitUntil: 'networkidle2' });
console.log(`auth ok, at ${page.url()}\n`);

const probes = [
  { method: 'GET',  path: '/export-bang-ke',   expectStatus: [200, 409], note: 'real route; 409 ok if blockers exist' },
  { method: 'POST', path: '/export-bang-ke',   expectStatus: [200, 409], note: 'real route via POST' },
  { method: 'GET',  path: '/origin',           expectStatus: [200],      note: 'valid step' },
  { method: 'GET',  path: '/shipment',         expectStatus: [200],      note: 'valid step' },
  { method: 'GET',  path: '/review',           expectStatus: [200],      note: 'valid step' },
  { method: 'GET',  path: '/nope',             expectStatus: [404],      note: 'invalid step → 404 from pattern reject' },
  { method: 'GET',  path: '/foo-bar',          expectStatus: [404],      note: 'invalid step → 404' },
];

console.log('Endpoint probes after the route-order fix:\n');
for (const probe of probes) {
  const result = await page.evaluate(async (url, method) => {
    const resp = await fetch(url, { method });
    const text = method === 'GET' ? '' : '';
    return { status: resp.status };
  }, caseUrl + probe.path, probe.method);
  const ok = probe.expectStatus.includes(result.status);
  console.log(`  [${ok ? 'OK ' : 'BAD'}] ${probe.method.padEnd(4)} ${probe.path.padEnd(28)} → ${result.status}  (expected ${probe.expectStatus.join('/')}; ${probe.note})`);
}

await browser.close();
