const { chromium } = require("playwright");
const { mkdirSync, writeFileSync } = require("fs");

const BASE = process.env.BASE || "http://127.0.0.1:8001";
const CID = process.env.CID || "growatt-vn";
const CASE = process.env.CASE || "co-case-e44fe2065b62";
const SHOTDIR = ".ai/screenshots/2026-06-14-co-flow-redesign";
const TMP = "/tmp/co-e2e-chungtu.pdf";

const log = (...a) => console.log(...a);

(async () => {
  mkdirSync(SHOTDIR, { recursive: true });
  writeFileSync(TMP, Buffer.from("%PDF-1.4\n% barry-CO e2e test document\n%%EOF\n", "utf8"));

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push("PAGEERROR " + e.message));

  const checks = [];
  const check = (name, cond, extra = "") => {
    checks.push({ name, ok: !!cond });
    log(`${cond ? "PASS" : "FAIL"}  ${name}${extra ? "  — " + extra : ""}`);
  };

  // STEP 1 — Lô hàng: form picker must be gone, market picker stays
  await page.goto(`${BASE}/clients/${CID}/co-case/${CASE}/shipment`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(400);
  // trigger the invoice preview so form-lane hints (if any) render
  await page.locator("[data-invoice-input]").first().fill("GUS28826A131-3F").catch(() => {});
  await page.waitForTimeout(1200);
  const formPreview = await page.locator("[data-form-preview]").count();
  const formHints = await page.locator(".invoice-form-hints").count();
  const marketInput = await page.locator("[data-market-input]").count();
  await page.screenshot({ path: `${SHOTDIR}/01-shipment.png`, fullPage: true });
  check("step1 form-preview removed", formPreview === 0, `data-form-preview=${formPreview}`);
  check("step1 invoice form-lanes removed", formHints === 0, `invoice-form-hints=${formHints}`);
  check("step1 market picker present", marketInput > 0, `market inputs=${marketInput}`);

  // STEP 2 — Chứng từ: dropzone redesign
  await page.goto(`${BASE}/clients/${CID}/co-case/${CASE}/documents`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(400);
  const panel = await page.locator("[data-documents-panel]").count();
  const slots = await page.locator("[data-doc-slot]").count();
  const dropzones = await page.locator(".doc-dropzone").count();
  const reqBefore = ((await page.locator("[data-doc-required-summary]").textContent()) || "").trim();
  await page.screenshot({ path: `${SHOTDIR}/02-documents.png`, fullPage: true });
  check("step2 documents panel", panel === 1);
  check("step2 has 7 slots", slots === 7, `slots=${slots}`);
  check("step2 has 7 dropzones", dropzones === 7, `dropzones=${dropzones}`);
  log("  required summary:", reqBefore);

  // STEP 2b — upload into optional "contract" slot via the hidden input
  const slot = page.locator('[data-doc-slot="contract"]');
  await slot.locator("[data-doc-input]").setInputFiles(TMP);
  await slot.locator(".doc-file:not(.is-pending)[data-doc-file]").first().waitFor({ timeout: 15000 });
  const chipName = ((await slot.locator(".doc-file-name").first().textContent()) || "").trim();
  const optSummary = ((await page.locator("[data-doc-optional-summary]").textContent()) || "").trim();
  const slotStatus = ((await slot.locator("[data-doc-slot-status]").textContent()) || "").trim();
  await page.screenshot({ path: `${SHOTDIR}/03-documents-uploaded.png`, fullPage: true });
  check("step2 chip appeared (async, no reload)", !!chipName, `name=${chipName}`);
  check("step2 optional counter incremented", /Bổ sung\s*1/.test(optSummary), `summary=${optSummary}`);
  check("step2 slot status updated", /1 file/.test(slotStatus), `status=${slotStatus}`);

  // STEP 2c — delete the uploaded file (also cleans up dev data)
  const before = await slot.locator(".doc-file").count();
  await slot.locator("[data-doc-remove]").first().click();
  await page.waitForTimeout(1000);
  const after = await slot.locator(".doc-file").count();
  await page.screenshot({ path: `${SHOTDIR}/04-documents-after-delete.png`, fullPage: true });
  check("step2 chip deleted (async)", after < before, `before=${before} after=${after}`);

  // STEPS 3-5 — walkthrough screenshots
  for (const [name, sub] of [["05-origin", "/origin"], ["06-exports", "/exports"], ["07-review", "/review"]]) {
    const resp = await page.goto(`${BASE}/clients/${CID}/co-case/${CASE}${sub}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${SHOTDIR}/${name}.png`, fullPage: true });
    check(`${name} renders 200`, resp && resp.status() === 200, `status=${resp && resp.status()}`);
  }

  await browser.close();
  const failed = checks.filter((c) => !c.ok);
  log(`\n=== ${checks.length - failed.length}/${checks.length} checks passed ===`);
  if (errors.length) {
    log(`\nconsole/page errors (${errors.length}):`);
    [...new Set(errors)].slice(0, 10).forEach((e) => log("  " + e));
  } else {
    log("no console/page errors");
  }
  process.exit(failed.length ? 1 : 0);
})();
