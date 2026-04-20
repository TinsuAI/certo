import { promises as fs } from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import WordExtractor from "word-extractor";

const ROOT = process.cwd();
const MANIFEST_PATH = path.join(ROOT, "data", "legal", "official-mirror", "ecosys", "manifest.json");
const NORMALIZED_ROOT = path.join(ROOT, "data", "legal", "normalized", "ecosys");
const EXTRACTIONS_DIR = path.join(NORMALIZED_ROOT, "extracted-text");
const ATTACHMENTS_DIR = path.join(NORMALIZED_ROOT, "attachments");
const SOURCE_ENRICHMENT_PATH = path.join(NORMALIZED_ROOT, "source-enrichment.json");
const DOCS_ROOT = path.join(ROOT, "docs", "legal");
const WIKI_DIR = path.join(DOCS_ROOT, "wiki");
const INDEX_PATH = path.join(DOCS_ROOT, "indexes", "ecosys-documents.md");
const WORD_EXTRACTOR = new WordExtractor();

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

  return document.relativeUrl
    ? Buffer.from(document.relativeUrl).toString("base64url").slice(0, 16)
    : slugify(`${document.issueCode}-${document.title}`).slice(0, 16);
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
      resolve({ stdout, stderr });
    });
  });
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

async function extractArchive(filePath, targetDir) {
  if (filePath.endsWith(".zip")) {
    await runCommand("unzip", ["-o", filePath, "-d", targetDir]);
    return true;
  }

  if (filePath.endsWith(".rar")) {
    const parentDir = path.dirname(filePath);
    const extractedDir = path.join(parentDir, path.basename(filePath, ".rar"));
    await runCommand("node", [path.join(ROOT, "scripts", "extract-rars.mjs"), parentDir]);
    if (await fileExists(extractedDir)) {
      await fs.cp(extractedDir, targetDir, { recursive: true, force: true });
    }
    return true;
  }

  return false;
}

async function extractPdf(filePath) {
  const { stdout } = await runCommand("pdftotext", ["-layout", filePath, "-"]);
  return stdout.trim();
}

async function extractDocx(filePath) {
  const { stdout } = await runCommand("pandoc", ["-f", "docx", "-t", "gfm", filePath]);
  return stdout.trim();
}

async function extractDoc(filePath) {
  const document = await WORD_EXTRACTOR.extract(filePath);
  return document.getBody().trim();
}

async function walkFiles(rootDir) {
  const entries = await fs.readdir(rootDir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const nextPath = path.join(rootDir, entry.name);
    if (entry.isDirectory()) {
      files.push(...await walkFiles(nextPath));
      continue;
    }
    files.push(nextPath);
  }

  return files;
}

async function gatherTextArtifacts(sourcePath, attachmentRoot) {
  const ext = path.extname(sourcePath).toLowerCase();
  const artifacts = [];

  async function pushArtifact(label, producer) {
    try {
      const body = await producer();
      artifacts.push({
        source: sourcePath,
        label,
        body,
      });
    } catch (error) {
      artifacts.push({
        source: sourcePath,
        label,
        body: `_Extraction failed: ${error instanceof Error ? error.message : String(error)}_`,
      });
    }
  }

  if (ext === ".pdf") {
    await pushArtifact(path.basename(sourcePath), () => extractPdf(sourcePath));
    return artifacts;
  }

  if (ext === ".docx") {
    await pushArtifact(path.basename(sourcePath), () => extractDocx(sourcePath));
    return artifacts;
  }

  if (ext === ".txt" || ext === ".md") {
    await pushArtifact(path.basename(sourcePath), async () => (await fs.readFile(sourcePath, "utf8")).trim());
    return artifacts;
  }

  if (ext === ".doc") {
    await pushArtifact(path.basename(sourcePath), () => extractDoc(sourcePath));
    return artifacts;
  }

  if (ext === ".zip" || ext === ".rar") {
    await ensureDir(attachmentRoot);
    await extractArchive(sourcePath, attachmentRoot);

    const files = await walkFiles(attachmentRoot);
    for (const filePath of files) {
      const nestedExt = path.extname(filePath).toLowerCase();
      if (nestedExt === ".pdf") {
        try {
          artifacts.push({
            source: filePath,
            label: path.relative(attachmentRoot, filePath),
            body: await extractPdf(filePath),
          });
        } catch (error) {
          artifacts.push({
            source: filePath,
            label: path.relative(attachmentRoot, filePath),
            body: `_Extraction failed: ${error instanceof Error ? error.message : String(error)}_`,
          });
        }
      } else if (nestedExt === ".docx") {
        try {
          artifacts.push({
            source: filePath,
            label: path.relative(attachmentRoot, filePath),
            body: await extractDocx(filePath),
          });
        } catch (error) {
          artifacts.push({
            source: filePath,
            label: path.relative(attachmentRoot, filePath),
            body: `_Extraction failed: ${error instanceof Error ? error.message : String(error)}_`,
          });
        }
      } else if (nestedExt === ".txt" || nestedExt === ".md") {
        artifacts.push({
          source: filePath,
          label: path.relative(attachmentRoot, filePath),
          body: (await fs.readFile(filePath, "utf8")).trim(),
        });
      } else if (nestedExt === ".doc") {
        try {
          artifacts.push({
            source: filePath,
            label: path.relative(attachmentRoot, filePath),
            body: await extractDoc(filePath),
          });
        } catch (error) {
          artifacts.push({
            source: filePath,
            label: path.relative(attachmentRoot, filePath),
            body: `_Extraction failed: ${error instanceof Error ? error.message : String(error)}_`,
          });
        }
      }
    }

    return artifacts;
  }

  return artifacts;
}

function buildWikiContent(document, artifacts) {
  const lines = [
    `# ${document.issueCode} - ${document.title}`,
    "",
    "## Metadata",
    `- Form / group: ${document.formType}`,
    `- Issuing unit: ${document.issuingUnit}`,
    `- Issued date: ${document.issuedDate}`,
    `- Official URL: ${document.absoluteUrl}`,
    `- Mirror path: \`${document.localPath}\``,
    "",
  ];

  if (document.sourceEnrichment) {
    lines.push("## Source Enrichment", "");
    lines.push(`- Preferred text source: ${document.sourceEnrichment.preferredTextSource || "official"}`);
    if (document.sourceEnrichment.tvpl?.pageUrl) {
      lines.push(`- TVPL page: ${document.sourceEnrichment.tvpl.pageUrl}`);
    } else if (document.sourceEnrichment.tvpl?.status) {
      lines.push(`- TVPL status: ${document.sourceEnrichment.tvpl.status}`);
    }
    if (document.sourceEnrichment.tvpl?.searchTerm) {
      lines.push(`- TVPL search term: ${document.sourceEnrichment.tvpl.searchTerm}`);
    }
    if (document.sourceEnrichment.tvpl?.cachedHtmlPath) {
      lines.push(`- TVPL cache: \`${document.sourceEnrichment.tvpl.cachedHtmlPath}\``);
    }
    lines.push("");
  }

  if (artifacts.length === 0) {
    lines.push("## Extracted Content", "", "_No extractable text artifact was produced for this document yet._", "");
  } else {
    lines.push("## Extracted Content", "");

    for (const artifact of artifacts) {
      lines.push(`### ${artifact.label}`, "");
      lines.push(artifact.body || "_Empty extraction output._", "");
    }
  }

  if (document.sourceEnrichment?.preferredTextSource === "tvpl" && document.sourceEnrichment.tvpl?.extractedMarkdown) {
    lines.push("## Fallback Digital Text", "");
    lines.push(document.sourceEnrichment.tvpl.extractedMarkdown, "");
  }

  return `${lines.join("\n")}\n`;
}

async function main() {
  const manifest = JSON.parse(await fs.readFile(MANIFEST_PATH, "utf8"));
  const sourceEnrichment = await fileExists(SOURCE_ENRICHMENT_PATH)
    ? JSON.parse(await fs.readFile(SOURCE_ENRICHMENT_PATH, "utf8"))
    : { documents: {} };
  await ensureDir(EXTRACTIONS_DIR);
  await ensureDir(ATTACHMENTS_DIR);
  await ensureDir(WIKI_DIR);
  await ensureDir(path.dirname(INDEX_PATH));

  const indexLines = [
    "# eCoSys Legal Mirror Index",
    "",
    "| Issue Code | Form / Group | Issued Date | Wiki |",
    "| --- | --- | --- | --- |",
  ];

  for (const document of manifest.documents) {
    const documentId = buildDocumentId(document);
    const docSlug = slugify(`${document.issueCode}-${document.title}`);
    const attachmentRoot = path.join(ATTACHMENTS_DIR, docSlug);
    const artifacts = await gatherTextArtifacts(document.localPath, attachmentRoot);
    const extractionPath = path.join(EXTRACTIONS_DIR, `${docSlug}.json`);
    const wikiPath = path.join(WIKI_DIR, `${docSlug}.md`);
    const enrichment = sourceEnrichment.documents?.[documentId];

    await fs.writeFile(extractionPath, `${JSON.stringify({
      document: {
        documentId,
        issueCode: document.issueCode,
        title: document.title,
        formType: document.formType,
        issuedDate: document.issuedDate,
        officialUrl: document.absoluteUrl,
        localPath: document.localPath,
      },
      sourceEnrichment: enrichment || null,
      artifacts,
    }, null, 2)}\n`);

    await fs.writeFile(wikiPath, buildWikiContent({
      ...document,
      documentId,
      sourceEnrichment: enrichment || null,
    }, artifacts));

    indexLines.push(`| ${document.issueCode} | ${document.formType} | ${document.issuedDate} | [${docSlug}](../wiki/${docSlug}.md) |`);
    console.log(`Built wiki page for ${document.issueCode}`);
  }

  await fs.writeFile(INDEX_PATH, `${indexLines.join("\n")}\n`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
