import { promises as fs } from "node:fs";
import path from "node:path";

import {
  buildCanonicalPilotOutputPath,
  normalizeLegalCanonicalMarkdown,
  selectBestCanonicalSource,
} from "./lib/legal-canonical-normalization.mjs";
import { buildOcrOutputPaths } from "./lib/legal-ocr-recovery.mjs";

const ROOT = process.cwd();
const REGISTRY_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "text-source-registry.json");
const CANONICAL_DIR = path.join(ROOT, "docs", "legal", "canonical", "pilot");
const INDEX_PATH = path.join(ROOT, "docs", "legal", "indexes", "canonical-pilot.md");
const PILOT_CODES = [
  "31/2018/NĐ-CP",
  "05/2018/TT-BCT",
  "38/2018/TT-BCT",
  "39/2018/TT-BCT",
  "23/2025/TT-BCT",
  "2412/QĐ-BCT",
  "1313/QĐ-BCT",
  "3624/QĐ-BCT",
  "4082/QĐ-BCT",
  "4099/QĐ-BCT",
  "9866/QĐ-BCT",
  "1619/QĐ-BCT",
  "2795/QĐ-BCT",
];

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

async function loadSourceBody(source) {
  if (!source) {
    return null;
  }

  if (source.sourceKind === "official_markdown") {
    return fs.readFile(source.path, "utf8");
  }

  if (source.sourceKind === "ocr_text") {
    const payload = JSON.parse(await fs.readFile(source.path, "utf8"));
    return payload.ocr?.text || null;
  }

  if (source.sourceKind === "binary_extraction") {
    const payload = JSON.parse(await fs.readFile(source.path, "utf8"));
    const artifactBodies = (payload.artifacts || [])
      .map((artifact) => artifact.body || "")
      .filter(Boolean);
    return artifactBodies.join("\n\n");
  }

  return null;
}

async function main() {
  const registry = JSON.parse(await fs.readFile(REGISTRY_PATH, "utf8"));
  await ensureDir(CANONICAL_DIR);
  await ensureDir(path.dirname(INDEX_PATH));

  const indexLines = [
    "# Canonical Pilot",
    "",
    "| Issue Code | Selected Source | Output |",
    "| --- | --- | --- |",
  ];

  const results = [];

  for (const issueCode of PILOT_CODES) {
    const entry = registry.documents.find((document) => document.issueCode === issueCode);
    if (!entry) {
      results.push({
        issueCode,
        status: "missing_registry_entry",
      });
      continue;
    }

    const { outputPath: ocrTextPath } = buildOcrOutputPaths(ROOT, entry.issueCode, entry.title);
    const source = selectBestCanonicalSource(entry, {
      ocrTextPath: await fileExists(ocrTextPath) ? ocrTextPath : null,
    });
    if (!source) {
      results.push({
        issueCode,
        status: "no_source",
      });
      continue;
    }

    const sourceBody = await loadSourceBody(source);
    if (!sourceBody) {
      results.push({
        issueCode,
        status: "empty_source_body",
        source,
      });
      continue;
    }

    const normalizedBody = normalizeLegalCanonicalMarkdown(sourceBody);
    const outputPath = buildCanonicalPilotOutputPath(ROOT, entry.issueCode, entry.title);
    const relativeOutputPath = path.relative(ROOT, outputPath);
    const metadataLines = [
      `# ${entry.issueCode} - ${entry.title}`,
      "",
      "## Metadata",
      `- Pilot source: \`${source.sourceId}\``,
      `- Source kind: \`${source.sourceKind}\``,
      `- Source path: \`${source.path}\``,
      `- Raw binary path: \`${entry.rawBinarySource.localPath}\``,
      `- Preferred text source status: \`${entry.preferredTextSource.status}\``,
      "",
      "## Canonical Text",
      "",
      normalizedBody,
      "",
    ];

    await ensureDir(path.dirname(outputPath));
    await fs.writeFile(outputPath, metadataLines.join("\n"));

    indexLines.push(`| ${entry.issueCode} | ${source.sourceId} / ${source.sourceKind} | [${path.basename(outputPath)}](/${outputPath}) |`);
    results.push({
      issueCode: entry.issueCode,
      status: "ok",
      source,
      outputPath: relativeOutputPath,
    });
  }

  await fs.writeFile(INDEX_PATH, `${indexLines.join("\n")}\n`);
  console.log(JSON.stringify(results, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
