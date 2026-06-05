const { chromium } = require("playwright");
const { mkdirSync } = require("fs");

const BASE = "https://barry-co.tinsu.ai";
const CID = "growatt-vn";
const EMAIL = "claude-check@local";
const PASSWORD = "claude-temp-2026";
const SHOTDIR = ".ai/screenshots/refactor-e2e-prod";

(async () => {
  mkdirSync(SHOTDIR, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();

  // --- SSO login ---
  await page.goto(`${BASE}/clients`, { waitUntil: "domcontentloaded", timeout: 45000 });
  // we should now be on the Data Hub SSO login page
  await page.waitForSelector("input[name=email]", { timeout: 20000 });
  await page.fill("input[name=email]", EMAIL);
  await page.fill("input[name=password]", PASSWORD);
  await page.screenshot({ path: `${SHOTDIR}/00-login.png` });
  await Promise.all([
    page.waitForLoadState("networkidle", { timeout: 45000 }),
    page.click('button:has-text("Đăng nhập"), input[type=submit]'),
  ]);
  const afterLogin = page.url();
  const loggedIn = !/login|auth/.test(afterLogin) || afterLogin.includes("barry-co");
  console.log(`after login url: ${afterLogin}`);
  if (/email|password/.test(await page.content()) && /login/i.test(page.url())) {
    console.log("LOGIN FAILED — still on login page");
    await page.screenshot({ path: `${SHOTDIR}/00-login-failed.png` });
    await browser.close(); process.exit(2);
  }

  // discover a case id from the co-case list
  await page.goto(`${BASE}/clients/${CID}/co-case`, { waitUntil: "domcontentloaded", timeout: 45000 });
  const hrefs = await page.locator('a[href*="/co-case/co-case-"]').evaluateAll((els) => els.map((e) => e.getAttribute("href")));
  const m = (hrefs.find(Boolean) || "").match(/co-case-[a-f0-9]+/);
  const CASE = m ? m[0] : null;
  console.log(`discovered case: ${CASE}`);

  const pages = [
    ["root", "/"],
    ["clients", "/clients"],
    ["workspace", `/clients/${CID}`],
    ["catalog", `/clients/${CID}/catalog`],
    ["catalog-materials", `/clients/${CID}/catalog/materials`],
    ["bom", `/clients/${CID}/bom`],
    ["bcct", `/clients/${CID}/bcct`],
    ["co-stock", `/clients/${CID}/co-stock`],
    ["cost-allocation", `/clients/${CID}/cost-allocation`],
    ["config", `/clients/${CID}/config`],
    ["co-case-list", `/clients/${CID}/co-case`],
    ...(CASE ? [["co-case-detail", `/clients/${CID}/co-case/${CASE}`], ["co-case-origin", `/clients/${CID}/co-case/${CASE}/origin`]] : []),
    ["customs-fx", `/customs-exchange-rates`],
    ["settings", `/settings`],
    ["co-forms", `/settings/co-forms`],
    ["user", `/user`],
  ];

  const results = [];
  for (const [name, path] of pages) {
    let status = 0, ok = false, note = "";
    try {
      const resp = await page.goto(BASE + path, { waitUntil: "domcontentloaded", timeout: 45000 });
      status = resp ? resp.status() : 0;
      const body = await page.content();
      const traceback = /Traceback \(most recent call last\)|Internal Server Error/.test(body);
      const isLogin = /name=.?password/.test(body) && /\/auth/.test(page.url());
      ok = status === 200 && !traceback && !isLogin;
      if (traceback) note = "TRACEBACK";
      else if (isLogin) note = "BOUNCED TO LOGIN";
      if (name === "co-case-origin") {
        const panels = await page.locator("[data-origin-sheet-panel]").count();
        const trig = await page.locator("[data-origin-substitute-trigger]").count();
        note = `sheet-panels=${panels} substitute-triggers=${trig}`;
      }
      await page.screenshot({ path: `${SHOTDIR}/${name}.png` });
    } catch (e) { note = "ERR " + e.message.split("\n")[0]; }
    results.push({ name, status, ok, note });
    console.log(`${ok ? "PASS" : "FAIL"}  ${String(status).padEnd(3)}  ${name.padEnd(20)} ${note}`);
  }

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n=== ${results.length - failed.length}/${results.length} passed (prod) ===`);
  process.exit(failed.length ? 1 : 0);
})();
