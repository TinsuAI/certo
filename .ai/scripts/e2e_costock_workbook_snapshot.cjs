// Co-stock workbook CONVERTER e2e (add-on tool, no DB write): upload agency
// .xlsm → Convert → standard-template preview → download the standard .xlsx.
// Ingest is the operator's separate step via the existing "Import tồn CO".
// Run: python3 .ai/scripts/gen_costock_wb_fixture.py /tmp/costock-wb-e2e.xlsm
//      PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright|head -1)"); \
//      NODE_PATH="$PWDIR" node .ai/scripts/e2e_costock_workbook_snapshot.cjs
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = "http://127.0.0.1:8001";
const CLIENT = "growatt-vn";
const FIXTURE = "/tmp/costock-wb-e2e.xlsm";
const OUT = ".ai/screenshots/2026-06-14-costock-workbook-converter";
fs.mkdirSync(OUT, { recursive: true });

const checks = [];
const ok = (name, cond, extra = "") => checks.push({ name, pass: !!cond, extra });

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("dialog", (d) => d.accept().catch(() => {})); // accept the ghi-đè confirm

  const visible = (sel) =>
    page.$eval(sel, (n) => !!(n.offsetWidth || n.offsetHeight || n.getClientRects().length)).catch(() => false);

  await page.goto(`${BASE}/clients/${CLIENT}/co-stock/workbook-tool`, { waitUntil: "networkidle" });
  ok("converter tool page present", await visible("[data-co-stock-snapshot-form]"));
  await page.$eval("[data-co-stock-snapshot]", (n) => n.scrollIntoView());
  await page.screenshot({ path: `${OUT}/00-panel.png` });

  // Upload .xlsm + Convert (real call, no DB write).
  await page.setInputFiles("[data-snapshot-file]", FIXTURE);
  await page.click("[data-snapshot-convert]");
  await page.waitForSelector("[data-snapshot-preview-wrap]:not([hidden])", { timeout: 10000 }).catch(() => {});
  ok("preview shown after convert", await visible("[data-snapshot-preview-wrap]"));
  const previewRowCount = await page.$$eval("[data-snapshot-preview-rows] tr", (r) => r.length).catch(() => 0);
  ok("preview has rows", previewRowCount >= 5, `${previewRowCount} rows`);
  const resultText = await page.$eval("[data-snapshot-result]", (n) => n.textContent.trim()).catch(() => "");
  ok("convert result message", /Đã convert/.test(resultText), resultText);
  const previewText = await page.$eval("[data-snapshot-preview-rows]", (n) => n.textContent).catch(() => "");
  ok("over-reconciled lot shows -2", previewText.includes("-2"));
  ok("zero-used lot keeps opening 1000", previewText.includes("1000"));
  // customs_code must be the name "#&" PREFIX (BCCT lot key), not the dotted Mã NPL/SP.
  const codeCells = await page.$$eval("[data-snapshot-preview-rows] tr", (trs) =>
    trs.map((tr) => tr.children[2] && tr.children[2].textContent.trim())).catch(() => []);
  ok("customs_code keyed on name prefix (DIOT)", codeCells.includes("DIOT"), codeCells.join(","));
  ok("customs_code is NOT the dotted Mã NPL/SP", !codeCells.includes("008.0035900"));
  await page.$eval("[data-snapshot-preview-wrap]", (n) => n.scrollIntoView());
  await page.screenshot({ path: `${OUT}/01-convert-preview.png`, fullPage: true });

  // Download the standard template (.xlsx) — the converter's only output.
  let dlName = "";
  try {
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 8000 }),
      page.click("[data-snapshot-download]"),
    ]);
    dlName = download.suggestedFilename();
    const saved = `${OUT}/${dlName}`;
    await download.saveAs(saved);
    ok("download is .xlsx", dlName.endsWith(".xlsx"), dlName);
    ok("downloaded file non-empty", fs.existsSync(saved) && fs.statSync(saved).size > 1000, `${fs.existsSync(saved) ? fs.statSync(saved).size : 0} bytes`);
    fs.unlinkSync(saved); // keep scratch xlsx out of committed screenshots dir
  } catch (e) {
    ok("download is .xlsx", false, String(e));
  }
  await page.screenshot({ path: `${OUT}/02-after-download.png` });

  // "Nạp snapshot vào tồn CO" button wiring — MOCK /import-snapshot so we don't
  // clobber growatt-vn's real 38k-row snapshot. Real ingest is covered by
  // tests/test_co_stock_workbook.py::test_standalone_import_sets_rows_and_reimport_replaces.
  await page.route("**/co-stock/import-snapshot", (route) =>
    route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ ok: true, rows_persisted: 5, rows_added: 5, rows_updated: 0, rows_removed: 0, rows_blocked_by_claims: 0 }),
    }));
  await page.click("[data-snapshot-ingest]");
  await page.waitForFunction(
    () => /Đã nạp snapshot/.test(document.querySelector("[data-snapshot-result]")?.textContent || ""),
    { timeout: 5000 }
  ).catch(() => {});
  const ingestMsg = await page.$eval("[data-snapshot-result]", (n) => n.textContent.trim()).catch(() => "");
  ok("Nạp snapshot button wiring (mocked)", /Đã nạp snapshot/.test(ingestMsg), ingestMsg);
  await page.screenshot({ path: `${OUT}/03-snapshot-ingested.png` });

  ok("no console errors", errors.length === 0, errors.slice(0, 3).join(" | "));

  await browser.close();
  let pass = 0;
  for (const c of checks) {
    console.log(`${c.pass ? "PASS" : "FAIL"}  ${c.name}${c.extra ? "  — " + c.extra : ""}`);
    if (c.pass) pass++;
  }
  console.log(`\n${pass}/${checks.length} checks passed → ${OUT}`);
  process.exit(pass === checks.length ? 0 : 1);
})();
