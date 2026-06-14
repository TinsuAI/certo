// RD3 verify: bảng kê Review ⇄ Sheet drill-in split + bottom Excel tabs.
// Run: PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright|head -1)"); \
//      NODE_PATH="$PWDIR" node .ai/scripts/e2e_bangke_split.cjs
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = "http://127.0.0.1:8001";
const CLIENT = "growatt-vn";
const CASE = "co-case-e44fe2065b62"; // BG1 case: 1 product, 122 materials
const OUT = ".ai/screenshots/2026-06-14-bangke-split";
fs.mkdirSync(OUT, { recursive: true });

const checks = [];
const ok = (name, cond, extra = "") =>
  checks.push({ name, pass: !!cond, extra });

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

  const view = () =>
    page.$eval("[data-origin-view]", (n) => n.dataset.originView).catch(() => null);
  const visible = (sel) =>
    page.$eval(sel, (n) => !!(n.offsetWidth || n.offsetHeight || n.getClientRects().length)).catch(() => false);

  // 1) Review view (default landing)
  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/origin`, { waitUntil: "networkidle" });
  ok("review: root view=review", (await view()) === "review");
  ok("review: dashboard visible", await visible("[data-origin-review]"));
  ok("review: sheet workspace hidden", !(await visible("[data-origin-sheet-workspace]")));
  ok("review: has drill row", await visible(".origin-review-drill"));
  await page.screenshot({ path: `${OUT}/01-review.png`, fullPage: true });

  // 2) Drill into the first sheet
  await page.click(".origin-review-drill");
  await page.waitForTimeout(250);
  ok("drill: root view=sheet", (await view()) === "sheet");
  ok("drill: grid visible", await visible(".origin-material-table"));
  ok("drill: bottom tabs visible", await visible(".origin-sheet-tabs-bottom"));
  ok("drill: active tab present", await visible(".origin-sheet-tabs-bottom .origin-sheet-tab-active"));
  ok("drill: review hidden", !(await visible("[data-origin-review]")));
  ok("drill: settings gear present", await visible("[data-origin-settings-open]"));
  ok("drill: config moved off-grid (not inline)", !(await visible(".origin-view-sheet [data-origin-sheet-panel]:not([hidden]) > .origin-column-controls")));
  ok("drill: URL has ?sheet=", page.url().includes("?sheet="));
  ok("drill: back button visible", await visible("[data-origin-back-to-review]"));
  await page.screenshot({ path: `${OUT}/02-sheet.png`, fullPage: true });
  // close-up of the bottom tab strip + active styling
  const strip = await page.$(".origin-sheet-tabs-bottom");
  if (strip) await strip.screenshot({ path: `${OUT}/03-bottom-tabs.png` });

  // 3) Open the settings (⚙) modal — config + cost-buildup + column toggles live here
  await page.click("[data-origin-settings-open]").catch(() => {});
  await page.waitForTimeout(200);
  ok("settings: modal opens", await visible("[data-origin-settings-modal]:not([hidden])"));
  ok("settings: has column toggles", await visible("[data-origin-settings-body] .origin-column-controls"));
  ok("settings: has config overrides", await visible("[data-origin-settings-body] .origin-config-disclosure"));
  ok("settings: has cost-buildup", await visible("[data-origin-settings-body] .cost-buildup-block"));
  await page.screenshot({ path: `${OUT}/04-settings-modal.png`, fullPage: true });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);

  // 4) Back to review
  await page.click("[data-origin-back-to-review]");
  await page.waitForTimeout(200);
  ok("back: root view=review", (await view()) === "review");
  ok("back: URL has no ?sheet=", !page.url().includes("?sheet="));
  await page.screenshot({ path: `${OUT}/05-back-to-review.png`, fullPage: true });

  // 5) Deep-link / F5 into a sheet
  const code = await page.$eval(".origin-review-drill", (n) => n.dataset.productCode);
  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/origin?sheet=${encodeURIComponent(code)}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(200);
  ok("deeplink: root view=sheet", (await view()) === "sheet");
  ok("deeplink: correct active sheet", (await page.$eval("[data-origin-view]", (n) => n.dataset.originActiveSheet)) === code);
  ok("deeplink: grid visible", await visible(".origin-material-table"));
  await page.screenshot({ path: `${OUT}/06-deeplink.png`, fullPage: true });

  // 6) Find a multi-product case for tab-switching (scan the list)
  let multiCase = null;
  await page.goto(`${BASE}/clients/${CLIENT}/co-case`, { waitUntil: "networkidle" });
  const caseIds = await page.$$eval("a[href*='/co-case/']", (as) =>
    [...new Set(as.map((a) => (a.getAttribute("href") || "").match(/co-case-[a-z0-9]+/)?.[0]).filter(Boolean))]
  );
  for (const id of caseIds.slice(0, 25)) {
    await page.goto(`${BASE}/clients/${CLIENT}/co-case/${id}/origin`, { waitUntil: "domcontentloaded" });
    const n = await page.$$eval(".origin-review-drill", (e) => e.length).catch(() => 0);
    if (n >= 2) { multiCase = id; break; }
  }
  if (multiCase) {
    await page.goto(`${BASE}/clients/${CLIENT}/co-case/${multiCase}/origin`, { waitUntil: "networkidle" });
    await page.click(".origin-review-drill");
    await page.waitForTimeout(200);
    const firstActive = await page.$eval(".origin-sheet-tab-active", (n) => n.dataset.productCode);
    const tabs = await page.$$(".origin-sheet-tabs-bottom .origin-sheet-tab");
    // click a non-active tab
    let switched = false;
    for (const t of tabs) {
      const c = await t.getAttribute("data-product-code");
      if (c && c !== firstActive) { await t.click(); switched = true; break; }
    }
    await page.waitForTimeout(200);
    const nowActive = await page.$eval(".origin-sheet-tab-active", (n) => n.dataset.productCode);
    ok(`multi(${multiCase}): tab switch changes active`, switched && nowActive !== firstActive, `${firstActive}→${nowActive}`);
    await page.screenshot({ path: `${OUT}/07-multi-tab-switch.png`, fullPage: true });
  } else {
    checks.push({ name: "multi: no 2+ product case found in first 25 (tab-switch not visually tested)", pass: true, extra: "INFO" });
  }

  ok("no console errors", errors.length === 0, errors.slice(0, 5).join(" | "));

  await browser.close();
  console.log("\n=== RD3 bảng kê split — checks ===");
  let passN = 0;
  for (const c of checks) {
    console.log(`${c.pass ? "PASS" : "FAIL"}  ${c.name}${c.extra ? "  [" + c.extra + "]" : ""}`);
    if (c.pass) passN++;
  }
  console.log(`\n${passN}/${checks.length} passed. Screenshots → ${OUT}`);
  process.exit(checks.every((c) => c.pass) ? 0 : 1);
})();
