import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

import { buildOcrOutputPaths } from "./lib/legal-ocr-recovery.mjs";
import { getOfficialVbplSeed } from "./lib/legal-official-source-resolution.mjs";
import {
  buildFusionReadiness,
  buildPacketTextLanes,
  summarizeAttachmentInventory,
} from "./lib/legal-source-packets.mjs";

const ROOT = process.cwd();
const MANIFEST_PATH = path.join(ROOT, "data", "legal", "official-mirror", "ecosys", "manifest.json");
const ENRICHMENT_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "source-enrichment.json");
const REGISTRY_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "text-source-registry.json");
const ATTACHMENTS_DIR = path.join(ROOT, "data", "legal", "normalized", "ecosys", "attachments");
const CANONICAL_PILOT_DIR = path.join(ROOT, "docs", "legal", "canonical", "pilot");
const CANONICAL_CORPUS_DIR = path.join(ROOT, "docs", "legal", "canonical", "corpus");
const TVPL_HTML_DIR = path.join(ROOT, "data", "legal", "normalized", "ecosys", "source-cache", "tvpl", "html");
const TVPL_MD_DIR = path.join(ROOT, "data", "legal", "normalized", "ecosys", "source-cache", "tvpl", "markdown");
const PACKETS_DIR = path.join(ROOT, "data", "legal", "normalized", "ecosys", "source-packets");
const PACKETS_JSON_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "source-packets.json");
const PACKETS_MD_PATH = path.join(ROOT, "docs", "legal", "indexes", "source-packets.md");

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

async function fileExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

async function loadJson(filePath, fallback) {
  if (!await fileExists(filePath)) {
    return fallback;
  }

  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

async function listAttachmentFiles(issueCode, title) {
  const attachmentRoot = path.join(ATTACHMENTS_DIR, slugify(`${issueCode}-${title}`));
  if (!await fileExists(attachmentRoot)) {
    return [];
  }

  const files = [];
  const queue = [attachmentRoot];
  while (queue.length > 0) {
    const dirPath = queue.shift();
    const entries = await fs.readdir(dirPath, { withFileTypes: true });
    for (const entry of entries) {
      const nextPath = path.join(dirPath, entry.name);
      if (entry.isDirectory()) {
        queue.push(nextPath);
      } else {
        files.push({
          path: nextPath,
          relativePath: path.relative(attachmentRoot, nextPath),
          extension: path.extname(entry.name).toLowerCase(),
        });
      }
    }
  }

  files.sort((left, right) => left.relativePath.localeCompare(right.relativePath));
  return files;
}

async function buildCanonicalMap() {
  const map = new Map();
  for (const canonicalDir of [CANONICAL_CORPUS_DIR, CANONICAL_PILOT_DIR]) {
    if (!await fileExists(canonicalDir)) {
      continue;
    }

    const fileNames = await fs.readdir(canonicalDir);
    for (const fileName of fileNames) {
      if (!fileName.endsWith(".md")) {
        continue;
      }

      const filePath = path.join(canonicalDir, fileName);
      const body = await fs.readFile(filePath, "utf8");
      const match = body.match(/^#\s+(.+?)(?:\s+-\s+.+)?$/m)
        || body.match(/\|\s*Issue Code\s*\|\s*(.+?)\s*\|/i);
      if (match && !map.has(match[1].trim())) {
        map.set(match[1].trim(), filePath);
      }
    }
  }

  return map;
}

async function resolveTvplCache(document, enrichmentEntry) {
  const slug = slugify(`${document.issueCode}-${document.title}`);
  const cachedHtmlPath = path.join(TVPL_HTML_DIR, `${slug}.html`);
  const extractedMarkdownPath = path.join(TVPL_MD_DIR, `${slug}.md`);
  const hasHtmlCache = await fileExists(cachedHtmlPath);
  const hasMarkdown = await fileExists(extractedMarkdownPath);

  let pageUrl = enrichmentEntry.tvpl?.pageUrl || null;
  if (!pageUrl && hasHtmlCache) {
    const html = await fs.readFile(cachedHtmlPath, "utf8");
    pageUrl = html.match(/<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)["']/i)?.[1] || null;
  }

  return {
    status: enrichmentEntry.tvpl?.status || (hasHtmlCache || hasMarkdown ? "cached" : "not_found"),
    pageUrl,
    cachedHtmlPath: hasHtmlCache ? cachedHtmlPath : null,
    extractedMarkdownPath: hasMarkdown ? extractedMarkdownPath : null,
  };
}

function buildSourceCoverageLabels({
  vbplResolved,
  vntrResolved,
  tvplAvailable,
  attachmentSummary,
}) {
  const labels = [];

  if (vbplResolved) {
    labels.push("VBPL");
  }
  if (vntrResolved) {
    labels.push("VNTR");
  }
  if (tvplAvailable) {
    labels.push("TVPL");
  }
  labels.push("eCoSys");
  if (attachmentSummary.textFormats.length > 0) {
    labels.push(`Attachments: ${attachmentSummary.mixedTextFormatLabel}`);
  }

  return labels;
}

function summarize(records) {
  return {
    documents: records.length,
    withOfficialResolved: records.filter((record) => record.packet.official.anyResolved).length,
    withVbplResolved: records.filter((record) => record.packet.official.vbpl.resolved).length,
    withVntrResolved: records.filter((record) => record.packet.official.vntr.resolved).length,
    withTvplCached: records.filter((record) => record.packet.tvpl.cachedHtmlPath || record.packet.tvpl.extractedMarkdownPath).length,
    withAttachmentTree: records.filter((record) => record.packet.ecosys.attachments.available).length,
    withAttachmentTextSource: records.filter((record) => record.packet.ecosys.attachments.summary.textFormats.length > 0).length,
    withOcr: records.filter((record) => record.packet.ocr.available).length,
    withCanonical: records.filter((record) => record.packet.canonical.available).length,
    readyForFusion: records.filter((record) => record.packet.fusion.status === "ready_for_fusion").length,
    partialPacket: records.filter((record) => record.packet.fusion.status === "partial_packet").length,
    sourceIncomplete: records.filter((record) => record.packet.fusion.status === "source_incomplete").length,
    canonicalExists: records.filter((record) => record.packet.fusion.status === "canonical_exists").length,
  };
}

async function main() {
  const manifest = await loadJson(MANIFEST_PATH, null);
  if (!manifest) {
    throw new Error("Missing eCoSys manifest. Run npm run mirror:ecosys-docs first.");
  }

  const enrichment = await loadJson(ENRICHMENT_PATH, { documents: {} });
  const registry = await loadJson(REGISTRY_PATH, { documents: [] });
  const registryByIssueCode = new Map((registry.documents || []).map((entry) => [entry.issueCode, entry]));
  const canonicalMap = await buildCanonicalMap();

  await ensureDir(PACKETS_DIR);
  await ensureDir(path.dirname(PACKETS_JSON_PATH));
  await ensureDir(path.dirname(PACKETS_MD_PATH));

  const records = [];

  for (const document of manifest.documents) {
    const documentId = buildDocumentId(document);
    const packetSlug = slugify(`${document.issueCode}-${document.title}`);
    const enrichmentEntry = enrichment.documents?.[documentId] || {};
    const registryEntry = registryByIssueCode.get(document.issueCode) || null;
    const officialCandidate = registryEntry?.textCandidates?.find((candidate) => candidate.sourceId === "official-text") || null;
    const tvplCandidate = registryEntry?.textCandidates?.find((candidate) => candidate.sourceId === "tvpl") || null;
    const extractionCandidate = registryEntry?.textCandidates?.find((candidate) => candidate.sourceId === "ecosys-extracted") || null;
    const attachmentFiles = await listAttachmentFiles(document.issueCode, document.title);
    const attachmentSummary = summarizeAttachmentInventory(attachmentFiles);
    const tvplCache = await resolveTvplCache(document, enrichmentEntry);
    const { outputPath: ocrPath } = buildOcrOutputPaths(ROOT, document.issueCode, document.title);
    const ocrAvailable = await fileExists(ocrPath);
    const canonicalPath = canonicalMap.get(document.issueCode) || null;
    const vbplSeed = getOfficialVbplSeed(document);

    const textLanes = buildPacketTextLanes({
      vbplAvailable: enrichmentEntry.official?.vbpl?.status === "resolved",
      vntrAvailable: enrichmentEntry.official?.vntr?.status === "resolved",
      tvplAvailable: Boolean(tvplCache.extractedMarkdownPath || tvplCache.cachedHtmlPath),
      ocrAvailable,
      ecosysExtractAvailable: extractionCandidate?.status === "resolved",
      canonicalAvailable: Boolean(canonicalPath),
    });

    const fusion = buildFusionReadiness({
      officialResolved: enrichmentEntry.official?.vbpl?.status === "resolved"
        || enrichmentEntry.official?.vntr?.status === "resolved",
      textLaneCount: textLanes.length,
      hasAttachmentTextSource: attachmentSummary.textFormats.length > 0,
      canonicalAvailable: Boolean(canonicalPath),
    });

    const record = {
      documentId,
      issueCode: document.issueCode,
      title: document.title,
      formType: document.formType,
      packetPath: path.join(PACKETS_DIR, `${packetSlug}.json`),
      packet: {
        discovery: {
          sourceType: "ecosys-documentview",
          discoveredFromPage: document.sourcePageSlug,
        },
        official: {
          anyResolved: enrichmentEntry.official?.vbpl?.status === "resolved"
            || enrichmentEntry.official?.vntr?.status === "resolved",
          vbpl: {
            seeded: Boolean(vbplSeed),
            resolved: enrichmentEntry.official?.vbpl?.status === "resolved",
            pageUrl: enrichmentEntry.official?.vbpl?.pageUrl || null,
            cachedHtmlPath: enrichmentEntry.official?.vbpl?.cachedHtmlPath || null,
            extractedMarkdownPath: enrichmentEntry.official?.vbpl?.extractedMarkdownPath || null,
          },
          vntr: {
            searched: Boolean(enrichmentEntry.official?.vntr?.searchUrl || enrichmentEntry.official?.searchUrl),
            resolved: enrichmentEntry.official?.vntr?.status === "resolved",
            searchUrl: enrichmentEntry.official?.vntr?.searchUrl || enrichmentEntry.official?.searchUrl || null,
            detailApiUrl: enrichmentEntry.official?.vntr?.detailApiUrl || enrichmentEntry.official?.detailApiUrl || null,
            detailId: enrichmentEntry.official?.vntr?.detailId || enrichmentEntry.official?.detailId || null,
            cachedSearchHtmlPath: enrichmentEntry.official?.vntr?.cachedSearchHtmlPath || null,
            cachedJsonPath: enrichmentEntry.official?.vntr?.cachedJsonPath || null,
            extractedMarkdownPath: enrichmentEntry.official?.vntr?.extractedMarkdownPath || null,
          },
          preferredOfficialLane: officialCandidate?.sourceProvider || null,
        },
        tvpl: tvplCache,
        ecosys: {
          mirroredFileUrl: document.absoluteUrl,
          localPath: document.localPath,
          fileExtension: path.extname(document.localPath || "").toLowerCase(),
          extraction: {
            available: extractionCandidate?.status === "resolved",
            extractionPath: extractionCandidate?.extractionPath || null,
            quality: extractionCandidate?.quality || null,
            issues: extractionCandidate?.issues || [],
          },
          attachments: {
            available: attachmentSummary.available,
            count: attachmentSummary.count,
            summary: attachmentSummary,
            files: attachmentFiles,
          },
        },
        ocr: {
          available: ocrAvailable,
          textPath: ocrAvailable ? ocrPath : null,
        },
        canonical: {
          available: Boolean(canonicalPath),
          path: canonicalPath,
        },
        textLanes,
        currentBestSourceId: registryEntry?.preferredTextSource?.sourceId || null,
        currentBestStatus: registryEntry?.preferredTextSource?.status || null,
        sourceCoverage: buildSourceCoverageLabels({
          vbplResolved: enrichmentEntry.official?.vbpl?.status === "resolved",
          vntrResolved: enrichmentEntry.official?.vntr?.status === "resolved",
          tvplAvailable: Boolean(tvplCache.extractedMarkdownPath || tvplCache.cachedHtmlPath),
          attachmentSummary,
        }),
        fusion,
      },
    };

    records.push(record);
    await fs.writeFile(record.packetPath, `${JSON.stringify(record, null, 2)}\n`);
  }

  records.sort((left, right) => left.issueCode.localeCompare(right.issueCode));
  const summary = summarize(records);

  const markdownLines = [
    "# Legal Source Packets",
    "",
    `- Documents: ${summary.documents}`,
    `- Official source resolved: ${summary.withOfficialResolved}`,
    `- VBPL resolved: ${summary.withVbplResolved}`,
    `- VNTR resolved: ${summary.withVntrResolved}`,
    `- TVPL cached: ${summary.withTvplCached}`,
    `- Attachment trees: ${summary.withAttachmentTree}`,
    `- Attachment text sources (DOC/DOCX/PDF/...): ${summary.withAttachmentTextSource}`,
    `- OCR available: ${summary.withOcr}`,
    `- Canonical present: ${summary.withCanonical}`,
    `- Ready for fusion: ${summary.readyForFusion}`,
    `- Partial packet: ${summary.partialPacket}`,
    `- Source incomplete: ${summary.sourceIncomplete}`,
    `- Canonical already exists: ${summary.canonicalExists}`,
    "",
    "| Issue Code | Coverage | Text Lanes | Attachment Formats | Current Best | Fusion | Blockers |",
    "| --- | --- | --- | --- | --- | --- | --- |",
  ];

  for (const record of records) {
    const attachmentFormats = [
      ...record.packet.ecosys.attachments.summary.textFormats,
      ...record.packet.ecosys.attachments.summary.supplementalFormats,
    ].join(" + ") || "-";

    markdownLines.push(
      `| ${record.issueCode} | ${record.packet.sourceCoverage.join(", ")} | ${record.packet.textLanes.join(", ") || "-"} | ${attachmentFormats} | ${record.packet.currentBestSourceId || "-"} | ${record.packet.fusion.status} | ${record.packet.fusion.blockers.join(", ") || "-"} |`,
    );
  }

  const output = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    summary,
    records,
  };

  await fs.writeFile(PACKETS_JSON_PATH, `${JSON.stringify(output, null, 2)}\n`);
  await fs.writeFile(PACKETS_MD_PATH, `${markdownLines.join("\n")}\n`);

  console.log(JSON.stringify(summary, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
