import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";

import { getOfficialVbplSeed } from "./lib/legal-official-source-resolution.mjs";

const ROOT = process.cwd();
const MANIFEST_PATH = path.join(ROOT, "data", "legal", "official-mirror", "ecosys", "manifest.json");
const ENRICHMENT_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "source-enrichment.json");
const REGISTRY_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "text-source-registry.json");
const ATTACHMENTS_DIR = path.join(ROOT, "data", "legal", "normalized", "ecosys", "attachments");
const CANONICAL_PILOT_DIR = path.join(ROOT, "docs", "legal", "canonical", "pilot");
const CANONICAL_CORPUS_DIR = path.join(ROOT, "docs", "legal", "canonical", "corpus");
const INVENTORY_JSON_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "source-inventory.json");
const INVENTORY_MD_PATH = path.join(ROOT, "docs", "legal", "indexes", "source-inventory.md");

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

  if (document.relativeUrl) {
    return createHash("sha1").update(document.relativeUrl).digest("hex").slice(0, 16);
  }

  return slugify(`${document.issueCode}-${document.title}`).slice(0, 16);
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
        files.push(nextPath);
      }
    }
  }

  files.sort();
  return files;
}

async function buildCanonicalIssueSet() {
  const issueCodes = new Set();
  for (const canonicalDir of [CANONICAL_PILOT_DIR, CANONICAL_CORPUS_DIR]) {
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
      const issueCodeMatch = body.match(/^#\s+(.+?)(?:\s+-\s+.+)?$/m)
        || body.match(/\|\s*Issue Code\s*\|\s*(.+?)\s*\|/i);
      if (issueCodeMatch) {
        issueCodes.add(issueCodeMatch[1].trim());
      }
    }
  }

  return issueCodes;
}

function buildCoverageLabel(record) {
  const parts = [];
  if (record.sources.vbpl.resolved) {
    parts.push("VBPL");
  } else if (record.sources.vbpl.seeded) {
    parts.push("VBPL?");
  }
  if (record.sources.vntr.resolved) {
    parts.push("VNTR");
  } else if (record.sources.vntr.searched) {
    parts.push("VNTR?");
  }
  if (record.sources.tvpl.resolved) {
    parts.push("TVPL");
  }
  if (record.sources.ecosys.binary) {
    parts.push("eCoSys");
  }
  return parts.join(" + ") || "-";
}

function buildGapFlags(record) {
  const gaps = [];

  if (!record.sources.vbpl.resolved) {
    gaps.push(record.sources.vbpl.seeded ? "vbpl_not_resolved" : "vbpl_not_seeded");
  }
  if (!record.sources.vntr.resolved) {
    gaps.push(record.sources.vntr.searched ? "vntr_not_resolved" : "vntr_not_searched");
  }
  if (!record.canonical.available) {
    gaps.push("canonical_missing");
  }
  if (!record.registry.available) {
    gaps.push("registry_missing");
  }
  if (!record.sources.ecosys.attachmentsAvailable && [".rar", ".zip"].includes(record.sources.ecosys.binaryExtension)) {
    gaps.push("attachments_missing");
  }
  if (!record.sources.officialAnyResolved) {
    gaps.push("official_source_missing");
  }

  return gaps;
}

function summarize(records) {
  return {
    documents: records.length,
    withEcosysBinary: records.filter((record) => record.sources.ecosys.binary).length,
    withAttachments: records.filter((record) => record.sources.ecosys.attachmentsAvailable).length,
    withVntrSearch: records.filter((record) => record.sources.vntr.searched).length,
    withVntrResolved: records.filter((record) => record.sources.vntr.resolved).length,
    withVbplSeed: records.filter((record) => record.sources.vbpl.seeded).length,
    withVbplResolved: records.filter((record) => record.sources.vbpl.resolved).length,
    withBothOfficialResolved: records.filter((record) => record.sources.vntr.resolved && record.sources.vbpl.resolved).length,
    withAnyOfficialResolved: records.filter((record) => record.sources.officialAnyResolved).length,
    withCanonical: records.filter((record) => record.canonical.available).length,
    preferredOfficialText: records.filter((record) => record.registry.preferredSourceId === "official-text").length,
    preferredOcrRecovery: records.filter((record) => record.registry.preferredSourceId === "ocr-recovery").length,
    preferredEcosysExtracted: records.filter((record) => record.registry.preferredSourceId === "ecosys-extracted").length,
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
  const canonicalIssues = await buildCanonicalIssueSet();

  await ensureDir(path.dirname(INVENTORY_JSON_PATH));
  await ensureDir(path.dirname(INVENTORY_MD_PATH));

  const records = [];

  for (const document of manifest.documents) {
    const documentId = buildDocumentId(document);
    const enrichmentEntry = enrichment.documents?.[documentId] || {};
    const registryEntry = registryByIssueCode.get(document.issueCode) || null;
    const attachmentFiles = await listAttachmentFiles(document.issueCode, document.title);
    const vbplSeed = getOfficialVbplSeed(document);
    const record = {
      documentId,
      issueCode: document.issueCode,
      title: document.title,
      formType: document.formType,
      sources: {
        ecosys: {
          binary: Boolean(document.localPath),
          binaryExtension: path.extname(document.localPath || "").toLowerCase(),
          mirroredFileUrl: document.absoluteUrl || null,
          attachmentsAvailable: attachmentFiles.length > 0,
          attachmentCount: attachmentFiles.length,
        },
        vntr: {
          searched: Boolean(enrichmentEntry.official?.vntr?.searchUrl || enrichmentEntry.official?.searchUrl),
          resolved: enrichmentEntry.official?.vntr?.status === "resolved",
          searchUrl: enrichmentEntry.official?.vntr?.searchUrl || enrichmentEntry.official?.searchUrl || null,
          detailId: enrichmentEntry.official?.vntr?.detailId || enrichmentEntry.official?.detailId || null,
          hasJsonCache: Boolean(enrichmentEntry.official?.vntr?.cachedJsonPath),
          hasMarkdown: Boolean(enrichmentEntry.official?.vntr?.extractedMarkdownPath),
        },
        vbpl: {
          seeded: Boolean(vbplSeed),
          resolved: enrichmentEntry.official?.vbpl?.status === "resolved",
          pageUrl: enrichmentEntry.official?.vbpl?.pageUrl || null,
          hasHtmlCache: Boolean(enrichmentEntry.official?.vbpl?.cachedHtmlPath),
          hasMarkdown: Boolean(enrichmentEntry.official?.vbpl?.extractedMarkdownPath),
        },
        tvpl: {
          resolved: enrichmentEntry.tvpl?.status === "found",
          pageUrl: enrichmentEntry.tvpl?.pageUrl || null,
          hasHtmlCache: Boolean(enrichmentEntry.tvpl?.cachedHtmlPath),
          hasMarkdown: Boolean(enrichmentEntry.tvpl?.extractedMarkdownPath),
        },
      },
      registry: {
        available: Boolean(registryEntry),
        preferredSourceId: registryEntry?.preferredTextSource?.sourceId || null,
        preferredSourceStatus: registryEntry?.preferredTextSource?.status || null,
        sourceClassification: registryEntry?.sourceClassification?.sourceType || null,
        quality: registryEntry?.extractionAudit?.quality || null,
      },
      canonical: {
        available: canonicalIssues.has(document.issueCode),
      },
    };

    record.sources.officialAnyResolved = record.sources.vntr.resolved || record.sources.vbpl.resolved;
    record.coverageLabel = buildCoverageLabel(record);
    record.gaps = buildGapFlags(record);
    records.push(record);
  }

  records.sort((left, right) => left.issueCode.localeCompare(right.issueCode));
  const summary = summarize(records);

  const markdownLines = [
    "# Legal Source Inventory",
    "",
    `- Documents: ${summary.documents}`,
    `- eCoSys mirrored binaries: ${summary.withEcosysBinary}`,
    `- Attachment trees present: ${summary.withAttachments}`,
    `- VNTR searched: ${summary.withVntrSearch}`,
    `- VNTR resolved: ${summary.withVntrResolved}`,
    `- VBPL seeded: ${summary.withVbplSeed}`,
    `- VBPL resolved: ${summary.withVbplResolved}`,
    `- Both official sources resolved: ${summary.withBothOfficialResolved}`,
    `- Any official source resolved: ${summary.withAnyOfficialResolved}`,
    `- Canonical pilot available: ${summary.withCanonical}`,
    "",
    "## Coverage Table",
    "",
    "| Issue Code | Form / Group | Coverage | Preferred | Canonical | Gaps |",
    "| --- | --- | --- | --- | --- | --- |",
    ...records.map((record) => `| ${record.issueCode} | ${record.formType || "-"} | ${record.coverageLabel} | ${record.registry.preferredSourceId || "-"} | ${record.canonical.available ? "yes" : "no"} | ${record.gaps.join(", ") || "-"} |`),
  ];

  await fs.writeFile(INVENTORY_JSON_PATH, `${JSON.stringify({
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    summary,
    records,
  }, null, 2)}\n`);
  await fs.writeFile(INVENTORY_MD_PATH, `${markdownLines.join("\n")}\n`);

  console.log(JSON.stringify(summary, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
