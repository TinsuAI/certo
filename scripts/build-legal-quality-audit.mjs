import { promises as fs } from "node:fs";
import path from "node:path";
import {
  auditExtractionArtifacts,
  classifyDocumentSourceType,
} from "./lib/legal-source-audit.mjs";

const ROOT = process.cwd();
const MANIFEST_PATH = path.join(ROOT, "data", "legal", "official-mirror", "ecosys", "manifest.json");
const EXTRACTIONS_DIR = path.join(ROOT, "data", "legal", "normalized", "ecosys", "extracted-text");
const AUDIT_JSON_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "quality-audit.json");
const AUDIT_MD_PATH = path.join(ROOT, "docs", "legal", "indexes", "quality-audit.md");

function slugify(value) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

async function fileExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function loadJson(filePath, fallback) {
  if (!await fileExists(filePath)) {
    return fallback;
  }

  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

function aggregateIssueCounts(documents) {
  const counts = new Map();

  for (const document of documents) {
    for (const issue of document.extractionAudit.issues) {
      counts.set(issue, (counts.get(issue) || 0) + 1);
    }
  }

  return Object.fromEntries([...counts.entries()].sort((a, b) => b[1] - a[1]));
}

function aggregateSourceTypeCounts(documents) {
  const counts = new Map();

  for (const document of documents) {
    counts.set(
      document.sourceClassification.sourceType,
      (counts.get(document.sourceClassification.sourceType) || 0) + 1,
    );
  }

  return Object.fromEntries([...counts.entries()].sort((a, b) => b[1] - a[1]));
}

async function main() {
  const manifest = await loadJson(MANIFEST_PATH, null);
  if (!manifest) {
    throw new Error("Missing eCoSys manifest. Run npm run mirror:ecosys-docs first.");
  }

  await ensureDir(path.dirname(AUDIT_JSON_PATH));
  await ensureDir(path.dirname(AUDIT_MD_PATH));

  const documents = [];

  for (const document of manifest.documents) {
    const slug = slugify(`${document.issueCode}-${document.title}`);
    const extractionPath = path.join(EXTRACTIONS_DIR, `${slug}.json`);
    const extraction = await loadJson(extractionPath, { artifacts: [] });
    const extractionAudit = auditExtractionArtifacts(extraction.artifacts || []);
    const sourceClassification = classifyDocumentSourceType({
      preferredTextSource: {
        sourceId: null,
        status: "unresolved",
      },
      rawBinarySource: {
        fileExtension: path.extname(document.localPath).toLowerCase(),
      },
      extractionAudit,
      officialTextResolved: false,
    });

    documents.push({
      documentId: document.documentId,
      issueCode: document.issueCode,
      title: document.title,
      formType: document.formType,
      rawBinaryExtension: path.extname(document.localPath).toLowerCase(),
      extractionPath: await fileExists(extractionPath) ? extractionPath : null,
      extractionAudit,
      sourceClassification,
    });
  }

  const summary = {
    documents: documents.length,
    ocrCandidates: documents.filter((document) => document.extractionAudit.ocrCandidate).length,
    unresolvedExtractions: documents.filter((document) => document.extractionAudit.status === "unresolved").length,
    noisyExtractions: documents.filter((document) => document.extractionAudit.quality === "noisy").length,
    issueCounts: aggregateIssueCounts(documents),
    sourceTypeCounts: aggregateSourceTypeCounts(documents),
  };

  const markdownLines = [
    "# Legal Quality Audit",
    "",
    `- Documents: ${summary.documents}`,
    `- OCR candidates: ${summary.ocrCandidates}`,
    `- Unresolved extractions: ${summary.unresolvedExtractions}`,
    `- Noisy extractions: ${summary.noisyExtractions}`,
    "",
    "## Source Type Counts",
    "",
    "| Source type | Count |",
    "| --- | ---: |",
    ...Object.entries(summary.sourceTypeCounts).map(([sourceType, count]) => `| ${sourceType} | ${count} |`),
    "",
    "## Issue Counts",
    "",
    "| Issue | Count |",
    "| --- | ---: |",
    ...Object.entries(summary.issueCounts).map(([issue, count]) => `| ${issue} | ${count} |`),
    "",
    "## OCR Candidates",
    "",
    "| Issue Code | Source Type | Raw Extension | Issues |",
    "| --- | --- | --- | --- |",
    ...documents
      .filter((document) => document.extractionAudit.ocrCandidate)
      .map((document) => `| ${document.issueCode} | ${document.sourceClassification.sourceType} | ${document.rawBinaryExtension} | ${document.extractionAudit.issues.join(", ") || "-"} |`),
  ];

  await fs.writeFile(AUDIT_JSON_PATH, `${JSON.stringify({
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    summary,
    documents,
  }, null, 2)}\n`);
  await fs.writeFile(AUDIT_MD_PATH, `${markdownLines.join("\n")}\n`);

  console.log(JSON.stringify(summary, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
