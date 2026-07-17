const puppeteer = require("puppeteer");
const BASE = "http://127.0.0.1:8754";
const OUT = "/home/vp/workspace/client/barry-CO-main/docs/huong-dan-su-dung/images";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 950 });
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
  await page.type('input[name="email"]', "admin@data-hub.local");
  await page.type('input[name="password"]', "admin123");
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }).catch(() => null), page.click('button[type="submit"]')]);

  // filtered clients list
  await page.goto(`${BASE}/clients`, { waitUntil: "networkidle0" });
  const box = await page.$('input[placeholder*="Tìm theo"]');
  if (box) { await box.type("demo"); await sleep(900); }
  await page.screenshot({ path: `${OUT}/dh-01-clients.png` }); // viewport, filtered
  console.log("SHOT dh-01-clients (filtered)");

  // BOM artifact detail (7 rows)
  await page.goto(`${BASE}/clients/demo-furniture/bom/artifact/ba_lt6we35iJ7Sx4qaM`, { waitUntil: "networkidle0" });
  await sleep(700);
  await page.screenshot({ path: `${OUT}/dh-06b-bom-detail.png`, fullPage: true });
  const rows = await page.evaluate(() => document.querySelectorAll("table tbody tr").length);
  console.log(`SHOT dh-06b-bom-detail (rows=${rows})`);

  await browser.close();
})().catch((e) => { console.error(e); process.exit(3); });
