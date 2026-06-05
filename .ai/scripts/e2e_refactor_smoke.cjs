const { chromium } = require("playwright");
const { mkdirSync } = require("fs");

const BASE = process.env.BASE || "http://127.0.0.1:8001";
const CID = "growatt-vn";
const CASE = process.env.CASE || "co-case-05d2f9ee982d";
const SHOTDIR = ".ai/screenshots/refactor-e2e";

const pages = [
  ["healthz", "/healthz", null],
  ["root", "/", "clients"],
  ["clients", "/clients", "clients"],
  ["workspace", `/clients/${CID}`, null],
  ["catalog", `/clients/${CID}/catalog`, null],
  ["catalog-materials", `/clients/${CID}/catalog/materials`, null],
  ["catalog-products", `/clients/${CID}/catalog/products`, null],
  ["bom", `/clients/${CID}/bom`, null],
  ["bcct", `/clients/${CID}/bcct`, null],
  ["bcct-imports", `/clients/${CID}/bcct/imports`, null],
  ["bcct-exports", `/clients/${CID}/bcct/exports`, null],
  ["co-stock", `/clients/${CID}/co-stock`, null],
  ["cost-allocation", `/clients/${CID}/cost-allocation`, null],
  ["config", `/clients/${CID}/config`, null],
  ["co-case-list", `/clients/${CID}/co-case`, null],
  ["co-case-detail", `/clients/${CID}/co-case/${CASE}`, null],
  ["co-case-origin", `/clients/${CID}/co-case/${CASE}/origin`, null],
  ["customs-fx", `/customs-exchange-rates`, null],
  ["settings", `/settings`, null],
  ["co-forms", `/settings/co-forms`, null],
];

(async () => {
  mkdirSync(SHOTDIR, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

  const results = [];
  for (const [name, path, expect] of pages) {
    let status = 0, ok = false, note = "";
    try {
      const resp = await page.goto(BASE + path, { waitUntil: "domcontentloaded", timeout: 30000 });
      status = resp ? resp.status() : 0;
      const body = await page.content();
      const hasTraceback = /Traceback \(most recent call last\)|Internal Server Error/.test(body);
      const hasExpect = expect ? body.toLowerCase().includes(expect.toLowerCase()) : true;
      ok = status === 200 && !hasTraceback && hasExpect;
      if (hasTraceback) note = "TRACEBACK";
      else if (expect && !hasExpect) note = `missing "${expect}"`;
      if (name === "co-case-origin") {
        const panels = await page.locator("[data-origin-sheet-panel]").count();
        const triggers = await page.locator("[data-origin-substitute-trigger]").count();
        note = `sheet-panels=${panels} substitute-triggers=${triggers}`;
      }
      await page.screenshot({ path: `${SHOTDIR}/${name}.png` });
    } catch (e) {
      note = "ERR " + e.message.split("\n")[0];
    }
    results.push({ name, status, ok, note });
    console.log(`${ok ? "PASS" : "FAIL"}  ${String(status).padEnd(3)}  ${name.padEnd(20)} ${note}`);
  }

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n=== ${results.length - failed.length}/${results.length} passed ===`);
  if (consoleErrors.length) {
    console.log(`\nconsole errors (${consoleErrors.length}):`);
    [...new Set(consoleErrors)].slice(0, 8).forEach((e) => console.log("  " + e));
  }
  process.exit(failed.length ? 1 : 0);
})();
