/* Capture footer badge + /whats-new page in light & dark for the
 * app-versioning feature folder. Local dev server on :8001 (auth off). */
const puppeteer = require('puppeteer');
const path = require('path');

const BASE = 'http://127.0.0.1:8001';
const OUT = path.resolve(__dirname, '..', '.ai/features/2026-06-07-co-app-versioning-changelog/screenshots');
const fs = require('fs');
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await puppeteer.launch({ args: ['--no-sandbox'] });
  for (const theme of ['light', 'dark']) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 2 });
    await page.setCookie({ name: 'co_theme', value: theme, domain: '127.0.0.1', path: '/' });

    // whats-new full page
    await page.goto(`${BASE}/whats-new`, { waitUntil: 'networkidle0' });
    await page.screenshot({ path: path.join(OUT, `whats_new_${theme}.png`), fullPage: true });

    // footer crop from the clients page
    await page.goto(`${BASE}/clients`, { waitUntil: 'networkidle0' });
    const footer = await page.$('.app-footer');
    if (footer) await footer.screenshot({ path: path.join(OUT, `footer_${theme}.png`) });
    console.log(`captured ${theme}`);
    await page.close();
  }
  await browser.close();
})();
