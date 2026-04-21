import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import path from "node:path";
import {
  assessTextPreservationQuality,
  buildPreferredTextSource,
} from "./lib/legal-source-resolution.mjs";
import {
  auditExtractionArtifacts,
  classifyDocumentSourceType,
} from "./lib/legal-source-audit.mjs";
import { buildOcrOutputPaths } from "./lib/legal-ocr-recovery.mjs";
import { normalizeOfficialSourceMetadata } from "./lib/legal-official-source-resolution.mjs";

const ROOT = process.cwd();
const ECOSYS_LISTING_URL = "https://ecosys.gov.vn/Homepage/DocumentView.aspx";
const MANIFEST_PATH = path.join(ROOT, "data", "legal", "official-mirror", "ecosys", "manifest.json");
const SOURCE_ENRICHMENT_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "source-enrichment.json");
const EXTRACTIONS_DIR = path.join(ROOT, "data", "legal", "normalized", "ecosys", "extracted-text");
const REGISTRY_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "text-source-registry.json");
const INDEX_PATH = path.join(ROOT, "docs", "legal", "indexes", "text-source-registry.md");

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

async function loadText(filePath) {
  if (!filePath || !await fileExists(filePath)) {
    return "";
  }

  return fs.readFile(filePath, "utf8");
}

async function assessCandidateQuality({
  sourceType,
  markdownPath,
  htmlPath = null,
}) {
  return assessTextPreservationQuality({
    sourceType,
    markdownBody: await loadText(markdownPath),
    htmlBody: await loadText(htmlPath),
  });
}

async function main() {
  const manifest = await loadJson(MANIFEST_PATH, null);
  if (!manifest) {
    throw new Error("Missing eCoSys manifest. Run npm run mirror:ecosys-docs first.");
  }

  const enrichment = await loadJson(SOURCE_ENRICHMENT_PATH, { documents: {} });
  await ensureDir(path.dirname(REGISTRY_PATH));
  await ensureDir(path.dirname(INDEX_PATH));

  const documents = [];
  const indexLines = [
    "# Legal Text Source Registry",
    "",
    "| Issue Code | Form / Group | Preferred Text Source | Resolution Status | Notes |",
    "| --- | --- | --- | --- | --- |",
  ];

  for (const document of manifest.documents) {
    const documentId = buildDocumentId(document);
    const slug = slugify(`${document.issueCode}-${document.title}`);
    const extractionPath = path.join(EXTRACTIONS_DIR, `${slug}.json`);
    const extraction = await loadJson(extractionPath, { artifacts: [] });
    const extractionSummary = auditExtractionArtifacts(extraction.artifacts || []);
    const enrichmentEntry = enrichment.documents?.[documentId] || {};
    const tvplFound = enrichmentEntry.tvpl?.status === "found" && enrichmentEntry.tvpl?.pageUrl;
    const officialTextResolved = enrichmentEntry.official?.resolvedText?.status === "resolved";
    const officialReference = normalizeOfficialSourceMetadata(enrichmentEntry.official || null);
    const officialHtmlPath = enrichmentEntry.official?.sourceType === "vbpl-toanvan"
      ? (enrichmentEntry.official?.vbpl?.cachedHtmlPath || null)
      : null;
    const officialQualityGate = await assessCandidateQuality({
      sourceType: enrichmentEntry.official?.sourceType || null,
      markdownPath: enrichmentEntry.official?.resolvedText?.textPath || null,
      htmlPath: officialHtmlPath,
    });

    const officialTextCandidate = {
      sourceId: "official-text",
      sourceType: "official-text",
      priority: 1,
      status: officialTextResolved ? "resolved" : "unresolved",
      role: "canonical_target",
      sourceProvider: officialReference.sourceProvider,
      pageUrl: officialReference.pageUrl,
      searchUrl: officialReference.searchUrl,
      detailApiUrl: officialReference.detailApiUrl,
      detailId: officialReference.detailId,
      cachedSearchHtmlPath: enrichmentEntry.official?.vntr?.cachedSearchHtmlPath || null,
      cachedHtmlPath: enrichmentEntry.official?.vbpl?.cachedHtmlPath || null,
      cachedJsonPath: enrichmentEntry.official?.vntr?.cachedJsonPath || null,
      extractedMarkdownPath: enrichmentEntry.official?.resolvedText?.textPath || null,
      preservationQuality: officialQualityGate.quality,
      qualityGate: officialQualityGate,
      notes: officialTextResolved
        ? [
          `Official text-based source resolved from ${enrichmentEntry.official?.sourceType || "official source"}.`,
          ...officialQualityGate.issues.map((issue) => `preservation:${issue}`),
        ]
        : [
          "Official text-based source has not been resolved yet.",
          "eCoSys listing should be treated as a discovery feed, not as the canonical text corpus.",
        ],
    };

    const tvplQualityGate = await assessCandidateQuality({
      sourceType: "tvpl",
      markdownPath: enrichmentEntry.tvpl?.extractedMarkdownPath || null,
      htmlPath: enrichmentEntry.tvpl?.cachedHtmlPath || null,
    });

    const tvplCandidate = {
      sourceId: "tvpl",
      sourceType: "third-party-text",
      priority: 2,
      status: tvplFound ? "resolved" : "not_found",
      role: "fallback_text",
      pageUrl: enrichmentEntry.tvpl?.pageUrl || null,
      cachedHtmlPath: enrichmentEntry.tvpl?.cachedHtmlPath || null,
      extractedMarkdownPath: enrichmentEntry.tvpl?.extractedMarkdownPath || null,
      preservationQuality: tvplQualityGate.quality,
      qualityGate: tvplQualityGate,
      notes: tvplFound
        ? [
          "Internal fallback text source until an official text-based source is resolved.",
          ...tvplQualityGate.issues.map((issue) => `preservation:${issue}`),
        ]
        : ["No TVPL fallback currently resolved."],
    };

    const { outputPath: ocrPath } = buildOcrOutputPaths(ROOT, document.issueCode, document.title);
    const ocrCandidate = {
      sourceId: "ocr-recovery",
      sourceType: "ocr-text",
      priority: 3,
      status: await fileExists(ocrPath) ? "resolved" : "unresolved",
      role: "fallback_text",
      extractionPath: await fileExists(ocrPath) ? ocrPath : null,
      notes: await fileExists(ocrPath)
        ? ["OCR fallback recovered from an official scan/binary source."]
        : ["No OCR fallback currently available."],
    };

    const ecosysExtractionCandidate = {
      sourceId: "ecosys-extracted",
      sourceType: "binary-extraction",
      priority: 4,
      status: extractionSummary.status,
      role: "secondary_text",
      extractionPath: await fileExists(extractionPath) ? extractionPath : null,
      quality: extractionSummary.quality,
      issues: extractionSummary.issues,
      metrics: extractionSummary.metrics,
      notes: [
        "Derived from the mirrored binary file linked from eCoSys.",
        "Useful for provenance and emergency lookup, but not the desired canonical text layer.",
      ],
    };

    const preferredTextSource = buildPreferredTextSource({
      officialTextCandidate,
      fallbackTextCandidate: tvplCandidate,
      ocrTextCandidate: ocrCandidate,
      binaryExtractionCandidate: ecosysExtractionCandidate,
    });
    const sourceClassification = classifyDocumentSourceType({
      preferredTextSource,
      rawBinarySource: {
        fileExtension: path.extname(document.localPath).toLowerCase(),
      },
      extractionAudit: extractionSummary,
    });

    const registryEntry = {
      documentId,
      issueCode: document.issueCode,
      title: document.title,
      formType: document.formType,
      issuingUnit: document.issuingUnit,
      issuedDate: document.issuedDate,
      discovery: {
        sourceType: "ecosys-documentview",
        listingUrl: ECOSYS_LISTING_URL,
        mirroredFileUrl: document.absoluteUrl,
        relativeUrl: document.relativeUrl,
        discoveredFromPage: document.sourcePageSlug,
      },
      rawBinarySource: {
        sourceId: "ecosys-file",
        sourceType: "official-binary-mirror",
        role: "secondary_binary",
        localPath: document.localPath,
        fileExtension: path.extname(document.localPath).toLowerCase(),
        sizeBytes: document.sizeBytes,
        sha256: document.sha256,
      },
      textCandidates: [
        officialTextCandidate,
        tvplCandidate,
        ocrCandidate,
        ecosysExtractionCandidate,
      ],
      extractionAudit: extractionSummary,
      sourceClassification,
      preferredTextSource,
    };

    documents.push(registryEntry);

    const notes = [];
    if (preferredTextSource.status !== "resolved") {
      notes.push(preferredTextSource.rationale);
    }
    if (officialTextCandidate.qualityGate.passed === false) {
      notes.push(`official-gate:${officialTextCandidate.qualityGate.issues.join(",")}`);
    }
    notes.push(sourceClassification.sourceType);
    if (ecosysExtractionCandidate.issues.length > 0) {
      notes.push(ecosysExtractionCandidate.issues.join(", "));
    }

    indexLines.push(`| ${document.issueCode} | ${document.formType} | ${preferredTextSource.sourceId || "unresolved"} | ${preferredTextSource.status} | ${notes.join("; ") || "-"} |`);
  }

  const counts = {
    documents: documents.length,
    preferredOfficialText: documents.filter((entry) => entry.preferredTextSource.sourceId === "official-text").length,
    preferredTvpl: documents.filter((entry) => entry.preferredTextSource.sourceId === "tvpl").length,
    preferredOcrRecovery: documents.filter((entry) => entry.preferredTextSource.sourceId === "ocr-recovery").length,
    temporaryEcosysExtraction: documents.filter((entry) => entry.preferredTextSource.sourceId === "ecosys-extracted").length,
    unresolved: documents.filter((entry) => entry.preferredTextSource.status === "unresolved").length,
    bySourceType: Object.fromEntries(
      ["official_html", "official_pdf_text", "official_pdf_scan", "official_binary_legacy_doc", "third_party_text", "unresolved"]
        .map((sourceType) => [
          sourceType,
          documents.filter((entry) => entry.sourceClassification.sourceType === sourceType).length,
        ]),
    ),
  };

  const registry = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    policy: {
      discoveryFeed: "eCoSys listing is used to detect and mirror documents, not as the canonical text corpus.",
      canonicalPreferenceOrder: [
        "official-text (quality-gated)",
        "tvpl (quality-gated)",
        "ocr-recovery",
        "ecosys-extracted",
      ],
      binaryPolicy: "PDF, DOC, DOCX, RAR, ZIP mirrored from eCoSys remain secondary provenance artifacts.",
    },
    counts,
    documents,
  };

  await fs.writeFile(REGISTRY_PATH, `${JSON.stringify(registry, null, 2)}\n`);
  await fs.writeFile(INDEX_PATH, `${indexLines.join("\n")}\n`);

  console.log(JSON.stringify(counts, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
