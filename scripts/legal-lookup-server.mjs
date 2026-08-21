import http from "node:http";
import { createReadStream, promises as fs } from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { URL } from "node:url";

import { buildVntrSearchUrl } from "./lib/legal-official-source-resolution.mjs";

const ROOT = process.cwd();
const PORT = Number(process.env.PORT || 4173);
const HOST = process.env.HOST || "127.0.0.1";

const REGISTRY_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "text-source-registry.json");
const CANONICAL_INDEX_PATH = path.join(ROOT, "docs", "legal", "indexes", "canonical-pilot.md");
const LOOKUP_DOC_PATH = path.join(ROOT, "docs", "legal", "reference", "co-legal-lookup-system.md");
const LEGAL_README_PATH = path.join(ROOT, "docs", "legal", "README.md");
const WIKI_DIR = path.join(ROOT, "docs", "legal", "wiki");
const CANONICAL_DIR = path.join(ROOT, "docs", "legal", "canonical", "pilot");
const ATTACHMENTS_DIR = path.join(ROOT, "data", "legal", "normalized", "ecosys", "attachments");
const SUPPORTED_LOCALES = new Set(["vi", "en"]);

const I18N = {
  vi: {
    htmlLang: "vi",
    brand: "Kho văn bản",
    navCorpus: "Danh sách",
    navCanonical: "Bản sạch",
    navLookup: "Hệ tra cứu",
    navWorkspace: "Ghi chú",
    tabCorpus: "Văn bản",
    tabPilot: "Pilot",
    tabModel: "Mô hình",
    surfaceMeta: "không gian vận hành pháp lý",
    homeTitle: "Kho văn bản C/O",
    homeSubtitle: "Mở nhanh từng văn bản, kiểm tra nguồn đang hiển thị, và theo dõi tình trạng làm sạch corpus.",
    searchTitle: "Tìm nhanh",
    searchPlaceholder: "Số văn bản, tiêu đề, nguồn, chất lượng...",
    searchButton: "Tìm",
    searchHelp: "Ưu tiên quét nhanh theo số văn bản, tiêu đề, nguồn đang dùng, và chất lượng dữ liệu.",
    searchPageTitle: "Tra cứu văn bản",
    searchPageSubtitle: "Lọc nhanh theo số văn bản, tiêu đề, nguồn render, và chất lượng dữ liệu.",
    corpusSummary: "Tình trạng corpus",
    corpusTable: "Danh sách văn bản",
    corpusTableHelp: "Bấm vào số văn bản để mở thẳng trang đọc tương ứng.",
    contentCoverage: "Lớp đang hiển thị",
    totalDocuments: "Tổng văn bản",
    preferredOfficialText: "Official text ưu tiên",
    preferredOcrRecovery: "OCR đang dùng",
    temporaryExtraction: "eCoSys extraction tạm",
    officialHtml: "Official HTML/text",
    officialPdfText: "Official PDF text",
    officialPdfScan: "Official PDF scan",
    officialLegacyBinary: "Official legacy binary",
    canonicalPilot: "Canonical pilot",
    officialMarkdown: "Official markdown",
    wikiFallback: "Wiki fallback",
    source: "Nguồn",
    quality: "Chất lượng",
    group: "Nhóm / form",
    issueCode: "Số văn bản",
    title: "Tiêu đề",
    issuedDate: "Ngày ban hành",
    issuer: "Cơ quan",
    renderedFrom: "Render từ",
    viewingFrom: "Đang xem từ",
    qualityState: "Chất lượng",
    open: "Mở",
    openDocument: "Xem",
    documentDetailTitle: "Kiểm tra nguồn render và tình trạng dữ liệu của văn bản này.",
    metadata: "Thông tin chính",
    backToCorpus: "Danh sách văn bản",
    pilotIndex: "Bản sạch",
    lookupSystem: "Hệ tra cứu",
    legalWorkspace: "Ghi chú nguồn",
    markdownReference: "Tài liệu tham chiếu trong cùng legal workspace.",
    markdownLabel: "Markdown reference",
    sourcePath: "Source Path",
    sourceCompare: "Nguồn gốc",
    sourceCompareHelp: "Giữ các nguồn cần đối chiếu trực tiếp: toàn văn chính thức, eCoSys, và file mirror gốc.",
    sourceLegend: "Nhãn nguồn luôn đi theo nguồn và loại text đang render: VBPL/VNTR/TVPL HTML, eCoSys DOCX, eCoSys PDF, eCoSys PDF OCR, hoặc eCoSys MIX (DOCX + PDF). RAR/ZIP chỉ là container trung gian nên không hiện như một lane riêng.",
    officialTextPage: "Trang toàn văn chính thức",
    officialSearchPage: "Trang tra cứu chính thức",
    rawBinaryFile: "File mirror nội bộ",
    mirrorAttachments: "File con mirror local",
    ecosysListing: "Trang danh sách eCoSys",
    ecosysFileUrl: "URL file gốc eCoSys",
    openSource: "Mở nguồn",
    openExternal: "Mở ngoài",
    downloadSource: "Tải file",
    appendixStatusTitle: "Trạng thái dữ liệu phụ lục",
    appendixStatusWarning: "Các bảng dưới đây đang lấy từ extraction cache của file nhị phân để đối chiếu. Chúng vẫn còn noise xuống dòng/ngắt trang, nên chưa thể coi là bảng chuẩn hóa sẵn cho database.",
    appendixStatusClean: "Các phụ lục dưới đây đã được ghép từ text cache hiện có. Vẫn nên đối chiếu với nguồn gốc trước khi chuẩn hóa vào database.",
    notFound: "Không tìm thấy",
    serverError: "Lỗi server",
    serverErrorMeta: "Render layer của legal viewer gặp lỗi.",
    unknown: "Không rõ",
    notResolved: "Chưa resolve",
    notAvailable: "Không có",
    noMajorIssues: "Chưa thấy lỗi extraction lớn.",
    metadataLabels: {
      issueCode: "Số văn bản",
      title: "Tiêu đề",
      issuedDate: "Ngày ban hành",
      issuingUnit: "Cơ quan ban hành",
      formType: "Nhóm / form",
      discoveryFeed: "Discovery feed",
      discoveredFrom: "Nguồn phát hiện",
      mirroredBinary: "Binary mirror",
      preferredTextSource: "Preferred text source",
      sourceClassification: "Source classification",
      extractionQuality: "Extraction quality",
      extractionIssues: "Extraction issues",
      renderedFrom: "Rendered from",
      renderedMarkdownPath: "Rendered markdown path",
      officialTextPage: "Official text page",
      officialMarkdownCache: "Official markdown cache",
      ocrCache: "OCR cache",
      rawExtractionCache: "Raw extraction cache",
      binaryMirrorPath: "Binary mirror path",
      binaryFileType: "Binary file type",
      binaryFileSize: "Binary file size",
    },
  },
  en: {
    htmlLang: "en",
    brand: "Legal Corpus",
    navCorpus: "Documents",
    navCanonical: "Clean Texts",
    navLookup: "Lookup",
    navWorkspace: "Notes",
    tabCorpus: "Corpus",
    tabPilot: "Pilot",
    tabModel: "Model",
    surfaceMeta: "legal operating surface",
    homeTitle: "CO Legal Corpus",
    homeSubtitle: "Open documents fast, check the active render source, and track corpus cleanup status.",
    searchTitle: "Quick Search",
    searchPlaceholder: "Issue code, title, source, quality...",
    searchButton: "Search",
    searchHelp: "Optimized for scan speed by issue code, title, active source, and data quality.",
    searchPageTitle: "Document Search",
    searchPageSubtitle: "Filter quickly by issue code, title, render source, and data quality.",
    corpusSummary: "Corpus Status",
    corpusTable: "Document List",
    corpusTableHelp: "Click an issue code to open the reading surface for that document.",
    contentCoverage: "Active Render Layers",
    totalDocuments: "Total documents",
    preferredOfficialText: "Preferred official text",
    preferredOcrRecovery: "OCR in use",
    temporaryExtraction: "Temporary eCoSys extraction",
    officialHtml: "Official HTML/text",
    officialPdfText: "Official PDF text",
    officialPdfScan: "Official PDF scan",
    officialLegacyBinary: "Official legacy binary",
    canonicalPilot: "Canonical pilot",
    officialMarkdown: "Official markdown",
    wikiFallback: "Wiki fallback",
    source: "Source",
    quality: "Quality",
    group: "Group / form",
    issueCode: "Issue code",
    title: "Title",
    issuedDate: "Issued date",
    issuer: "Issuing unit",
    renderedFrom: "Rendered from",
    viewingFrom: "Viewing from",
    qualityState: "Quality",
    open: "Open",
    openDocument: "Open",
    documentDetailTitle: "Inspect the active render source and data condition for this document.",
    metadata: "Key details",
    backToCorpus: "Documents list",
    pilotIndex: "Clean Texts",
    lookupSystem: "Lookup System",
    legalWorkspace: "Source Notes",
    markdownReference: "Reference markdown inside the same legal workspace.",
    markdownLabel: "Markdown reference",
    sourcePath: "Source Path",
    sourceCompare: "Sources",
    sourceCompareHelp: "Keep only the sources needed for direct cross-checking: official full text, eCoSys, and the mirrored source file.",
    sourceLegend: "Source labels always show the active provenance plus text format: VBPL/VNTR/TVPL HTML, eCoSys DOCX, eCoSys PDF, eCoSys PDF OCR, or eCoSys MIX (DOCX + PDF). RAR/ZIP are only intermediate containers, not final lanes.",
    officialTextPage: "Official full-text page",
    officialSearchPage: "Official search page",
    rawBinaryFile: "Mirrored source file",
    mirrorAttachments: "Local mirrored files",
    ecosysListing: "eCoSys listing page",
    ecosysFileUrl: "Original eCoSys file URL",
    openSource: "Open source",
    openExternal: "Open external",
    downloadSource: "Download file",
    appendixStatusTitle: "Appendix data status",
    appendixStatusWarning: "The tables below are assembled from binary extraction cache for comparison. They still contain line-break and page-break noise, so they are not yet normalized database-ready tables.",
    appendixStatusClean: "The appendices below are assembled from the currently available text cache. They should still be cross-checked with the source before database normalization.",
    notFound: "Not found",
    serverError: "Server error",
    serverErrorMeta: "The legal viewer render layer failed.",
    unknown: "Unknown",
    notResolved: "Not resolved",
    notAvailable: "Not available",
    noMajorIssues: "No major extraction issues flagged.",
    metadataLabels: {
      issueCode: "Issue code",
      title: "Title",
      issuedDate: "Issued date",
      issuingUnit: "Issuing unit",
      formType: "Group / form",
      discoveryFeed: "Discovery feed",
      discoveredFrom: "Discovered from",
      mirroredBinary: "Mirrored binary",
      preferredTextSource: "Preferred text source",
      sourceClassification: "Source classification",
      extractionQuality: "Extraction quality",
      extractionIssues: "Extraction issues",
      renderedFrom: "Rendered from",
      renderedMarkdownPath: "Rendered markdown path",
      officialTextPage: "Official text page",
      officialMarkdownCache: "Official markdown cache",
      ocrCache: "OCR cache",
      rawExtractionCache: "Raw extraction cache",
      binaryMirrorPath: "Binary mirror path",
      binaryFileType: "Binary file type",
      binaryFileSize: "Binary file size",
    },
  },
};

function resolveLocale(value) {
  return SUPPORTED_LOCALES.has(value) ? value : "vi";
}

function t(locale, key) {
  return I18N[locale]?.[key] ?? I18N.vi[key] ?? key;
}

function metadataLabel(locale, key) {
  return I18N[locale]?.metadataLabels?.[key] ?? I18N.vi.metadataLabels[key] ?? key;
}

function buildHref(pathname, locale, extraParams = {}) {
  const params = new URLSearchParams();
  if (locale !== "vi") {
    params.set("lang", locale);
  }
  for (const [key, value] of Object.entries(extraParams)) {
    if (value !== null && value !== undefined && value !== "") {
      params.set(key, value);
    }
  }
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function slugify(value) {
  return String(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

export function buildDocumentRouteSlug(document) {
  return slugify(document.issueCode || "") || slugify(`${document.issueCode}-${document.title}`);
}

function renderLayout(title, body, locale = "vi", options = {}) {
  const pageClass = options.pageClass ? ` ${options.pageClass}` : "";
  const currentPath = options.currentPath || "/";
  const navMode = options.navMode || "default";
  const navItems = [
    { href: "/", label: t(locale, "navCorpus"), active: currentPath === "/" || currentPath.startsWith("/search") || currentPath.startsWith("/doc/") },
    { href: "/index", label: t(locale, "navCanonical"), active: currentPath.startsWith("/index") },
    { href: "/lookup-system", label: t(locale, "navLookup"), active: currentPath.startsWith("/lookup-system") },
    { href: "/about", label: t(locale, "navWorkspace"), active: currentPath.startsWith("/about") },
  ];
  const topnav = navMode === "document"
    ? `
  <div class="topnav topnav-compact">
    <div class="topnav-primary shell">
      <a href="${buildHref("/", locale)}" class="topnav-brand">
        <span class="topnav-brand-mark">CO</span>
        <span class="topnav-brand-label">${escapeHtml(t(locale, "brand"))}</span>
      </a>
      <div class="topnav-links">
        <a class="topnav-back" href="${buildHref("/", locale)}">${escapeHtml(t(locale, "backToCorpus"))}</a>
        <a class="topnav-link" href="${buildHref("/search", locale)}">${escapeHtml(t(locale, "searchTitle"))}</a>
      </div>
      <div class="locale-switch">
        <a class="locale-link ${locale === "vi" ? "locale-link-active" : ""}" href="${buildHref(currentPath, "vi")}">VI</a>
        <a class="locale-link ${locale === "en" ? "locale-link-active" : ""}" href="${buildHref(currentPath, "en")}">EN</a>
      </div>
    </div>
  </div>`
    : `
  <div class="topnav">
    <div class="topnav-primary shell">
      <a href="${buildHref("/", locale)}" class="topnav-brand">
        <span class="topnav-brand-mark">CO</span>
        <span class="topnav-brand-label">${escapeHtml(t(locale, "brand"))}</span>
      </a>
      <div class="topnav-links">
        ${navItems.map((item) => `
          <a class="topnav-link${item.active ? " topnav-link-active" : ""}" href="${buildHref(item.href, locale)}">${escapeHtml(item.label)}</a>
        `).join("")}
      </div>
      <div class="locale-switch">
        <a class="locale-link ${locale === "vi" ? "locale-link-active" : ""}" href="${buildHref(currentPath, "vi")}">VI</a>
        <a class="locale-link ${locale === "en" ? "locale-link-active" : ""}" href="${buildHref(currentPath, "en")}">EN</a>
      </div>
    </div>
  </div>`;

  return `<!doctype html>
<html lang="${escapeHtml(I18N[locale].htmlLang)}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHtml(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --radius-xl: 26px;
      --radius-lg: 20px;
      --background: #f3f6f8;
      --background-top: #f8fafc;
      --background-accent: rgba(22, 163, 74, 0.08);
      --background-accent-2: rgba(37, 99, 235, 0.06);
      --foreground: #0f172a;
      --foreground-muted: #64748b;
      --foreground-soft: #334155;
      --card: rgba(255, 255, 255, 0.94);
      --card-strong: rgba(255, 255, 255, 0.98);
      --surface-subtle: rgba(241, 245, 249, 0.86);
      --surface-hover: rgba(226, 232, 240, 0.72);
      --surface-overlay: rgba(255, 255, 255, 0.82);
      --surface-input: rgba(255, 255, 255, 0.96);
      --border: rgba(148, 163, 184, 0.24);
      --border-strong: rgba(148, 163, 184, 0.4);
      --ring: rgba(5, 150, 105, 0.2);
      --primary: #059669;
      --primary-hover: #047857;
      --primary-foreground: #ffffff;
      --primary-soft: rgba(5, 150, 105, 0.12);
      --good: #16a34a;
      --warn: #d97706;
      --bad: #ef4444;
      --info: #2563eb;
      --rail-bg: rgba(248, 250, 252, 0.9);
      --panel-highlight: rgba(5, 150, 105, 0.18);
      --shadow-lg: 0 30px 70px rgba(15, 23, 42, 0.08);
      --shadow-md: 0 12px 32px rgba(15, 23, 42, 0.08);
    }
    * {
      box-sizing: border-box;
    }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--foreground);
      font-family: "Manrope", "Segoe UI Variable", sans-serif;
      background:
        radial-gradient(circle at top left, var(--background-accent), transparent 28%),
        radial-gradient(circle at 78% 18%, var(--background-accent-2), transparent 26%),
        linear-gradient(180deg, var(--background-top) 0%, var(--background) 100%);
    }
    body.page-document {
      background:
        radial-gradient(circle at top left, rgba(22, 163, 74, 0.05), transparent 24%),
        linear-gradient(180deg, #f8fafc 0%, #f3f6f8 100%);
    }
    a {
      color: inherit;
      text-decoration: none;
    }
    .shell-noise {
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(var(--border) 1px, transparent 1px),
        linear-gradient(90deg, var(--border) 1px, transparent 1px);
      background-size: 24px 24px;
      mask-image: radial-gradient(circle at center, black 55%, transparent 100%);
      opacity: 0.32;
    }
    body.page-document .shell-noise {
      opacity: 0.18;
    }
    .topnav {
      position: sticky;
      top: 0;
      z-index: 40;
      display: flex;
      flex-direction: column;
      background: color-mix(in srgb, var(--surface-overlay) 94%, transparent);
      border-bottom: 1px solid var(--border);
      backdrop-filter: blur(20px);
    }
    .topnav-primary,
    .topnav-secondary,
    .shell {
      max-width: 1440px;
      width: 100%;
      margin: 0 auto;
      padding-left: 1.2rem;
      padding-right: 1.2rem;
    }
    .topnav-primary,
    .topnav-secondary {
      display: flex;
      align-items: center;
      gap: 1rem;
    }
    .topnav-primary {
      padding-top: 0.65rem;
      padding-bottom: 0.65rem;
    }
    .topnav-compact .topnav-primary {
      padding-top: 0.45rem;
      padding-bottom: 0.45rem;
      gap: 0.9rem;
    }
    .topnav-secondary {
      min-height: 3rem;
      padding-top: 0.55rem;
      padding-bottom: 0.55rem;
      border-top: 1px solid var(--border);
    }
    .topnav-brand {
      display: inline-flex;
      align-items: center;
      gap: 0.7rem;
      font-weight: 800;
      letter-spacing: 0.01em;
    }
    .topnav-brand-mark {
      width: 2rem;
      height: 2rem;
      display: grid;
      place-items: center;
      border-radius: 0.75rem;
      border: 1px solid var(--panel-highlight);
      background: linear-gradient(135deg, var(--primary-soft), transparent);
      color: var(--primary);
      font-size: 0.72rem;
      font-weight: 800;
      letter-spacing: 0.08em;
    }
    .topnav-brand-label {
      font-size: 0.95rem;
    }
    .topnav-links {
      display: flex;
      gap: 0.2rem;
      flex: 1 1 auto;
    }
    .topnav-compact .topnav-links {
      gap: 0.1rem;
    }
    .topnav-link,
    .topnav-back,
    .topnav-tab {
      display: inline-flex;
      align-items: center;
      padding: 0.5rem 0.8rem;
      border-radius: 10px;
      color: var(--foreground-muted);
      font-size: 0.86rem;
      font-weight: 600;
      transition: color 140ms ease, background 140ms ease, border-color 140ms ease, transform 140ms ease;
    }
    .topnav-compact .topnav-link,
    .topnav-compact .topnav-back {
      padding: 0.42rem 0.7rem;
      font-size: 0.82rem;
    }
    .topnav-link:hover,
    .topnav-back:hover,
    .topnav-tab:hover {
      color: var(--foreground);
      background: var(--surface-hover);
    }
    .topnav-link-active,
    .topnav-tab-active {
      color: var(--primary);
      background: var(--primary-soft);
    }
    .topnav-back::before {
      content: "←";
      font-size: 1rem;
      line-height: 1;
      margin-right: 0.35rem;
    }
    .topnav-context {
      display: inline-flex;
      align-items: baseline;
      gap: 0.55rem;
      min-width: 0;
      flex: 1 1 auto;
    }
    .topnav-context strong {
      font-size: 0.98rem;
      color: var(--foreground);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 24rem;
    }
    .topnav-context-meta {
      font-size: 0.76rem;
      color: var(--foreground-muted);
      font-family: "IBM Plex Mono", monospace;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .topnav-tabs {
      display: flex;
      gap: 0.2rem;
      padding: 0.2rem;
      background: var(--surface-subtle);
      border: 1px solid var(--border);
      border-radius: 10px;
    }
    .locale-switch {
      display: inline-flex;
      gap: 0.2rem;
      padding: 0.2rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--surface-subtle);
    }
    .locale-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 2.4rem;
      padding: 0.38rem 0.62rem;
      border-radius: 999px;
      color: var(--foreground-muted);
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.72rem;
      font-weight: 600;
    }
    .locale-link-active {
      color: var(--foreground);
      background: var(--card-strong);
      box-shadow: 0 0 0 1px var(--border);
    }
    .topnav-compact .locale-link {
      min-width: 2.15rem;
      padding: 0.32rem 0.52rem;
    }
    .shell {
      padding-top: 0;
      padding-bottom: 1.6rem;
    }
    body.page-document .shell {
      padding-bottom: 2.2rem;
    }
    .workspace-topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 1rem;
      margin: 1rem 0 1.25rem;
      padding: 1.05rem 1.2rem;
      border: 1px solid var(--border);
      border-radius: 1.1rem;
      background: var(--surface-overlay);
      backdrop-filter: blur(18px);
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
    }
    .workspace-topbar h1 {
      margin: 0;
      font-size: clamp(1.65rem, 2vw, 2.45rem);
      line-height: 1.05;
      letter-spacing: -0.04em;
    }
    .workspace-topbar p {
      margin: 0;
      color: var(--foreground-muted);
      max-width: 70ch;
    }
    .workspace-topbar-meta {
      display: flex;
      align-items: center;
      gap: 0.65rem;
      flex-wrap: wrap;
    }
    .nav {
      display: flex;
      gap: 0.45rem;
      flex-wrap: wrap;
      margin-top: 0.8rem;
    }
    .nav a {
      display: inline-flex;
      align-items: center;
      padding: 0.48rem 0.8rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--card);
      color: var(--foreground-soft);
      font-size: 0.82rem;
      font-weight: 600;
      transition: background 140ms ease, border-color 140ms ease, transform 140ms ease;
    }
    .nav a:hover {
      background: var(--surface-hover);
      border-color: var(--border-strong);
      transform: translateY(-1px);
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(330px, 390px) minmax(0, 1fr);
      gap: 20px;
      align-items: start;
    }
    .rail {
      position: sticky;
      top: 11.5rem;
      align-self: start;
      display: flex;
      flex-direction: column;
      gap: 1rem;
      padding: 1rem;
      border: 1px solid var(--border);
      border-radius: var(--radius-xl);
      background: color-mix(in srgb, var(--rail-bg) 92%, transparent);
      box-shadow: var(--shadow-lg);
      backdrop-filter: blur(18px);
    }
    .panel {
      position: relative;
      background: linear-gradient(180deg, var(--card-strong) 0%, var(--card) 100%);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 1.15rem;
      box-shadow: var(--shadow-md);
      min-width: 0;
      overflow: hidden;
    }
    .panel::before {
      content: "";
      position: absolute;
      inset: 0 auto auto 0;
      width: 100%;
      height: 1px;
      background: linear-gradient(90deg, var(--panel-highlight), transparent 55%);
    }
    .panel h2 {
      margin: 0 0 0.8rem;
      font-size: 0.95rem;
      letter-spacing: 0.01em;
    }
    .search {
      display: flex;
      gap: 8px;
      margin-bottom: 0.9rem;
    }
    input[type="search"] {
      width: 100%;
      padding: 0.85rem 0.95rem;
      border-radius: 10px;
      border: 1px solid var(--border);
      font: inherit;
      background: var(--surface-input);
      color: var(--foreground);
      transition: border-color 140ms ease, background 140ms ease, box-shadow 140ms ease;
    }
    input[type="search"]:focus {
      outline: none;
      border-color: var(--primary);
      box-shadow: 0 0 0 3px var(--ring);
      background: var(--card-strong);
    }
    button {
      padding: 0.85rem 1rem;
      border-radius: 10px;
      border: 1px solid var(--primary);
      background: var(--primary);
      color: var(--primary-foreground);
      font: inherit;
      cursor: pointer;
      font-weight: 700;
      transition: transform 140ms ease, background 140ms ease;
    }
    button:hover {
      transform: translateY(-1px);
      background: var(--primary-hover);
    }
    .meta {
      color: var(--foreground-muted);
      font-size: 0.84rem;
      line-height: 1.5;
    }
    .count {
      font-size: 0.8rem;
      color: var(--foreground-muted);
      margin-bottom: 0.65rem;
      font-family: "IBM Plex Mono", monospace;
    }
    .doc-list {
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 0.35rem;
      max-height: calc(100vh - 330px);
      overflow: auto;
      padding-right: 0.2rem;
    }
    .doc-item {
      border: 1px solid transparent;
      border-radius: 16px;
      padding: 0.9rem 0.95rem;
      background: transparent;
      transition: background 140ms ease, border-color 140ms ease, transform 140ms ease;
    }
    .doc-item:hover {
      background: var(--surface-hover);
      border-color: var(--border);
      transform: translateY(-1px);
    }
    .doc-item strong {
      display: block;
      margin-bottom: 0.2rem;
      font-size: 0.92rem;
      letter-spacing: -0.01em;
    }
    .doc-item-title {
      margin-bottom: 0.45rem;
      color: var(--foreground-soft);
      font-size: 0.88rem;
      line-height: 1.45;
    }
    .tag-row {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      margin-top: 0.7rem;
    }
    .tag {
      display: inline-block;
      padding: 0.28rem 0.55rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--surface-subtle);
      color: var(--foreground-soft);
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.02em;
    }
    .tag.good {
      border-color: color-mix(in srgb, var(--good) 30%, var(--border));
      background: color-mix(in srgb, var(--good) 10%, white);
      color: var(--good);
    }
    .tag.warn {
      border-color: color-mix(in srgb, var(--warn) 30%, var(--border));
      background: color-mix(in srgb, var(--warn) 12%, white);
      color: var(--warn);
    }
    .tag.bad {
      border-color: color-mix(in srgb, var(--bad) 26%, var(--border));
      background: color-mix(in srgb, var(--bad) 10%, white);
      color: #b42318;
    }
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    .stat {
      padding: 0.95rem 1rem;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: linear-gradient(180deg, var(--card-strong), var(--surface-subtle));
    }
    .stat-label {
      display: block;
      margin-bottom: 0.35rem;
      color: var(--foreground-muted);
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-family: "IBM Plex Mono", monospace;
    }
    .stat-value {
      font-size: 1.45rem;
      line-height: 1;
      letter-spacing: -0.05em;
      font-weight: 800;
    }
    .summary-strip {
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
      margin-top: 0.9rem;
    }
    .summary-chip {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      padding: 0.42rem 0.7rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--card);
      color: var(--foreground-soft);
      font-size: 0.76rem;
      font-weight: 700;
    }
    .summary-chip strong {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.76rem;
    }
    .document-header {
      display: grid;
      gap: 0.35rem;
      margin: 0.25rem 0 0.8rem;
    }
    .document-header-head {
      display: grid;
      gap: 0.42rem;
    }
    .document-code {
      color: var(--primary);
      font-size: 0.74rem;
      font-family: "IBM Plex Mono", monospace;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .document-title {
      margin: 0;
      max-width: 28ch;
      font-size: clamp(1.35rem, 1.7vw, 1.92rem);
      line-height: 1.05;
      letter-spacing: -0.05em;
    }
    .document-meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.25rem 0.65rem;
      color: var(--foreground-muted);
      font-size: 0.86rem;
      line-height: 1.45;
    }
    .document-meta-row span + span::before {
      content: "•";
      margin-right: 0.65rem;
      color: var(--border-strong);
    }
    .document-chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }
    .document-chip {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.32rem 0.56rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--surface-subtle);
      color: var(--foreground-soft);
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.01em;
      white-space: normal;
    }
    .document-chip-label {
      color: var(--foreground-muted);
      font-weight: 600;
    }
    .document-stage {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 240px;
      gap: 1.35rem;
      align-items: start;
    }
    .reading-surface {
      min-width: 0;
      padding: clamp(1rem, 1.5vw, 1.55rem);
      border: 1px solid rgba(148, 163, 184, 0.16);
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
    }
    .inspector {
      position: sticky;
      top: 4.3rem;
      display: grid;
      gap: 0.8rem;
      align-self: start;
    }
    .inspector-section {
      padding-top: 0.75rem;
      border-top: 1px solid var(--border);
    }
    .inspector-section:first-child {
      padding-top: 0;
      border-top: none;
    }
    .inspector-title {
      margin: 0 0 0.7rem;
      color: var(--foreground);
      font-size: 0.78rem;
      font-family: "IBM Plex Mono", monospace;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .fact-list {
      display: grid;
      gap: 0.18rem;
    }
    .fact-item {
      display: grid;
      grid-template-columns: 5.6rem minmax(0, 1fr);
      gap: 0.5rem;
      align-items: start;
      padding: 0.38rem 0;
      border-bottom: 1px dotted var(--border);
    }
    .fact-item:last-child {
      border-bottom: none;
    }
    .fact-label {
      color: var(--foreground-muted);
      font-size: 0.66rem;
      font-family: "IBM Plex Mono", monospace;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .fact-value {
      color: var(--foreground);
      font-size: 0.84rem;
      line-height: 1.38;
    }
    .content {
      overflow-wrap: anywhere;
      line-height: 1.7;
    }
    .content h1, .content h2, .content h3 {
      scroll-margin-top: 24px;
      letter-spacing: -0.03em;
    }
    .content pre {
      overflow: auto;
      padding: 12px 14px;
      background: linear-gradient(180deg, #f8fafc, #f5f8fb);
      border: 1px solid var(--border);
      border-radius: 14px;
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.8rem;
      line-height: 1.55;
    }
    .content table {
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0;
      font-size: 0.92rem;
    }
    .content th, .content td {
      border: 1px solid var(--border);
      padding: 8px;
      vertical-align: top;
      text-align: left;
    }
    .detail-meta {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.86rem;
    }
    .table-shell {
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: var(--card-strong);
    }
    .document-table {
      width: 100%;
      min-width: 980px;
      border-collapse: collapse;
      font-size: 0.86rem;
    }
    .document-table thead th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: #f8fafc;
      color: var(--foreground-muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.74rem;
      font-family: "IBM Plex Mono", monospace;
    }
    .document-table th,
    .document-table td {
      border-bottom: 1px solid var(--border);
      padding: 0.78rem 0.8rem;
      text-align: left;
      vertical-align: top;
    }
    .document-table tbody tr:hover {
      background: var(--surface-hover);
    }
    .table-link {
      color: var(--info);
      font-weight: 700;
    }
    .table-link-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 4.25rem;
      padding: 0.42rem 0.72rem;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--info) 22%, var(--border));
      background: color-mix(in srgb, var(--info) 8%, white);
      white-space: nowrap;
    }
    .table-code-cell,
    .table-date-cell,
    .table-action-cell {
      white-space: nowrap;
    }
    .table-code-cell {
      width: 9.5rem;
    }
    .table-date-cell {
      width: 8.5rem;
    }
    .table-source-cell {
      width: 11.5rem;
    }
    .table-action-cell {
      width: 5.5rem;
      text-align: right;
    }
    .table-title {
      min-width: 340px;
      color: var(--foreground-soft);
      line-height: 1.5;
    }
    .document-table-overview {
      min-width: 760px;
    }
    .document-table-overview .table-title {
      min-width: 300px;
    }
    .table-subtle {
      margin-top: 0.28rem;
      color: var(--foreground-muted);
      font-size: 0.8rem;
      font-weight: 600;
    }
    .table-status-stack {
      display: flex;
      flex-wrap: wrap;
      gap: 0.38rem;
      max-width: 17rem;
    }
    .table-source-main {
      font-weight: 700;
      color: var(--foreground);
      white-space: nowrap;
    }
    .table-source-main .tag {
      margin-top: 0.35rem;
    }
    .source-links {
      display: grid;
      gap: 0;
    }
    .source-link {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: baseline;
      gap: 0.75rem;
      padding: 0.42rem 0;
      border-top: 1px dotted var(--border);
      transition: color 140ms ease;
    }
    .source-link:first-child {
      border-top: none;
      padding-top: 0;
    }
    .source-link:hover {
      color: var(--primary);
    }
    .source-link-copy {
      display: grid;
      gap: 0.12rem;
      min-width: 0;
    }
    .source-link-label {
      font-weight: 700;
      color: var(--foreground);
      font-size: 0.84rem;
    }
    .source-link-note {
      color: var(--foreground-muted);
      font-size: 0.74rem;
      line-height: 1.4;
      word-break: break-word;
    }
    .source-link-meta {
      color: var(--foreground-muted);
      font-size: 0.64rem;
      font-family: "IBM Plex Mono", monospace;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      white-space: nowrap;
    }
    .source-note {
      display: grid;
      gap: 0.3rem;
      margin: 0.95rem 0 1rem;
      padding: 0.85rem 0.95rem;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: var(--surface-subtle);
      color: var(--foreground-soft);
      line-height: 1.55;
    }
    .source-note-warn {
      border-color: rgba(217, 119, 6, 0.24);
      background: rgba(217, 119, 6, 0.08);
    }
    .coverage-note {
      margin-top: 0.9rem;
      color: var(--foreground-muted);
      font-size: 0.84rem;
      line-height: 1.6;
    }
    .artifact-block {
      margin-top: 1rem;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: var(--card-strong);
      overflow: hidden;
    }
    .artifact-block summary {
      cursor: pointer;
      list-style: none;
      padding: 0.95rem 1rem;
      font-weight: 700;
      color: var(--foreground);
      background: linear-gradient(180deg, var(--card-strong), var(--surface-subtle));
      border-bottom: 1px solid var(--border);
    }
    .artifact-block summary::-webkit-details-marker {
      display: none;
    }
    .artifact-pre {
      margin: 0;
      padding: 1rem;
      overflow: auto;
      background: #f8fafc;
      color: var(--foreground-soft);
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.76rem;
      line-height: 1.55;
      white-space: pre;
    }
    .artifact-meta {
      padding: 0 1rem 0.85rem;
      color: var(--foreground-muted);
      font-size: 0.8rem;
      font-family: "IBM Plex Mono", monospace;
    }
    .detail-meta th, .detail-meta td {
      border: 1px solid var(--border);
      padding: 0.7rem 0.75rem;
      vertical-align: top;
      text-align: left;
    }
    .detail-meta th {
      width: 180px;
      background: #f8fafc;
      color: var(--foreground-muted);
      font-weight: 700;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .empty {
      color: var(--foreground-muted);
      font-style: italic;
    }
    .inspector-stack {
      display: grid;
      gap: 1rem;
    }
    .mono {
      font-family: "IBM Plex Mono", monospace;
      font-size: 0.76rem;
      line-height: 1.7;
      word-break: break-word;
    }
    .markdown-frame {
      min-height: calc(100vh - 220px);
    }
    .content h1 {
      font-size: clamp(1.7rem, 2vw, 2.4rem);
    }
    .content h2 {
      font-size: 1.15rem;
      margin-top: 1.75rem;
    }
    .content h3 {
      font-size: 1rem;
      margin-top: 1.3rem;
    }
    .content p,
    .content li {
      color: var(--foreground-soft);
      font-size: 0.95rem;
    }
    .content strong {
      color: var(--foreground);
    }
    @media (max-width: 1000px) {
      .topnav-primary,
      .topnav-secondary,
      .shell {
        padding-left: 0.9rem;
        padding-right: 0.9rem;
      }
      .topnav-links,
      .topnav-chip {
        display: none;
      }
      .topnav-compact .topnav-links {
        display: flex;
      }
      .topnav-secondary {
        flex-wrap: wrap;
      }
      .topnav-context strong {
        max-width: 16rem;
      }
      .workspace-topbar {
        top: 6.6rem;
        padding: 0.9rem 1rem;
        flex-direction: column;
        align-items: flex-start;
      }
      .grid {
        grid-template-columns: 1fr;
      }
      .rail {
        position: static;
      }
      .document-header-head,
      .document-stage {
        display: grid;
        grid-template-columns: 1fr;
      }
      .document-title {
        max-width: none;
      }
      .document-chip-row {
        justify-content: flex-start;
        max-width: none;
      }
      .inspector {
        position: static;
      }
      .fact-item {
        grid-template-columns: 1fr;
        gap: 0.15rem;
      }
      .doc-list {
        max-height: none;
      }
      .stats-grid {
        grid-template-columns: 1fr 1fr;
      }
    }
    @media (max-width: 640px) {
      .stats-grid {
        grid-template-columns: 1fr;
      }
      .detail-meta th,
      .detail-meta td {
        display: block;
        width: 100%;
      }
      .detail-meta tr {
        display: block;
        margin-bottom: 0.55rem;
      }
      .table-shell {
        overflow: visible;
        border: none;
        background: transparent;
      }
      .document-table,
      .document-table-overview {
        min-width: 0;
      }
      .document-table thead {
        display: none;
      }
      .document-table tbody,
      .document-table tr,
      .document-table td {
        display: block;
        width: 100%;
      }
      .document-table tbody tr {
        padding: 0.9rem 1rem;
        border-bottom: 1px solid var(--border);
        background: var(--card-strong);
      }
      .document-table td {
        padding: 0.15rem 0;
        border-bottom: none;
      }
      .table-action-cell {
        margin-top: 0.55rem;
        text-align: left;
      }
    }
  </style>
</head>
<body class="${escapeHtml(pageClass.trim())}">
  <div class="shell-noise"></div>
  ${topnav}
  <div class="shell">
    ${body}
  </div>
</body>
</html>`;
}

function runPandoc(filePath) {
  return new Promise((resolve, reject) => {
    const child = spawn("pandoc", ["-f", "gfm", "-t", "html5", filePath], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || stdout || `pandoc failed for ${filePath}`));
        return;
      }
      resolve(stdout);
    });
  });
}

async function fileExists(filePath) {
  if (!filePath) {
    return false;
  }

  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

function findTextCandidate(entry, sourceId) {
  return entry.textCandidates?.find((candidate) => candidate.sourceId === sourceId) || null;
}

function titleCaseLabel(value) {
  return String(value || "")
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatFileSize(sizeBytes) {
  if (!sizeBytes || Number.isNaN(sizeBytes)) {
    return "Unknown";
  }
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }
  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`;
  }
  return `${(sizeBytes / (1024 * 1024)).toFixed(2)} MB`;
}

function isLocalAppPath(value) {
  if (!value) {
    return false;
  }
  // Compare on a path boundary, not a raw prefix: a sibling directory whose name
  // merely starts with ROOT (barry-CO next to barry-CO-main) is not inside it.
  const resolved = path.resolve(String(value));
  const root = path.resolve(ROOT);
  return resolved === root || resolved.startsWith(root + path.sep);
}

function binaryContentType(filePath) {
  const extension = path.extname(filePath || "").toLowerCase();
  switch (extension) {
    case ".pdf":
      return "application/pdf";
    case ".json":
      return "application/json; charset=utf-8";
    case ".md":
      return "text/markdown; charset=utf-8";
    case ".html":
    case ".htm":
      return "text/html; charset=utf-8";
    case ".txt":
      return "text/plain; charset=utf-8";
    case ".rar":
      return "application/vnd.rar";
    case ".zip":
      return "application/zip";
    case ".doc":
      return "application/msword";
    case ".docx":
      return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    default:
      return "application/octet-stream";
  }
}

function describePreferredSource(sourceId) {
  switch (sourceId) {
    case "official-text":
      return "Official text";
    case "ocr-recovery":
      return "eCoSys PDF OCR";
    case "ecosys-extracted":
      return "eCoSys PDF";
    case "tvpl":
      return "TVPL HTML";
    default:
      return sourceId || "Unknown";
  }
}

function detectPathExtension(filePath) {
  if (!filePath) {
    return "";
  }
  try {
    const pathname = String(filePath).startsWith("http")
      ? new URL(filePath).pathname
      : filePath;
    return path.extname(pathname || "").toLowerCase();
  } catch {
    return path.extname(String(filePath || "")).toLowerCase();
  }
}

function describeFormatFromExtension(extension) {
  switch (String(extension || "").toLowerCase()) {
    case ".html":
    case ".htm":
      return "HTML";
    case ".doc":
    case ".docx":
      return "DOCX";
    case ".pdf":
      return "PDF";
    default:
      return "";
  }
}

function pushFormat(formats, extension) {
  const format = describeFormatFromExtension(extension);
  if (format) {
    formats.add(format);
  }
}

function sortFormats(formats) {
  const formatOrder = ["HTML", "DOCX", "PDF"];
  return Array.from(formats).sort((left, right) => {
    const leftIndex = formatOrder.indexOf(left);
    const rightIndex = formatOrder.indexOf(right);
    const normalizedLeft = leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex;
    const normalizedRight = rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex;
    if (normalizedLeft !== normalizedRight) {
      return normalizedLeft - normalizedRight;
    }
    return left.localeCompare(right);
  });
}

function inferEcosysFormats(document = null) {
  const formats = new Set();

  pushFormat(formats, document?.rawBinarySource?.fileExtension);
  pushFormat(formats, detectPathExtension(document?.rawBinarySource?.localPath));
  pushFormat(formats, detectPathExtension(document?.discovery?.mirroredFileUrl));

  for (const attachment of document?.attachmentFiles || []) {
    pushFormat(formats, detectPathExtension(attachment?.path || attachment?.label));
  }

  return sortFormats(formats);
}

function describeEcosysLane(document = null) {
  const formats = inferEcosysFormats(document);
  if (formats.length === 0) {
    return "eCoSys";
  }
  if (formats.length === 1) {
    return `eCoSys ${formats[0]}`;
  }
  return `eCoSys MIX (${formats.join(" + ")})`;
}

function describeOfficialLane(document = null) {
  const source = describeOfficialTextSource(document);
  const sourceType = document?.sourceClassification?.sourceType;

  if (sourceType === "official_pdf_text") {
    return `${source} PDF`;
  }
  if (sourceType === "official_binary_legacy_doc") {
    return `${source} DOCX`;
  }
  return `${source} HTML`;
}

function localizedPreferredSource(locale, sourceId, document = null) {
  if (sourceId === "official-text") {
    return describeOfficialLane(document);
  }
  if (sourceId === "ocr-recovery") {
    const formats = inferEcosysFormats(document);
    if (formats.includes("PDF")) {
      return "eCoSys PDF OCR";
    }
    return "eCoSys OCR";
  }
  if (sourceId === "ecosys-extracted") {
    return describeEcosysLane(document);
  }
  if (sourceId === "tvpl") {
    return "TVPL HTML";
  }
  if (locale === "en") {
    return describePreferredSource(sourceId);
  }
  switch (sourceId) {
    case "official-text":
      return "Official HTML";
    default:
      return sourceId || t(locale, "unknown");
  }
}

function describeSourceClassification(sourceType) {
  switch (sourceType) {
    case "official_html":
      return "Official HTML/text";
    case "official_pdf_text":
      return "Official PDF text";
    case "official_pdf_scan":
      return "Official PDF scan";
    case "official_binary_legacy_doc":
      return "Official legacy binary";
    case "third_party_text":
      return "Third-party text";
    case "unresolved":
      return "Unresolved";
    default:
      return sourceType || "Unknown";
  }
}

function localizedSourceClassification(locale, sourceType) {
  if (locale === "en") {
    return describeSourceClassification(sourceType);
  }
  switch (sourceType) {
    case "official_html":
      return "HTML/text chính thức";
    case "official_pdf_text":
      return "PDF text chính thức";
    case "official_pdf_scan":
      return "PDF scan chính thức";
    case "official_binary_legacy_doc":
      return "Binary legacy chính thức";
    case "third_party_text":
      return "Text bên thứ ba";
    case "unresolved":
      return "Chưa resolve";
    default:
      return sourceType || t(locale, "unknown");
  }
}

function describeQuality(quality) {
  switch (quality) {
    case "usable":
      return "Usable";
    case "noisy":
      return "Noisy";
    case "empty":
      return "Empty";
    case "unresolved":
      return "Unresolved";
    default:
      return quality || "Unknown";
  }
}

function localizedQuality(locale, quality) {
  if (locale === "en") {
    return describeQuality(quality);
  }
  switch (quality) {
    case "usable":
      return "Dùng được";
    case "noisy":
      return "Nhiễu";
    case "empty":
      return "Rỗng";
    case "unresolved":
      return "Chưa resolve";
    default:
      return quality || t(locale, "unknown");
  }
}

function qualityClass(quality) {
  if (quality === "usable") {
    return "good";
  }
  if (quality === "noisy") {
    return "warn";
  }
  return "bad";
}

function normalizeAscii(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function slugifyIssueAndTitle(issueCode, title) {
  return slugify(`${issueCode || ""}-${title || ""}`);
}

function describeHost(urlValue) {
  if (!urlValue) {
    return "";
  }
  try {
    return new URL(urlValue).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function describeSourceTarget(urlValue, fallback = "") {
  const host = describeHost(urlValue);
  if (!host) {
    return fallback;
  }
  if (host.includes("vbpl.vn")) {
    return "VBPL";
  }
  if (host.includes("vntr.moit.gov.vn")) {
    return "VNTR";
  }
  if (host.includes("thuvienphapluat.vn")) {
    return "TVPL";
  }
  if (host.includes("ecosys.gov.vn")) {
    return "eCoSys";
  }
  return host;
}

function inferOfficialSourceFromCache(document = null) {
  const cachePaths = [
    document?.officialMarkdownPath,
    document?.officialHtmlPath,
    document?.officialSearchHtmlPath,
    document?.officialJsonPath,
  ].filter(Boolean);

  for (const cachePath of cachePaths) {
    const normalized = String(cachePath).toLowerCase();
    if (normalized.includes("/official/vbpl/")) {
      return "VBPL";
    }
    if (normalized.includes("/official/vntr/")) {
      return "VNTR";
    }
    if (normalized.includes("/official/tvpl/")) {
      return "TVPL";
    }
  }

  return "";
}

function isTrustedOfficialTextUrl(urlValue) {
  const source = describeSourceTarget(urlValue, "");
  return source === "VBPL" || source === "VNTR" || source === "TVPL";
}

function describeOfficialTextSource(document = null) {
  if (document?.officialSourceProvider === "vbpl") {
    return "VBPL";
  }
  if (document?.officialSourceProvider === "vntr") {
    return "VNTR";
  }
  if (isTrustedOfficialTextUrl(document?.officialPageUrl)) {
    return describeSourceTarget(document?.officialPageUrl, "Official");
  }
  return inferOfficialSourceFromCache(document) || "Official";
}

function buildFallbackOfficialSourceLink(document = null, locale = "vi") {
  const source = describeOfficialTextSource(document);
  if (source === "VNTR" && (document?.officialSearchUrl || document?.issueCode)) {
    return {
      id: "official-search-page",
      label: `${source} · ${t(locale, "officialSearchPage")}`,
      href: document?.officialSearchUrl || buildVntrSearchUrl(document),
      external: true,
      note: describeHost(document?.officialSearchUrl) || "vntr.moit.gov.vn",
    };
  }
  return null;
}

async function listLocalMirrorAttachments(issueCode, title) {
  const attachmentRoot = path.join(ATTACHMENTS_DIR, slugifyIssueAndTitle(issueCode, title));
  if (!await fileExists(attachmentRoot)) {
    return [];
  }

  const collected = [];
  const queue = [{ dirPath: attachmentRoot, relativeDir: "" }];

  while (queue.length > 0) {
    const current = queue.shift();
    const entries = await fs.readdir(current.dirPath, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));

    for (const entry of entries) {
      const nextPath = path.join(current.dirPath, entry.name);
      const relativePath = path.join(current.relativeDir, entry.name);
      if (entry.isDirectory()) {
        queue.push({ dirPath: nextPath, relativeDir: relativePath });
        continue;
      }
      if (entry.isFile()) {
        collected.push({
          label: relativePath,
          path: nextPath,
        });
      }
    }
  }

  return collected.slice(0, 40);
}

export function selectSupplementalArtifacts(artifacts = []) {
  return artifacts
    .filter((artifact) => {
      const body = String(artifact?.body || "").trim();
      if (!body || body.startsWith("_Extraction failed")) {
        return false;
      }
      const normalizedLabel = normalizeAscii(artifact?.label || "");
      return normalizedLabel.includes("phu luc")
        || normalizedLabel.includes("appendix")
        || normalizedLabel.includes("annex")
        || normalizedLabel.includes("schedule");
    })
    .map((artifact) => ({
      label: artifact.label,
      body: artifact.body,
    }));
}

async function loadExtractionArtifacts(extractionPath) {
  if (!await fileExists(extractionPath)) {
    return [];
  }
  const payload = JSON.parse(await fs.readFile(extractionPath, "utf8"));
  return payload.artifacts || [];
}

function renderSupplementalArtifacts(artifacts, locale) {
  if (!artifacts.length) {
    return "";
  }

  const hasLikelyNoise = artifacts.some((artifact) => String(artifact.body || "").includes("\f"));

  return `
    <section>
      <h2>${locale === "vi" ? "Phụ lục và bảng tra cứu" : "Appendices and lookup tables"}</h2>
      <p>${locale === "vi"
        ? "Các phần dưới đây được ghép từ extraction cache của phụ lục/attachment để giữ đủ nội dung tra cứu, đặc biệt là các bảng HS và tiêu chí."
        : "The sections below are assembled from extracted appendix/attachment text so the lookup content remains complete, especially HS and criteria tables."}</p>
      <div class="source-note ${hasLikelyNoise ? "source-note-warn" : ""}">
        <strong>${escapeHtml(t(locale, "appendixStatusTitle"))}</strong>
        <span>${escapeHtml(hasLikelyNoise ? t(locale, "appendixStatusWarning") : t(locale, "appendixStatusClean"))}</span>
      </div>
      ${artifacts.map((artifact, index) => `
        <details class="artifact-block" ${index === 0 ? "open" : ""}>
          <summary>${escapeHtml(artifact.label)}</summary>
          <div class="artifact-meta">${escapeHtml(locale === "vi" ? "Nguồn phụ lục đã extract" : "Extracted appendix source")}</div>
          <pre class="artifact-pre">${escapeHtml(artifact.body)}</pre>
        </details>
      `).join("")}
    </section>
  `;
}

function renderLocalMirrorFiles(document, locale) {
  if (!document.attachmentFiles?.length) {
    return "";
  }

  return `
    <section class="inspector-section">
      <h2 class="inspector-title">${escapeHtml(t(locale, "mirrorAttachments"))}</h2>
      <div class="source-links">
        ${document.attachmentFiles.map((file, index) => `
          <a class="source-link" href="${escapeHtml(buildHref(`/source/${encodeURIComponent(document.routeSlug)}/attachment/${index}`, locale))}">
            <span class="source-link-copy">
              <span class="source-link-label">${escapeHtml(path.basename(file.label))}</span>
              <span class="source-link-note">${escapeHtml(file.label)}</span>
            </span>
            <span class="source-link-meta">${escapeHtml(t(locale, "openSource"))}</span>
          </a>
        `).join("")}
      </div>
    </section>
  `;
}

function renderSourceLinksPanel(document, locale) {
  const links = buildSourceLinkModels(document, locale);
  if (!links.length && !document.attachmentFiles?.length) {
    return "";
  }

  return `
    <section class="inspector-section">
      <h2 class="inspector-title">${escapeHtml(t(locale, "sourceCompare"))}</h2>
      <p class="source-note">${escapeHtml(t(locale, "sourceLegend"))}</p>
      <div class="source-links">
        ${links.map((link) => `
          <a class="source-link" href="${escapeHtml(link.href)}"${link.external ? ' target="_blank" rel="noreferrer"' : ""}>
            <span class="source-link-copy">
              <span class="source-link-label">${escapeHtml(link.label)}</span>
              ${link.note ? `<span class="source-link-note">${escapeHtml(link.note)}</span>` : ""}
            </span>
            <span class="source-link-meta">${escapeHtml(link.download ? t(locale, "downloadSource") : (link.external ? t(locale, "openExternal") : t(locale, "openSource")))}</span>
          </a>
        `).join("")}
      </div>
      ${renderLocalMirrorFiles(document, locale)}
    </section>
  `;
}

async function buildCanonicalMap() {
  const canonicalMap = new Map();
  if (!await fileExists(CANONICAL_DIR)) {
    return canonicalMap;
  }

  const fileNames = await fs.readdir(CANONICAL_DIR);
  for (const fileName of fileNames) {
    if (!fileName.endsWith(".md")) {
      continue;
    }

    const filePath = path.join(CANONICAL_DIR, fileName);
    const body = await fs.readFile(filePath, "utf8");
    const issueCodeMatch = body.match(/^#\s+(.+?)(?:\s+-\s+.+)?$/m)
      || body.match(/\|\s*Issue Code\s*\|\s*(.+?)\s*\|/i);
    if (issueCodeMatch) {
      canonicalMap.set(issueCodeMatch[1].trim(), filePath);
    }
  }

  return canonicalMap;
}

export function resolveRenderableMarkdown(entry, canonicalMap) {
  const canonicalPath = canonicalMap.get(entry.issueCode);
  if (canonicalPath) {
    return {
      sourceId: "canonical-pilot",
      label: "Canonical pilot markdown",
      path: canonicalPath,
    };
  }

  const officialTextCandidate = findTextCandidate(entry, "official-text");
  if (
    entry.preferredTextSource?.sourceId === "official-text" &&
    officialTextCandidate?.extractedMarkdownPath &&
    officialTextCandidate?.qualityGate?.passed !== false
  ) {
    return {
      sourceId: "official-text",
      label: "Official markdown",
      path: officialTextCandidate.extractedMarkdownPath,
    };
  }

  const tvplCandidate = findTextCandidate(entry, "tvpl");
  if (
    entry.preferredTextSource?.sourceId === "tvpl" &&
    tvplCandidate?.extractedMarkdownPath &&
    tvplCandidate?.qualityGate?.passed !== false
  ) {
    return {
      sourceId: "tvpl",
      label: "TVPL markdown",
      path: tvplCandidate.extractedMarkdownPath,
    };
  }

  return {
    sourceId: "wiki",
    label: "Wiki markdown",
    path: path.join(WIKI_DIR, `${buildDocumentRouteSlug(entry)}.md`),
  };
}

export function buildLegalDocumentViewModel(entry, canonicalMap) {
  const routeSlug = buildDocumentRouteSlug(entry);
  const renderSource = resolveRenderableMarkdown(entry, canonicalMap);
  const officialTextCandidate = findTextCandidate(entry, "official-text");
  const tvplCandidate = findTextCandidate(entry, "tvpl");
  const ocrCandidate = findTextCandidate(entry, "ocr-recovery");
  const extractionCandidate = findTextCandidate(entry, "ecosys-extracted");

  return {
    ...entry,
    routeSlug,
    renderSource,
    preferredTextSourceLabel: localizedPreferredSource("en", entry.preferredTextSource?.sourceId, {
      ...entry,
      officialSourceProvider: officialTextCandidate?.sourceProvider || entry.officialSourceProvider || null,
      officialPageUrl: officialTextCandidate?.pageUrl || entry.officialPageUrl || null,
      officialSearchUrl: officialTextCandidate?.searchUrl || entry.officialSearchUrl || null,
      officialMarkdownPath: officialTextCandidate?.extractedMarkdownPath || entry.officialMarkdownPath || null,
      officialHtmlPath: officialTextCandidate?.cachedHtmlPath || entry.officialHtmlPath || null,
      officialSearchHtmlPath: officialTextCandidate?.cachedSearchHtmlPath || entry.officialSearchHtmlPath || null,
      officialJsonPath: officialTextCandidate?.cachedJsonPath || entry.officialJsonPath || null,
    }),
    sourceClassificationLabel: describeSourceClassification(entry.sourceClassification?.sourceType),
    qualityLabel: describeQuality(entry.extractionAudit?.quality),
    qualityClassName: qualityClass(entry.extractionAudit?.quality),
    notesSummary: (entry.extractionAudit?.issues || []).join(", ") || "No major extraction issues flagged.",
    officialSourceProvider: officialTextCandidate?.sourceProvider || null,
    officialPageUrl: officialTextCandidate?.pageUrl || null,
    officialSearchUrl: officialTextCandidate?.searchUrl || null,
    officialDetailApiUrl: officialTextCandidate?.detailApiUrl || null,
    officialDetailId: officialTextCandidate?.detailId || null,
    officialMarkdownPath: officialTextCandidate?.extractedMarkdownPath || null,
    officialHtmlPath: officialTextCandidate?.cachedHtmlPath || null,
    officialSearchHtmlPath: officialTextCandidate?.cachedSearchHtmlPath || null,
    officialJsonPath: officialTextCandidate?.cachedJsonPath || null,
    tvplMarkdownPath: tvplCandidate?.extractedMarkdownPath || null,
    tvplPageUrl: tvplCandidate?.pageUrl || null,
    ocrPath: ocrCandidate?.extractionPath || null,
    extractionPath: extractionCandidate?.extractionPath || null,
  };
}

function resolveDocumentSourceAsset(document, kind) {
  switch (kind) {
    case "rendered-markdown":
      return document.renderSource?.path ? { type: "markdown", path: document.renderSource.path, title: document.renderSource.label } : null;
    case "official-markdown":
      return document.officialMarkdownPath ? { type: "markdown", path: document.officialMarkdownPath, title: "Official markdown cache" } : null;
    case "official-html":
      return document.officialHtmlPath ? { type: "text", path: document.officialHtmlPath, title: "Official HTML cache", contentType: "text/html; charset=utf-8" } : null;
    case "official-search-html":
      return document.officialSearchHtmlPath ? { type: "text", path: document.officialSearchHtmlPath, title: "Official search cache", contentType: "text/html; charset=utf-8" } : null;
    case "official-json":
      return document.officialJsonPath ? { type: "json", path: document.officialJsonPath, title: "Official JSON cache", contentType: "application/json; charset=utf-8" } : null;
    case "extraction-json":
      return document.extractionPath ? { type: "json", path: document.extractionPath, title: "Raw extraction JSON", contentType: "application/json; charset=utf-8" } : null;
    case "ocr-json":
      return document.ocrPath ? { type: "json", path: document.ocrPath, title: "OCR JSON", contentType: "application/json; charset=utf-8" } : null;
    case "raw-binary":
      return document.rawBinarySource?.localPath ? { type: "binary", path: document.rawBinarySource.localPath, title: "Binary mirror file", contentType: binaryContentType(document.rawBinarySource.localPath) } : null;
    case "attachment":
      return null;
    default:
      return null;
  }
}

export function buildSourceLinkModels(document, locale = "vi") {
  const links = [];
  const pushLink = (id, label, href, options = {}) => {
    if (!href) {
      return;
    }
    links.push({
      id,
      label,
      href,
      external: Boolean(options.external),
      download: Boolean(options.download),
      note: options.note || "",
    });
  };

  if (isTrustedOfficialTextUrl(document.officialPageUrl)) {
    pushLink(
      "official-page",
      `${describeOfficialTextSource(document)} · ${t(locale, "officialTextPage")}`,
      document.officialPageUrl,
      { external: true, note: describeHost(document.officialPageUrl) },
    );
  } else {
    const fallbackOfficialLink = buildFallbackOfficialSourceLink(document, locale);
    if (fallbackOfficialLink) {
      pushLink(
        fallbackOfficialLink.id,
        fallbackOfficialLink.label,
        fallbackOfficialLink.href,
        fallbackOfficialLink,
      );
    }
  }
  pushLink(
    "tvpl-page",
    "TVPL · Text page",
    document.tvplPageUrl,
    { external: true, note: describeHost(document.tvplPageUrl) },
  );
  pushLink(
    "ecosys-listing",
    `eCoSys · ${t(locale, "ecosysListing")}`,
    document.discovery?.listingUrl,
    { external: true, note: describeHost(document.discovery?.listingUrl) },
  );
  pushLink(
    "ecosys-file-url",
    `eCoSys · ${t(locale, "ecosysFileUrl")}`,
    document.discovery?.mirroredFileUrl,
    { external: true, note: describeHost(document.discovery?.mirroredFileUrl) },
  );
  if (isLocalAppPath(document.rawBinarySource?.localPath)) {
    pushLink(
      "raw-binary",
      `Local mirror · ${path.basename(document.rawBinarySource.localPath)}`,
      buildHref(`/source/${encodeURIComponent(document.routeSlug)}/raw-binary`, locale),
      {
        download: true,
        note: document.rawBinarySource.fileExtension || path.extname(document.rawBinarySource.localPath),
      },
    );
  }

  return links;
}

export function rewriteRenderedMarkdownLinks(html, documentPathMap, locale = "vi") {
  return html.replace(/href="([^"]+)"/g, (fullMatch, href) => {
    const normalizedHref = href.startsWith("//") ? href.slice(1) : href;
    const appRoute = documentPathMap.get(normalizedHref);
    if (!appRoute) {
      return fullMatch;
    }
    return `href="${buildHref(appRoute, locale)}"`;
  });
}

async function loadRegistryDocuments() {
  const registry = JSON.parse(await fs.readFile(REGISTRY_PATH, "utf8"));
  const canonicalMap = await buildCanonicalMap();
  const documents = await Promise.all(
    registry.documents.map(async (entry) => ({
      ...buildLegalDocumentViewModel(entry, canonicalMap),
      attachmentFiles: await listLocalMirrorAttachments(entry.issueCode, entry.title),
    })),
  );
  documents.sort((left, right) => {
    const leftDate = left.issuedDate || "";
    const rightDate = right.issuedDate || "";
    return rightDate.localeCompare(leftDate) || left.issueCode.localeCompare(right.issueCode);
  });
  return {
    counts: registry.counts,
    documents,
  };
}

function filterDocuments(documents, query) {
  if (!query) {
    return documents;
  }

  const q = query.toLowerCase();
  return documents.filter((document) =>
    [
      document.issueCode,
      document.title,
      document.formType,
      document.issuedDate,
      document.issuingUnit,
      document.preferredTextSourceLabel,
      document.sourceClassificationLabel,
      document.qualityLabel,
      document.notesSummary,
    ]
      .join(" ")
      .toLowerCase()
      .includes(q),
  );
}

function renderDocumentList(documents, locale) {
  return documents.map((document) => `
    <li class="doc-item">
      <strong><a href="${buildHref(`/doc/${encodeURIComponent(document.routeSlug)}`, locale)}">${escapeHtml(document.issueCode)}</a></strong>
      <div class="doc-item-title">${escapeHtml(document.title)}</div>
      <div class="meta">${escapeHtml(document.issuedDate || t(locale, "unknown"))} · ${escapeHtml(document.issuingUnit || t(locale, "unknown"))}</div>
      <div class="tag-row">
        <span class="tag">${escapeHtml(document.formType || t(locale, "unknown"))}</span>
        <span class="tag ${document.qualityClassName}">${escapeHtml(localizedQuality(locale, document.extractionAudit?.quality))}</span>
        <span class="tag">${escapeHtml(localizedPreferredSource(locale, document.preferredTextSource?.sourceId, document))}</span>
      </div>
    </li>
  `).join("");
}

function renderDocumentsTable(documents, locale, options = {}) {
  const mode = options.mode || "full";

  if (mode === "overview") {
    return `
      <div class="table-shell">
        <table class="document-table document-table-overview">
          <thead>
            <tr>
              <th>${escapeHtml(t(locale, "issueCode"))}</th>
              <th>${escapeHtml(t(locale, "title"))}</th>
              <th>${escapeHtml(t(locale, "issuedDate"))}</th>
              <th>${escapeHtml(t(locale, "source"))}</th>
              <th>${escapeHtml(t(locale, "open"))}</th>
            </tr>
          </thead>
          <tbody>
            ${documents.map((document) => `
              <tr>
                <td class="table-code-cell"><a class="table-link" href="${buildHref(`/doc/${encodeURIComponent(document.routeSlug)}`, locale)}">${escapeHtml(document.issueCode)}</a></td>
                <td class="table-title">
                  <div>${escapeHtml(document.title)}</div>
                  <div class="table-subtle">${escapeHtml([document.issuingUnit || t(locale, "unknown"), document.formType || t(locale, "unknown")].join(" · "))}</div>
                </td>
                <td class="table-date-cell">${escapeHtml(document.issuedDate || t(locale, "unknown"))}</td>
                <td class="table-source-cell">
                  <div class="table-source-main">${escapeHtml(localizedPreferredSource(locale, document.preferredTextSource?.sourceId, document))}</div>
                  <div class="table-status-stack">
                    <span class="tag ${document.qualityClassName}">${escapeHtml(localizedQuality(locale, document.extractionAudit?.quality))}</span>
                  </div>
                </td>
                <td class="table-action-cell"><a class="table-link table-link-button" href="${buildHref(`/doc/${encodeURIComponent(document.routeSlug)}`, locale)}">${escapeHtml(t(locale, "openDocument"))}</a></td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  return `
    <div class="table-shell">
      <table class="document-table">
        <thead>
          <tr>
            <th>${escapeHtml(t(locale, "issueCode"))}</th>
            <th>${escapeHtml(t(locale, "title"))}</th>
            <th>${escapeHtml(t(locale, "issuedDate"))}</th>
            <th>${escapeHtml(t(locale, "issuer"))}</th>
            <th>${escapeHtml(t(locale, "group"))}</th>
            <th>${escapeHtml(t(locale, "source"))}</th>
            <th>${escapeHtml(t(locale, "renderedFrom"))}</th>
            <th>${escapeHtml(t(locale, "quality"))}</th>
            <th>${escapeHtml(t(locale, "open"))}</th>
          </tr>
        </thead>
        <tbody>
          ${documents.map((document) => `
            <tr>
              <td><a class="table-link" href="${buildHref(`/doc/${encodeURIComponent(document.routeSlug)}`, locale)}">${escapeHtml(document.issueCode)}</a></td>
              <td class="table-title">${escapeHtml(document.title)}</td>
              <td>${escapeHtml(document.issuedDate || t(locale, "unknown"))}</td>
              <td>${escapeHtml(document.issuingUnit || t(locale, "unknown"))}</td>
              <td>${escapeHtml(document.formType || t(locale, "unknown"))}</td>
              <td>${escapeHtml(localizedPreferredSource(locale, document.preferredTextSource?.sourceId, document))}</td>
              <td>${escapeHtml(document.renderSource.label)}</td>
              <td><span class="tag ${document.qualityClassName}">${escapeHtml(localizedQuality(locale, document.extractionAudit?.quality))}</span></td>
              <td><a class="table-link" href="${buildHref(`/doc/${encodeURIComponent(document.routeSlug)}`, locale)}">${escapeHtml(t(locale, "openDocument"))}</a></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderHome(documents, counts, query, locale) {
  const renderCoverage = documents.reduce((acc, document) => {
    acc[document.renderSource.sourceId] = (acc[document.renderSource.sourceId] || 0) + 1;
    return acc;
  }, {});
  const ocrCount = counts.preferredOcrRecovery || 0;
  const body = `
    <section class="workspace-topbar">
      <div>
        <h1>${escapeHtml(t(locale, "homeTitle"))}</h1>
        <p>${escapeHtml(t(locale, "homeSubtitle"))}</p>
        <div class="nav">
          <a href="${buildHref("/search", locale)}">${escapeHtml(t(locale, "searchTitle"))}</a>
          <a href="${buildHref("/index", locale)}">${escapeHtml(t(locale, "pilotIndex"))}</a>
          <a href="${buildHref("/lookup-system", locale)}">${escapeHtml(t(locale, "lookupSystem"))}</a>
          <a href="${buildHref("/about", locale)}">${escapeHtml(t(locale, "legalWorkspace"))}</a>
        </div>
      </div>
    </section>
    <div class="grid">
      <aside class="rail">
        <div class="panel">
          <h2>${escapeHtml(t(locale, "corpusSummary"))}</h2>
          <div class="stats-grid">
            <div class="stat">
              <span class="stat-label">${escapeHtml(t(locale, "totalDocuments"))}</span>
              <span class="stat-value">${counts.documents}</span>
            </div>
            <div class="stat">
              <span class="stat-label">${escapeHtml(t(locale, "preferredOfficialText"))}</span>
              <span class="stat-value">${counts.preferredOfficialText}</span>
            </div>
            <div class="stat">
              <span class="stat-label">${escapeHtml(t(locale, "preferredOcrRecovery"))}</span>
              <span class="stat-value">${ocrCount}</span>
            </div>
            <div class="stat">
              <span class="stat-label">${escapeHtml(t(locale, "temporaryExtraction"))}</span>
              <span class="stat-value">${counts.temporaryEcosysExtraction}</span>
            </div>
          </div>
        </div>
        <div class="panel">
          <h2>${escapeHtml(t(locale, "contentCoverage"))}</h2>
          <table class="detail-meta">
            <tbody>
              <tr><th>${escapeHtml(t(locale, "canonicalPilot"))}</th><td>${renderCoverage["canonical-pilot"] || 0}</td></tr>
              <tr><th>${escapeHtml(t(locale, "officialMarkdown"))}</th><td>${renderCoverage["official-text"] || 0}</td></tr>
              <tr><th>TVPL</th><td>${renderCoverage.tvpl || 0}</td></tr>
              <tr><th>${escapeHtml(t(locale, "wikiFallback"))}</th><td>${renderCoverage.wiki || 0}</td></tr>
            </tbody>
          </table>
        </div>
      </aside>
      <main class="panel content">
        <h2>${escapeHtml(t(locale, "corpusTable"))}</h2>
        <p>${escapeHtml(t(locale, "corpusTableHelp"))}</p>
        ${renderDocumentsTable(documents, locale, { mode: "overview" })}
      </main>
    </div>
  `;

  return renderLayout(t(locale, "homeTitle"), body, locale, {
    currentPath: "/",
  });
}

function renderSearchPage(documents, query, locale) {
  const filtered = filterDocuments(documents, query);
  const body = `
    <section class="workspace-topbar">
      <div>
        <h1>${escapeHtml(t(locale, "searchPageTitle"))}</h1>
        <p>${escapeHtml(t(locale, "searchPageSubtitle"))}</p>
        <div class="nav">
          <a href="${buildHref("/", locale)}">${escapeHtml(t(locale, "homeTitle"))}</a>
          <a href="${buildHref("/index", locale)}">${escapeHtml(t(locale, "pilotIndex"))}</a>
          <a href="${buildHref("/lookup-system", locale)}">${escapeHtml(t(locale, "lookupSystem"))}</a>
        </div>
      </div>
      <div class="workspace-topbar-meta">
        <span class="summary-chip"><strong>${filtered.length}</strong> / ${documents.length}</span>
      </div>
    </section>
    <div class="grid">
      <aside class="rail">
        <div>
          <h2>${escapeHtml(t(locale, "searchTitle"))}</h2>
          <form class="search" method="get" action="/search">
            ${locale !== "vi" ? `<input type="hidden" name="lang" value="${escapeHtml(locale)}" />` : ""}
            <input type="search" name="q" value="${escapeHtml(query)}" placeholder="${escapeHtml(t(locale, "searchPlaceholder"))}" />
            <button type="submit">${escapeHtml(t(locale, "searchButton"))}</button>
          </form>
          <div class="count">${filtered.length} / ${documents.length}</div>
          <div class="meta">${escapeHtml(t(locale, "searchHelp"))}</div>
        </div>
        <div class="summary-strip">
          <span class="summary-chip"><strong>${filtered.filter((document) => document.renderSource.sourceId === "canonical-pilot").length}</strong> ${escapeHtml(t(locale, "canonicalPilot").toLowerCase())}</span>
          <span class="summary-chip"><strong>${filtered.filter((document) => document.renderSource.sourceId === "official-text").length}</strong> ${escapeHtml(t(locale, "officialMarkdown").toLowerCase())}</span>
          <span class="summary-chip"><strong>${filtered.filter((document) => document.renderSource.sourceId === "wiki").length}</strong> ${escapeHtml(t(locale, "wikiFallback").toLowerCase())}</span>
        </div>
        <ul class="doc-list">
          ${renderDocumentList(filtered, locale)}
        </ul>
      </aside>
      <main class="panel content">
        <h2>${escapeHtml(t(locale, "corpusTable"))}</h2>
        <p>${escapeHtml(t(locale, "corpusTableHelp"))}</p>
        ${renderDocumentsTable(filtered, locale, { mode: "full" })}
      </main>
    </div>
  `;

  return renderLayout(t(locale, "searchPageTitle"), body, locale, {
    currentPath: "/search",
  });
}

function renderMetadataTable(document, locale) {
  const rows = [
    [metadataLabel(locale, "issuedDate"), document.issuedDate || t(locale, "unknown")],
    [metadataLabel(locale, "issuingUnit"), document.issuingUnit || t(locale, "unknown")],
    [metadataLabel(locale, "formType"), document.formType || t(locale, "unknown")],
    [metadataLabel(locale, "extractionQuality"), localizedQuality(locale, document.extractionAudit?.quality)],
  ];

  return `
    <section class="inspector-section">
      <h2 class="inspector-title">${escapeHtml(t(locale, "metadata"))}</h2>
      <div class="fact-list">
        ${rows.map(([label, value]) => `
          <div class="fact-item">
            <div class="fact-label">${escapeHtml(label)}</div>
            <div class="fact-value">${escapeHtml(value)}</div>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

async function renderDocumentPage(document, locale) {
  const markdownExists = await fileExists(document.renderSource.path);
  const html = markdownExists
    ? await runPandoc(document.renderSource.path)
    : `<p class="empty">${locale === "vi" ? "Không tìm thấy markdown file để render tại" : "Markdown file not found for render at"} ${escapeHtml(document.renderSource.path)}.</p>`;
  const supplementalArtifacts = selectSupplementalArtifacts(await loadExtractionArtifacts(document.extractionPath));
  const supplementalHtml = renderSupplementalArtifacts(supplementalArtifacts, locale);
  const summary = [
    document.issuedDate,
    document.issuingUnit,
    document.formType,
  ].filter(Boolean).join(" · ") || t(locale, "documentDetailTitle");

  const body = `
    <section class="document-header">
      <div class="document-header-head">
        <div class="document-chip-row">
          <span class="document-code">${escapeHtml(document.issueCode)}</span>
          <span class="document-chip"><span class="document-chip-label">${escapeHtml(t(locale, "viewingFrom"))}:</span> ${escapeHtml(localizedPreferredSource(locale, document.preferredTextSource?.sourceId, document))}</span>
          <span class="document-chip"><span class="document-chip-label">${escapeHtml(t(locale, "qualityState"))}:</span> ${escapeHtml(localizedQuality(locale, document.extractionAudit?.quality))}</span>
        </div>
        <h1 class="document-title">${escapeHtml(document.title)}</h1>
        <div class="document-meta-row">
          ${summary.split(" · ").map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
        </div>
      </div>
    </section>
    <div class="document-stage">
      <main class="reading-surface content markdown-frame">${html}${supplementalHtml}</main>
      <aside class="inspector">
        ${renderMetadataTable(document, locale)}
        ${renderSourceLinksPanel(document, locale)}
      </aside>
    </div>
  `;

  return renderLayout(`${document.issueCode} - ${document.title}`, body, locale, {
    pageClass: "page-document",
    navMode: "document",
    currentPath: `/doc/${document.routeSlug}`,
  });
}

async function renderMarkdownPage(title, filePath, documentPathMap, locale, backHref = "/") {
  const html = rewriteRenderedMarkdownLinks(await runPandoc(filePath), documentPathMap, locale);
  const body = `
    <section class="workspace-topbar">
      <div>
        <h1>${escapeHtml(title)}</h1>
        <p>${escapeHtml(t(locale, "markdownReference"))}</p>
        <div class="nav">
          <a href="${buildHref(backHref, locale)}">${escapeHtml(t(locale, "backToCorpus"))}</a>
        </div>
      </div>
      <div class="workspace-topbar-meta">
        <span class="summary-chip"><strong>Markdown</strong> ${escapeHtml(t(locale, "markdownLabel").toLowerCase())}</span>
      </div>
    </section>
    <div class="grid">
      <aside class="rail">
        <div class="panel">
          <h2>${escapeHtml(t(locale, "navLookup"))}</h2>
          <div class="nav">
            <a href="${buildHref("/", locale)}">${escapeHtml(t(locale, "backToCorpus"))}</a>
            <a href="${buildHref("/index", locale)}">${escapeHtml(t(locale, "pilotIndex"))}</a>
            <a href="${buildHref("/lookup-system", locale)}">${escapeHtml(t(locale, "lookupSystem"))}</a>
            <a href="${buildHref("/about", locale)}">${escapeHtml(t(locale, "legalWorkspace"))}</a>
          </div>
        </div>
        <div class="panel">
          <h2>${escapeHtml(t(locale, "sourcePath"))}</h2>
          <div class="meta mono">${escapeHtml(filePath.replace(`${ROOT}/`, ""))}</div>
        </div>
      </aside>
      <main class="panel content markdown-frame">${html}</main>
    </div>
  `;
  return renderLayout(title, body, locale, {
    currentPath: backHref === "/" ? "/" : backHref,
  });
}

async function renderRawSourcePage(title, filePath, locale, backHref = "/") {
  const extension = path.extname(filePath || "").toLowerCase();
  const rawText = await fs.readFile(filePath, "utf8");
  let bodyText = rawText;

  if (extension === ".json") {
    try {
      bodyText = JSON.stringify(JSON.parse(rawText), null, 2);
    } catch {
      bodyText = rawText;
    }
  }

  const body = `
    <section class="workspace-topbar">
      <div>
        <h1>${escapeHtml(title)}</h1>
        <p>${escapeHtml(t(locale, "sourceCompareHelp"))}</p>
        <div class="nav">
          <a href="${buildHref(backHref, locale)}">${escapeHtml(t(locale, "backToCorpus"))}</a>
        </div>
      </div>
      <div class="workspace-topbar-meta">
        <span class="summary-chip"><strong>Raw</strong> ${escapeHtml(t(locale, "source").toLowerCase())}</span>
      </div>
    </section>
    <div class="grid">
      <aside class="rail">
        <div class="panel">
          <h2>${escapeHtml(t(locale, "sourcePath"))}</h2>
          <div class="meta mono">${escapeHtml(filePath.replace(`${ROOT}/`, ""))}</div>
        </div>
      </aside>
      <main class="panel content"><pre>${escapeHtml(bodyText)}</pre></main>
    </div>
  `;
  return renderLayout(title, body, locale, {
    currentPath: backHref === "/" ? "/" : backHref,
  });
}

function sendHtml(res, html, statusCode = 200) {
  res.writeHead(statusCode, { "content-type": "text/html; charset=utf-8" });
  res.end(html);
}

async function sendBinaryFile(res, filePath) {
  const stat = await fs.stat(filePath);
  res.writeHead(200, {
    "content-type": binaryContentType(filePath),
    "content-length": stat.size,
    "content-disposition": `inline; filename="${path.basename(filePath).replaceAll('"', "")}"`,
  });
  await new Promise((resolve, reject) => {
    const stream = createReadStream(filePath);
    stream.on("error", reject);
    stream.on("end", resolve);
    stream.pipe(res);
  });
}

function sendNotFound(res, locale, message = "Not found") {
  sendHtml(
    res,
    renderLayout(t(locale, "notFound"), `<section class="workspace-topbar"><div><h1>${escapeHtml(t(locale, "notFound"))}</h1><p>${escapeHtml(message)}</p><div class="nav"><a href="${buildHref("/", locale)}">${escapeHtml(t(locale, "backToCorpus"))}</a></div></div></section>`, locale),
    404,
  );
}

export async function createLegalLookupServerData() {
  const registryData = await loadRegistryDocuments();
  const documentPathMap = new Map();
  for (const document of registryData.documents) {
    documentPathMap.set(path.resolve(document.renderSource.path), `/doc/${document.routeSlug}`);
    if (document.officialMarkdownPath) {
      documentPathMap.set(path.resolve(document.officialMarkdownPath), `/doc/${document.routeSlug}`);
    }
    if (document.extractionPath) {
      documentPathMap.set(path.resolve(document.extractionPath), `/doc/${document.routeSlug}`);
    }
  }
  return {
    ...registryData,
    documentMap: new Map(registryData.documents.map((document) => [document.routeSlug, document])),
    documentPathMap,
  };
}

export function createLegalLookupServer({ documents, counts, documentMap, documentPathMap }) {
  return http.createServer(async (req, res) => {
    try {
      const requestUrl = new URL(req.url, `http://${req.headers.host || `${HOST}:${PORT}`}`);
      const locale = resolveLocale(requestUrl.searchParams.get("lang"));

      if (requestUrl.pathname === "/") {
        sendHtml(res, renderHome(documents, counts, requestUrl.searchParams.get("q") || "", locale));
        return;
      }

      if (requestUrl.pathname === "/search") {
        sendHtml(res, renderSearchPage(documents, requestUrl.searchParams.get("q") || "", locale));
        return;
      }

      if (requestUrl.pathname === "/index") {
        sendHtml(res, await renderMarkdownPage(t(locale, "pilotIndex"), CANONICAL_INDEX_PATH, documentPathMap, locale));
        return;
      }

      if (requestUrl.pathname === "/lookup-system") {
        sendHtml(res, await renderMarkdownPage(t(locale, "lookupSystem"), LOOKUP_DOC_PATH, documentPathMap, locale));
        return;
      }

      if (requestUrl.pathname === "/about") {
        sendHtml(res, await renderMarkdownPage(t(locale, "legalWorkspace"), LEGAL_README_PATH, documentPathMap, locale));
        return;
      }

      if (requestUrl.pathname.startsWith("/source/")) {
        const segments = requestUrl.pathname.split("/").filter(Boolean);
        const slug = decodeURIComponent(segments[1] || "");
        const kind = segments[2] || "";
        const document = documentMap.get(slug);

        if (!document) {
          sendNotFound(res, locale, locale === "vi" ? `Không có document cho slug ${slug}` : `No document found for slug ${slug}`);
          return;
        }

        let sourceAsset = null;
        if (kind === "attachment") {
          const attachmentIndex = Number.parseInt(segments[3] || "", 10);
          const attachment = Number.isInteger(attachmentIndex) ? document.attachmentFiles?.[attachmentIndex] : null;
          sourceAsset = attachment ? {
            type: "binary",
            path: attachment.path,
            title: attachment.label,
            contentType: binaryContentType(attachment.path),
          } : null;
        } else {
          sourceAsset = resolveDocumentSourceAsset(document, kind);
        }
        if (!sourceAsset || !await fileExists(sourceAsset.path)) {
          sendNotFound(res, locale, locale === "vi" ? `Không có source ${kind} cho ${slug}` : `No source ${kind} found for ${slug}`);
          return;
        }

        if (sourceAsset.type === "markdown") {
          sendHtml(res, await renderMarkdownPage(`${document.issueCode} - ${sourceAsset.title}`, sourceAsset.path, documentPathMap, locale, `/doc/${encodeURIComponent(document.routeSlug)}`));
          return;
        }

        if (sourceAsset.type === "binary") {
          await sendBinaryFile(res, sourceAsset.path);
          return;
        }

        sendHtml(res, await renderRawSourcePage(`${document.issueCode} - ${sourceAsset.title}`, sourceAsset.path, locale, `/doc/${encodeURIComponent(document.routeSlug)}`));
        return;
      }

      if (requestUrl.pathname.startsWith("/doc/")) {
        const slug = decodeURIComponent(requestUrl.pathname.slice("/doc/".length));
        const document = documentMap.get(slug);

        if (!document) {
          sendNotFound(res, locale, locale === "vi" ? `Không có document cho slug ${slug}` : `No document found for slug ${slug}`);
          return;
        }

        sendHtml(res, await renderDocumentPage(document, locale));
        return;
      }

      sendNotFound(res, locale);
    } catch (error) {
      const locale = "vi";
      sendHtml(
        res,
        renderLayout(t(locale, "serverError"), `<section class="workspace-topbar"><div><h1>${escapeHtml(t(locale, "serverError"))}</h1><p>${escapeHtml(t(locale, "serverErrorMeta"))}</p></div></section><div class="panel content"><pre>${escapeHtml(error instanceof Error ? error.stack || error.message : String(error))}</pre></div>`, locale),
        500,
      );
    }
  });
}

async function main() {
  const serverData = await createLegalLookupServerData();
  const server = createLegalLookupServer(serverData);
  server.listen(PORT, HOST, () => {
    console.log(`CO legal lookup server listening on http://${HOST}:${PORT}`);
  });
}

const entryPath = process.argv[1] ? path.resolve(process.argv[1]) : null;
const isMain = entryPath === fileURLToPath(import.meta.url);

if (isMain) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.stack : String(error));
    process.exitCode = 1;
  });
}
