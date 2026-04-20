import test from "node:test";
import assert from "node:assert/strict";

import {
  buildTvplBrowserLaunchOptions,
  buildPreferredTextSource,
  buildTvplBrowserConnectionConfig,
  classifySearchResponse,
  extractTvplContentFragment,
  extractTvplSearchEntriesFromHtml,
  resolveWindowsBrowserExecutable,
  shouldResolveFallbackTextSource,
} from "../scripts/lib/legal-source-resolution.mjs";
import {
  auditExtractionArtifacts,
  classifyDocumentSourceType,
} from "../scripts/lib/legal-source-audit.mjs";
import {
  buildOcrOutputPaths,
  selectOcrCandidateDocuments,
} from "../scripts/lib/legal-ocr-recovery.mjs";
import {
  buildVntrSearchUrl,
  extractHtmlElementById,
  extractVntrCsrfToken,
  extractVntrSearchEntriesFromHtml,
  extractVbplContentFragment,
  getOfficialVbplSeed,
  pickBestVntrSearchEntry,
} from "../scripts/lib/legal-official-source-resolution.mjs";
import {
  buildCanonicalPilotOutputPath,
  normalizeLegalCanonicalMarkdown,
  selectBestCanonicalSource,
} from "../scripts/lib/legal-canonical-normalization.mjs";

test("fallback text source should still be resolved when only raw binary extraction is available", () => {
  assert.equal(
    shouldResolveFallbackTextSource({
      officialTextResolved: false,
      binaryExtractionQuality: "usable",
    }),
    true,
  );
});

test("preferred text source should favor text-based fallback over raw binary extraction", () => {
  const preferred = buildPreferredTextSource({
    officialTextCandidate: {
      sourceId: "official-text",
      status: "unresolved",
    },
    fallbackTextCandidate: {
      sourceId: "tvpl",
      status: "resolved",
    },
    binaryExtractionCandidate: {
      sourceId: "ecosys-extracted",
      status: "resolved",
    },
  });

  assert.deepEqual(preferred, {
    sourceId: "tvpl",
    status: "resolved",
    rationale: "fallback_text_source_resolved_before_official_text_source",
  });
});

test("preferred text source should still favor official text over fallback text", () => {
  const preferred = buildPreferredTextSource({
    officialTextCandidate: {
      sourceId: "official-text",
      status: "resolved",
    },
    fallbackTextCandidate: {
      sourceId: "tvpl",
      status: "resolved",
    },
    binaryExtractionCandidate: {
      sourceId: "ecosys-extracted",
      status: "resolved",
    },
  });

  assert.deepEqual(preferred, {
    sourceId: "official-text",
    status: "resolved",
    rationale: "official_text_source_resolved",
  });
});

test("preferred text source should use OCR fallback before unresolved binary extraction", () => {
  const preferred = buildPreferredTextSource({
    officialTextCandidate: {
      sourceId: "official-text",
      status: "unresolved",
    },
    fallbackTextCandidate: {
      sourceId: "tvpl",
      status: "not_found",
    },
    ocrTextCandidate: {
      sourceId: "ocr-recovery",
      status: "resolved",
    },
    binaryExtractionCandidate: {
      sourceId: "ecosys-extracted",
      status: "unresolved",
    },
  });

  assert.deepEqual(preferred, {
    sourceId: "ocr-recovery",
    status: "temporary",
    rationale: "ocr_recovery_is_current_best_available_text_source",
  });
});

test("search responses blocked by Cloudflare should not be classified as not found", () => {
  const response = classifySearchResponse(`
    <!DOCTYPE html>
    <html lang="en-US">
      <head><title>Just a moment...</title></head>
      <body>
        <script>window._cf_chl_opt = { cZone: 'thuvienphapluat.vn' };</script>
      </body>
    </html>
  `);

  assert.deepEqual(response, {
    status: "blocked",
    blocker: "cloudflare_challenge",
  });
});

test("should extract TVPL search result entries from rendered html", () => {
  const entries = extractTvplSearchEntriesFromHtml(`
    <div class="news-card">
      <a href="https://thuvienphapluat.vn/van-ban/Thuong-mai/Thong-tu-05-2018-TT-BCT-quy-dinh-ve-xuat-xu-hang-hoa-366061.aspx">
        Thông tư 05/2018/TT-BCT quy định về xuất xứ hàng hóa
      </a>
    </div>
  `);

  assert.deepEqual(entries, [
    {
      url: "https://thuvienphapluat.vn/van-ban/Thuong-mai/Thong-tu-05-2018-TT-BCT-quy-dinh-ve-xuat-xu-hang-hoa-366061.aspx",
      title: "Thông tư 05/2018/TT-BCT quy định về xuất xứ hàng hóa",
    },
  ]);
});

test("should extract the main TVPL content fragment from rendered html", () => {
  const fragment = extractTvplContentFragment(`
    <html>
      <body>
        <div class="content1">
          <h1>Thông tư 05/2018/TT-BCT</h1>
          <p>Quy định về xuất xứ hàng hóa</p>
        </div>
      </body>
    </html>
  `);

  assert.match(fragment || "", /Thông tư 05\/2018\/TT-BCT/);
  assert.match(fragment || "", /Quy định về xuất xứ hàng hóa/);
});

test("should prefer a remote browser session when a debugging url is configured", () => {
  assert.deepEqual(
    buildTvplBrowserConnectionConfig({
      TVPL_REMOTE_DEBUGGING_URL: "http://127.0.0.1:9222",
    }),
    {
      mode: "connect",
      browserURL: "http://127.0.0.1:9222",
      headless: false,
    },
  );
});

test("should allow forcing a local headed browser session", () => {
  assert.deepEqual(
    buildTvplBrowserConnectionConfig({
      TVPL_BROWSER_MODE: "headful",
    }),
    {
      mode: "launch",
      browserURL: null,
      headless: false,
    },
  );
});

test("should prefer Edge on Windows when it exists", () => {
  assert.equal(
    resolveWindowsBrowserExecutable("edge", (candidate) => candidate.includes("Edge")),
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  );
});

test("should fall back to Chrome on Windows when Edge is missing", () => {
  assert.equal(
    resolveWindowsBrowserExecutable("edge", (candidate) => candidate.includes("Google\\Chrome")),
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  );
});

test("should build headed Windows launch options with a native browser executable", () => {
  assert.deepEqual(
    buildTvplBrowserLaunchOptions(
      {
        TVPL_BROWSER_MODE: "headful",
        TVPL_WINDOWS_BROWSER: "edge",
      },
      "win32",
      (candidate) => candidate.includes("Edge"),
    ),
    {
      headless: false,
      args: [],
      executablePath: "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    },
  );
});

test("should classify empty PDF extraction as scan-like and OCR-worthy", () => {
  assert.deepEqual(
    auditExtractionArtifacts([
      {
        label: "scan.pdf",
        body: "",
      },
    ]),
    {
      status: "unresolved",
      quality: "empty",
      ocrCandidate: true,
      metrics: {
        artifactCount: 1,
        emptyArtifacts: 1,
        placeholderArtifacts: 0,
        textArtifacts: 0,
        mojibakeHits: 0,
        formFeedCount: 0,
      },
      issues: ["empty_artifacts"],
    },
  );
});

test("should classify noisy text extraction without forcing OCR", () => {
  assert.deepEqual(
    auditExtractionArtifacts([
      {
        label: "legacy.doc",
        body: "Céng hßa x· héi chñ nghÜa viÖt nam\fĐiều 1",
      },
    ]),
    {
      status: "resolved",
      quality: "noisy",
      ocrCandidate: false,
      metrics: {
        artifactCount: 1,
        emptyArtifacts: 0,
        placeholderArtifacts: 0,
        textArtifacts: 1,
        mojibakeHits: 5,
        formFeedCount: 1,
      },
      issues: ["mojibake", "page_break_noise"],
    },
  );
});

test("should classify preferred TVPL text as third-party text source", () => {
  assert.deepEqual(
    classifyDocumentSourceType({
      preferredTextSource: {
        sourceId: "tvpl",
        status: "resolved",
      },
      rawBinarySource: {
        fileExtension: ".pdf",
      },
      extractionAudit: {
        status: "resolved",
        quality: "usable",
      },
    }),
    {
      sourceType: "third_party_text",
      rationale: "tvpl_fallback_is_current_preferred_text_source",
    },
  );
});

test("should classify unresolved PDF text as official PDF scan candidate", () => {
  assert.deepEqual(
    classifyDocumentSourceType({
      preferredTextSource: {
        sourceId: null,
        status: "unresolved",
      },
      rawBinarySource: {
        fileExtension: ".pdf",
      },
      extractionAudit: {
        status: "unresolved",
        quality: "empty",
      },
    }),
    {
      sourceType: "official_pdf_scan",
      rationale: "official_pdf_extraction_is_empty_or_unresolved",
    },
  );
});

test("should classify OCR fallback on official scans as official PDF scan", () => {
  assert.deepEqual(
    classifyDocumentSourceType({
      preferredTextSource: {
        sourceId: "ocr-recovery",
        status: "temporary",
      },
      rawBinarySource: {
        fileExtension: ".pdf",
      },
      extractionAudit: {
        status: "unresolved",
        quality: "empty",
      },
    }),
    {
      sourceType: "official_pdf_scan",
      rationale: "official_pdf_scan_requires_ocr_fallback",
    },
  );
});

test("should select only PDF scan documents for OCR recovery", () => {
  assert.deepEqual(
    selectOcrCandidateDocuments([
      {
        issueCode: "23/2025/TT-BCT",
        sourceClassification: { sourceType: "official_pdf_scan" },
        extractionAudit: { ocrCandidate: true },
      },
      {
        issueCode: "49/2025/TT-BCT",
        sourceClassification: { sourceType: "official_binary_legacy_doc" },
        extractionAudit: { ocrCandidate: false },
      },
      {
        issueCode: "31/2018/NĐ-CP",
        sourceClassification: { sourceType: "official_pdf_scan" },
        extractionAudit: { ocrCandidate: false },
      },
    ]),
    [
      {
        issueCode: "23/2025/TT-BCT",
        sourceClassification: { sourceType: "official_pdf_scan" },
        extractionAudit: { ocrCandidate: true },
      },
    ],
  );
});

test("should build OCR cache paths under the normalized OCR directory", () => {
  assert.deepEqual(
    buildOcrOutputPaths("/repo", "23/2025/TT-BCT", "Thông tư sửa đổi"),
    {
      outputDir: "/repo/data/legal/normalized/ecosys/ocr-text",
      outputPath: "/repo/data/legal/normalized/ecosys/ocr-text/23-2025-tt-bct-thong-tu-sua-oi.json",
    },
  );
});

test("should build a VNTR search url from the issue code", () => {
  assert.equal(
    buildVntrSearchUrl({
      issueCode: "05/2018/TT-BCT",
    }),
    "https://vntr.moit.gov.vn/legal-documents?doc_code=05%2F2018%2FTT-BCT&page=agreements",
  );
});

test("should extract the CSRF token from a VNTR legal-document page", () => {
  assert.equal(
    extractVntrCsrfToken('<meta name="csrf-token" content="abc123token">'),
    "abc123token",
  );
});

test("should extract VNTR summary rows including the detail id", () => {
  assert.deepEqual(
    extractVntrSearchEntriesFromHtml(`
      <tr class="tr-measures tr-measures-607">
        <td class="docType">Circular</td>
        <td class="docCode">05/2018/TT-BCT</td>
        <td class="docName">Circular No. 05/2018/TT-BCT dated April 3, 2018 on origin of goods</td>
        <td class="docAgent">Ministry of Industry and Trade <br></td>
        <td class="docDate">03-04-2018</td>
        <td class="row_content"><a onclick="showDocument(607)"><img></a></td>
      </tr>
    `),
    [
      {
        detailId: 607,
        docType: "Circular",
        issueCode: "05/2018/TT-BCT",
        title: "Circular No. 05/2018/TT-BCT dated April 3, 2018 on origin of goods",
        issuingAgency: "Ministry of Industry and Trade",
        issuedDate: "03-04-2018",
      },
    ],
  );
});

test("should prefer the exact VNTR issue-code match", () => {
  assert.deepEqual(
    pickBestVntrSearchEntry(
      {
        issueCode: "31/2018/NĐ-CP",
      },
      [
        {
          detailId: 1,
          issueCode: "31/2018/TT-BCT",
          title: "Wrong document",
        },
        {
          detailId: 2,
          issueCode: "31/2018/ND-CP",
          title: "Decree No. 31/2018/ND-CP on origin of goods",
        },
      ],
    ),
    {
      detailId: 2,
      issueCode: "31/2018/ND-CP",
      title: "Decree No. 31/2018/ND-CP on origin of goods",
    },
  );
});

test("should return a seeded VBPL official source for known CO legal texts", () => {
  assert.deepEqual(
    getOfficialVbplSeed({
      issueCode: "23/2025/TT-BCT",
    }),
    {
      sourceType: "vbpl-toanvan",
      pageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=177442&dvid=13",
    },
  );
});

test("should extract a nested html element by id", () => {
  const fragment = extractHtmlElementById(`
    <div>
      <div id="toanvancontent">
        <div class="inner">
          <p>Điều 1.</p>
        </div>
      </div>
    </div>
  `, "toanvancontent");

  assert.match(fragment || "", /<div id="toanvancontent">/);
  assert.match(fragment || "", /Điều 1\./);
  assert.match(fragment || "", /class="inner"/);
});

test("should extract the VBPL full-text fragment", () => {
  const fragment = extractVbplContentFragment(`
    <html>
      <body>
        <div class="toanvancontent" id="toanvancontent">
          <p><strong>THÔNG TƯ</strong></p>
          <p>Điều 1. Phạm vi điều chỉnh</p>
        </div>
      </body>
    </html>
  `);

  assert.match(fragment || "", /THÔNG TƯ/);
  assert.match(fragment || "", /Điều 1\. Phạm vi điều chỉnh/);
});

test("should prefer official text over OCR and binary extraction for canonical build", () => {
  assert.deepEqual(
    selectBestCanonicalSource({
      issueCode: "05/2018/TT-BCT",
      title: "Quy định về xuất xứ hàng hóa",
      preferredTextSource: {
        sourceId: "official-text",
        status: "resolved",
      },
      textCandidates: [
        {
          sourceId: "official-text",
          status: "resolved",
          extractedMarkdownPath: "/cache/official.md",
        },
      ],
      rawBinarySource: {
        localPath: "/raw/file.rar",
      },
    }, {
      ocrTextPath: "/ocr/05.json",
    }),
    {
      sourceId: "official-text",
      sourceKind: "official_markdown",
      path: "/cache/official.md",
    },
  );
});

test("should fall back to OCR text when official text is unresolved", () => {
  assert.deepEqual(
    selectBestCanonicalSource({
      issueCode: "23/2025/TT-BCT",
      title: "Thông tư sửa đổi",
      preferredTextSource: {
        sourceId: null,
        status: "unresolved",
      },
      textCandidates: [
        {
          sourceId: "official-text",
          status: "unresolved",
          extractedMarkdownPath: null,
        },
      ],
      rawBinarySource: {
        localPath: "/raw/file.pdf",
      },
    }, {
      ocrTextPath: "/ocr/23.json",
    }),
    {
      sourceId: "ocr-recovery",
      sourceKind: "ocr_text",
      path: "/ocr/23.json",
    },
  );
});

test("should normalize legal markdown into canonical chapter and article headings", () => {
  const normalized = normalizeLegalCanonicalMarkdown(`
<span id="chuong_1">**Chương I**</span>

<span id="chuong_1_name">**QUY ĐỊNH CHUNG**</span>
<span id="dieu_1">**Điều 1. Phạm vi điều chỉnh**</span>
Thông tư này quy định về xuất xứ hàng hóa.
1\\. C/O là giấy chứng nhận.
<span id="dieu_2">**Điều 2. Đối tượng áp dụng**</span>
Áp dụng đối với thương nhân.
  `);

  assert.match(normalized, /^## Chương I$/m);
  assert.match(normalized, /^### QUY ĐỊNH CHUNG$/m);
  assert.match(normalized, /^## Điều 1\. Phạm vi điều chỉnh$/m);
  assert.match(normalized, /^1\. C\/O là giấy chứng nhận\.$/m);
  assert.doesNotMatch(normalized, /<span/);
});

test("should keep appendix references inside sentences as body text", () => {
  const normalized = normalizeLegalCanonicalMarkdown(`
Điều 6. Quy tắc xuất xứ hàng hóa không ưu đãi
2. Hàng hóa đáp ứng tiêu chí xuất xứ thuộc Danh mục Quy tắc cụ thể mặt hàng quy định tại
Phụ lục I ban hành kèm theo Thông tư này để hướng dẫn Điều 8 Nghị định số 31/2018/NĐ-CP.
  `);

  assert.doesNotMatch(normalized, /^## Phụ lục I ban hành kèm theo/m);
  assert.match(normalized, /Phụ lục I ban hành kèm theo Thông tư này/);
});

test("should normalize OCR noise in decision headers", () => {
  const normalized = normalizeLegalCanonicalMarkdown(`
BỘ CÔNG THƯƠNG CONG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Số: 2 4 1 2 /QD-BCT
QUYET ĐỊNH
Điều 1. Ban hành kèm theo Quyết định này.
  `);

  assert.match(normalized, /CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM/);
  assert.match(normalized, /Số: 2412\/QĐ-BCT/);
  assert.match(normalized, /^## QUYẾT ĐỊNH$/m);
});

test("should trim trailing noi nhan administrative blocks from canonical text", () => {
  const normalized = normalizeLegalCanonicalMarkdown(`
Điều 3. Điều khoản thi hành
1. Thông tư này có hiệu lực.
Nơi nhận:
- Văn phòng Chính phủ;
- Lưu: VT.
  `);

  assert.match(normalized, /Điều 3\. Điều khoản thi hành/);
  assert.doesNotMatch(normalized, /Nơi nhận:/);
  assert.doesNotMatch(normalized, /Văn phòng Chính phủ/);
});

test("should build canonical pilot output paths under docs legal canonical pilot", () => {
  assert.equal(
    buildCanonicalPilotOutputPath("/repo", "31/2018/NĐ-CP", "Nghị định quy định"),
    "/repo/docs/legal/canonical/pilot/31-2018-nd-cp-nghi-dinh-quy-dinh.md",
  );
});
