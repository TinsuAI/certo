// Visual confirm Trục B fix on a real growatt-vn origin sheet: count materials
// flagged "không tồn" (data-row-no-stock="1", i.e. allocation_count==0) BEFORE
// (stored pre-fix calc) vs AFTER re-calc against the fixed stock pool.
// Run: PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright|head -1)"); \
//      NODE_PATH="$PWDIR" node .ai/scripts/e2e_growatt_origin_stock.cjs
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = "http://127.0.0.1:8001";
const CLIENT = "growatt-vn";
const CASE = "co-case-e44fe2065b62"; // growatt-vn, product SD00.0010600
const OUT = ".ai/screenshots/2026-06-14-growatt-origin-stock";
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("dialog", async (d) => { await d.accept().catch(() => {}); }); // accept ghi-đè/confirm

  const visible = (sel) =>
    page.$eval(sel, (n) => !!(n.offsetWidth || n.offsetHeight || n.getClientRects().length)).catch(() => false);
  const drill = async () => {
    if (await visible(".origin-material-table")) return true;
    const d = await page.$(".origin-review-drill");
    if (d) { await d.click().catch(() => {}); await page.waitForTimeout(500); }
    return visible(".origin-material-table");
  };
  const counts = async () => page.$$eval("[data-origin-material-row]", (rows) => {
    const active = rows.filter((r) => !r.classList.contains("origin-row-foldable") && !r.classList.contains("origin-row-deleted"));
    const noStock = active.filter((r) => r.getAttribute("data-row-no-stock") === "1");
    return { total: active.length, noStock: noStock.length };
  }).catch(() => ({ total: 0, noStock: 0 }));

  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/origin`, { waitUntil: "networkidle" });
  await drill();
  const before = await counts();
  console.log(`BEFORE re-calc:  total=${before.total}  KHÔNG tồn=${before.noStock}`);
  await page.screenshot({ path: `${OUT}/01-before-recalc.png`, fullPage: true });

  // Make the sheet calculable then re-calc against the fixed stock.
  const loadBom = await page.$("[data-origin-sheet-load-bom]");
  if (loadBom) { await loadBom.click().catch(() => {}); await page.waitForTimeout(2500); await drill(); }
  let calc = await page.$("[data-origin-sheet-calculate]");
  let calcDisabled = calc ? await calc.evaluate((b) => b.hasAttribute("disabled")) : true;
  console.log(`calc button: present=${!!calc} disabled=${calcDisabled}`);
  if (calc && !calcDisabled) {
    await calc.click().catch(() => {});
    await page.waitForTimeout(4000); // allocation can take a few s
    await drill();
  }
  const after = await counts();
  console.log(`AFTER re-calc:   total=${after.total}  KHÔNG tồn=${after.noStock}`);
  await page.screenshot({ path: `${OUT}/02-after-recalc.png`, fullPage: true });

  console.log(`\nKHÔNG tồn: ${before.noStock} → ${after.noStock}  (total active: ${before.total}/${after.total})`);
  console.log(`console errors: ${errors.length}${errors.length ? " | " + errors.slice(0, 3).join(" | ") : ""}`);
  await browser.close();
})();
