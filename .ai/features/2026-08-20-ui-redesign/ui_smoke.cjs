// Ảnh chứng minh cho vòng thiết kế lại giao diện Data Hub (2026-08-20).
// Chỉ ĐỌC: đăng nhập, đi qua danh sách trang cố định, chụp toàn trang, không
// tải tệp lên, không duyệt đề xuất, không sửa dữ liệu.
//
//   NODE_PATH=/home/vp/workspace/client/barry-CO-main/node_modules \
//     node .ai/features/2026-08-20-ui-redesign/ui_smoke.cjs
//
// Tên ảnh khớp bộ ảnh cẩm nang đang có (dh-*.png) để so trước/sau theo cặp.
const puppeteer = require("puppeteer");
const { mkdirSync } = require("fs");
const { join } = require("path");

const DH = process.env.DH_BASE || "http://127.0.0.1:8754";
const EMAIL = process.env.DH_EMAIL || "admin@data-hub.local";
const PASSWORD = process.env.DH_PASSWORD || "admin123";
const CLIENT = process.env.CLIENT || "demo-furniture";
const OUT = join(__dirname, "screenshots");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const warns = [];

(async () => {
  mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1560, height: 1000, deviceScaleFactor: 1 });

  await page.goto(`${DH}/login`, { waitUntil: "networkidle0", timeout: 30000 });
  await page.screenshot({ path: `${OUT}/dh-00-login.png`, fullPage: true });
  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle0", timeout: 30000 }).catch(() => null),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
  if (/\/login/.test(page.url())) throw new Error("đăng nhập Data Hub THẤT BẠI");

  const pages = [
    ["dh-01-clients", "/clients"],
    ["dh-02-client-overview", `/clients/${CLIENT}`],
    ["dh-03-catalog", `/clients/${CLIENT}/catalog`],
    ["dh-04-bcct", `/clients/${CLIENT}/bcct`],
    ["dh-05-bom", `/clients/${CLIENT}/bom`],
    ["dh-07-proposals", `/clients/${CLIENT}/proposals`],
    ["dh-08-declarations", `/clients/${CLIENT}/declarations`],
    ["dh-09-uploads", `/clients/${CLIENT}/uploads`],
    ["dh-10-catalog-upload", `/clients/${CLIENT}/catalog/upload`],
    ["dh-11-admin-users", "/admin/users"],
    ["dh-12-jobs", "/jobs"],
  ];

  for (const [name, path] of pages) {
    try {
      const resp = await page.goto(`${DH}${path}`, {
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
