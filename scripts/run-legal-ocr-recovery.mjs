import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

import {
  buildOcrOutputPaths,
  selectOcrCandidateDocuments,
} from "./lib/legal-ocr-recovery.mjs";

const ROOT = process.cwd();
const MANIFEST_PATH = path.join(ROOT, "data", "legal", "official-mirror", "ecosys", "manifest.json");
const AUDIT_PATH = path.join(ROOT, "data", "legal", "normalized", "ecosys", "quality-audit.json");
const OCR_LANG = process.env.LEGAL_OCR_LANG || "vie+eng";
const OCR_DPI = process.env.LEGAL_OCR_DPI || "200";
const OCR_LIMIT = process.env.LEGAL_OCR_LIMIT ? Number(process.env.LEGAL_OCR_LIMIT) : null;

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

async function loadJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, "utf8"));
}

function resolveManifestDocument(manifest, auditDocument) {
  return manifest.documents.find((document) =>
    document.issueCode === auditDocument.issueCode
    && document.title === auditDocument.title,
  );
}

async function assertDependencies() {
  for (const command of ["pdfinfo", "pdftoppm", "tesseract"]) {
    try {
      await runCommand("bash", ["-lc", `command -v ${command}`]);
    } catch {
      throw new Error(`Missing required OCR dependency: ${command}`);
    }
  }
}

function parsePageCount(pdfinfoOutput) {
  const match = pdfinfoOutput.match(/^Pages:\s+(\d+)$/m);
  return match ? Number(match[1]) : null;
}

async function runTesseractOnPdf(pdfPath) {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "barry-co-ocr-"));
  const prefix = path.join(tempDir, "page");

  try {
    const { stdout: infoOutput } = await runCommand("pdfinfo", [pdfPath]);
    const pageCount = parsePageCount(infoOutput);
    await runCommand("pdftoppm", ["-png", "-r", OCR_DPI, pdfPath, prefix]);

    const files = (await fs.readdir(tempDir))
      .filter((fileName) => fileName.endsWith(".png"))
      .sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));

    const pages = [];
    for (let index = 0; index < files.length; index += 1) {
      const imagePath = path.join(tempDir, files[index]);
      const { stdout } = await runCommand("tesseract", [imagePath, "stdout", "-l", OCR_LANG]);
      pages.push({
        pageNumber: index + 1,
        text: stdout.trim(),
      });
    }

    return {
      pageCount,
      pages,
      text: pages
        .map((page) => `[[page ${page.pageNumber}]]\n${page.text}`.trim())
        .join("\n\n"),
    };
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
}

async function main() {
  await assertDependencies();

  const manifest = await loadJson(MANIFEST_PATH);
  const audit = await loadJson(AUDIT_PATH);
  const candidates = selectOcrCandidateDocuments(audit.documents);
  const selectedCandidates = OCR_LIMIT ? candidates.slice(0, OCR_LIMIT) : candidates;
  const results = [];

  for (const auditDocument of selectedCandidates) {
    const manifestDocument = resolveManifestDocument(manifest, auditDocument);
    if (!manifestDocument) {
      results.push({
        issueCode: auditDocument.issueCode,
        status: "skipped",
        reason: "manifest_document_not_found",
      });
      continue;
    }

    const { outputDir, outputPath } = buildOcrOutputPaths(
      ROOT,
      auditDocument.issueCode,
      auditDocument.title,
    );
    await ensureDir(outputDir);

    const ocrResult = await runTesseractOnPdf(manifestDocument.localPath);
    const payload = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      issueCode: auditDocument.issueCode,
      title: auditDocument.title,
      sourcePdfPath: manifestDocument.localPath,
      sourceClassification: auditDocument.sourceClassification,
      extractionAudit: auditDocument.extractionAudit,
      ocr: {
        engine: "tesseract",
        language: OCR_LANG,
        dpi: Number(OCR_DPI),
        pageCount: ocrResult.pageCount,
        pages: ocrResult.pages,
        text: ocrResult.text,
      },
    };

    await fs.writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`);
    results.push({
      issueCode: auditDocument.issueCode,
      status: "ok",
      outputPath,
      pageCount: ocrResult.pageCount,
      textLength: ocrResult.text.length,
    });
  }

  console.log(JSON.stringify({
    attempted: selectedCandidates.length,
    completed: results.filter((result) => result.status === "ok").length,
    skipped: results.filter((result) => result.status !== "ok").length,
    results,
  }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
