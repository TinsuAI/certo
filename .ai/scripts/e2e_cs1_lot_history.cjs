// CS1 lot-history modal: verify system-event fold (readded) renders cleanly.
// Recipe: PWDIR=$(dirname "$(ls -d ~/.npm/_npx/*/node_modules/playwright|head -1)"); NODE_PATH="$PWDIR" node .ai/scripts/e2e_cs1_lot_history.cjs
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

(async () => {
  const OUT = path.join(__dirname, "..", "screenshots", "2026-06-14-cs1-lot-history-modal");
  fs.mkdirSync(OUT, { recursive: true });
  const base = "http://127.0.0.1:8001";
  const client = "johnson-vn";
  const lot = { declaration_no: "107646384310", line_no: "33", customs_code: "1000434001" };

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

  await page.goto(`${base}/clients/${client}/co-stock`, { waitUntil: "networkidle" });

  // Fire the body-delegated modal handler for our target lot.
  await page.evaluate((lot) => {
    const b = document.createElement("button");
    b.setAttribute("data-co-stock-history-btn", "");
    b.dataset.declarationNo = lot.declaration_no;
    b.dataset.lineNo = lot.line_no;
    b.dataset.customsCode = lot.customs_code;
    b.style.cssText = "position:fixed;top:0;left:0";
    document.body.appendChild(b);
    b.click();
  }, lot);

  await page.waitForSelector(".co-stock-event-system", { timeout: 8000 });
  await page.waitForTimeout(300);
  const card = page.locator(".co-stock-history-modal-card");
  await card.screenshot({ path: path.join(OUT, "grouped-system-readded.png") });

  await page.click("[data-co-stock-history-toggle]");
  await page.waitForTimeout(300);
  await card.screenshot({ path: path.join(OUT, "raw-detail.png") });

  console.log("console/page errors:", JSON.stringify(errors));
  console.log("screenshots →", OUT);
  await browser.close();
})();
