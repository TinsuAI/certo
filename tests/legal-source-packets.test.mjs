import test from "node:test";
import assert from "node:assert/strict";

import {
  buildFusionReadiness,
  buildPacketTextLanes,
  summarizeAttachmentInventory,
} from "../scripts/lib/legal-source-packets.mjs";

test("should summarize attachment formats for text and supplemental files", () => {
  const summary = summarizeAttachmentInventory([
    "/tmp/Appendix I.docx",
    "/tmp/Appendix II.pdf",
    "/tmp/Form B.xlsx",
    "/tmp/Form C.xls",
  ]);

  assert.deepEqual(summary, {
    available: true,
    count: 4,
    byExtension: {
      ".docx": 1,
      ".pdf": 1,
      ".xlsx": 1,
      ".xls": 1,
    },
    textFormats: ["DOCX", "PDF"],
    supplementalFormats: ["XLSX", "XLS"],
    mixedTextFormatLabel: "DOCX + PDF",
  });
});

test("should build text lanes in a stable audit order", () => {
  const lanes = buildPacketTextLanes({
    vntrAvailable: true,
    tvplAvailable: true,
    ecosysExtractAvailable: true,
    canonicalAvailable: true,
  });

  assert.deepEqual(lanes, ["VNTR", "TVPL", "eCoSys extract", "Canonical"]);
});

test("should mark packet as ready for fusion when official text and attachment text are both available", () => {
  assert.deepEqual(
    buildFusionReadiness({
      officialResolved: true,
      textLaneCount: 2,
      hasAttachmentTextSource: true,
      canonicalAvailable: false,
    }),
    {
      status: "ready_for_fusion",
      blockers: ["canonical_missing"],
    },
  );
});

test("should mark packet as partial when only a temporary text lane exists", () => {
  assert.deepEqual(
    buildFusionReadiness({
      officialResolved: false,
      textLaneCount: 1,
      hasAttachmentTextSource: false,
      canonicalAvailable: false,
    }),
    {
      status: "partial_packet",
      blockers: [
        "official_text_missing",
        "attachment_text_source_missing",
        "insufficient_text_lanes",
        "canonical_missing",
      ],
    },
  );
});
