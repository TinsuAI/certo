const { chromium } = require("playwright");

const BASE = "http://127.0.0.1:8001";
// (client, case) candidates to probe for a calculated origin sheet with substitute triggers
const CANDIDATES = [
  ["growatt-vn", "co-case-05d2f9ee982d"],
  ["growatt-vn", "co-case-3b36f4820935"],
  ["growatt-vn", "co-case-86b31dd3badc"],
  ["johnson-vn", "co-case-4e9f5a3b1e9c"],
  ["johnson-vn", "co-case-ec000d03522e"],
];

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newContext({ viewport: { width: 1440, height: 1000 } }).then((c) => c.newPage());
  const xhr = [];
  page.on("response", (r) => {
    const u = r.url();
    if (/substitute-(stock|candidates)/.test(u)) xhr.push(`${r.status()} ${u.replace(BASE, "")}`);
  });

  let found = null;
  for (const [cid, cs] of CANDIDATES) {
    await page.goto(`${BASE}/clients/${cid}/co-case/${cs}/origin`, { waitUntil: "networkidle", timeout: 30000 });
    // try each product tab
    const tabs = await page.locator("[data-origin-sheet-tab], [data-origin-product-tab]").all().catch(() => []);
    const tabCount = Math.max(tabs.length, 1);
    for (let i = 0; i < tabCount; i++) {
      if (tabs[i]) { await tabs[i].click().catch(() => {}); await page.waitForTimeout(300); }
      const trig = page.locator("[data-origin-substitute-trigger]:not([disabled]):visible").first();
      if (await trig.count()) { found = { cid, cs, i };
        await trig.click();
        break;
      }
    }
    if (found) break;
  }

  if (!found) {
    console.log("No visible substitute trigger across probed cases (data-dependent; sheets may be uncalculated or have no substitutable materials).");
    await browser.close();
    process.exit(0);
  }

  console.log(`Substitute trigger clicked on ${found.cid}/${found.cs} (tab ${found.i})`);
  // wait for modal + lazy fetch
  await page.waitForTimeout(2500);
  const modal = await page.locator("[data-origin-substitute-modal], .modal:visible, [role=dialog]:visible").count();
  const freshness = await page.locator("[data-origin-substitute-freshness]").count();
  await page.screenshot({ path: ".ai/screenshots/refactor-e2e/substitute-modal.png" });
  console.log(`modal-visible=${modal}  freshness-chip=${freshness}`);
  console.log("substitute XHR:");
  [...new Set(xhr)].forEach((x) => console.log("  " + x));
  const bad = xhr.filter((x) => !x.startsWith("200"));
  await browser.close();
  process.exit(bad.length ? 1 : 0);
})();
