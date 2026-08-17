// E2E: the dossier-export progress panel must keep polling after an IN-APP tab
// switch, and must turn into the download button without a page reload.
//
// Prod defect (johnson-vn VNG26030107, 2026-08-17): the poll lived in an inline
// <script> inside the review section. In-app navigation replaces the shell with
// importNode, which never executes script nodes, so the server-rendered
// "Đang tạo hồ sơ .zip…" froze — the zip was ready after 5m42s and the operator
// only got it 33 minutes later, after F5.
//
//   set -a; . ./.env; set +a
//   PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_dossier_export_panel_seed.py
//   node .ai/scripts/e2e_dossier_export_panel.cjs
//   PYTHONPATH=$(pwd) uv run python .ai/scripts/e2e_dossier_export_panel_seed.py --cleanup
const puppeteer = require("puppeteer");

const BASE = process.env.BASE || "http://127.0.0.1:8001";
const CLIENT = process.env.CLIENT || "johnson-vn";
const CASE = process.env.CASE || "e2e-export-panel";

let failed = 0;
const fail = (m) => { failed++; console.error("  FAIL: " + m); };
const ok = (m) => console.log("  ok:   " + m);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({ args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  let statusHits = 0;
  let serveDone = false;
  await page.setRequestInterception(true);
  page.on("request", (req) => {
    const url = req.url();
    if (url.includes("/export-dossier-zip/status")) {
      statusHits++;
      if (!serveDone) return req.continue();
      // Flip to a finished export so the panel must swap in the download link.
      return req.respond({
        status: 200,
        contentType: "text/html; charset=utf-8",
        body: `<div class="dossier-export-state" data-export-status="done" data-export-stale="0">
                 <a class="btn-primary review-action-link" href="#dl"><strong>Tải hồ sơ .zip</strong></a>
               </div>`,
      });
    }
    return req.continue();
  });

  const reviewUrl = `${BASE}/clients/${CLIENT}/co-case/${CASE}/review`;
  await page.goto(reviewUrl, { waitUntil: "networkidle2", timeout: 120000 });

  const spinner = await page.$eval("#dossier-export-panel .dossier-export-state",
    (el) => el.getAttribute("data-export-status")).catch(() => null);
  spinner === "running" ? ok("full load renders the running panel") : fail(`panel status on load = ${spinner}`);

  const afterLoad = statusHits;
  await wait(5000);
  const polledOnFullLoad = statusHits - afterLoad;
  polledOnFullLoad >= 2
    ? ok(`full load polls (${polledOnFullLoad} hits / 5s)`)
    : fail(`full load did not poll (${polledOnFullLoad} hits / 5s)`);

  // In-app navigation: leave Review through a workflow step, then come back the
  // same way. No page load happens — this is the swap that used to kill polling.
  await page.evaluate(() => {
    const steps = Array.from(document.querySelectorAll("[data-co-case-shell] .workflow-step"));
    const target = steps.find((s) => (s.textContent || "").includes("Chứng từ")) || steps[1];
    target.click();
  });
  await wait(3000);
  await page.evaluate(() => {
    const steps = Array.from(document.querySelectorAll("[data-co-case-shell] .workflow-step"));
    const target = steps.find((s) => (s.textContent || "").includes("Review")) || steps[steps.length - 1];
    target.click();
  });
  await wait(2500);

  const navigations = await page.evaluate(() => window.performance.getEntriesByType("navigation").length);
  navigations === 1 ? ok("stayed on the same document (in-app swap, no reload)") : fail(`page reloaded (${navigations} navigations)`);

  const panelAfterSwap = await page.$eval("#dossier-export-panel .dossier-export-state",
    (el) => el.getAttribute("data-export-status")).catch(() => null);
  panelAfterSwap === "running" ? ok("panel is server-rendered after the swap") : fail(`panel after swap = ${panelAfterSwap}`);

  const afterSwap = statusHits;
  await wait(5000);
  const polledAfterSwap = statusHits - afterSwap;
  polledAfterSwap >= 2
    ? ok(`polling resumed after the in-app swap (${polledAfterSwap} hits / 5s)`)
    : fail(`NO polling after the in-app swap (${polledAfterSwap} hits / 5s) — the prod defect`);

  // Completion must reach the UI without a reload.
  serveDone = true;
  await wait(4000);
  const done = await page.$eval("#dossier-export-panel .dossier-export-state",
    (el) => el.getAttribute("data-export-status")).catch(() => null);
  const link = await page.$("#dossier-export-panel a.review-action-link");
  done === "done" && link
    ? ok("finished export swaps in the download button with no reload")
    : fail(`panel did not reach done (status=${done}, link=${!!link})`);

  await browser.close();
  console.log(failed ? `FAILED ${failed}` : "ALL OK");
  process.exit(failed ? 1 : 0);
})().catch((error) => { console.error(error); process.exit(1); });
