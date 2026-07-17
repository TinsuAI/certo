// Capture Data Hub UI screenshots for the user guide (logged-in session).
const puppeteer = require("puppeteer");
const { mkdirSync } = require("fs");

const BASE = process.env.DH_BASE || "http://127.0.0.1:8754";
const EMAIL = process.env.DH_EMAIL || "admin@data-hub.local";
const PASSWORD = process.env.DH_PASSWORD || "admin123";
const CID = "demo-furniture";
const OUT = process.env.OUT || "/home/vp/workspace/client/barry-CO-main/docs/huong-dan-su-dung/images";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const shots = [
  ["dh-01-clients", `/clients`, "danh sách công ty"],
  ["dh-02-client-overview", `/clients/${CID}`, "tổng quan công ty"],
  ["dh-03-catalog", `/clients/${CID}/catalog`, "danh mục NVL/SP"],
  ["dh-04-bcct", `/clients/${CID}/bcct`, "tờ khai hải quan (BCCT)"],
  ["dh-05-bom", `/clients/${CID}/bom`, "danh sách BOM"],
  ["dh-06-bom-chair", `/clients/${CID}/bom/CHAIR01/artifacts`, "BOM artifact CHAIR01"],
  ["dh-07-proposals", `/clients/${CID}/proposals`, "đề xuất BOM"],
];

(async () => {
  mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 1000 });

  // login
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle0", timeout: 30000 });
  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle0", timeout: 30000 }).catch(() => null),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
  const loggedIn = !/\/login/.test(page.url());
  console.log(`LOGIN -> ${page.url()} (${loggedIn ? "OK" : "FAILED"})`);
  if (!loggedIn) { await browser.close(); process.exit(2); }

  for (const [name, path, label] of shots) {
    try {
      const resp = await page.goto(`${BASE}${path}`, { waitUntil: "networkidle0", timeout: 30000 });
      await sleep(700);
      await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
      const h = await page.evaluate(() => (document.querySelector("h1,h2,.page-title")?.textContent || "").trim().slice(0, 60));
      console.log(`SHOT ${name}  http=${resp ? resp.status() : "?"}  «${h}»  (${label})`);
    } catch (e) {
      console.log(`MISS ${name}  ${path}  ${e.message}`);
    }
  }
  await browser.close();
  console.log("done");
})().catch((e) => { console.error(e); process.exit(3); });
