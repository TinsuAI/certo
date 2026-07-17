// Verify the demo-furniture 5-step flow on the REAL auth-off CO dev server (:8001)
// and capture guide screenshots. Drives one sheet through Load BOM → Tính bảng kê
// → Chốt and asserts it reaches 'calculated' (lockable) then 'locked'.
const puppeteer = require("puppeteer");
const { mkdirSync } = require("fs");

const BASE = process.env.BASE || "http://127.0.0.1:8001";
const CLIENT = "demo-furniture";
const CASE = process.env.CASE_ID;
const SHEET = process.env.SHEET || "CHAIR01";
const OUT = process.env.OUT || "/home/vp/workspace/client/barry-CO-main/docs/huong-dan-su-dung/images";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fails = [];
const ok = (c, m) => { console.log(`${c ? "PASS" : "FAIL"}  ${m}`); if (!c) fails.push(m); };

(async () => {
  if (!CASE) { console.error("set CASE_ID"); process.exit(2); }
  mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 1000 });
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
  page.on("dialog", (d) => d.accept());

  const originUrl = `${BASE}/clients/${CLIENT}/co-case/${CASE}/origin?sheet=${SHEET}`;
  await page.goto(originUrl, { waitUntil: "networkidle0", timeout: 60000 });
  await sleep(800);

  // sheets present?
  const sheets = await page.evaluate(() =>
    Array.from(document.querySelectorAll("[data-origin-sheet-tab]")).map(t => (t.dataset.productCode || t.textContent).trim()));
  console.log("SHEETS=" + JSON.stringify(sheets));
  ok(sheets.length >= 1, `origin has product sheets: ${sheets.join(", ")}`);

  // 1. Load BOM
  const loadResp = page.waitForResponse(r => /\/load-bom$/.test(r.url()), { timeout: 60000 }).catch(() => null);
  await page.click("[data-origin-sheet-load-bom]");
  await loadResp; await sleep(1500);
  ok(true, "clicked Load BOM");

  // 2. Tính bảng kê
  const calcResp = page.waitForResponse(r => /\/calculate$/.test(r.url()), { timeout: 60000 }).catch(() => null);
  await page.click("[data-origin-sheet-calculate]");
  await calcResp; await sleep(1800);

  // read computed state from the page
  const state = await page.evaluate(() => {
    const txt = document.body.innerText;
    const lvc = (txt.match(/LVC[^%]*?([\d.,]+)\s*%/) || [])[1] || null;
    const calcBadge = /Đã tính|calculated/i.test(txt);
    const lockBtn = document.querySelector('button[formaction$="/lock"]');
    return {
      lvc,
      calcBadge,
      lockDisabled: lockBtn ? lockBtn.disabled : null,
      lockTitle: lockBtn ? lockBtn.title : null,
    };
  });
  console.log("STATE_AFTER_CALC=" + JSON.stringify(state));
  await page.screenshot({ path: `${OUT}/co-08-bang-ke-calculated.png`, fullPage: true });
  ok(state.lockDisabled === false, `sheet is lockable after Tính (lock enabled). title=${state.lockTitle || ""}`);

  // 3. Chốt (lock)
  if (state.lockDisabled === false) {
    const lockResp = page.waitForResponse(r => /\/lock$/.test(r.url()), { timeout: 60000 }).catch(() => null);
    await page.click('button[formaction$="/lock"]');
    await lockResp; await sleep(1800);
    const locked = await page.evaluate(() => {
      const reopen = document.querySelector('button[formaction$="/reopen"]');
      return { reopenEnabled: reopen ? !reopen.disabled : null, txt: /🔒|Đã chốt|locked/i.test(document.body.innerText) };
    });
    console.log("STATE_AFTER_LOCK=" + JSON.stringify(locked));
    await page.screenshot({ path: `${OUT}/co-09-bang-ke-locked.png`, fullPage: true });
    ok(locked.reopenEnabled === true || locked.txt, "sheet locked (reopen affordance enabled / locked marker visible)");
  }

  console.log("CONSOLE_ERRORS=" + JSON.stringify(errs.slice(0, 5)));
  await browser.close();
  console.log(fails.length ? `\n${fails.length} FAIL` : "\nALL PASS");
  process.exit(fails.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(3); });
