// E2E for the 2026-08-19 config round: saving ⚙ Cấu hình recalculates the sheet, the
// Tiền tệ option no longer claims "nguyên tệ = VND", and the money columns drop the
// decimals a VND figure does not have.
//
//   set -a; . ./.env; set +a
//   CLIENT=johnson-vn CASE=co-case-e0b390ead3b0 node .ai/scripts/e2e_config_autorecalc_and_decimals.cjs
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer");

const BASE = process.env.BASE || "http://127.0.0.1:8001";
const CLIENT = process.env.CLIENT || "johnson-vn";
const CASE = process.env.CASE || "co-case-e0b390ead3b0";
const SHOTS = path.join(__dirname, "..", "screenshots", "2026-08-19-config-autorecalc");

let failed = 0;
const fail = (m) => { failed++; console.error("  FAIL: " + m); };
const ok = (m) => console.log("  ok:   " + m);

const openSheet = async (page) => {
  await page.evaluate(() => document.querySelector("[data-origin-drill]")?.click());
  await page.waitForSelector("[data-origin-sheet-panel] [data-origin-cell-unit-value]", { timeout: 180000 });
  await new Promise((r) => setTimeout(r, 2500));
};
const openSettings = async (page) => {
  await page.evaluate(() => {
    const panel = [...document.querySelectorAll("[data-origin-sheet-panel]")].find((p) => !p.hidden);
    panel?.querySelector("[data-origin-settings-open]")?.click();
  });
  await page.waitForSelector("[data-origin-settings-modal]:not([hidden])", { timeout: 15000 });
};
const sheetState = (page) => page.evaluate(() => {
  const panel = [...document.querySelectorAll("[data-origin-sheet-panel]")].find((p) => !p.hidden);
  return {
    code: panel?.dataset.productCode || "",
    status: panel?.dataset.originSheetStatus || "",
    decimals: panel?.dataset.displayDecimals || "",
    criteria: panel?.querySelector("[data-origin-criteria-chip] strong")?.textContent.trim() || "",
    lvc: panel?.querySelector("[data-origin-lvc-cell]")?.textContent.replace(/\s+/g, " ").trim() || "",
    unit: [...panel.querySelectorAll("[data-origin-cell-unit-value]")].slice(0, 3).map((c) => c.textContent.trim()),
    amount: [...panel.querySelectorAll("[data-origin-cell-material-value]")].slice(0, 3).map((c) => c.textContent.trim()),
  };
});

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await puppeteer.launch({ args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
  page.on("dialog", async (d) => await d.accept());

  await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/origin`, { waitUntil: "networkidle2", timeout: 240000 });
  await openSheet(page);

  console.log("1. Tiền tệ không còn tự nhận là VND");
  await openSettings(page);
  const currencyOptions = await page.$$eval(
    "[data-origin-settings-modal]:not([hidden]) [data-origin-recommendation-currency] option",
    (n) => n.map((o) => o.textContent.trim()),
  );
  /VND\)/.test(currencyOptions[0])
    ? fail(`nhãn nguyên tệ vẫn kèm tiền tệ: ${currencyOptions[0]}`)
    : ok(`nhãn nguyên tệ: "${currencyOptions[0]}"`);

  console.log("2. Số lẻ: mặc định theo tiền tệ, VND không có số lẻ");
  const before = await sheetState(page);
  const vndNoDecimals = before.unit.every((v) => !v.includes(","));
  vndNoDecimals ? ok(`đơn giá VND: ${before.unit.join(" · ")}`) : fail(`đơn giá VND vẫn còn số lẻ: ${before.unit.join(" · ")}`);
  await page.screenshot({ path: path.join(SHOTS, "01-so-le-theo-tien-te.png") });

  await page.evaluate(() => {
    const sel = document.querySelector("[data-origin-settings-modal]:not([hidden]) [data-origin-recommendation-decimals]");
    sel.value = "2"; sel.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await new Promise((r) => setTimeout(r, 500));
  const withTwo = await sheetState(page);
  withTwo.unit.every((v) => /,\d{2}$/.test(v))
    ? ok(`đặt 2 số lẻ, áp ngay không cần Lưu: ${withTwo.unit.join(" · ")}`)
    : fail(`đặt 2 số lẻ không áp: ${withTwo.unit.join(" · ")}`);
  await page.screenshot({ path: path.join(SHOTS, "02-so-le-2.png") });
  await page.evaluate(() => {
    const sel = document.querySelector("[data-origin-settings-modal]:not([hidden]) [data-origin-recommendation-decimals]");
    sel.value = ""; sel.dispatchEvent(new Event("change", { bubbles: true }));
  });

  console.log("3. Lưu cấu hình → bảng kê tự tính lại");
  await page.evaluate(() => { window.__coShellMarker = "alive"; });
  const responses = [];
  page.on("response", async (r) => {
    if (!r.url().includes("recommendation-override")) return;
    try { responses.push(await r.json()); } catch (_e) { /* ignore */ }
  });
  await page.evaluate(() => {
    const modal = document.querySelector("[data-origin-settings-modal]:not([hidden])");
    modal.querySelector('[data-criteria-seg="RVC"]').click();
    const thr = modal.querySelector("[data-origin-recommendation-threshold]");
    thr.value = "40"; thr.dispatchEvent(new Event("input", { bubbles: true }));
    modal.querySelector("[data-origin-recommendation-save]").click();
  });
  await page.waitForFunction(
    () => {
      const panel = [...document.querySelectorAll("[data-origin-sheet-panel]")].find((p) => !p.hidden);
      return /RVC/.test(panel?.querySelector("[data-origin-criteria-chip] strong")?.textContent || "");
    },
    { timeout: 180000 },
  ).catch(() => fail("chip Tiêu chí không đổi sang RVC"));
  const after = await sheetState(page);
  const survived = await page.evaluate(() => window.__coShellMarker || "");
  survived === "alive" ? ok("màn hình dựng lại tại chỗ, không F5") : fail("trang bị reload");
  responses.some((r) => r && r.recalculated === true)
    ? ok("server báo đã tính lại (recalculated=true)")
    : fail(`server không tính lại: ${JSON.stringify(responses)}`);
  after.status === "calculated"
    ? ok(`bảng kê ${after.code} vẫn ở "Đã tính" sau khi đổi tiêu chí`)
    : fail(`bảng kê ${after.code} rơi về trạng thái "${after.status}"`);
  /40/.test(after.lvc) ? ok(`ô LVC theo ngưỡng mới: ${after.lvc}`) : fail(`ô LVC chưa theo ngưỡng mới: ${after.lvc}`);
  await page.screenshot({ path: path.join(SHOTS, "03-luu-la-tu-tinh-lai.png") });

  console.log("4. Trả cấu hình về khuyến nghị");
  await openSettings(page);
  await page.evaluate(() => {
    document.querySelector("[data-origin-settings-modal]:not([hidden]) [data-origin-recommendation-reset]")?.click();
  });
  await page.waitForFunction(
    () => {
      const panel = [...document.querySelectorAll("[data-origin-sheet-panel]")].find((p) => !p.hidden);
      return !/RVC/.test(panel?.querySelector("[data-origin-criteria-chip] strong")?.textContent || "");
    },
    { timeout: 180000 },
  ).catch(() => fail("reset không trả tiêu chí về khuyến nghị"));
  ok("đã reset về khuyến nghị");

  if (errors.length) fail("console errors: " + errors.slice(0, 4).join(" | "));
  else ok("không có lỗi console");

  await browser.close();
  console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
})();
