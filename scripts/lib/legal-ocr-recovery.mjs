import path from "node:path";

function slugify(value) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

export function selectOcrCandidateDocuments(documents = []) {
  return documents.filter((document) =>
    document.sourceClassification?.sourceType === "official_pdf_scan"
    && document.extractionAudit?.ocrCandidate === true,
  );
}

export function buildOcrOutputPaths(rootDir, issueCode, title) {
  const outputDir = path.join(rootDir, "data", "legal", "normalized", "ecosys", "ocr-text");
  return {
    outputDir,
    outputPath: path.join(outputDir, `${slugify(`${issueCode}-${title}`)}.json`),
  };
}
