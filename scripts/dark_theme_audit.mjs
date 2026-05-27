// Capture dark-mode screenshots of every affected page, plus a low-contrast scan.
// Auth: relies on the auto-issued local Data Hub session cookies already in /tmp/cookies.txt.
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:8001';
const OUT = '/home/vp/workspace/client/barry-CO-main/.ai/screenshots/dark-theme-audit';
fs.mkdirSync(OUT, { recursive: true });

// Parse Netscape-format cookies.txt -> puppeteer cookies.
function readNsCookies(file, urlHost) {
  const txt = fs.readFileSync(file, 'utf8');
  const cookies = [];
  for (const line of txt.split('\n')) {
    if (!line || line.startsWith('#')) {
      // puppeteer ignores #HttpOnly_ marker, strip it
      if (!line.startsWith('#HttpOnly_')) continue;
    }
    const clean = line.replace(/^#HttpOnly_/, '');
    const parts = clean.split('\t');
    if (parts.length < 7) continue;
    const [domain, , pathv, secureFlag, expires, name, value] = parts;
    if (!domain.includes(urlHost.replace(/.*\/\//,'').replace(/:.*/,''))) continue;
    cookies.push({
      name, value,
      domain: domain.replace(/^\./, ''),
      path: pathv,
      expires: Number(expires) || -1,
      httpOnly: line.startsWith('#HttpOnly_'),
      secure: secureFlag === 'TRUE',
    });
  }
  return cookies;
}

const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
const ctx = browser;
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });

const sessionCookies = readNsCookies('/tmp/cookies.txt', BASE);
sessionCookies.push({
  name: 'co_theme', value: 'dark',
  domain: '127.0.0.1', path: '/', expires: -1, httpOnly: false, secure: false,
});
await page.setCookie(...sessionCookies);

const pages = [
  ['clients', '/clients'],
  ['client-home', '/clients/growatt-vn'],
  ['cost-allocation', '/clients/growatt-vn/cost-allocation'],
  ['co-stock', '/clients/growatt-vn/co-stock'],
  ['co-case-list', '/clients/growatt-vn/co-case'],
  ['case-overview', '/clients/growatt-vn/co-case/co-case-3b36f4820935'],
  ['case-shipment', '/clients/growatt-vn/co-case/co-case-3b36f4820935/shipment'],
  ['case-documents', '/clients/growatt-vn/co-case/co-case-3b36f4820935/documents'],
  ['case-origin', '/clients/growatt-vn/co-case/co-case-3b36f4820935/origin'],
  ['case-exports', '/clients/growatt-vn/co-case/co-case-3b36f4820935/exports'],
  ['case-review', '/clients/growatt-vn/co-case/co-case-3b36f4820935/review'],
  ['catalog', '/clients/growatt-vn/catalog'],
  ['bom', '/clients/growatt-vn/bom'],
  ['bcct', '/clients/growatt-vn/bcct'],
  ['client-config', '/clients/growatt-vn/config'],
  ['settings', '/settings'],
  ['settings-data-hub', '/settings/data-hub'],
  ['settings-co-forms', '/settings/co-forms'],
  ['settings-technical', '/settings/technical'],
  ['customs-exchange-rates', '/customs-exchange-rates'],
];

// Low-contrast scanner: walk visible text nodes, compute fg vs bg luminance ratio.
async function scanContrast(p) {
  return await p.evaluate(() => {
    function parse(c) {
      const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
      if (!m) return null;
      return { r: +m[1], g: +m[2], b: +m[3], a: m[4] !== undefined ? +m[4] : 1 };
    }
    function L({r,g,b}) {
      const f = v => { v /= 255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
      return 0.2126*f(r) + 0.7152*f(g) + 0.0722*f(b);
    }
    function ratio(fg, bg) {
      const l1 = L(fg), l2 = L(bg);
      const a = Math.max(l1, l2), b = Math.min(l1, l2);
      return (a + 0.05) / (b + 0.05);
    }
    function effectiveBg(el) {
      let cur = el;
      while (cur && cur !== document.body) {
        const s = getComputedStyle(cur);
        const bg = parse(s.backgroundColor);
        if (bg && bg.a > 0.5) return bg;
        cur = cur.parentElement;
      }
      const bodyBg = parse(getComputedStyle(document.body).backgroundColor) || { r: 15, g: 23, b: 32, a: 1 };
      return bodyBg;
    }
    const bad = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    let count = 0;
    while ((n = walker.nextNode())) {
      const txt = n.nodeValue && n.nodeValue.trim();
      if (!txt || txt.length < 2) continue;
      const el = n.parentElement;
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const s = getComputedStyle(el);
      if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity < 0.3) continue;
      const fg = parse(s.color);
      if (!fg || fg.a < 0.5) continue;
      const bg = effectiveBg(el);
      const cr = ratio(fg, bg);
      if (cr < 3.0) {
        bad.push({
          text: txt.slice(0, 80),
          fg: `rgb(${fg.r},${fg.g},${fg.b})`,
          bg: `rgb(${bg.r},${bg.g},${bg.b})`,
          ratio: cr.toFixed(2),
          selector: el.tagName.toLowerCase() + (el.id ? '#'+el.id : '') + (el.className && typeof el.className === 'string' ? '.'+el.className.split(/\s+/).slice(0,2).join('.') : ''),
        });
      }
      if (++count > 1500) break;
    }
    return bad;
  });
}

const report = [];
for (const [label, url] of pages) {
  const target = BASE + url;
  console.log(`-> ${label} ${target}`);
  let status = 'ok';
  try {
    const resp = await page.goto(target, { waitUntil: 'networkidle2', timeout: 25000 });
    if (!resp || !resp.ok()) status = `http ${resp ? resp.status() : '??'}`;
  } catch (e) {
    status = 'err ' + e.message.slice(0, 80);
  }
  await new Promise(r => setTimeout(r, 400));
  await page.screenshot({ path: path.join(OUT, `${label}.png`), fullPage: true });
  let bad = [];
  if (status === 'ok') bad = await scanContrast(page);
  report.push({ label, url, status, lowContrastCount: bad.length, samples: bad.slice(0, 8) });
}

fs.writeFileSync(path.join(OUT, 'contrast-report.json'), JSON.stringify(report, null, 2));
console.log('\n=== SUMMARY ===');
for (const r of report) {
  console.log(`${r.label.padEnd(28)} ${r.status.padEnd(12)} low-contrast: ${r.lowContrastCount}`);
}
await browser.close();
