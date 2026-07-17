// Re-shoot co-01: CO clients page focused on the demo company (hide other cards).
const puppeteer = require("puppeteer");
const BASE = "http://127.0.0.1:8001";
const OUT = "/home/vp/workspace/client/barry-CO-main/docs/huong-dan-su-dung/images";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 760 });
  await page.goto(`${BASE}/clients`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(500);
  const kept = await page.evaluate(() => {
    let kept = 0;
    document.querySelectorAll(".client-card").forEach((card) => {
      const a = card.matches("a[href]") ? card : card.querySelector("a[href]");
      const href = card.getAttribute("href") || (a && a.getAttribute("href")) || "";
      if (href.endsWith("/clients/demo-furniture")) { kept++; } else { card.style.display = "none"; }
    });
    return kept;
  });
  console.log(`kept ${kept} card(s)`);
  await sleep(300);
  await page.screenshot({ path: `${OUT}/co-01-clients.png` }); // viewport only — short + clean
  console.log("SHOT co-01-clients (focused)");
  await browser.close();
})().catch((e) => { console.error(e); process.exit(3); });
