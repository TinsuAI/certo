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
  const perSheetMounts = await count(page, "[data-sheet-rac-mount]");
  console.log(`  static: data-bulk-delete-enabled=${aggEnabled} perSheetMounts=${perSheetMounts}`);

  if (MODE === "off") {
    aggEnabled === "0" ? ok("aggregate flag = 0") : fail(`aggregate flag should be 0 (got ${aggEnabled})`);
    perSheetMounts === 0 ? ok("no per-sheet rác mounts (gated off)") : fail(`per-sheet rác mounts should be absent (got ${perSheetMounts})`);
  } else {
    aggEnabled === "1" ? ok("aggregate flag = 1") : fail(`aggregate flag should be 1 (got ${aggEnabled})`);
    perSheetMounts >= 1 ? ok(`per-sheet rác mounts present (${perSheetMounts})`) : fail("expected ≥1 per-sheet rác mount");
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

  const AGG = "[data-run-stock-summary] ";   // scope to the aggregate (per-sheet also renders rác panels)
  const pickUnm = AGG + '[data-rs-rac-pick="declarable_unmatched"]';
  const unmRows = AGG + '[data-rs-rac-row][data-kind="declarable_unmatched"]';
  const phiRows = AGG + '[data-rs-rac-row][data-kind="excluded_non_material"]';
  const pickBtns = await count(page, AGG + "[data-rs-rac-pick]");
  const racRows = await count(page, AGG + "[data-rs-rac-row]");
  console.log(`  aggregate rác: pickButtons=${pickBtns} rows=${racRows}`);

  if (MODE === "off") {
    pickBtns === 0 ? ok("no rác pick buttons (gated off)") : fail(`rác pick buttons should be absent (got ${pickBtns})`);
    racRows === 0 ? ok("no inline rác rows") : fail(`rác rows should be absent (got ${racRows})`);
    errors.filter((e) => !/Failed to load resource/i.test(e)).length === 0 ? ok("no console errors") : fail("console errors: " + errors.slice(0, 3).join(" | "));
    await browser.close();
    process.exit(failed ? 1 : 0);
  }

  // MODE=on — inline select: quick-select a kind → bulk Xoá → confirm modal → delete.
  if (!(await page.$(pickUnm))) { fail("expected 'Chọn NVL không có trong BCCT' button"); await browser.close(); process.exit(1); }
  const unmLabel = await page.$eval(pickUnm, (n) => n.textContent.trim());
  const nUnm = await count(page, unmRows), nPhi = await count(page, phiRows);
  ok(`pick button "${unmLabel}"; rows: unmatched=${nUnm} phi-vật-tư=${nPhi}`);

  await page.$eval(pickUnm, (el) => el.click());   // quick-select the declarable_unmatched rows
  const checkedAfterPick = await page.$$eval(AGG + "[data-rs-rac-select]", (cbs) => cbs.filter((c) => c.checked).length);
  const delVisible = await page.$eval(AGG + "[data-rs-rac-delete]", (n) => !n.hidden).catch(() => false);
  const delText = await page.$eval(AGG + "[data-rs-rac-delete]", (n) => n.textContent.trim()).catch(() => "");
  await page.screenshot({ path: `${OUT}/on-02-selected.png`, fullPage: true });
  checkedAfterPick === nUnm ? ok(`quick-select checked ${checkedAfterPick} unmatched rows`) : fail(`expected ${nUnm} checked, got ${checkedAfterPick}`);
  delVisible ? ok(`bulk delete visible: "${delText}"`) : fail("bulk delete should be visible after select");

  await page.$eval(AGG + "[data-rs-rac-delete]", (el) => el.click());   // → confirm modal
  await page.waitForSelector("[data-rac-modal] [data-rac-confirm]", { visible: true, timeout: 8000 });
  const modalItems = await count(page, "[data-rac-modal] [data-rac-check]");
  const confirmText = await page.$eval("[data-rac-modal] [data-rac-confirm]", (n) => n.textContent.trim());
  await page.screenshot({ path: `${OUT}/on-03-confirm-modal.png`, fullPage: true });
  console.log(`  confirm modal: items=${modalItems} confirmBtn="${confirmText}"`);
  modalItems === nUnm ? ok(`confirm modal lists the ${modalItems} selected NVL`) : fail(`confirm should list ${nUnm} (got ${modalItems})`);
  /Xoá/.test(confirmText) ? ok(`confirm button = "${confirmText}"`) : fail("confirm button should say Xoá (N)");

  await page.$eval("[data-rac-modal] [data-rac-confirm]", (el) => el.click());
  await page.waitForFunction(() => !document.querySelector("[data-rac-modal]"), { timeout: 15000 }).catch(() => {});
  await page.waitForFunction((sel) => !document.querySelector(sel), { timeout: 30000 }, unmRows).catch(() => {});   // aggregate unmatched rows gone after delete
  await page.screenshot({ path: `${OUT}/on-04-after-delete.png`, fullPage: true });

  const unmAfter = await count(page, unmRows), phiAfter = await count(page, phiRows);
  console.log(`  after delete: unmatched rows=${unmAfter} phi-vật-tư rows=${phiAfter}`);
  unmAfter === 0 ? ok("'không có trong BCCT' rows cleared") : fail(`unmatched rows should be gone (got ${unmAfter})`);
  phiAfter >= 1 ? ok("'phi vật tư' rows still present (kind isolation)") : fail("phi-vật-tư rows should remain");

  // Per-sheet: aggregate → Review → drill into a sheet (real sheet VIEW), verify the
  // SAME inline rác panel + capture. [data-origin-drill] is the Review→sheet trigger.
  await page.$eval("[data-origin-back-to-review]", (el) => el.click()).catch(() => {});
  await new Promise((r) => setTimeout(r, 300));
  const drills = await page.$$("[data-origin-drill]");
  let perSheetRows = 0;
  for (const d of drills) {
    await d.evaluate((el) => el.click());
    await new Promise((r) => setTimeout(r, 450));
    perSheetRows = await page.$$eval("[data-origin-sheet-panel].origin-sheet-panel-active [data-sheet-rac-mount] [data-rs-rac-row]", (e) => e.length).catch(() => 0);
    if (perSheetRows > 0) break;
  }
  const perSheetPicks = await page.$$eval("[data-origin-sheet-panel].origin-sheet-panel-active [data-sheet-rac-mount] [data-rs-rac-pick]", (e) => e.length).catch(() => 0);
  await page.screenshot({ path: `${OUT}/on-05-per-sheet.png`, fullPage: true });
  console.log(`  per-sheet: racRows=${perSheetRows} pickButtons=${perSheetPicks}`);
  perSheetRows >= 1 ? ok(`per-sheet inline rác panel renders (${perSheetRows} rows)`) : fail("per-sheet rác panel should render inline");

  const real = errors.filter((e) => !/favicon|Failed to load resource/i.test(e));
  real.length === 0 ? ok("no console errors") : fail("console errors: " + real.slice(0, 3).join(" | "));
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error("E2E ERROR:", e); process.exit(1); });
