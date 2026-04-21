import path from "node:path";

const TEXT_ATTACHMENT_EXTENSION_LABELS = new Map([
  [".html", "HTML"],
  [".htm", "HTML"],
  [".docx", "DOCX"],
  [".doc", "DOC"],
  [".pdf", "PDF"],
  [".rtf", "RTF"],
  [".txt", "TXT"],
]);

const SUPPLEMENTAL_ATTACHMENT_EXTENSION_LABELS = new Map([
  [".xls", "XLS"],
  [".xlsx", "XLSX"],
  [".csv", "CSV"],
]);

const ORDERED_TEXT_FORMATS = ["HTML", "DOCX", "DOC", "PDF", "RTF", "TXT"];
const ORDERED_SUPPLEMENTAL_FORMATS = ["XLSX", "XLS", "CSV"];

function incrementCounter(counters, key) {
  counters[key] = (counters[key] || 0) + 1;
}

function sortFormats(formats, order) {
  return [...formats].sort((left, right) => {
    const leftIndex = order.indexOf(left);
    const rightIndex = order.indexOf(right);
    const normalizedLeftIndex = leftIndex === -1 ? order.length : leftIndex;
    const normalizedRightIndex = rightIndex === -1 ? order.length : rightIndex;
    if (normalizedLeftIndex !== normalizedRightIndex) {
      return normalizedLeftIndex - normalizedRightIndex;
    }
    return left.localeCompare(right);
  });
}

export function summarizeAttachmentInventory(files) {
  const byExtension = {};
  const textFormats = new Set();
  const supplementalFormats = new Set();

  for (const file of files) {
    const filePath = typeof file === "string" ? file : file.path;
    const extension = path.extname(filePath || "").toLowerCase();
    if (!extension) {
      continue;
    }

    incrementCounter(byExtension, extension);

    const textFormat = TEXT_ATTACHMENT_EXTENSION_LABELS.get(extension);
    if (textFormat) {
      textFormats.add(textFormat);
      continue;
    }

    const supplementalFormat = SUPPLEMENTAL_ATTACHMENT_EXTENSION_LABELS.get(extension);
    if (supplementalFormat) {
      supplementalFormats.add(supplementalFormat);
    }
  }

  const orderedTextFormats = sortFormats(textFormats, ORDERED_TEXT_FORMATS);
  const orderedSupplementalFormats = sortFormats(supplementalFormats, ORDERED_SUPPLEMENTAL_FORMATS);

  return {
    available: files.length > 0,
    count: files.length,
    byExtension,
    textFormats: orderedTextFormats,
    supplementalFormats: orderedSupplementalFormats,
    mixedTextFormatLabel: orderedTextFormats.join(" + ") || null,
  };
}

export function buildPacketTextLanes({
  vbplAvailable = false,
  vntrAvailable = false,
  tvplAvailable = false,
  ocrAvailable = false,
  ecosysExtractAvailable = false,
  canonicalAvailable = false,
}) {
  const lanes = [];

  if (vbplAvailable) {
    lanes.push("VBPL");
  }
  if (vntrAvailable) {
    lanes.push("VNTR");
  }
  if (tvplAvailable) {
    lanes.push("TVPL");
  }
  if (ocrAvailable) {
    lanes.push("OCR");
  }
  if (ecosysExtractAvailable) {
    lanes.push("eCoSys extract");
  }
  if (canonicalAvailable) {
    lanes.push("Canonical");
  }

  return lanes;
}

export function buildFusionReadiness({
  officialResolved = false,
  textLaneCount = 0,
  hasAttachmentTextSource = false,
  canonicalAvailable = false,
}) {
  const blockers = [];

  if (!officialResolved) {
    blockers.push("official_text_missing");
  }
  if (!hasAttachmentTextSource) {
    blockers.push("attachment_text_source_missing");
  }
  if (textLaneCount < 2) {
    blockers.push("insufficient_text_lanes");
  }
  if (!canonicalAvailable) {
    blockers.push("canonical_missing");
  }

  let status = "source_incomplete";
  if (canonicalAvailable) {
    status = "canonical_exists";
  } else if (officialResolved && hasAttachmentTextSource) {
    status = "ready_for_fusion";
  } else if (textLaneCount > 0 || hasAttachmentTextSource) {
    status = "partial_packet";
  }

  return {
    status,
    blockers,
  };
}
