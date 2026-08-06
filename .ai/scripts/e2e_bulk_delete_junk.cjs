// E2E: "Xoá NVL rác hàng loạt" (2 nhóm) ở sheet Tổng hợp NVL + per-sheet.
// Rác = folded rows: declarable_unmatched ("không có trong BCCT") + excluded_non_material
// ("phi vật tư"). Seeded Johnson clone johnson-e2e-rac has both kinds.
//
// MODE=on  : flag on → 2 nhóm nút ở aggregate + per-sheet; click 1 nhóm → modal cuộn
//            (checkbox pre-checked) → Xoá → nhóm đó biến mất, nhóm kia còn.
// MODE=off : flag off → KHÔNG có nút rác ở aggregate lẫn per-sheet (dù case vẫn có rác).
//
//   set -a; . ./.env; set +a
//   CLIENT=johnson-vn CASE=johnson-e2e-rac MODE=on node .ai/scripts/e2e_bulk_delete_junk.cjs
const puppeteer = require("puppeteer");
const fs = require("fs");

const BASE = "http://127.0.0.1:8001";
const CLIENT = process.env.CLIENT || "johnson-vn";
const CASE = process.env.CASE || "johnson-e2e-rac";
const MODE = (process.env.MODE || "on").toLowerCase();
const OUT = process.env.OUT || ".ai/screenshots/2026-08-06-bulk-delete-rac";
fs.mkdirSync(OUT, { recursive: true });

let failed = 0;
const fail = (m) => { failed++; console.error("  FAIL: " + m); };
const ok = (m) => console.log("  ok:   " + m);
const count = (page, sel) => page.$$eval(sel, (e) => e.length).catch(() => 0);

(async () => {
  const browser = await puppeteer.launch({ args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 1000 });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("response", async (r) => {
    if (r.status() >= 400 && !/favicon/.test(r.url())) console.log(`  [net ${r.status()}] ${r.url()}`);
    if (r.url().includes("/origin/calculate-all") || r.url().includes("/origin/bulk-delete-rac")) {
      try { const j = await r.json(); const tag = r.url().split("/origin/")[1];
        console.log(`  [net] ${tag}: mats=${j.rollup && j.rollup.material_count} folded_rac=${j.rollup && j.rollup.folded_rac_count} deleted=${(j.deleted||[]).length}`); } catch (_e) {}
    }
  });

  console.log(`\n=== MODE=${MODE}  ${CLIENT}/${CASE} ===`);
  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/origin`, { waitUntil: "networkidle2" });

  const aggEnabled = await page.$eval("[data-origin-aggregate]", (n) => n.dataset.bulkDeleteEnabled).catch(() => null);
  const perSheetInDom = await count(page, "[data-sheet-rac-kind]");
  const perSheetVisible = await page.$$eval("[data-sheet-rac-kind]", (els) => els.filter((e) => !e.hidden).length).catch(() => 0);
  console.log(`  static: data-bulk-delete-enabled=${aggEnabled} perSheetButtons(dom=${perSheetInDom}, visible=${perSheetVisible})`);

  if (MODE === "off") {
    aggEnabled === "0" ? ok("aggregate flag = 0") : fail(`aggregate flag should be 0 (got ${aggEnabled})`);
    perSheetInDom === 0 ? ok("no per-sheet rác buttons in DOM") : fail(`per-sheet rác buttons should be absent (got ${perSheetInDom})`);
  } else {
    aggEnabled === "1" ? ok("aggregate flag = 1") : fail(`aggregate flag should be 1 (got ${aggEnabled})`);
    perSheetVisible >= 1 ? ok(`per-sheet rác button visible (${perSheetVisible})`) : fail("expected ≥1 visible per-sheet rác button");
  }

  // Run "Tính tồn tất cả" → aggregate renders (handle BOM-selection modal).
  await page.$eval("[data-origin-aggregate] [data-run-stock-all]", (el) => el.click());
  await page.waitForSelector("[data-bom-select-modal]:not([hidden]) [data-bsm-confirm]", { visible: true, timeout: 4000 })
    .then(() => page.$eval("[data-bom-select-modal] [data-bsm-confirm]", (el) => el.click())).catch(() => {});
  await page.waitForFunction(() => {
    const b = document.querySelector("[data-run-stock-summary]");
    return b && !b.hidden && (b.querySelector(".rs-mat") || b.querySelector(".rs-done") || b.querySelector(".rs-rac-tools") || b.querySelector(".rs-nobom"));
  }, { timeout: 30000 }).catch(() => {});
  await page.screenshot({ path: `${OUT}/${MODE}-01-aggregate.png`, fullPage: true });

  const unmBtn = "[data-rs-rac-kind=\"declarable_unmatched\"]";
  const phiBtn = "[data-rs-rac-kind=\"excluded_non_material\"]";
  const racBtns = await count(page, "[data-rs-rac-kind]");
  console.log(`  aggregate rác buttons: ${racBtns}`);

  if (MODE === "off") {
    racBtns === 0 ? ok("no aggregate rác buttons (gated off)") : fail(`aggregate rác buttons should be absent (got ${racBtns})`);
    errors.filter((e) => !/Failed to load resource/i.test(e)).length === 0 ? ok("no console errors") : fail("console errors: " + errors.slice(0, 3).join(" | "));
    await browser.close();
    process.exit(failed ? 1 : 0);
  }

  // MODE=on — exercise the "không có trong BCCT" group via the scrollable modal.
  if (!(await page.$(unmBtn))) { fail("expected the declarable_unmatched rác button (Johnson has these)"); await browser.close(); process.exit(1); }
  const unmLabel = await page.$eval(unmBtn, (n) => n.textContent);
  const phiBefore = !!(await page.$(phiBtn));
  ok(`rác button present: "${unmLabel.trim()}" (phi-vật-tư present=${phiBefore})`);

  await page.$eval(unmBtn, (el) => el.click());
  await page.waitForSelector("[data-rac-modal] [data-rac-confirm]", { visible: true, timeout: 8000 });
  const modalItems = await count(page, "[data-rac-modal] [data-rac-check]");
  const modalChecked = await page.$$eval("[data-rac-modal] [data-rac-check]", (e) => e.filter((x) => x.checked).length);
  const confirmText = await page.$eval("[data-rac-modal] [data-rac-confirm]", (n) => n.textContent.trim());
  await page.screenshot({ path: `${OUT}/on-02-modal.png`, fullPage: true });
  console.log(`  modal: items=${modalItems} checked=${modalChecked} confirmBtn="${confirmText}"`);
  modalItems >= 1 ? ok(`modal lists ${modalItems} NVL`) : fail("modal should list NVL");
  modalChecked === modalItems ? ok("all pre-checked") : fail(`all should be pre-checked (got ${modalChecked}/${modalItems})`);
  /Xoá/.test(confirmText) ? ok(`confirm button = "${confirmText}"`) : fail("confirm button should say Xoá (N)");

  await page.$eval("[data-rac-modal] [data-rac-confirm]", (el) => el.click());
  await page.waitForFunction(() => !document.querySelector("[data-rac-modal]"), { timeout: 15000 }).catch(() => {});
  await page.waitForFunction((sel) => {
    const b = document.querySelector("[data-run-stock-summary]");
    return b && !b.querySelector(sel);   // the declarable_unmatched button is gone after delete
  }, { timeout: 30000 }, unmBtn).catch(() => {});
  await page.screenshot({ path: `${OUT}/on-03-after-delete.png`, fullPage: true });

  const unmAfter = await count(page, unmBtn);
  const phiAfter = await count(page, phiBtn);
  console.log(`  after delete: declarable_unmatched button=${unmAfter} phi-vật-tư button=${phiAfter}`);
  unmAfter === 0 ? ok("'không có trong BCCT' group cleared") : fail(`declarable_unmatched button should be gone (got ${unmAfter})`);
  phiAfter >= 1 ? ok("'phi vật tư' group still present (kinds isolated)") : fail("excluded_non_material group should remain");

  const real = errors.filter((e) => !/favicon|Failed to load resource/i.test(e));
  real.length === 0 ? ok("no console errors") : fail("console errors: " + real.slice(0, 3).join(" | "));
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error("E2E ERROR:", e); process.exit(1); });
