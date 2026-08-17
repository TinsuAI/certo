// E2E: aggregate panel must NOT invite "Chốt tất cả" while rác chưa khớp tờ khai
// vẫn còn. Reproduces prod johnson-vn VNG26020033 (2026-08-17): every NVL thiếu tồn
// was resolved (material_count = 0) but 35+19 declarable_unmatched rows kept both
// sheets at bom_loaded, so "Chốt tất cả" reported "Đã chốt 0 sheet · bỏ qua 2" right
// after the panel said "✓ Đủ tồn cho tất cả SP — có thể Chốt tất cả".
//
// The rollup shape is SYNTHETIC (request interception) because reaching
// material_count=0 on real data means substituting every shortfall first; the branch
// under test reads only rollup.materials / folded_rac, so a stubbed body exercises it
// exactly. The other two branches are covered live by e2e_bulk_delete_junk.cjs.
//
//   set -a; . ./.env; set +a
//   CLIENT=johnson-vn CASE=johnson-e2e-rac node .ai/scripts/e2e_rac_blocks_chot_message.cjs
const puppeteer = require("puppeteer");

const BASE = process.env.BASE || "http://127.0.0.1:8001";
const CLIENT = process.env.CLIENT || "johnson-vn";
const CASE = process.env.CASE || "johnson-e2e-rac";

let failed = 0;
const fail = (m) => { failed++; console.error("  FAIL: " + m); };
const ok = (m) => console.log("  ok:   " + m);

const rollup = (folded) => ({
  status: "ok",
  rollup: {
    materials: [], material_count: 0,
    no_bom_products: [], no_bom_count: 0,
    folded_rac: folded, folded_rac_count: folded.length,
  },
});
const racEntry = (code, kind) => ({
  material_code: code, name: code, uom: "EA", needed: "4", available: "0", short_qty: "4",
  using: [{ product_code: "SP1", status: "calculated", is_short: true, noise: true, kind }],
  using_count: 1, short_products: ["SP1"], short_count: 1,
  kind, products: ["SP1"], count: 1,
});

(async () => {
  const browser = await puppeteer.launch({ args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 1000 });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

  // Case A: only phi-vật-tư left → nothing blocks Chốt → keep the ✓ invite.
  // Case B: a declarable_unmatched remains → belt 2 holds every sheet → warn instead.
  const CASES = [
    { name: "phi vật tư only", folded: [racEntry("P1", "excluded_non_material")], expectBlock: false },
    { name: "unmatched present", folded: [racEntry("U1", "declarable_unmatched"),
                                          racEntry("P1", "excluded_non_material")], expectBlock: true },
  ];

  for (const c of CASES) {
    await page.setRequestInterception(true);
    const handler = (req) => {
      if (req.url().includes("/origin/calculate-all")) {
        req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(rollup(c.folded)) });
      } else req.continue();
    };
    page.on("request", handler);

    await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/origin`, { waitUntil: "networkidle2" });
    await page.$eval("[data-origin-aggregate] [data-run-stock-all]", (el) => el.click());
    await page.waitForSelector("[data-bom-select-modal]:not([hidden]) [data-bsm-confirm]", { visible: true, timeout: 4000 })
      .then(() => page.$eval("[data-bom-select-modal] [data-bsm-confirm]", (el) => el.click())).catch(() => {});
    await page.waitForFunction(() => {
      const b = document.querySelector("[data-run-stock-summary]");
      return b && !b.hidden && (b.querySelector(".rs-done") || b.querySelector(".rs-blocked") || b.querySelector(".rs-nobom"));
    }, { timeout: 20000 }).catch(() => {});

    const box = "[data-run-stock-summary] ";
    const done = await page.$eval(box + ".rs-done", (n) => n.textContent.trim()).catch(() => "");
    const warn = await page.$eval(box + ".rs-blocked", (n) => n.textContent.trim()).catch(() => "");
    const state = await page.$eval("[data-run-stock-summary]", (n) => n.dataset.state).catch(() => "");
    const badge = await page.$eval("[data-agg-badge]", (n) => (n.hidden ? "" : n.textContent.trim())).catch(() => "");
    const ribbonNow = await page.$$eval(box + ".rs-ph.now", (ns) => ns.map((n) => n.textContent.trim())).catch(() => []);
    console.log(`\n=== ${c.name} ===\n  done="${done}"\n  warn="${warn}"\n  state=${state} badge="${badge}" ribbonNow=${JSON.stringify(ribbonNow)}`);

    if (c.expectBlock) {
      /chưa có tờ khai nhập/.test(warn) ? ok("warns about mã chưa có tờ khai nhập") : fail(`expected the unmatched warning, got "${warn}"`);
      /Chốt tất cả/.test(done) ? fail(`must NOT invite "Chốt tất cả" (got "${done}")`) : ok('no "có thể Chốt tất cả" invite');
      state === "warning" ? ok("panel state = warning") : fail(`state should be warning (got ${state})`);
      badge === "1" ? ok("tab badge counts the 1 blocking mã") : fail(`badge should be 1 (got "${badge}")`);
      ribbonNow.some((t) => /Xử lý thiếu tồn/.test(t)) ? ok("ribbon still on 'Xử lý thiếu tồn'") : fail(`ribbon should not advance (got ${JSON.stringify(ribbonNow)})`);
    } else {
      /Chốt tất cả/.test(done) ? ok('keeps the "✓ Đủ tồn … có thể Chốt tất cả" invite') : fail(`expected the ✓ invite, got "${done}"`);
      warn === "" ? ok("no false block warning") : fail(`should not warn (got "${warn}")`);
      state === "ok" ? ok("panel state = ok") : fail(`state should be ok (got ${state})`);
      badge === "" ? ok("no tab badge") : fail(`badge should be hidden (got "${badge}")`);
    }

    page.off("request", handler);
    await page.setRequestInterception(false);
  }

  errors.filter((e) => !/Failed to load resource/i.test(e)).length === 0
    ? ok("no console errors") : fail("console errors: " + errors.slice(0, 3).join(" | "));
  await browser.close();
  process.exit(failed ? 1 : 0);
})();
