// Screenshot walk-through of everything changed in the last two working sessions
// (2026-08-17/18 + 2026-08-19), into ONE folder.
//
//   set -a; . ./.env; set +a
//   CLIENT=johnson-vn CASE=co-case-e0b390ead3b0 node .ai/scripts/e2e_shots_two_sessions.cjs
//
// Read-only on the ledger: it never clicks Chốt / Chốt tất cả / Tính. The one
// persisted change is the lô-hàng criterion, which the run sets and then clears,
// leaving the case as it found it.
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer");

const BASE = process.env.BASE || "http://127.0.0.1:8001";
const CLIENT = process.env.CLIENT || "johnson-vn";
const CASE = process.env.CASE || "co-case-e0b390ead3b0";
const OUT = path.join(__dirname, "..", "screenshots", "2026-08-19-e2e-2-sessions");

const captions = [];
let n = 0;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  page.on("dialog", async (d) => await d.accept());

  const shot = async (slug, caption, selector) => {
    n += 1;
    const file = `${String(n).padStart(2, "0")}-${slug}.png`;
    const target = selector ? await page.$(selector) : page;
    if (!target) { console.log(`  SKIP ${file} — no ${selector}`); return; }
    if (selector) await page.evaluate((s) => document.querySelector(s)?.scrollIntoView({ block: "center" }), selector);
    await target.screenshot({ path: path.join(OUT, file) });
    captions.push(`| \`${file}\` | ${caption} |`);
    console.log(`  ${file}`);
  };
  const goOrigin = async () => {
    await page.goto(`${BASE}/clients/${CLIENT}/co-case/${CASE}/origin`, { waitUntil: "networkidle2", timeout: 240000 });
  };

  await goOrigin();

  // --- 2026-08-17/18 + 2026-08-19: the criterion must be a person's choice -----
  console.log("A. Tiêu chí");
  await shot("tieu-chi-chua-chon-khong-chot-duoc",
    "Chưa chọn tiêu chí: thanh 'Tiêu chí cho cả lô' ở trạng thái cảnh báo và ghi rõ N bảng kê không chốt được (3e41f24 + 2c25147).",
    ".origin-review-toolbar, .origin-case-criteria");
  await shot("thanh-tieu-chi-ca-lo",
    "Thanh tiêu chí cho cả lô, trạng thái 'chưa chọn'.", "[data-origin-case-criteria]");

  await page.click("[data-origin-case-criteria-edit]");
  await page.waitForSelector("[data-case-criteria-modal]:not([hidden])", { timeout: 10000 });
  await page.click('[data-case-criteria-panel] [data-criteria-seg="CTH"]');
  await shot("tieu-chi-modal-chon-bang-nut",
    "MỚI (2026-08-19): chọn tiêu chí bằng nút WO/PE/CC/CTH/CTSH/RVC/LVC/PSR + 'Khác…' + hàng 'hoặc', thay cho ô nhập tay window.prompt (812eb0b).",
    "[data-case-criteria-modal] .origin-settings-dialog");
  await page.click('[data-case-criteria-panel] [data-criteria-seg="RVC"]');
  await page.type("[data-case-criteria-panel] [data-origin-recommendation-threshold]", "40");
  await shot("tieu-chi-rvc-hien-nguong",
    "Ô 'Ngưỡng %' chỉ hiện với tiêu chí xét hàm lượng giá trị (RVC/LVC); CTH/WO thì ẩn.",
    "[data-case-criteria-modal] .origin-settings-dialog");
  await page.click('[data-case-criteria-panel] [data-criteria-seg="CTH"]');
  await page.evaluate(() => { window.__coShellMarker = "alive"; });
  await page.click("[data-case-criteria-save]");
  await page.waitForFunction(
    () => /CTH/.test(document.querySelector("[data-origin-case-criteria-value]")?.textContent || ""),
    { timeout: 120000 },
  );
  const survived = await page.evaluate(() => window.__coShellMarker || "");
  console.log(`  (no-F5 check: JS context ${survived === "alive" ? "survived" : "LOST"})`);
  await shot("luu-tieu-chi-khong-can-f5",
    `MỚI (2026-08-19): sau khi Lưu, màn hình tự dựng lại tại chỗ — không reload (JS context ${survived === "alive" ? "còn nguyên" : "mất"}). Thanh tiêu chí và trạng thái các sheet cập nhật ngay (812eb0b).`,
    ".origin-review-toolbar, .origin-case-criteria");
  await shot("cac-sheet-thua-huong-tieu-chi",
    "Mỗi bảng kê hiển thị 'tiêu chí: theo lô hàng' — thừa hưởng lựa chọn của cả lô, vẫn ghi đè riêng được.",
    ".origin-review-table");

  // --- sheet view: chip, money lanes, rounding ---------------------------------
  console.log("B. Bảng kê con");
  await page.evaluate(() => document.querySelector("[data-origin-drill]")?.click());
  await page.waitForSelector("[data-origin-sheet-panel] [data-origin-strip]", { timeout: 120000 });
  await shot("chip-tieu-chi-trong-o-rieng",
    "2026-08-17 (e5d31b3): chip 'Tiêu chí' nằm trong ô riêng trên thanh số liệu, cạnh LVC và CTC — hai ô này chỉ là đối chiếu tham khảo CỦA tiêu chí đó.",
    "[data-origin-sheet-panel]:not([hidden]) .origin-config-metrics");
  await shot("luoi-bang-ke-nguyen-te",
    "2026-08-17/18 (e00f174 → 240a9d8): cột Đơn giá / Trị giá NVL đọc theo NGUYÊN TỆ của lô, kèm nhãn tiền tệ trên từng dòng. Hồ sơ local này khai toàn bộ 534 dòng bằng VND nên hai làn trùng nhau; làn USD đã kiểm trên prod VNG26030107.",
    "[data-origin-sheet-panel]:not([hidden]) .origin-table-scroll");

  await page.evaluate(() => {
    const panel = [...document.querySelectorAll("[data-origin-sheet-panel]")].find((p) => !p.hidden);
    panel?.querySelector("[data-origin-settings-open]")?.click();
  });
  await page.waitForSelector("[data-origin-settings-modal]:not([hidden])", { timeout: 10000 });
  await shot("cau-hinh-bang-ke-tien-te",
    "2026-08-17/18 (240a9d8): mỗi bảng kê tự chọn TIỀN TỆ (Nguyên tệ / VND) và chiều tối ưu; mọi lô đều mang hai làn tiền nên đổi qua lại không phải tính lại.",
    "[data-origin-settings-modal]:not([hidden]) .origin-settings-dialog");

  await page.evaluate(() => document.querySelector("[data-origin-settings-modal]:not([hidden])")?.setAttribute("hidden", ""));
  await page.evaluate(() => {
    const panel = [...document.querySelectorAll("[data-origin-sheet-panel]")].find((p) => !p.hidden);
    panel?.querySelector("[data-allocation-toggle]")?.click();
  });
  await new Promise((r) => setTimeout(r, 800));
  // A lot row on its own is a thin strip; capture the NVL row together with the lot
  // rows it expanded to, so the pairing is visible.
  const lotClip = await page.evaluate(() => {
    const panel = [...document.querySelectorAll("[data-origin-sheet-panel]")].find((p) => !p.hidden);
    const detail = panel?.querySelector("[data-origin-allocation-row]:not([hidden])");
    if (!detail) return null;
    const group = detail.getAttribute("data-allocation-group");
    const rows = [...panel.querySelectorAll(`[data-allocation-group="${group}"]`)].filter((r) => !r.hidden);
    if (!rows.length) return null;
    rows[0].scrollIntoView({ block: "center" });
    const boxes = rows.map((r) => r.getBoundingClientRect());
    const top = Math.min(...boxes.map((b) => b.top));
    const bottom = Math.max(...boxes.map((b) => b.bottom));
    const left = Math.min(...boxes.map((b) => b.left));
    const right = Math.max(...boxes.map((b) => b.right));
    return { x: Math.max(0, left - 4), y: Math.max(0, top - 4), width: right - left + 8, height: bottom - top + 8 };
  });
  if (lotClip && lotClip.height > 0) {
    n += 1;
    const file = `${String(n).padStart(2, "0")}-dong-ton-cua-mot-nvl.png`;
    await page.screenshot({ path: path.join(OUT, file), clip: lotClip });
    captions.push(`| \`${file}\` | 2026-08-17/18 (240a9d8): mở một dòng NVL ra thấy từng dòng tồn (tờ khai nhập, số lượng, đơn giá, NT) — mỗi lô mang cả hai làn tiền, nên đổi Tiền tệ ở ⚙ Cấu hình không phải tính lại. |`);
    console.log(`  ${file}`);
  }
  await shot("don-gia-lam-tron-6-so",
    "2026-08-18 (efbdc31): đơn giá quy đổi theo tỷ giá được làm tròn 6 chữ số thập phân (trước đây in ra 28 chữ số).",
    "[data-origin-sheet-panel]:not([hidden]) .origin-material-table");

  // --- ĐVT ---------------------------------------------------------------------
  console.log("C. ĐVT");
  const realUomButton = await page.$("[data-origin-uom-confirm]");
  if (realUomButton) {
    await page.evaluate(() => document.querySelector("[data-origin-uom-confirm]")?.click());
  } else {
    await page.evaluate(() => {
      const m = document.querySelector("[data-uom-factor-modal]");
      m.dataset.materialCode = "1000096510"; m.dataset.bomUom = "EA"; m.dataset.lotUom = "CAY";
      m.querySelectorAll("[data-uom-factor-material]").forEach((e) => e.textContent = "1000096510");
      m.querySelectorAll("[data-uom-factor-bom-uom]").forEach((e) => e.textContent = "EA");
      m.querySelectorAll("[data-uom-factor-lot-uom]").forEach((e) => e.textContent = "CAY");
      m.removeAttribute("hidden");
    });
  }
  await page.waitForSelector("[data-uom-factor-modal]:not([hidden])", { timeout: 10000 });
  await shot("he-so-quy-doi-dvt-modal",
    `MỚI (2026-08-19): xác nhận hệ số ĐVT trong cửa sổ — một câu hỏi "1 CAY = mấy EA" + chọn phạm vi (chỉ mã này / mọi mã có cặp EA→CAY), thay cho window.prompt luôn ghi phạm vi "chỉ mã này"${realUomButton ? "" : ". (Dữ liệu local hiện không còn cặp ĐVT khác đại lượng nào nên cửa sổ được mở trực tiếp để chụp.)"}`,
    "[data-uom-factor-modal] .origin-settings-dialog");
  await page.evaluate(() => document.querySelector("[data-uom-factor-modal]")?.setAttribute("hidden", ""));

  // --- substitute search --------------------------------------------------------
  console.log("D. Tìm NVL thay thế");
  await page.waitForSelector("[data-origin-substitute-trigger]", { timeout: 60000 });
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll("[data-origin-substitute-trigger]")].find((b) => b.offsetParent !== null)
      || document.querySelector("[data-origin-substitute-trigger]");
    btn.scrollIntoView({ block: "center" });
    btn.click();
  });
  await page.waitForSelector("[data-origin-substitute-modal]:not([hidden])", { timeout: 60000 });
  const search = async (query) => {
    await page.evaluate(() => [...document.querySelectorAll("[data-origin-substitute-tab-trigger]")]
      .find((x) => x.dataset.originSubstituteTabTrigger === "search")?.click());
    await page.evaluate(() => { const i = document.querySelector("[data-origin-substitute-search]"); i.value = ""; });
    await page.type("[data-origin-substitute-search]", query);
    await page.click("[data-origin-substitute-search-button]");
    await page.waitForFunction(() => {
      const c = document.querySelector('[data-origin-substitute-list="search"] .origin-substitute-stock-summary');
      return c && !/—/.test(c.textContent) && !/^0 /.test(c.textContent.trim());
    }, { timeout: 240000 }).catch(() => console.log("    (tồn chưa merge kịp)"));
  };
  await search("bu lông");
  const count1 = await page.$eval("[data-origin-substitute-search-count]", (e) => e.textContent.trim());
  await shot("tim-nvl-day-du-co-ton",
    `MỚI (2026-08-19): tìm "bu lông" ra ĐỦ mọi cách viết (Bu lông… / Bộ bu lông… / Bộ ốc vít, bu lông…) — ${count1} Trước đây trần là 20 mã.`,
    "[data-origin-substitute-modal] .origin-substitute-modal-card");
  await search("bu long");
  const count2 = await page.$eval("[data-origin-substitute-search-count]", (e) => e.textContent.trim());
  await shot("tim-nvl-khong-dau",
    `Gõ KHÔNG DẤU cũng ra đúng ngần ấy mã — ${count2}`,
    "[data-origin-substitute-modal] .origin-substitute-modal-card");
  await page.evaluate(() => document.querySelector("[data-origin-substitute-modal]")?.setAttribute("hidden", ""));

  // --- review ------------------------------------------------------------------
  // The "Tổng hợp NVL" panel is deliberately not shot: it only fills after a
  // whole-case run, which takes over 10 minutes on this dataset locally. The defect
  // it exposed (aggregate said đủ tồn while sheets said "Cần tính lại") is pinned by
  // tests/test_bulk_recalc_downstream_sheets.py instead.
  console.log("E. Review");
  await goOrigin();
  await shot("review-tat-ca-da-tinh",
    "Danh sách bảng kê: không sheet nào còn nằm ở 'Cần tính lại', và mỗi dòng ghi rõ tiêu chí đang theo lô hàng — trước 2026-08-19 dòng nào cũng ghi 'tiêu chí: khuyến nghị' dù lô đã chọn.",
    ".origin-review-table");

  // --- clear the criterion (also proves it persists) ----------------------------
  console.log("F. Bỏ chọn");
  await page.click("[data-origin-case-criteria-clear]");
  await page.waitForFunction(
    () => document.querySelector("[data-origin-case-criteria]")?.classList.contains("origin-case-criteria-unset"),
    { timeout: 120000 },
  );
  await page.reload({ waitUntil: "networkidle2", timeout: 240000 });
  await shot("bo-chon-tieu-chi-luu-that",
    "MỚI (2026-08-19): 'Bỏ chọn' nay thật sự xoá lựa chọn — ảnh này chụp SAU khi F5. Trước đây tiêu chí cũ quay lại vì route pop key khỏi dict mà update_case_record chỉ ghi các key có mặt (812eb0b).",
    "[data-origin-case-criteria]");

  fs.writeFileSync(path.join(OUT, "README.md"),
    `# Ảnh e2e — thay đổi của 2 session gần nhất\n\n` +
    `Chụp trên \`${BASE}\`, khách \`${CLIENT}\`, hồ sơ \`${CASE}\` (dữ liệu Johnson thật, local).\n` +
    `Sinh bằng \`.ai/scripts/e2e_shots_two_sessions.cjs\`. Không bấm Tính / Chốt / Chốt tất cả;\n` +
    `thay đổi duy nhất có ghi xuống là tiêu chí của lô, đã được bỏ chọn lại ở bước cuối.\n\n` +
    `**Giới hạn của dữ liệu local:** mọi lô của hồ sơ này khai bằng VND và không còn cặp ĐVT khác\n` +
    `đại lượng nào, nên làn tiền USD (\`e00f174\`/\`240a9d8\`) và nút "Cần hệ số" trên dòng không\n` +
    `xuất hiện được ở đây; hai thứ đó đã kiểm trên prod VNG26030107. Bảng 'Tổng hợp NVL'\n` +
    `chỉ có dữ liệu sau một lượt tính cả lô — trên máy local lượt đó chạy quá 10 phút nên\n` +
    `không chụp; phần sửa của nó được chốt bằng \`tests/test_bulk_recalc_downstream_sheets.py\`.\n\n` +
    `## Session 2026-08-17 → 2026-08-18\n` +
    `\`3e41f24\` tiêu chí là lựa chọn tường minh · \`e00f174\` bảng kê nộp theo tiền tệ hoá đơn (về sau \`240a9d8\` thay bằng hai làn tiền, chọn theo bảng kê) ·\n` +
    `\`e5d31b3\` chip Tiêu chí có ô riêng · \`240a9d8\` hai làn tiền trên mọi lô, tiền tệ chọn theo bảng kê ·\n` +
    `\`2c25147\` quy đổi ĐVT tại dòng + bắt buộc chọn tiêu chí trước khi Chốt ·\n` +
    `\`5f6a065\` sheet cũ lấy lại làn hoá đơn khi tính lại · \`efbdc31\` làm tròn đơn giá quy đổi tỷ giá\n\n` +
    `## Session 2026-08-19\n` +
    `\`812eb0b\` sáu lỗi khách báo · \`aad9493\` test phạm vi hệ số ĐVT · \`698fbda\` tồn "—" khi đang tải ·\n` +
    `\`6d89aea\` changelog 0.17.0 + yêu cầu API ĐVT gửi Data Hub\n\n` +
    `| Ảnh | Nội dung |\n| --- | --- |\n${captions.join("\n")}\n`,
    "utf-8");

  await browser.close();
  console.log(`\n${n} ảnh trong ${OUT}`);
})();
