// BG1 fix verify: soft-delete (giữ dòng + fold), Load BOM ghi-đè confirm (P3),
// xoá lẻ KHÔNG confirm (P1), nhãn "Tính bảng kê"/"Tính lại" contextual (P2).
// Run: PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright|head -1)"); \
//      NODE_PATH="$PWDIR" node .ai/scripts/e2e_bangke_bg1_fix.cjs
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = "http://127.0.0.1:8001";
const CLIENT = "growatt-vn";
const CASE = "co-case-e44fe2065b62"; // BG1 case: 1 product, ~122 materials
const OUT = ".ai/screenshots/2026-06-14-bangke-bg1-fix";
fs.mkdirSync(OUT, { recursive: true });

const checks = [];
const ok = (name, cond, extra = "") => checks.push({ name, pass: !!cond, extra });

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

  let dialogMode = "dismiss"; // dismiss | accept
  let dialogCount = 0;
  let lastDialog = "";
  page.on("dialog", async (d) => {
    dialogCount++;
    lastDialog = d.message();
    if (dialogMode === "accept") await d.accept();
    else await d.dismiss();
  });

  const visible = (sel) =>
    page.$eval(sel, (n) => !!(n.offsetWidth || n.offsetHeight || n.getClientRects().length)).catch(() => false);

  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/origin`, { waitUntil: "networkidle" });
  // Drill into the sheet
  await page.click(".origin-review-drill");
  await page.waitForTimeout(300);
  ok("drill: grid visible", await visible(".origin-material-table"));

  // P2 — contextual "Tính bảng kê" button: label + disabled state
  const calc = await page.$eval("[data-origin-sheet-calculate]", (b) => ({
    text: b.textContent.trim(),
    disabled: b.hasAttribute("disabled"),
    title: b.getAttribute("title") || "",
  })).catch(() => null);
  ok("P2: calc button present", !!calc, calc ? `"${calc.text}" disabled=${calc.disabled}` : "");
  ok("P2: label is Tính bảng kê|Tính lại", calc && /Tính (bảng kê|lại)/.test(calc.text), calc?.text);
  await page.screenshot({ path: `${OUT}/01-toolbar.png` });

  // Count active (non-folded) material rows before delete
  const activeBefore = await page.$$eval(
    "[data-origin-material-row]",
    (rows) => rows.filter((r) => !r.classList.contains("origin-row-foldable") && !r.classList.contains("origin-row-deleted")).length
  );

  // P1 — xoá lẻ qua modal thay thế "Xoá dòng này" KHÔNG confirm
  const dlgBefore = dialogCount;
  await page.click("[data-origin-material-row]:not(.origin-row-foldable) [data-origin-substitute-trigger]");
  await page.waitForSelector("[data-origin-substitute-delete-row]", { state: "visible", timeout: 4000 });
  await page.click("[data-origin-substitute-delete-row]");
  await page.waitForTimeout(400);
  ok("P1: single delete fires NO confirm dialog", dialogCount === dlgBefore, `dialogs=${dialogCount - dlgBefore}`);

  // soft-delete: dòng được đánh dấu `origin-row-deleted`, KHÔNG biến mất khỏi DOM
  const domRows = await page.$$eval("[data-origin-material-row]", (r) => r.length);
  const stagedDeleted = await page.$$eval("[data-origin-material-row].origin-row-deleted", (r) => r.length);
  const activeAfter = await page.$$eval(
    "[data-origin-material-row]",
    (rows) => rows.filter((r) => !r.classList.contains("origin-row-foldable") && !r.classList.contains("origin-row-deleted")).length
  );
  ok("soft-delete: row stays in DOM (marked, not removed)", stagedDeleted >= 1, `marked=${stagedDeleted}`);
  ok("soft-delete: exactly 1 fewer active row", activeBefore - activeAfter === 1, `${activeBefore}→${activeAfter}`);
  await page.screenshot({ path: `${OUT}/02-soft-deleted-row.png`, fullPage: false });

  // P3 — Load BOM (sheet giờ có pending edit) PHẢI bật confirm ghi đè
  dialogMode = "dismiss";
  const dlgB = dialogCount;
  await page.click("[data-origin-sheet-load-bom]");
  await page.waitForTimeout(500);
  ok("P3: Load BOM fires a confirm dialog", dialogCount > dlgB, `dialogs=${dialogCount - dlgB}`);
  ok("P3: confirm mentions ghi đè", /ghi đè/i.test(lastDialog), lastDialog.slice(0, 60));

  ok("no console errors", errors.length === 0, errors.slice(0, 3).join(" | "));

  console.log("\n=== BG1 fix — checks ===");
  for (const c of checks) console.log(`${c.pass ? "PASS" : "FAIL"}  ${c.name}${c.extra ? "  [" + c.extra + "]" : ""}`);
  const passed = checks.filter((c) => c.pass).length;
  console.log(`\n${passed}/${checks.length} passed. Screenshots → ${OUT}`);
  await browser.close();
  process.exit(passed === checks.length ? 0 : 1);
})();
