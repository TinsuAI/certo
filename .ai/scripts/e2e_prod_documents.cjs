const { chromium } = require("playwright");
const { mkdirSync } = require("fs");

const BASE = "https://barry-co.tinsu.ai";
const EMAIL = "claude-check@local";
const PASSWORD = "claude-temp-2026";
const SHOTDIR = ".ai/screenshots/2026-06-14-co-flow-redesign";
const CIDS = ["growatt-vn", "johnson-vn"];

const log = (...a) => console.log(...a);

(async () => {
  mkdirSync(SHOTDIR, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 }, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push("PAGEERROR " + e.message));

  // --- SSO login ---
  await page.goto(`${BASE}/clients`, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForSelector("input[name=email]", { timeout: 20000 });
  await page.fill("input[name=email]", EMAIL);
  await page.fill("input[name=password]", PASSWORD);
  await Promise.all([
    page.waitForLoadState("networkidle", { timeout: 45000 }),
    page.click('button:has-text("Đăng nhập"), input[type=submit]'),
  ]);
  if (/name=.?password/.test(await page.content()) && /auth|login/i.test(page.url())) {
    log("LOGIN FAILED"); await page.screenshot({ path: `${SHOTDIR}/prod-login-failed.png` });
    await browser.close(); process.exit(2);
  }
  log("logged in:", page.url());

  // --- discover a case (try growatt-vn then johnson-vn) ---
  let CID = null, CASE = null;
  for (const cid of CIDS) {
    await page.goto(`${BASE}/clients/${cid}/co-case`, { waitUntil: "domcontentloaded", timeout: 45000 });
    const hrefs = await page.locator('a[href*="/co-case/co-case-"]').evaluateAll((els) => els.map((e) => e.getAttribute("href")));
    const m = (hrefs.find(Boolean) || "").match(/co-case-[a-f0-9]+/);
    if (m) { CID = cid; CASE = m[0]; break; }
  }
  if (!CASE) { log("NO CASE FOUND on prod"); await browser.close(); process.exit(3); }
  log(`case: ${CID}/${CASE}`);

  const checks = [];
  const check = (name, cond, extra = "") => { checks.push({ name, ok: !!cond }); log(`${cond ? "PASS" : "FAIL"}  ${name}${extra ? "  — " + extra : ""}`); };

  // --- STEP 1: shipment — form must be gone ---
  await page.goto(`${BASE}/clients/${CID}/co-case/${CASE}/shipment`, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForTimeout(600);
  const fp = await page.locator("[data-form-preview]").count();
  const fh = await page.locator(".invoice-form-hints").count();
  await page.screenshot({ path: `${SHOTDIR}/prod-01-shipment.png`, fullPage: true });
  check("prod step1 form-preview removed", fp === 0, `data-form-preview=${fp}`);
  check("prod step1 invoice form-lanes removed", fh === 0, `invoice-form-hints=${fh}`);

  // --- STEP 2: documents — dropzone redesign (visual only, no upload on prod) ---
  await page.goto(`${BASE}/clients/${CID}/co-case/${CASE}/documents`, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForTimeout(600);
  const panel = await page.locator("[data-documents-panel]").count();
  const slots = await page.locator("[data-doc-slot]").count();
  const dz = await page.locator(".doc-dropzone").count();
  const reqSummary = ((await page.locator("[data-doc-required-summary]").textContent().catch(() => "")) || "").trim();
  await page.screenshot({ path: `${SHOTDIR}/prod-02-documents.png`, fullPage: true });
  check("prod step2 documents panel", panel === 1);
  check("prod step2 has 7 slots", slots === 7, `slots=${slots}`);
  check("prod step2 has 7 dropzones", dz === 7, `dropzones=${dz}`);
  log("  required summary:", reqSummary);

  await browser.close();
  const failed = checks.filter((c) => !c.ok);
  log(`\n=== ${checks.length - failed.length}/${checks.length} prod checks passed ===`);
  if (errors.length) { log(`console/page errors (${errors.length}):`); [...new Set(errors)].slice(0, 8).forEach((e) => log("  " + e)); }
  else log("no console/page errors");
  process.exit(failed.length ? 1 : 0);
})();
