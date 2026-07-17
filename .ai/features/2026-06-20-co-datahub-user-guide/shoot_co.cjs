// Capture CO UI screenshots for the user guide by driving a fresh demo-furniture
// dossier through the full 5-step flow on the auth-off dev server (:8001).
const puppeteer = require("puppeteer");
const { mkdirSync } = require("fs");

const BASE = "http://127.0.0.1:8001";
const CLIENT = "demo-furniture";
const OUT = "/home/vp/workspace/client/barry-CO-main/docs/huong-dan-su-dung/images";
const EXPORTS = "105100100100, 105100100101"; // E42 declarations → CHAIR01, TABLE01
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (m) => console.log(m);

async function shot(page, name, full = true) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
  log(`SHOT ${name}`);
}

async function driveSheet(page, caseId, sheet, capture) {
  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${caseId}/origin?sheet=${sheet}`, { waitUntil: "networkidle0", timeout: 60000 });
  await sleep(700);
  // Load BOM
  let r = page.waitForResponse((x) => /\/load-bom$/.test(x.url()), { timeout: 60000 }).catch(() => null);
  await page.click("[data-origin-sheet-load-bom]");
  await r; await sleep(1400);
  if (capture) await shot(page, "co-07-load-bom");
  // Tính bảng kê
  r = page.waitForResponse((x) => /\/calculate$/.test(x.url()), { timeout: 60000 }).catch(() => null);
  await page.click("[data-origin-sheet-calculate]");
  await r; await sleep(1600);
  if (capture) {
    const lvc = await page.evaluate(() => (document.body.innerText.match(/LVC[^%]*?([\d.,]+)\s*%/) || [])[1] || "?");
    log(`  ${sheet} LVC=${lvc}`);
    await shot(page, "co-08-bang-ke-calculated");
    // substitute modal (best-effort)
    try {
      const trig = await page.$("[data-origin-substitute-trigger]");
      if (trig) {
        await trig.click();
        await page.waitForSelector("[data-origin-substitute-modal]", { timeout: 8000 });
        await sleep(1000);
        await shot(page, "co-10-substitute-modal", false);
        await page.keyboard.press("Escape");
        await sleep(400);
      } else { log("  (no substitute trigger rendered — skip modal shot)"); }
    } catch (e) { log(`  substitute modal skip: ${e.message}`); }
  }
  // Chốt
  const lockBtn = await page.$('button[formaction$="/lock"]');
  const enabled = lockBtn ? await page.evaluate((b) => !b.disabled, lockBtn) : false;
  if (enabled) {
    r = page.waitForResponse((x) => /\/lock$/.test(x.url()), { timeout: 60000 }).catch(() => null);
    await page.click('button[formaction$="/lock"]');
    await r; await sleep(1400);
    if (capture) await shot(page, "co-09-bang-ke-locked");
    log(`  ${sheet} locked`);
  } else {
    log(`  ${sheet} NOT lockable (${lockBtn ? lockBtn.title : "no lock btn"})`);
  }
}

(async () => {
  mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 1000 });
  page.on("dialog", (d) => d.accept());

  // ensure stock materialized (client-level, idempotent)
  await page.goto(`${BASE}/clients/${CLIENT}/co-stock`, { waitUntil: "networkidle0", timeout: 60000 });
  await sleep(600);
  await shot(page, "co-13-co-stock");

  // 1. CO clients home
  await page.goto(`${BASE}/clients`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(500);
  await shot(page, "co-01-clients");

  // 2. dossier list + create modal
  await page.goto(`${BASE}/clients/${CLIENT}/co-case`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(500);
  await shot(page, "co-02-case-list");
  await page.click("[data-create-case-open]");
  await sleep(500);
  await page.evaluate((exp) => {
    const modal = document.querySelector("[data-create-case-modal]");
    const set = (sel, v) => { const el = modal.querySelector(sel); if (el) { el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); } };
    set('[name="destination_market"]', "Hàn Quốc");
    set('[name="export_declaration_nos"]', exp);
    set('[name="title"]', "Hồ sơ C/O mẫu — ghế & bàn gỗ");
  }, EXPORTS);
  await sleep(400);
  await shot(page, "co-03-create-modal");
  // submit → new case
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle0", timeout: 60000 }).catch(() => null),
    page.click('[data-create-case-modal] button[type="submit"]'),
  ]);
  const caseId = (page.url().match(/co-case-[a-z0-9]+/) || [])[0];
  log(`NEW CASE = ${caseId}`);
  if (!caseId) { await browser.close(); process.exit(2); }

  // 4. overview (shipment step + stepper)
  await sleep(800);
  await shot(page, "co-04-case-overview");

  // 5. documents step
  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${caseId}/documents`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(600);
  await shot(page, "co-05-documents");

  // 6. origin sheets (before Load BOM)
  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${caseId}/origin`, { waitUntil: "networkidle0", timeout: 60000 });
  await sleep(800);
  await shot(page, "co-06-origin-sheets");

  // 7-10. drive CHAIR01 with captures, then TABLE01 silently
  await driveSheet(page, caseId, "CHAIR01", true);
  await driveSheet(page, caseId, "TABLE01", false);

  // 11. both locked
  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${caseId}/origin`, { waitUntil: "networkidle0", timeout: 60000 });
  await sleep(800);
  await shot(page, "co-11-origin-all-locked");

  // 12. exports / review step
  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${caseId}/exports`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(600);
  await shot(page, "co-12-exports");

  // 14. graceful error page (latest feature)
  await page.goto(`${BASE}/clients/${CLIENT}/co-case/co-case-doesnotexist/origin`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(500);
  await shot(page, "co-14-error-page");

  await browser.close();
  log(`done. case=${caseId}`);
})().catch((e) => { console.error(e); process.exit(3); });
