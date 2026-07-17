// Finish the dossier: lock TABLE01 (sheet-scoped selectors) + capture the
// remaining guide shots (all-locked, exports, error page).
const puppeteer = require("puppeteer");
const BASE = "http://127.0.0.1:8001";
const CLIENT = "demo-furniture";
const OUT = "/home/vp/workspace/client/barry-CO-main/docs/huong-dan-su-dung/images";
const CASE = process.env.CASE_ID;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const shot = async (p, n, full = true) => { await p.screenshot({ path: `${OUT}/${n}.png`, fullPage: full }); console.log(`SHOT ${n}`); };

async function driveSheet(page, sheet) {
  const A = (suffix) => `button[formaction*="/sheet/${sheet}/${suffix}"]`;
  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/origin?sheet=${sheet}`, { waitUntil: "networkidle0", timeout: 60000 });
  await sleep(800);
  let r = page.waitForResponse((x) => /\/load-bom$/.test(x.url()), { timeout: 60000 }).catch(() => null);
  await page.click(A("load-bom"));
  await r; await sleep(1400);
  r = page.waitForResponse((x) => /\/calculate$/.test(x.url()), { timeout: 60000 }).catch(() => null);
  await page.click(A("calculate"));
  await r; await sleep(1500);
  const lockBtn = await page.$(A("lock"));
  const enabled = lockBtn ? await page.evaluate((b) => !b.disabled, lockBtn) : false;
  if (enabled) {
    r = page.waitForResponse((x) => /\/lock$/.test(x.url()), { timeout: 60000 }).catch(() => null);
    await page.click(A("lock"));
    await r; await sleep(1400);
    console.log(`  ${sheet} locked`);
  } else { console.log(`  ${sheet} NOT lockable (${lockBtn ? lockBtn.title : "no btn"})`); }
}

(async () => {
  if (!CASE) { console.error("set CASE_ID"); process.exit(2); }
  const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 1000 });
  page.on("dialog", (d) => d.accept());

  await driveSheet(page, "TABLE01");

  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/origin`, { waitUntil: "networkidle0", timeout: 60000 });
  await sleep(800);
  await shot(page, "co-11-origin-all-locked");

  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/exports`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(700);
  await shot(page, "co-12-exports");

  await page.goto(`${BASE}/clients/${CLIENT}/co-case/co-case-doesnotexist/origin`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(500);
  await shot(page, "co-14-error-page");

  await browser.close();
  console.log("done");
})().catch((e) => { console.error(e); process.exit(3); });
