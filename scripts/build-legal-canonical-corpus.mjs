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
const CANONICAL_DIR = path.join(ROOT, "docs", "legal", "canonical", "corpus");
const INDEX_PATH = path.join(ROOT, "docs", "legal", "indexes", "canonical-corpus.md");
const EXCLUDED_SOURCE_IDS = ["tvpl"];

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

  if (source.sourceKind === "official_markdown" || source.sourceKind === "fallback_markdown") {
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

function buildCorpusOutputPath(root, issueCode, title) {
  const pilotPath = buildCanonicalPilotOutputPath(root, issueCode, title);
  return pilotPath.replace(`${path.sep}pilot${path.sep}`, `${path.sep}corpus${path.sep}`);
}

async function main() {
  const registry = JSON.parse(await fs.readFile(REGISTRY_PATH, "utf8"));
  await ensureDir(CANONICAL_DIR);
  await ensureDir(path.dirname(INDEX_PATH));

  const indexLines = [
    "# Canonical Corpus",
    "",
    `- Excluded source ids: ${EXCLUDED_SOURCE_IDS.join(", ")}`,
    "",
    "| Issue Code | Selected Source | Status | Output |",
    "| --- | --- | --- | --- |",
  ];

  const results = [];

  for (const entry of registry.documents) {
    const { outputPath: ocrTextPath } = buildOcrOutputPaths(ROOT, entry.issueCode, entry.title);
    const source = selectBestCanonicalSource(entry, {
      ocrTextPath: await fileExists(ocrTextPath) ? ocrTextPath : null,
      excludedSourceIds: EXCLUDED_SOURCE_IDS,
    });

    if (!source) {
      results.push({
        issueCode: entry.issueCode,
        title: entry.title,
        status: "no_source",
      });
      indexLines.push(`| ${entry.issueCode} | - | no_source | - |`);
      continue;
    }

    const sourceBody = await loadSourceBody(source);
    if (!sourceBody) {
      results.push({
        issueCode: entry.issueCode,
        title: entry.title,
        status: "empty_source_body",
        source,
      });
      indexLines.push(`| ${entry.issueCode} | ${source.sourceId} / ${source.sourceKind} | empty_source_body | - |`);
      continue;
    }

    const normalizedBody = normalizeLegalCanonicalMarkdown(sourceBody);
    const outputPath = buildCorpusOutputPath(ROOT, entry.issueCode, entry.title);
    const relativeOutputPath = path.relative(ROOT, outputPath);
    const metadataLines = [
      `# ${entry.issueCode} - ${entry.title}`,
      "",
      "## Metadata",
      `- Corpus source: \`${source.sourceId}\``,
      `- Source kind: \`${source.sourceKind}\``,
      `- Source path: \`${source.path}\``,
      `- Raw binary path: \`${entry.rawBinarySource.localPath}\``,
      `- Preferred text source: \`${entry.preferredTextSource.sourceId}\``,
      `- Preferred text source status: \`${entry.preferredTextSource.status}\``,
      `- Excluded source ids: \`${EXCLUDED_SOURCE_IDS.join(", ")}\``,
      "",
      "## Canonical Text",
      "",
      normalizedBody,
      "",
    ];

    await ensureDir(path.dirname(outputPath));
    await fs.writeFile(outputPath, metadataLines.join("\n"));

    indexLines.push(`| ${entry.issueCode} | ${source.sourceId} / ${source.sourceKind} | ok | [${path.basename(outputPath)}](/${outputPath}) |`);
    results.push({
      issueCode: entry.issueCode,
      title: entry.title,
      status: "ok",
      source,
      outputPath: relativeOutputPath,
    });
  }

  await fs.writeFile(INDEX_PATH, `${indexLines.join("\n")}\n`);

  const summary = {
    documents: results.length,
    ok: results.filter((result) => result.status === "ok").length,
    noSource: results.filter((result) => result.status === "no_source").length,
    emptySourceBody: results.filter((result) => result.status === "empty_source_body").length,
    bySource: Object.fromEntries(
      results
        .filter((result) => result.status === "ok")
        .reduce((counts, result) => {
          const key = `${result.source.sourceId}/${result.source.sourceKind}`;
          counts.set(key, (counts.get(key) || 0) + 1);
          return counts;
        }, new Map()),
    ),
  };

  console.log(JSON.stringify({ summary, results }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
