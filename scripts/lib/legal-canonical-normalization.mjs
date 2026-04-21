import path from "node:path";

function slugify(value) {
  return value
    .replace(/[đĐ]/g, "d")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

function stripHtmlTags(value) {
  return value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|tr|table|tbody|thead|colgroup)>/gi, "\n")
    .replace(/<\/td>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

function normalizeLine(line) {
  return line
    .replace(/\[\[page \d+\]\]/gi, "")
    .replace(/\u00a0/g, " ")
    .replace(/[†‡•·]/g, "")
    .replace(/\bQD-BCT\b/gi, "QĐ-BCT")
    .replace(/\bQÐ-BCT\b/g, "QĐ-BCT")
    .replace(/\bQUYÉT\b/g, "QUYẾT")
    .replace(/\bQUYET\b/g, "QUYẾT")
    .replace(/\bCONG HÒA\b/g, "CỘNG HÒA")
    .replace(/\bHOI\b/g, "HỘI")
    .replace(/\bTHUONG\b/g, "THƯƠNG")
    .replace(/\*\*/g, "")
    .replace(/\\\./g, ".")
    .replace(/\b(\d)\s+(?=\d\b)/g, "$1")
    .replace(/\b(\d{1,2})\s*\/\s*QĐ-BCT\b/gi, "$1/QĐ-BCT")
    .replace(/\b(\d)\s+(\d)\s+(\d)\s+(\d)\s*\/\s*QĐ-BCT\b/gi, "$1$2$3$4/QĐ-BCT")
    .replace(/\b(\d)\s+(\d)\s+(\d)\s+(\d)\s*\/\s*OD-BCT\b/gi, "$1$2$3$4/QĐ-BCT")
    .replace(/\b(\d)\s+(\d)\s+(\d)\s+(\d)\s*\/\s*QD-BCT\b/gi, "$1$2$3$4/QĐ-BCT")
    .replace(/\b(\d+)\s+\/\s*QĐ-BCT\b/gi, "$1/QĐ-BCT")
    .replace(/[ \t]+/g, " ")
    .trim();
}

function isChapterHeading(line) {
  return /^Chương\s+[IVXLC]+$/i.test(line);
}

function isChapterTitle(line) {
  return /^[A-ZÀ-Ỵ0-9 ,().\-/:]+$/u.test(line) && line.length > 3;
}

function isDecisionTitleLine(line) {
  return /^(QUYẾT ĐỊNH|THÔNG TƯ|NGHỊ ĐỊNH)$/i.test(line);
}

function isAdministrativeHeaderLine(line) {
  return /^(Số:|Hà Nội, ngày|Độc lập - Tự do - Hạnh phúc|BỘ CÔNG THƯƠNG\b|CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\b)/i.test(line);
}

function isArticleHeading(line) {
  return /^Điều\s+\d+[A-Za-z]?\.\s*/i.test(line);
}

function isAppendixHeading(line) {
  return /^Phụ lục\s+[A-Z0-9IVXLC]+/i.test(line) && !/ban hành kèm/i.test(line);
}

function isClauseLine(line) {
  return /^\d+\./.test(line);
}

function isPointLine(line) {
  return /^[a-zđ]\)/i.test(line);
}

function isStructuralLine(line) {
  return isChapterHeading(line)
    || isArticleHeading(line)
    || isAppendixHeading(line)
    || isClauseLine(line)
    || isPointLine(line)
    || isDecisionTitleLine(line)
    || isAdministrativeHeaderLine(line);
}

function isLikelyHeadingContinuation(line) {
  return Boolean(
    line
    && !isStructuralLine(line)
    && !/[.!?;:]$/.test(line)
    && (/^[A-ZÀ-ỴĐ]/u.test(line) || isChapterTitle(line))
    && line.length < 120,
  );
}

function getArticleTitleFragment(line) {
  return line.replace(/^Điều\s+\d+[A-Za-z]?\.\s*/i, "").trim();
}

function shouldMergeArticleHeadingWithNext(line, nextLine) {
  if (!/^Điều\s+\d+\./i.test(line) || !nextLine || isStructuralLine(nextLine)) {
    return false;
  }

  if (isLikelyHeadingContinuation(nextLine)) {
    return true;
  }

  const titleFragment = getArticleTitleFragment(line);
  return Boolean(
    titleFragment
    && titleFragment.length < 24
    && !/[.!?;:]$/.test(nextLine)
    && nextLine.length < 120,
  );
}

function mergeBrokenLines(lines) {
  const merged = [];

  for (let index = 0; index < lines.length; index += 1) {
    let line = lines[index];
    if (!line) {
      merged.push("");
      continue;
    }

    if (/^Chương$/i.test(line) && lines[index + 1] && /^[IVXLC]+$/i.test(lines[index + 1])) {
      line = `${line} ${lines[index + 1]}`;
      index += 1;
    }

    while (
      lines[index + 1]
      && line
      && !isStructuralLine(line)
      && isChapterTitle(line)
      && isChapterTitle(lines[index + 1])
      && line.length < 80
    ) {
      line = `${line} ${lines[index + 1]}`;
      index += 1;
    }

    while (
      shouldMergeArticleHeadingWithNext(line, lines[index + 1])
    ) {
      line = `${line} ${lines[index + 1]}`;
      index += 1;
    }

    merged.push(line);
  }

  return merged;
}

function joinParagraphLines(lines) {
  const output = [];
  let buffer = "";

  const flush = () => {
    if (buffer) {
      output.push(buffer);
      buffer = "";
    }
  };

  for (const line of lines) {
    if (!line) {
      flush();
      if (output[output.length - 1] !== "") {
        output.push("");
      }
      continue;
    }

    if (isStructuralLine(line) || isChapterTitle(line)) {
      flush();
      output.push(line);
      continue;
    }

    buffer = buffer ? `${buffer} ${line}` : line;
  }

  flush();
  return output;
}

function trimTrailingAdministrativeBlock(lines) {
  const cutoffIndex = lines.findIndex((line) => /^(Nơi|Noi)\s+nhận\s*:/i.test(line));
  if (cutoffIndex === -1) {
    return lines;
  }
  return lines.slice(0, cutoffIndex);
}

export function selectBestCanonicalSource(registryEntry, { ocrTextPath = null, excludedSourceIds = [] } = {}) {
  const excludedSet = new Set(excludedSourceIds);
  const preferredSourceId = registryEntry.preferredTextSource?.sourceId || null;
  const orderedSourceIds = [
    preferredSourceId,
    "official-text",
    "tvpl",
    "ocr-recovery",
    "ecosys-extracted",
  ].filter((sourceId, index, array) => (
    sourceId
    && array.indexOf(sourceId) === index
    && !excludedSet.has(sourceId)
  ));

  for (const sourceId of orderedSourceIds) {
    if (sourceId === "ocr-recovery" && ocrTextPath) {
      return {
        sourceId: "ocr-recovery",
        sourceKind: "ocr_text",
        path: ocrTextPath,
      };
    }

    const candidate = registryEntry.textCandidates?.find((entry) => entry.sourceId === sourceId);
    if (!candidate || candidate.status !== "resolved") {
      continue;
    }

    if ((sourceId === "official-text" || sourceId === "tvpl") && candidate.qualityGate?.passed === false) {
      continue;
    }

    if (sourceId === "official-text" && candidate.extractedMarkdownPath) {
      return {
        sourceId: "official-text",
        sourceKind: "official_markdown",
        path: candidate.extractedMarkdownPath,
      };
    }

    if (sourceId === "tvpl" && candidate.extractedMarkdownPath) {
      return {
        sourceId: "tvpl",
        sourceKind: "fallback_markdown",
        path: candidate.extractedMarkdownPath,
      };
    }

    if (sourceId === "ecosys-extracted" && candidate.extractionPath) {
      return {
        sourceId: "ecosys-extracted",
        sourceKind: "binary_extraction",
        path: candidate.extractionPath,
      };
    }
  }

  if (ocrTextPath) {
    return {
      sourceId: "ocr-recovery",
      sourceKind: "ocr_text",
      path: ocrTextPath,
    };
  }

  return null;
}

export function normalizeLegalCanonicalMarkdown(input) {
  const stripped = stripHtmlTags(input);
  const rawLines = stripped.split(/\r?\n/).map(normalizeLine);
  const filteredLines = rawLines.filter((line, index, array) => {
    if (!line) {
      return index > 0 && array[index - 1] !== "";
    }
    if (/^[-–—_`'".,;:]+$/.test(line)) {
      return false;
    }
    if (/^\d+$/.test(line)) {
      return false;
    }
    return true;
  });
  const lines = trimTrailingAdministrativeBlock(joinParagraphLines(mergeBrokenLines(filteredLines)));

  const output = [];
  const getLastNonEmptyOutputLine = () => {
    for (let index = output.length - 1; index >= 0; index -= 1) {
      if (output[index]) {
        return output[index];
      }
    }
    return null;
  };

  for (const line of lines) {
    if (!line) {
      if (output[output.length - 1] !== "") {
        output.push("");
      }
      continue;
    }

    if (isChapterHeading(line)) {
      output.push(`## ${line}`);
      continue;
    }

    if (isArticleHeading(line)) {
      output.push(`## ${line}`);
      continue;
    }

    if (isDecisionTitleLine(line)) {
      output.push(`## ${line}`);
      continue;
    }

    if (isAppendixHeading(line)) {
      output.push(`## ${line}`);
      continue;
    }

    if (isChapterTitle(line) && /^## Chương\s+/i.test(getLastNonEmptyOutputLine() ?? "")) {
      output.push(`### ${line}`);
      continue;
    }

    output.push(line);
  }

  return output.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function buildCanonicalPilotOutputPath(rootDir, issueCode, title) {
  return path.join(
    rootDir,
    "docs",
    "legal",
    "canonical",
    "pilot",
    `${slugify(`${issueCode}-${title}`)}.md`,
  );
}
