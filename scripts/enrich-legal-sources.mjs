import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { shouldResolveFallbackTextSource } from "./lib/legal-source-resolution.mjs";
import { TvplBrowserClient } from "./lib/tvpl-browser-client.mjs";
import {
  buildVntrSearchUrl,
  extractVbplContentFragment,
  extractVntrCsrfToken,
  extractVntrSearchEntriesFromHtml,
  getOfficialVbplSeed,
  pickBestVntrSearchEntry,
} from "./lib/legal-official-source-resolution.mjs";

const ROOT = process.cwd();
const MANIFEST_PATH = path.join(ROOT, "data", "legal", "official-mirror", "ecosys", "manifest.json");
const EXTRACTIONS_DIR = path.join(ROOT, "data", "legal", "normalized", "ecosys", "extracted-text");
const NORMALIZED_ROOT = path.join(ROOT, "data", "legal", "normalized", "ecosys");
const SOURCE_ENRICHMENT_PATH = path.join(NORMALIZED_ROOT, "source-enrichment.json");
const OFFICIAL_VNTR_ROOT = path.join(NORMALIZED_ROOT, "source-cache", "official", "vntr");
const OFFICIAL_VNTR_SEARCH_HTML_DIR = path.join(OFFICIAL_VNTR_ROOT, "search-html");
const OFFICIAL_VNTR_JSON_DIR = path.join(OFFICIAL_VNTR_ROOT, "json");
const OFFICIAL_VNTR_MD_DIR = path.join(OFFICIAL_VNTR_ROOT, "markdown");
const OFFICIAL_VBPL_ROOT = path.join(NORMALIZED_ROOT, "source-cache", "official", "vbpl");
const OFFICIAL_VBPL_HTML_DIR = path.join(OFFICIAL_VBPL_ROOT, "html");
const OFFICIAL_VBPL_MD_DIR = path.join(OFFICIAL_VBPL_ROOT, "markdown");
const TVPL_HTML_DIR = path.join(NORMALIZED_ROOT, "source-cache", "tvpl", "html");
const TVPL_MD_DIR = path.join(NORMALIZED_ROOT, "source-cache", "tvpl", "markdown");
const TITLE_STOPWORDS = new Set([
  "thong", "tu", "nghi", "dinh", "quyet", "dinh", "cong", "van", "thong", "bao",
  "quy", "dinh", "sua", "doi", "bo", "sung", "mot", "so", "dieu", "cua",
  "cap", "giay", "chung", "nhan", "xuat", "xu", "hang", "hoa", "theo", "mau",
  "form", "danh", "muc", "co", "quan", "to", "chuc", "ngay", "nam", "bo", "truong",
  "bo", "cong", "thuong",
]);

function slugify(value) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

function buildDocumentId(document) {
  if (document.documentId) {
    return document.documentId;
  }

  return createHash("sha1").update(document.relativeUrl).digest("hex").slice(0, 16);
}

function normalizeText(value) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

function runCommand(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
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
        reject(new Error(`${command} ${args.join(" ")} failed: ${stderr || stdout}`));
        return;
      }
      resolve(stdout);
    });
  });
}

async function fileExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

function buildSearchTerms(document) {
  const titleChunk = document.title.replace(/\s+/g, " ").trim().slice(0, 120);
  const issueCodeWeak = shouldTreatIssueCodeAsWeak(document.issueCode);
  return issueCodeWeak
    ? [titleChunk, `${document.issueCode} ${titleChunk}`]
    : [document.issueCode, `${document.issueCode} ${titleChunk}`, titleChunk];
}

function shouldTreatIssueCodeAsWeak(issueCode) {
  const normalized = normalizeText(issueCode).replace(/\s+/g, "");
  const digits = normalized.match(/\d+/g) || [];
  return digits.length === 0 || normalized.length <= 4;
}

function scoreSearchEntry(document, entry) {
  const issueCompact = normalizeText(document.issueCode).replace(/\s+/g, "");
  const issueCodeWeak = shouldTreatIssueCodeAsWeak(document.issueCode);
  const issueTokens = normalizeText(document.issueCode).split(/\s+/).filter(Boolean);
  const titleTokens = normalizeText(document.title)
    .split(/\s+/)
    .filter((token) => token.length >= 4 && !TITLE_STOPWORDS.has(token))
    .slice(0, 10);
  const haystack = `${normalizeText(entry.title)} ${normalizeText(entry.url)}`;
  const haystackCompact = haystack.replace(/\s+/g, "");

  let score = 0;

  if (issueCompact && haystackCompact.includes(issueCompact)) {
    score += 200;
  }

  for (const token of issueTokens) {
    if (haystack.includes(token)) {
      score += /^\d+$/.test(token) ? 40 : 15;
    }
  }

  for (const token of titleTokens) {
    if (haystack.includes(token)) {
      score += 10;
    }
  }

  const titleMatchCount = titleTokens.filter((token) => haystack.includes(token)).length;
  if (issueCodeWeak && titleMatchCount < 2) {
    score -= 200;
  }

  const numericIssueTokens = issueTokens.filter((token) => /^\d+$/.test(token));
  if (!issueCodeWeak && numericIssueTokens.length > 0 && !numericIssueTokens.every((token) => haystack.includes(token))) {
    score -= 120;
  }

  return score;
}

async function runPandocHtmlFragment(fragmentHtml) {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "tvpl-html-"));
  const tempFile = path.join(tempDir, "fragment.html");
  await fs.writeFile(tempFile, fragmentHtml);

  try {
    const markdown = await new Promise((resolve, reject) => {
      const child = spawn("pandoc", ["-f", "html", "-t", "gfm", tempFile], {
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
          reject(new Error(stderr || stdout || "pandoc failed"));
          return;
        }
        resolve(stdout.trim());
      });
    });

    return markdown;
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
}

function buildCookieHeader(setCookieValues) {
  return setCookieValues
    .map((value) => value.split(";")[0].trim())
    .filter(Boolean)
    .join("; ");
}

async function fetchText(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${url}`);
  }

  return response;
}

async function enrichOfficialTextFromVntr(document) {
  const searchUrl = buildVntrSearchUrl(document);
  const slug = slugify(`${document.issueCode}-${document.title}`);
  const cachedSearchHtmlPath = path.join(OFFICIAL_VNTR_SEARCH_HTML_DIR, `${slug}.html`);
  const cachedJsonPath = path.join(OFFICIAL_VNTR_JSON_DIR, `${slug}.json`);
  const extractedMarkdownPath = path.join(OFFICIAL_VNTR_MD_DIR, `${slug}.md`);

  const searchResponse = await fetchText(searchUrl, {
    headers: {
      "accept-language": "en-US,en;q=0.9,vi;q=0.8",
    },
  });
  const searchHtml = await searchResponse.text();
  await fs.writeFile(cachedSearchHtmlPath, searchHtml);

  const csrfToken = extractVntrCsrfToken(searchHtml);
  const searchEntries = extractVntrSearchEntriesFromHtml(searchHtml);
  const match = pickBestVntrSearchEntry(document, searchEntries);
  if (!csrfToken || !match) {
    return {
      status: "not_found",
      sourceType: "vntr-legal-documents",
      searchUrl,
      cachedSearchHtmlPath,
      detailId: match?.detailId || null,
      resolvedText: {
        status: "unresolved",
        sourceId: "official-text",
        textPath: null,
        format: null,
        rationale: "official_text_source_not_found_in_vntr",
      },
    };
  }

  const detailResponse = await fetchText("https://vntr.moit.gov.vn/legal-documentapi", {
    method: "POST",
    headers: {
      "accept": "application/json, text/javascript, */*; q=0.01",
      "accept-language": "en-US,en;q=0.9,vi;q=0.8",
      "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
      "cookie": buildCookieHeader(searchResponse.headers.getSetCookie()),
      "referer": searchUrl,
      "x-csrf-token": csrfToken,
      "x-requested-with": "XMLHttpRequest",
    },
    body: new URLSearchParams({
      _token: csrfToken,
      id: String(match.detailId),
    }),
  });
  const detailPayload = await detailResponse.json();
  await fs.writeFile(cachedJsonPath, `${JSON.stringify(detailPayload, null, 2)}\n`);

  const preferredHtml = detailPayload.doc_content_vi || detailPayload.summary_vi || "";
  if (!preferredHtml) {
    return {
      status: "found_without_text",
      sourceType: "vntr-legal-documents",
      searchUrl,
      cachedSearchHtmlPath,
      cachedJsonPath,
      detailId: match.detailId,
      detailTitle: detailPayload.title_vi || detailPayload.title_en || match.title,
      resolvedText: {
        status: "unresolved",
        sourceId: "official-text",
        textPath: null,
        format: null,
        rationale: "official_text_detail_has_no_html_content",
      },
    };
  }

  const extractedMarkdown = await runPandocHtmlFragment(preferredHtml);
  await fs.writeFile(extractedMarkdownPath, `${extractedMarkdown}\n`);

  return {
    status: "resolved",
    sourceType: "vntr-legal-documents",
    searchUrl,
    cachedSearchHtmlPath,
    cachedJsonPath,
    extractedMarkdownPath,
    detailId: match.detailId,
    detailTitle: detailPayload.title_vi || detailPayload.title_en || match.title,
    docCodeVi: detailPayload.doc_code_vi || null,
    docCodeEn: detailPayload.doc_code_en || null,
    language: detailPayload.doc_content_vi ? "vi" : "vi-summary",
    resolvedText: {
      status: "resolved",
      sourceId: "official-text",
      textPath: extractedMarkdownPath,
      format: "markdown",
      rationale: "official_text_source_resolved",
    },
  };
}

async function enrichOfficialTextFromVbpl(document) {
  const seed = getOfficialVbplSeed(document);
  if (!seed) {
    return {
      status: "not_configured",
      sourceType: "vbpl-toanvan",
      pageUrl: null,
      resolvedText: {
        status: "unresolved",
        sourceId: "official-text",
        textPath: null,
        format: null,
        rationale: "official_text_source_not_seeded_for_vbpl",
      },
    };
  }

  const slug = slugify(`${document.issueCode}-${document.title}`);
  const cachedHtmlPath = path.join(OFFICIAL_VBPL_HTML_DIR, `${slug}.html`);
  const extractedMarkdownPath = path.join(OFFICIAL_VBPL_MD_DIR, `${slug}.md`);
  const response = await fetchText(seed.pageUrl, {
    headers: {
      "accept-language": "vi,en-US;q=0.9,en;q=0.8",
    },
  });
  const html = await response.text();
  await fs.writeFile(cachedHtmlPath, html);

  const fragment = extractVbplContentFragment(html);
  if (!fragment) {
    return {
      status: "found_without_text",
      sourceType: seed.sourceType,
      pageUrl: seed.pageUrl,
      cachedHtmlPath,
      resolvedText: {
        status: "unresolved",
        sourceId: "official-text",
        textPath: null,
        format: null,
        rationale: "official_text_detail_has_no_vbpl_fragment",
      },
    };
  }

  const extractedMarkdown = await runPandocHtmlFragment(fragment);
  await fs.writeFile(extractedMarkdownPath, `${extractedMarkdown}\n`);

  return {
    status: "resolved",
    sourceType: seed.sourceType,
    pageUrl: seed.pageUrl,
    cachedHtmlPath,
    extractedMarkdownPath,
    resolvedText: {
      status: "resolved",
      sourceId: "official-text",
      textPath: extractedMarkdownPath,
      format: "markdown",
      rationale: "official_text_source_resolved_from_vbpl",
    },
  };
}

async function enrichOfficialText(document) {
  const vntr = await enrichOfficialTextFromVntr(document);
  if (vntr.resolvedText?.status === "resolved") {
    return {
      sourceType: vntr.sourceType,
      pageUrl: vntr.searchUrl,
      vntr,
      vbpl: null,
      resolvedText: vntr.resolvedText,
      extractedMarkdownPath: vntr.extractedMarkdownPath || vntr.resolvedText.textPath,
    };
  }

  const vbpl = await enrichOfficialTextFromVbpl(document);
  const active = vbpl.resolvedText?.status === "resolved" ? vbpl : vntr;

  return {
    sourceType: active.sourceType,
    pageUrl: active.pageUrl || active.searchUrl || null,
    vntr,
    vbpl,
    resolvedText: active.resolvedText,
    extractedMarkdownPath: active.extractedMarkdownPath || active.resolvedText?.textPath || null,
  };
}

async function searchTvpl(browserClient, document) {
  const searchTerms = buildSearchTerms(document);
  let best = null;
  let blocked = null;

  for (const term of searchTerms) {
    const searchResult = await browserClient.search(term);
    if (searchResult.status === "blocked") {
      blocked = {
        ...searchResult,
      };
      continue;
    }
    const entries = searchResult.entries;

    for (const entry of entries) {
      const score = scoreSearchEntry(document, entry);
      if (!best || score > best.score) {
        best = {
          status: "found",
          searchTerm: term,
          pageUrl: entry.url,
          resultTitle: entry.title,
          score,
        };
      }
    }
  }

  const minScore = shouldTreatIssueCodeAsWeak(document.issueCode) ? 40 : 1;
  if (best && best.score >= minScore) {
    return best;
  }

  if (blocked) {
    return blocked;
  }

  return {
    status: "not_found",
  };
}

async function enrichTvpl(document, { officialTextResolved }) {
  if (process.env.SKIP_TVPL === "1") {
    return {
      status: "skipped",
      reason: "tvpl_disabled_by_env",
    };
  }

  if (!shouldResolveFallbackTextSource({ officialTextResolved })) {
    return {
      status: "skipped",
      reason: "official_text_source_already_resolved",
    };
  }

  const browserClient = enrichTvpl.browserClient;
  const search = await searchTvpl(browserClient, document);
  if (search.status !== "found") {
    return search;
  }

  const slug = slugify(`${document.issueCode}-${document.title}`);
  const htmlPath = path.join(TVPL_HTML_DIR, `${slug}.html`);
  const markdownPath = path.join(TVPL_MD_DIR, `${slug}.md`);

  const pageResult = await browserClient.fetchPage(search.pageUrl);
  if (pageResult.status !== "ok") {
    return {
      ...search,
      status: "blocked",
      blocker: pageResult.blocker,
      pageUrl: search.pageUrl,
    };
  }

  await fs.writeFile(htmlPath, pageResult.html);

  const contentHtml = pageResult.contentHtml;
  let extractedMarkdown = "";
  if (contentHtml) {
    extractedMarkdown = await runPandocHtmlFragment(contentHtml);
    await fs.writeFile(markdownPath, `${extractedMarkdown}\n`);
  }

  return {
    ...search,
    cachedHtmlPath: htmlPath,
    extractedMarkdownPath: contentHtml ? markdownPath : null,
    extractedMarkdown,
    extractedStatus: contentHtml ? "ok" : "content_not_found",
    intendedUse: "fallback",
  };
}

async function classifyOfficialExtraction(document) {
  const slug = slugify(`${document.issueCode}-${document.title}`);
  const extractionPath = path.join(EXTRACTIONS_DIR, `${slug}.json`);

  if (!await fileExists(extractionPath)) {
    return { quality: "none" };
  }

  const extraction = JSON.parse(await fs.readFile(extractionPath, "utf8"));
  const artifacts = extraction.artifacts || [];

  if (artifacts.length === 0) {
    return { quality: "none" };
  }

  const weakBodies = artifacts.filter((artifact) =>
    typeof artifact.body === "string" &&
    (
      artifact.body.startsWith("_Legacy .doc") ||
      artifact.body.startsWith("_No extractable") ||
      artifact.body.startsWith("_Extraction failed")
    ),
  ).length;

  if (weakBodies === artifacts.length) {
    return { quality: "weak" };
  }

  return { quality: "rich" };
}

async function main() {
  const manifest = JSON.parse(await fs.readFile(MANIFEST_PATH, "utf8"));
  const filter = process.env.DOC_FILTER?.toLowerCase().trim();
  await ensureDir(path.dirname(SOURCE_ENRICHMENT_PATH));
  await ensureDir(OFFICIAL_VNTR_SEARCH_HTML_DIR);
  await ensureDir(OFFICIAL_VNTR_JSON_DIR);
  await ensureDir(OFFICIAL_VNTR_MD_DIR);
  await ensureDir(OFFICIAL_VBPL_HTML_DIR);
  await ensureDir(OFFICIAL_VBPL_MD_DIR);
  await ensureDir(TVPL_HTML_DIR);
  await ensureDir(TVPL_MD_DIR);

  const existing = await fileExists(SOURCE_ENRICHMENT_PATH)
    ? JSON.parse(await fs.readFile(SOURCE_ENRICHMENT_PATH, "utf8"))
    : { schemaVersion: 1, documents: {} };

  const output = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    policy: "official-first, TVPL fallback for digitalized internal lookup",
    documents: existing.documents || {},
  };
  const browserClient = new TvplBrowserClient();
  enrichTvpl.browserClient = browserClient;

  try {
    for (const document of manifest.documents) {
      if (filter) {
        const issueCode = document.issueCode.toLowerCase();
        const title = document.title.toLowerCase();
        if (issueCode !== filter && !title.includes(filter)) {
          continue;
        }
      }

      const documentId = buildDocumentId(document);
      const officialExtraction = await classifyOfficialExtraction(document);
      const officialResolved = await enrichOfficialText(document);
      const tvpl = await enrichTvpl(document, {
        officialTextResolved: officialResolved.resolvedText?.status === "resolved",
      });

      output.documents[documentId] = {
        documentId,
        issueCode: document.issueCode,
        title: document.title,
        official: {
          sourceType: officialResolved.sourceType || "ecosys-official-mirror",
          pageUrl: officialResolved.pageUrl || document.absoluteUrl,
          extractionQuality: officialExtraction.quality,
          vntr: officialResolved.vntr || null,
          vbpl: officialResolved.vbpl || null,
          resolvedText: officialResolved.resolvedText,
        },
        tvpl,
        preferredTextSource: officialResolved.resolvedText?.status === "resolved"
          ? "official-text"
          : (tvpl.status === "found" ? "tvpl" : "official"),
      };

      console.log(`${document.issueCode} -> ${output.documents[documentId].preferredTextSource}${officialResolved.extractedMarkdownPath ? ` (${officialResolved.extractedMarkdownPath})` : (tvpl.pageUrl ? ` (${tvpl.pageUrl})` : "")}`);
    }

    await fs.writeFile(SOURCE_ENRICHMENT_PATH, `${JSON.stringify(output, null, 2)}\n`);
  } finally {
    await browserClient.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
