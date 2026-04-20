function countMatches(text, pattern) {
  return (text.match(pattern) || []).length;
}

function summarizeArtifactQuality(body) {
  const text = typeof body === "string" ? body.trim() : "";

  if (!text) {
    return {
      bodyState: "empty",
      placeholder: false,
      mojibakeScore: 0,
      formFeedCount: 0,
    };
  }

  const placeholder = text.startsWith("_");
  const mojibakeScore = countMatches(text, /chÝnh phñ|Céng hßa|x· héi|nghÜa|viÖt nam|Ý|ß|·|Ü|ñ/g);
  const formFeedCount = countMatches(text, /\f/g);

  return {
    bodyState: placeholder ? "placeholder" : "text",
    placeholder,
    mojibakeScore,
    formFeedCount,
  };
}

export function auditExtractionArtifacts(artifacts = []) {
  if (!artifacts.length) {
    return {
      status: "unresolved",
      quality: "none",
      ocrCandidate: false,
      metrics: {
        artifactCount: 0,
        emptyArtifacts: 0,
        placeholderArtifacts: 0,
        textArtifacts: 0,
        mojibakeHits: 0,
        formFeedCount: 0,
      },
      issues: ["no_artifacts"],
    };
  }

  let emptyArtifacts = 0;
  let placeholderArtifacts = 0;
  let textArtifacts = 0;
  let mojibakeHits = 0;
  let formFeedCount = 0;

  for (const artifact of artifacts) {
    const summary = summarizeArtifactQuality(artifact.body);
    mojibakeHits += summary.mojibakeScore;
    formFeedCount += summary.formFeedCount;

    if (summary.bodyState === "empty") {
      emptyArtifacts += 1;
    } else if (summary.bodyState === "placeholder") {
      placeholderArtifacts += 1;
    } else {
      textArtifacts += 1;
    }
  }

  const issues = [];
  if (emptyArtifacts) {
    issues.push("empty_artifacts");
  }
  if (placeholderArtifacts) {
    issues.push("placeholder_artifacts");
  }
  if (mojibakeHits) {
    issues.push("mojibake");
  }
  if (formFeedCount) {
    issues.push("page_break_noise");
  }

  let quality = "usable";
  let status = "resolved";
  let ocrCandidate = false;

  if (textArtifacts === 0 && (emptyArtifacts > 0 || placeholderArtifacts > 0)) {
    quality = "empty";
    status = "unresolved";
    ocrCandidate = true;
  } else if (issues.length > 0) {
    quality = "noisy";
  }

  return {
    status,
    quality,
    ocrCandidate,
    metrics: {
      artifactCount: artifacts.length,
      emptyArtifacts,
      placeholderArtifacts,
      textArtifacts,
      mojibakeHits,
      formFeedCount,
    },
    issues,
  };
}

export function classifyDocumentSourceType({
  preferredTextSource,
  rawBinarySource,
  extractionAudit,
  officialTextResolved = false,
} = {}) {
  if (officialTextResolved || preferredTextSource?.sourceId === "official-text") {
    return {
      sourceType: "official_html",
      rationale: "official_text_source_is_preferred",
    };
  }

  if (preferredTextSource?.sourceId === "tvpl" && preferredTextSource?.status === "resolved") {
    return {
      sourceType: "third_party_text",
      rationale: "tvpl_fallback_is_current_preferred_text_source",
    };
  }

  if (preferredTextSource?.sourceId === "ocr-recovery") {
    return {
      sourceType: "official_pdf_scan",
      rationale: "official_pdf_scan_requires_ocr_fallback",
    };
  }

  const fileExtension = rawBinarySource?.fileExtension?.toLowerCase() || "";
  if (fileExtension === ".pdf") {
    if (extractionAudit?.status === "resolved") {
      return {
        sourceType: "official_pdf_text",
        rationale: "official_pdf_text_layer_is_current_best_available_source",
      };
    }

    return {
      sourceType: "official_pdf_scan",
      rationale: "official_pdf_extraction_is_empty_or_unresolved",
    };
  }

  if ([".doc", ".docx", ".rar", ".zip"].includes(fileExtension)) {
    return {
      sourceType: "official_binary_legacy_doc",
      rationale: "official_source_is_legacy_binary_or_archive",
    };
  }

  return {
    sourceType: "unresolved",
    rationale: "no_preferred_text_source_or_classifiable_binary_source",
  };
}
