// Chụp ảnh minh hoạ cho cẩm nang gộp CO + Data Hub tại
// `app/static/docs/huong-dan/index.html`. Mỗi ảnh mang KHUNG ĐỎ + SỐ THỨ TỰ do
// annotate() vẽ vào DOM trước khi chụp; số phải khớp <ol> bước của thẻ hướng dẫn
// tương ứng trong index.html. Cổng dev auth-off (CO :8001) + Data Hub :8754.
//
//   node .ai/features/2026-07-28-co-datahub-guide-site/shoot_guide.cjs
//
// Ảnh là SẢN PHẨM tài liệu → ghi cùng thư mục index.html (tham chiếu tương đối,
// copy sang host tĩnh khác là chạy). annotate() SOFT: selector trượt thì log cảnh
// báo, vẫn chụp — xem lại log + ảnh rồi siết selector.
const puppeteer = require("puppeteer");
const { mkdirSync } = require("fs");

const CO = "http://127.0.0.1:8001";
const DH = process.env.DH_BASE || "http://127.0.0.1:8754";
const DH_EMAIL = process.env.DH_EMAIL || "admin@data-hub.local";
const DH_PASSWORD = process.env.DH_PASSWORD || "admin123";
const CLIENT = "demo-furniture";
const EXPORTS = "105100100100, 105100100101"; // E42 → CHAIR01, TABLE01
const OUT =
  process.env.OUT ||
  "/home/vp/workspace/client/barry-CO-main/app/static/docs/huong-dan";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (m) => console.log(m);
const warns = [];

// Vẽ khung đỏ + badge số. marks: [selector, n] hoặc [selector, n, {pad, side}].
const ANNOTATE_JS = (marks) => {
  document.querySelectorAll(".g-anno").forEach((e) => e.remove());
  const layer = document.createElement("div");
  layer.className = "g-anno";
  Object.assign(layer.style, {
    position: "absolute", left: "0", top: "0", width: "0", height: "0",
    zIndex: "2147483000", pointerEvents: "none",
  });
  document.body.appendChild(layer);
  const br = document.body.getBoundingClientRect();
  const missing = [];
  for (const m of marks) {
    const el = document.querySelector(m.sel);
    if (!el) { missing.push(m.sel); continue; }
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) { missing.push(m.sel); continue; }
    const pad = m.pad === undefined ? 4 : m.pad;
    const box = document.createElement("div");
    Object.assign(box.style, {
      position: "absolute",
      left: r.left - br.left - pad + "px",
      top: r.top - br.top - pad + "px",
      width: r.width + pad * 2 + "px",
      height: r.height + pad * 2 + "px",
      border: "2.5px solid #e11d48", borderRadius: "8px",
      boxShadow: "0 0 0 2px rgba(255,255,255,.9)",
    });
    const tag = document.createElement("div");
    tag.textContent = m.n;
    const side = m.side || "left";
    Object.assign(tag.style, {
      position: "absolute", top: "-14px", [side]: "-14px",
      width: "27px", height: "27px", borderRadius: "50%",
      background: "#e11d48", color: "#fff",
      font: "700 15px/27px ui-sans-serif, system-ui, sans-serif",
      textAlign: "center", boxShadow: "0 1px 5px rgba(225,29,72,.55)",
    });
    box.appendChild(tag);
    layer.appendChild(box);
  }
  return missing;
};

async function annotate(page, marks, name) {
  const payload = marks.map((m) => ({
    sel: m[0], n: m[1], ...(m[2] || {}),
  }));
  const missing = await page.evaluate(ANNOTATE_JS, payload);
  if (missing.length) {
    warns.push(`${name}: selector trượt → ${missing.join(" | ")}`);
    log(`  ! ${name}: MISS ${missing.join(" | ")}`);
  }
}
async function clearAnno(page) {
  await page.evaluate(() =>
    document.querySelectorAll(".g-anno").forEach((e) => e.remove()),
  );
}
async function shot(page, name, full = false) {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
  await clearAnno(page);
  log(`  SHOT ${name}`);
}

// ── Data Hub ─────────────────────────────────────────────────────────────────
async function shootDataHub(page) {
  log("A. Data Hub");
  await page.goto(`${DH}/login`, { waitUntil: "networkidle0", timeout: 30000 });
  await annotate(page, [
    ['input[name="email"]', 1],
    ['input[name="password"]', 2],
    ['button[type="submit"], input[type="submit"]', 3, { side: "right" }],
  ], "dh-00-login");
  await shot(page, "dh-00-login");
  await page.type('input[name="email"]', DH_EMAIL);
  await page.type('input[name="password"]', DH_PASSWORD);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle0", timeout: 30000 }).catch(() => null),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
  if (/\/login/.test(page.url())) throw new Error("DH login FAILED");

  await page.goto(`${DH}/clients`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(500);
  await annotate(page, [
    [`a[href="/clients/${CLIENT}"]`, 1],
    ['a[href="/clients/new"]', 2, { side: "right" }],
  ], "dh-01-clients");
  await shot(page, "dh-01-clients", true);

  await page.goto(`${DH}/clients/${CLIENT}`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(400);
  await annotate(page, [[".client-tabs, .tabs", 1, { pad: 6 }]], "dh-02-overview");
  await shot(page, "dh-02-client-overview", true);

  const plain = [
    ["dh-03-catalog", `/clients/${CLIENT}/catalog`, [[".dh-table", 1, { pad: 6 }]]],
    ["dh-04-bcct", `/clients/${CLIENT}/bcct`, [[".dh-table", 1, { pad: 6 }]]],
    ["dh-05-bom", `/clients/${CLIENT}/bom`, [['a[href*="/bom/"]', 1]]],
    ["dh-06-bom-chair", `/clients/${CLIENT}/bom/CHAIR01/artifacts`, [['a[href*="/bom/artifact/"]', 1, { side: "right" }]]],
    ["dh-07-proposals", `/clients/${CLIENT}/proposals`, []],
  ];
  for (const [nm, path, marks] of plain) {
    try {
      const resp = await page.goto(`${DH}${path}`, { waitUntil: "networkidle0", timeout: 30000 });
      await sleep(500);
      if (marks.length) await annotate(page, marks, nm);
      await shot(page, nm, true);
      log(`    (${nm} http=${resp ? resp.status() : "?"})`);
    } catch (e) {
      warns.push(`${nm}: ${e.message}`);
      log(`  ! MISS ${nm} ${e.message}`);
    }
  }
}

// ── CO: drive one origin sheet ───────────────────────────────────────────────
async function driveSheet(page, caseId, sheet, capture) {
  await page.goto(`${CO}/clients/${CLIENT}/co-case/${caseId}/origin?sheet=${sheet}`, { waitUntil: "networkidle0", timeout: 60000 });
  await sleep(700);
  if (capture) {
    await annotate(page, [
      ["[data-origin-sheet-load-bom]", 1, { side: "right" }],
    ], "co-06-origin-sheets");
    await shot(page, "co-06-origin-sheets");
  }
  let r = page.waitForResponse((x) => /\/load-bom$/.test(x.url()), { timeout: 60000 }).catch(() => null);
  await page.click("[data-origin-sheet-load-bom]");
  await r; await sleep(1400);
  if (capture) {
    await annotate(page, [["[data-origin-sheet-calculate]", 1]], "co-07-load-bom");
    await shot(page, "co-07-load-bom");
  }
  r = page.waitForResponse((x) => /\/calculate$/.test(x.url()), { timeout: 60000 }).catch(() => null);
  await page.click("[data-origin-sheet-calculate]");
  await r; await sleep(1600);
  if (capture) {
    const lvc = await page.evaluate(() => (document.body.innerText.match(/LVC[^%]*?([\d.,]+)\s*%/) || [])[1] || "?");
    log(`  ${sheet} LVC=${lvc}`);
    await annotate(page, [
      [".origin-config-bar", 1, { pad: 6 }],
      ['button[formaction$="/lock"]', 2, { side: "right" }],
    ], "co-08-bang-ke-calculated");
    await shot(page, "co-08-bang-ke-calculated", true);
    try {
      const trig = await page.$("[data-origin-substitute-trigger]");
      if (trig) {
        await trig.click();
        await page.waitForSelector("[data-origin-substitute-modal]", { timeout: 8000 });
        await sleep(1000);
        await annotate(page, [["[data-origin-substitute-modal]", 1, { pad: 6 }]], "co-10-substitute-modal");
        await shot(page, "co-10-substitute-modal");
        await page.keyboard.press("Escape");
        await sleep(400);
      } else { warns.push("co-10: no substitute trigger"); }
    } catch (e) { warns.push(`co-10: ${e.message}`); }
  }
  const lockBtn = await page.$('button[formaction$="/lock"]');
  const enabled = lockBtn ? await page.evaluate((b) => !b.disabled, lockBtn) : false;
  if (process.env.NOLOCK) { log(`  ${sheet} NOLOCK → skip lock (btn enabled=${enabled})`); return false; }
  if (enabled) {
    r = page.waitForResponse((x) => /\/lock$/.test(x.url()), { timeout: 60000 }).catch(() => null);
    await page.click('button[formaction$="/lock"]');
    await r; await sleep(1400);
    if (capture) {
      await annotate(page, [[".origin-sheet-status-pill.origin-sheet-state-locked", 1, { side: "right" }]], "co-09-bang-ke-locked");
      await shot(page, "co-09-bang-ke-locked", true);
    }
    log(`  ${sheet} locked`);
    return true;
  }
  log(`  ${sheet} NOT lockable`);
  return false;
}

async function shootCO(page) {
  log("B. CO");
  // stock (materialize button)
  await page.goto(`${CO}/clients/${CLIENT}/co-stock`, { waitUntil: "networkidle0", timeout: 60000 });
  await sleep(600);
  await annotate(page, [["[data-co-stock-refresh-btn]", 1, { side: "right" }]], "co-13-co-stock");
  await shot(page, "co-13-co-stock", true);

  // CO clients
  await page.goto(`${CO}/clients`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(400);
  await annotate(page, [
    [`a[href="/clients/${CLIENT}"]`, 1],
  ], "co-01-clients");
  await shot(page, "co-01-clients", true);

  // case list + create modal
  await page.goto(`${CO}/clients/${CLIENT}/co-case`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(400);
  await annotate(page, [["[data-create-case-open]", 1, { side: "right" }]], "co-02-case-list");
  await shot(page, "co-02-case-list", true);

  await page.click("[data-create-case-open]");
  await sleep(500);
  await page.evaluate((exp) => {
    const modal = document.querySelector("[data-create-case-modal]");
    const set = (sel, v) => { const el = modal && modal.querySelector(sel); if (el) { el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); } };
    set('[name="destination_market"]', "Hàn Quốc");
    set('[name="export_declaration_nos"]', exp);
    set('[name="title"]', "Hồ sơ C/O mẫu — ghế & bàn gỗ");
  }, EXPORTS);
  await sleep(400);
  await annotate(page, [
    ['[data-create-case-modal] [name="export_declaration_nos"]', 1],
    ['[data-create-case-modal] [name="destination_market"]', 2],
    ['[data-create-case-modal] button[type="submit"]', 3, { side: "right" }],
  ], "co-03-create-modal");
  await shot(page, "co-03-create-modal");

  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle0", timeout: 60000 }).catch(() => null),
    page.click('[data-create-case-modal] button[type="submit"]'),
  ]);
  const caseId = (page.url().match(/co-case-[a-z0-9]+/) || [])[0];
  log(`NEW CASE = ${caseId}`);
  if (!caseId) throw new Error("create case failed");

  await sleep(800);
  await annotate(page, [[".workflow-stepper", 1, { pad: 6 }]], "co-04-case-overview");
  await shot(page, "co-04-case-overview", true);

  await page.goto(`${CO}/clients/${CLIENT}/co-case/${caseId}/documents`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(500);
  await shot(page, "co-05-documents", true);

  // drive CHAIR01 with captures; TABLE01 load+calc only (leave 1/2 locked)
  const locked = await driveSheet(page, caseId, "CHAIR01", true);
  if (!process.env.NOLOCK && locked) {
    try {
      await driveSheetNoLock(page, caseId, "TABLE01");
    } catch (e) {
      warns.push(`TABLE01 drive (non-fatal): ${e.message}`);
      log(`  ! TABLE01 drive skipped: ${e.message}`);
    }
    await page.goto(`${CO}/clients/${CLIENT}/co-case/${caseId}/origin`, { waitUntil: "networkidle0", timeout: 60000 });
    await sleep(800);
    await shot(page, "co-11-origin-all-locked", true);
    await page.goto(`${CO}/clients/${CLIENT}/co-case/${caseId}/exports`, { waitUntil: "networkidle0", timeout: 30000 });
    await sleep(500);
    await shot(page, "co-12-exports", true);
  }
  return caseId;
}

async function driveSheetNoLock(page, caseId, sheet) {
  await page.goto(`${CO}/clients/${CLIENT}/co-case/${caseId}/origin?sheet=${sheet}`, { waitUntil: "networkidle0", timeout: 60000 });
  await sleep(700);
  let r = page.waitForResponse((x) => /\/load-bom$/.test(x.url()), { timeout: 60000 }).catch(() => null);
  await page.click("[data-origin-sheet-load-bom]");
  await r; await sleep(1200);
  r = page.waitForResponse((x) => /\/calculate$/.test(x.url()), { timeout: 60000 }).catch(() => null);
  await page.click("[data-origin-sheet-calculate]");
  await r; await sleep(1400);
  log(`  ${sheet} loaded+calculated (left unlocked → 1/2)`);
}

async function dhLogin(page) {
  await page.goto(`${DH}/login`, { waitUntil: "networkidle0", timeout: 30000 });
  await page.type('input[name="email"]', DH_EMAIL);
  await page.type('input[name="password"]', DH_PASSWORD);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle0", timeout: 30000 }).catch(() => null),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
  if (/\/login/.test(page.url())) throw new Error("DH login FAILED");
}

// ── Data Hub: các trang NẠP DỮ LIỆU (GET forms — không ghi dữ liệu) ───────────
async function shootIngest(page) {
  log("A'. Data Hub — nạp dữ liệu");
  await dhLogin(page);
  const FILE = 'input[type="file"][name="file"]';
  // submit của form UPLOAD (đều là multipart) — tránh khớp nút btn-primary ở header
  const SUBMIT = 'form[enctype="multipart/form-data"] button[type="submit"], form[enctype="multipart/form-data"] button.btn-primary';
  const NEWSUBMIT = 'form[action$="/clients/new"] button[type="submit"], form[action$="/clients/new"] button.btn-primary, form[action$="/clients"] button.btn-primary';

  // 1. Tạo công ty mới — điền (không submit → không tạo)
  await page.goto(`${DH}/clients/new`, { waitUntil: "networkidle0", timeout: 30000 });
  await sleep(400);
  await page.evaluate(() => {
    const set = (s, v) => { const el = document.querySelector(s); if (el) { el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); } };
    set('input[name="name"]', "Demo Upload Co.");
    set('input[name="tax_code"]', "0312345678");
    const m = document.querySelector('select[name="code_resolution_mode"]');
    if (m) { m.value = m.options[Math.min(1, m.options.length - 1)].value; m.dispatchEvent(new Event("change", { bubbles: true })); }
  });
  await annotate(page, [
    ['input[name="name"]', 1],
    ['input[name="tax_code"]', 2],
    ['select[name="code_resolution_mode"]', 3],
    [NEWSUBMIT, 4, { side: "right" }],
  ], "dh-new-company");
  await shot(page, "dh-new-company", true);

  // 2..5 upload forms (GET — không ghi)
  const forms = [
    ["dh-catalog-upload", `/clients/${CLIENT}/catalog/upload`, [
      [FILE, 1], ['input[name="is_hq_registered"]', 2], [SUBMIT, 3, { side: "right" }],
    ]],
    ["dh-bqd-upload", `/clients/${CLIENT}/bqd/upload`, [
      [FILE, 1], [SUBMIT, 2, { side: "right" }],
    ]],
    ["dh-bcct-upload", `/clients/${CLIENT}/bcct/upload`, [
      [FILE, 1], [SUBMIT, 2, { side: "right" }],
    ]],
    ["dh-bom-upload", `/clients/${CLIENT}/bom/upload`, [
      ['select[name="profile"]', 1], [FILE, 2], [SUBMIT, 3, { side: "right" }],
    ]],
    ["dh-uploads", `/clients/${CLIENT}/uploads`, [
      ['.chip, [data-module-filter], nav a', 1, { pad: 6 }],
    ]],
  ];
  for (const [nm, path, marks] of forms) {
    try {
      const resp = await page.goto(`${DH}${path}`, { waitUntil: "networkidle0", timeout: 30000 });
      await sleep(400);
      await annotate(page, marks, nm);
      await shot(page, nm, true);
      log(`    (${nm} http=${resp ? resp.status() : "?"})`);
    } catch (e) { warns.push(`${nm}: ${e.message}`); log(`  ! MISS ${nm} ${e.message}`); }
  }
}

(async () => {
  mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  page.on("dialog", (d) => d.accept());
  try {
    if (process.env.INGEST) {
      await shootIngest(page);
    } else {
      if (process.env.ONLY !== "co") await shootDataHub(page);
      if (process.env.ONLY !== "dh") await shootCO(page);
    }
  } finally {
    await browser.close();
  }
  log("\n=== WARNINGS ===");
  if (warns.length) warns.forEach((w) => log("  - " + w));
  else log("  (none)");
  log(`done → ${OUT}`);
})().catch((e) => { console.error(e); process.exit(3); });
