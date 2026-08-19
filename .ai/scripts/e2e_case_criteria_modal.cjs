// E2E: tiêu chí cho cả lô is a segmented picker in a modal, and saving it (or a
// per-sheet ⚙ Cấu hình) re-renders the case shell without an F5.
//
// Client report 2026-08-19 items 2 + 3: the case-level criterion opened a native
// window.prompt with a free-text box (nothing told the engine which rule was meant),
// and after saving a criterion the sheet chips kept the old text until a manual
// reload.
//
//   set -a; . ./.env; set +a
//   CLIENT=johnson-vn CASE=co-case-e0b390ead3b0 node .ai/scripts/e2e_case_criteria_modal.cjs
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer");

const BASE = process.env.BASE || "http://127.0.0.1:8001";
const CLIENT = process.env.CLIENT || "johnson-vn";
const CASE = process.env.CASE || "co-case-e0b390ead3b0";
const SHOTS = path.join(__dirname, "..", "screenshots", "2026-08-19-tieu-chi-picker");

let failed = 0;
const fail = (m) => { failed++; console.error("  FAIL: " + m); };
const ok = (m) => console.log("  ok:   " + m);

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await puppeteer.launch({ args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 1000 });
  const errors = [];
  // Resource errors arrive as a generic "Failed to load resource" console line with
  // no URL, so they are tracked from the response instead — /favicon.ico is 404 on
  // this app in every environment and is not a page defect.
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("response", (r) => {
    if (r.status() >= 400 && !r.url().endsWith("/favicon.ico")) errors.push(`${r.status()} ${r.url()}`);
  });

  // A native prompt() would hang the run; record it instead so the assertion is real.
  let promptSeen = false;
  page.on("dialog", async (d) => { promptSeen = true; await d.dismiss(); });

  const url = `${BASE}/clients/${CLIENT}/co-case/${CASE}/origin`;
  await page.goto(url, { waitUntil: "networkidle2", timeout: 180000 });

  const hasBar = await page.$("[data-origin-case-criteria]");
  if (!hasBar) { console.error("no [data-origin-case-criteria] on this case — pick a case with products"); process.exit(2); }

  console.log("1. modal replaces window.prompt");
  await page.click("[data-origin-case-criteria-edit]");
  await page.waitForSelector("[data-case-criteria-modal]:not([hidden])", { timeout: 5000 });
  if (promptSeen) fail("a native prompt() still fired"); else ok("no native prompt()");
  const segCount = await page.$$eval("[data-case-criteria-panel] [data-criteria-seg]", (n) => n.length);
  segCount === 8 ? ok(`${segCount} criterion buttons (WO…PSR)`) : fail(`expected 8 criterion buttons, got ${segCount}`);
  await page.screenshot({ path: path.join(SHOTS, "01-case-criteria-modal.png") });

  console.log("2. picking a segment composes the criterion text");
  await page.click('[data-case-criteria-panel] [data-criteria-seg="CTH"]');
  let composed = await page.$eval("[data-case-criteria-panel] [data-origin-recommendation-criteria]", (n) => n.value);
  composed === "CTH" ? ok("CTH → 'CTH'") : fail(`CTH composed '${composed}'`);
  const altsHidden = await page.$eval("[data-case-criteria-panel] [data-criteria-alts]", (n) => n.hidden);
  altsHidden ? fail("'hoặc' alternates stayed hidden for CTH") : ok("'hoặc' alternates revealed for CTH");

  console.log("3. RVC reveals the Ngưỡng % row, CTH does not");
  await page.click('[data-case-criteria-panel] [data-criteria-seg="RVC"]');
  const thrShown = await page.$eval("[data-case-criteria-panel] [data-criteria-threshold-row]", (n) => !n.hidden);
  thrShown ? ok("Ngưỡng % shown for RVC") : fail("Ngưỡng % stayed hidden for RVC");
  await page.type("[data-case-criteria-panel] [data-origin-recommendation-threshold]", "40");
  composed = await page.$eval("[data-case-criteria-panel] [data-origin-recommendation-criteria]", (n) => n.value);
  composed.startsWith("RVC") ? ok(`composed '${composed}'`) : fail(`composed '${composed}'`);
  await page.screenshot({ path: path.join(SHOTS, "02-rvc-threshold.png") });

  console.log("4. save re-renders in place — no navigation, no F5");
  // history.replaceState (which the shell swap does) also fires framenavigated, so
  // the reliable signal is whether the JS context survived: a real reload drops it.
  await page.evaluate(() => { window.__coShellMarker = "alive"; });
  await page.click("[data-case-criteria-save]");
  await page.waitForFunction(
    () => document.querySelector("[data-case-criteria-modal]")?.hasAttribute("hidden"),
    { timeout: 30000 },
  ).catch(async () => {
    const s = await page.$eval("[data-case-criteria-status]", (n) => n.textContent).catch(() => "(no status)");
    fail(`save did not close the modal — status: ${s}`);
  });
  await page.waitForFunction(
    () => {
      const v = document.querySelector("[data-origin-case-criteria-value]");
      return v && /RVC/.test(v.textContent || "");
    },
    { timeout: 90000 },
  );
  const survived = await page.evaluate(() => window.__coShellMarker || "");
  survived === "alive" ? ok("shell swapped in place (JS context survived)") : fail("the page fully reloaded instead of swapping the shell");
  const barText = await page.$eval("[data-origin-case-criteria-value]", (n) => n.textContent.trim());
  ok(`bar now reads: ${barText}`);
  const stillUnset = await page.$eval("[data-origin-case-criteria]", (n) => n.classList.contains("origin-case-criteria-unset"));
  stillUnset ? fail("bar still renders the 'chưa chọn' state after saving") : ok("bar left the 'chưa chọn' state");
  const chipSources = await page.$$eval("[data-origin-criteria-chip] .occ-src", (n) => n.map((e) => e.textContent.trim()));
  chipSources.length && chipSources.every((s) => s === "theo lô hàng")
    ? ok(`${chipSources.length} sheet chips read "theo lô hàng"`)
    : fail(`sheet chips did not inherit: ${JSON.stringify(chipSources)}`);
  await page.screenshot({ path: path.join(SHOTS, "03-after-save-no-reload.png") });

  console.log("5. clear puts it back — and actually persists");
  // Regression: the route used to pop `criteria_choice` off the case dict, but
  // update_case_record only copies keys PRESENT in the incoming case, so the stored
  // choice survived and "Bỏ chọn" did nothing.
  page.removeAllListeners("dialog");
  page.on("dialog", async (d) => { await d.accept(); });
  await page.click("[data-origin-case-criteria-clear]");
  await page.waitForFunction(
    () => document.querySelector("[data-origin-case-criteria]")?.classList.contains("origin-case-criteria-unset"),
    { timeout: 90000 },
  );
  ok("criterion cleared, bar back to 'chưa chọn'");
  await page.reload({ waitUntil: "networkidle2", timeout: 180000 });
  const clearedAfterReload = await page.$eval("[data-origin-case-criteria]", (n) => n.classList.contains("origin-case-criteria-unset"));
  clearedAfterReload ? ok("still cleared after F5 (persisted)") : fail("the clear did not persist — F5 brings the criterion back");

  if (errors.length) fail("console errors: " + errors.slice(0, 5).join(" | "));
  else ok("no console errors");

  await browser.close();
  console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
