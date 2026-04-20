import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

const BASE_URL = "https://ecosys.gov.vn";
const LISTING_URL = `${BASE_URL}/Homepage/DocumentView.aspx`;
const ROOT_DIR = path.join(process.cwd(), "data", "legal", "official-mirror", "ecosys");
const PAGES_DIR = path.join(ROOT_DIR, "documentview-pages");
const DOWNLOADS_DIR = path.join(ROOT_DIR, "downloads");
const MANIFEST_PATH = path.join(ROOT_DIR, "manifest.json");
const MANIFEST_VERSION = 2;

function decodeHtml(value) {
  return value
    .replace(/&#(\d+);/g, (_, num) => String.fromCharCode(Number(num)))
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ");
}

function cleanText(value) {
  return decodeHtml(
    value
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim(),
  );
}

function slugify(value) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

function buildDocumentId(relativeUrl) {
  return createHash("sha1").update(relativeUrl).digest("hex").slice(0, 16);
}

function extractHiddenField(html, name) {
  const pattern = new RegExp(`<input type="hidden" name="${name}" id="${name}" value="([\\s\\S]*?)" \\/?>`);
  const match = html.match(pattern);
  return match ? decodeHtml(match[1]) : "";
}

function parseRows(html) {
  const tableMatch = html.match(/<table[\s\S]*?id="ctl00_cplhContent_gridDocument"[\s\S]*?>([\s\S]*?)<\/table>/);
  if (!tableMatch) {
    return [];
  }

  const rows = [];
  const rowPattern = /<tr>([\s\S]*?)<\/tr>/g;

  for (const match of tableMatch[1].matchAll(rowPattern)) {
    const rowHtml = match[1];
    if (!rowHtml.includes('href="/Documents/') && !rowHtml.includes('href="/Public/')) {
      continue;
    }

    const cells = [...rowHtml.matchAll(/<td\b[\s\S]*?>([\s\S]*?)<\/td>/g)].map((cell) => cleanText(cell[1]));
    const hrefMatch = rowHtml.match(/<a href="([^"]+)"/);

    if (!hrefMatch || cells.length < 6) {
      continue;
    }

    const stt = Number(cells[0]);
    const issueCode = cells[1];
    const formType = cells[2];
    const title = cells[3];
    const issuingUnit = cells[4];
    const issuedDate = cells[5];
    const relativeUrl = decodeHtml(hrefMatch[1]);

    rows.push({
      documentId: buildDocumentId(relativeUrl),
      stt,
      issueCode,
      formType,
      title,
      issuingUnit,
      issuedDate,
      relativeUrl,
      absoluteUrl: new URL(relativeUrl, BASE_URL).toString(),
      sourcePageSlug: slugify(`${stt}-${issueCode}-${title}`),
    });
  }

  return rows;
}

function getPageState(html) {
  return {
    __VIEWSTATE: extractHiddenField(html, "__VIEWSTATE"),
    __VIEWSTATEGENERATOR: extractHiddenField(html, "__VIEWSTATEGENERATOR"),
    __EVENTVALIDATION: extractHiddenField(html, "__EVENTVALIDATION"),
    __PREVIOUSPAGE: extractHiddenField(html, "__PREVIOUSPAGE"),
  };
}

async function fetchText(url, options = {}) {
  const response = await fetch(url, {
    redirect: "follow",
    headers: {
      "user-agent": "Mozilla/5.0",
      ...options.headers,
    },
    method: options.method ?? "GET",
    body: options.body,
  });

  if (!response.ok) {
    throw new Error(`Request failed for ${url}: ${response.status} ${response.statusText}`);
  }

  return response.text();
}

async function fetchBuffer(url) {
  const response = await fetch(url, {
    redirect: "follow",
    headers: {
      "user-agent": "Mozilla/5.0",
    },
  });

  if (!response.ok) {
    throw new Error(`Download failed for ${url}: ${response.status} ${response.statusText}`);
  }

  const arrayBuffer = await response.arrayBuffer();
  return Buffer.from(arrayBuffer);
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

async function savePage(pageNumber, html) {
  const filename = `page-${String(pageNumber).padStart(3, "0")}.html`;
  await fs.writeFile(path.join(PAGES_DIR, filename), html);
}

function buildPostBody(pageState) {
  const form = new URLSearchParams();
  form.set("__EVENTTARGET", "ctl00$cplhContent$gridDocument");
  form.set("__EVENTARGUMENT", "Page$Next");
  form.set("__LASTFOCUS", "");
  form.set("__VIEWSTATE", pageState.__VIEWSTATE);
  form.set("__VIEWSTATEGENERATOR", pageState.__VIEWSTATEGENERATOR);
  form.set("__EVENTVALIDATION", pageState.__EVENTVALIDATION);
  if (pageState.__PREVIOUSPAGE) {
    form.set("__PREVIOUSPAGE", pageState.__PREVIOUSPAGE);
  }
  form.set("ctl00$cplhContent$txtKeyword", "");
  form.set("ctl00$cplhContent$cmbFormCO", "-1");
  return form.toString();
}

async function scrapeAllPages() {
  const seenUrls = new Set();
  const pages = [];
  let pageNumber = 1;
  let html = await fetchText(LISTING_URL);

  while (true) {
    await savePage(pageNumber, html);
    const rows = parseRows(html);
    if (rows.length === 0) {
      throw new Error(`No document rows found on page ${pageNumber}`);
    }

    const newRows = rows.filter((row) => !seenUrls.has(row.relativeUrl));
    newRows.forEach((row) => seenUrls.add(row.relativeUrl));

    pages.push({
      pageNumber,
      rowCount: rows.length,
      rows: newRows,
    });

    const hasNext = html.includes("Page$Next");
    if (!hasNext) {
      break;
    }

    const pageState = getPageState(html);
    html = await fetchText(LISTING_URL, {
      method: "POST",
      headers: {
        "content-type": "application/x-www-form-urlencoded",
        referer: LISTING_URL,
      },
      body: buildPostBody(pageState),
    });
    pageNumber += 1;
  }

  return pages.flatMap((page) => page.rows);
}

async function downloadDocument(document) {
  const targetPath = path.join(DOWNLOADS_DIR, document.relativeUrl.replace(/^\//, ""));
  await ensureDir(path.dirname(targetPath));

  const buffer = await fetchBuffer(document.absoluteUrl);
  await fs.writeFile(targetPath, buffer);

  const hash = createHash("sha256").update(buffer).digest("hex");

  return {
    ...document,
    localPath: targetPath,
    sizeBytes: buffer.length,
    sha256: hash,
    downloadedAt: new Date().toISOString(),
  };
}

async function main() {
  await ensureDir(PAGES_DIR);
  await ensureDir(DOWNLOADS_DIR);

  const documents = await scrapeAllPages();
  const downloaded = [];

  for (const document of documents) {
    const result = await downloadDocument(document);
    downloaded.push(result);
    console.log(`${document.issueCode} -> ${document.relativeUrl}`);
  }

  const manifest = {
    manifestVersion: MANIFEST_VERSION,
    source: {
      site: "ecosys.gov.vn",
      listingUrl: LISTING_URL,
      mirroredAt: new Date().toISOString(),
    },
    counts: {
      documents: downloaded.length,
    },
    documents: downloaded,
  };

  await fs.writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(`Mirrored ${downloaded.length} documents to ${ROOT_DIR}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
