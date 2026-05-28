/** Smoke for delta refresh against live Data Hub.
 *
 * Refresh 3x in a row. Run 1 may be full (if no last_server_time stored);
 * runs 2-3 should be delta with 0 changes and millisecond wall-time.
 */
import puppeteer from 'puppeteer';

const BASE_CO = 'http://127.0.0.1:8001';
const BASE_HUB = 'http://127.0.0.1:8754';

const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.goto(`${BASE_CO}/clients`, { waitUntil: 'networkidle2' });
if (page.url().includes(BASE_HUB)) {
  await page.type('input[name="email"]', 'admin@data-hub.local');
  await page.type('input[name="password"]', 'admin123');
  await Promise.all([page.click('button[type="submit"]'), page.waitForNavigation({ waitUntil: 'networkidle2' })]);
}

async function refresh(label) {
  const result = await page.evaluate(async () => {
    const t0 = performance.now();
    const resp = await fetch('/clients/growatt/co-stock/refresh', { method: 'POST' });
    const body = await resp.json();
    return { status: resp.status, body, ms: Math.round(performance.now() - t0) };
  });
  const b = result.body;
  console.log(
    `${label}: status=${result.status} mode=${b.mode} ` +
    `added=${b.rows_added} updated=${b.rows_updated} removed=${b.rows_removed} ` +
    `took=${b.took_seconds}s wall=${result.ms}ms ` +
    `server_time=${b.server_time || 'NONE'} tombstones=${b.tombstones_received ?? 'n/a'}`
  );
}
await refresh('Refresh #1');
await refresh('Refresh #2');
await refresh('Refresh #3');
await browser.close();
