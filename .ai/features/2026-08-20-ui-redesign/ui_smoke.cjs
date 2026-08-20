// Ảnh chứng minh cho vòng thiết kế lại giao diện CO (2026-08-20).
// Chỉ ĐỌC: đi qua danh sách trang cố định, chụp toàn trang, không bấm nút nào
// làm đổi dữ liệu (không load-bom, không calculate, không lock).
//
//   node .ai/features/2026-08-20-ui-redesign/ui_smoke.cjs
//
// Tên ảnh khớp bộ ảnh cẩm nang đang có ở app/static/docs/huong-dan/co-*.png để
// so được trước/sau theo từng cặp.
const puppeteer = require("puppeteer");
const { mkdirSync } = require("fs");
const { join } = require("path");

const CO = process.env.CO_BASE || "http://127.0.0.1:8001";
const CLIENT = process.env.CLIENT || "demo-furniture";
const OUT = join(__dirname, "screenshots");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const warns = [];

async function pickCaseId(page) {
  const r = await page.goto(`${CO}/clients/${CLIENT}/co-case`, {
    waitUntil: "networkidle0", timeout: 60000,
  });
  if (!r || r.status() >= 400) return null;
  return page.evaluate(() => {
    const a = document.querySelector('a[href*="/co-case/"]');
    if (!a) return null;
    const m = a.getAttribute("href").match(/\/co-case\/([^/?#]+)/);
    return m ? m[1] : null;
  });
}

(async () => {
  mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1560, height: 1000, deviceScaleFactor: 1 });

  const caseId = await pickCaseId(page);
  console.log(`case = ${caseId || "(none found)"}`);

  const pages = [
    ["co-01-clients", "/clients"],
    ["co-02-case-list", `/clients/${CLIENT}/co-case`],
    ["co-13-co-stock", `/clients/${CLIENT}/co-stock`],
    ["co-14-catalog", `/clients/${CLIENT}/catalog`],
    ["co-15-client-config", `/clients/${CLIENT}/config`],
    ["co-16-settings", "/settings"],
    ["co-17-bcct", `/clients/${CLIENT}/bcct`],
    ["co-18-bom", `/clients/${CLIENT}/bom`],
    ["co-19-suppliers", `/clients/${CLIENT}/suppliers`],
    ["co-20-cost-allocation", `/clients/${CLIENT}/cost-allocation`],
    ["co-21-fx", `/clients/${CLIENT}/customs-exchange-rates`],
  ];
  if (caseId) {
    pages.push(
      ["co-04-case-overview", `/clients/${CLIENT}/co-case/${caseId}`],
      ["co-05-documents", `/clients/${CLIENT}/co-case/${caseId}/documents`],
      ["co-06-origin-sheets", `/clients/${CLIENT}/co-case/${caseId}/origin`],
      ["co-11-review", `/clients/${CLIENT}/co-case/${caseId}/review`],
      ["co-12-exports", `/clients/${CLIENT}/co-case/${caseId}/exports`],
    );
  }

  for (const [name, path] of pages) {
    try {
      const resp = await page.goto(`${CO}${path}`, {
        waitUntil: "networkidle0", timeout: 60000,
      });
      await sleep(500);
      await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
      console.log(`  SHOT ${name} http=${resp ? resp.status() : "?"}`);
    } catch (e) {
      warns.push(`${name}: ${e.message}`);
      console.log(`  ! MISS ${name} ${e.message}`);
    }
  }

  await browser.close();
  if (warns.length) {
    console.log("\nCẢNH BÁO:");
    warns.forEach((w) => console.log("  - " + w));
  }
  console.log(`\nẢnh ở ${OUT}`);
})();
