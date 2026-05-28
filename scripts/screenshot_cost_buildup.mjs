/**
 * Takes screenshots of the cost-buildup UI variants using Playwright.
 * Reads the HTML files rendered by render_cost_buildup_preview.py.
 */
import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const dir = path.join(root, '.ai/screenshots/cost-buildup-ui');

const variants = [
  { html: 'preview.html',         png: 'cost-buildup-filled.png',   label: 'Filled (LVC sample data)' },
  { html: 'preview-empty.html',   png: 'cost-buildup-empty.png',    label: 'Empty (hint: bảng kê block II-VII sẽ trống)' },
  { html: 'preview-warning.html', png: 'cost-buildup-warning.png',  label: 'Warning (sum > FOB)' },
];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 700 }, deviceScaleFactor: 2 });

for (const v of variants) {
  const page = await ctx.newPage();
  const url = 'file://' + path.join(dir, v.html);
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(200);
  const out = path.join(dir, v.png);
  await page.screenshot({ path: out, fullPage: false, clip: { x: 0, y: 0, width: 1280, height: 380 } });
  console.log(`${v.label} → ${path.relative(root, out)}`);
  await page.close();
}

await browser.close();
