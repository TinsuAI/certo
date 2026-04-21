import test from "node:test";
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";

import {
  buildDocumentRouteSlug,
  buildLegalDocumentViewModel,
  buildSourceLinkModels,
  createLegalLookupServer,
  rewriteRenderedMarkdownLinks,
  resolveRenderableMarkdown,
  selectSupplementalArtifacts,
} from "../scripts/legal-lookup-server.mjs";

test("should prefer canonical markdown when it exists", () => {
  const entry = {
    documentId: "doc-1",
    issueCode: "05/2018/TT-BCT",
    title: "Thông tư Quy định về xuất xứ hàng hóa",
    formType: "Văn bản pháp luật chung về C/O",
    issuingUnit: "Bộ Công Thương",
    issuedDate: "03/04/2018",
    discovery: {
      sourceType: "ecosys-documentview",
      listingUrl: "https://ecosys.gov.vn/Homepage/DocumentView.aspx",
      mirroredFileUrl: "https://ecosys.gov.vn/Documents/example.rar",
      discoveredFromPage: "ecosys-page-1",
    },
    rawBinarySource: {
      localPath: "/tmp/example.rar",
      fileExtension: ".rar",
      sizeBytes: 123,
    },
    textCandidates: [
      {
        sourceId: "official-text",
        extractedMarkdownPath: "/tmp/official.md",
        pageUrl: "https://vntr.moit.gov.vn/legal/123",
      },
      {
        sourceId: "ecosys-extracted",
        extractionPath: "/tmp/extracted.json",
      },
    ],
    extractionAudit: {
      quality: "usable",
      issues: [],
    },
    sourceClassification: {
      sourceType: "official_html",
      rationale: "official_text_source_is_preferred",
    },
    preferredTextSource: {
      sourceId: "official-text",
      status: "resolved",
      rationale: "official_text_source_resolved",
    },
  };

  const canonicalMap = new Map([
    ["05/2018/TT-BCT", "/tmp/canonical.md"],
  ]);

  const renderable = resolveRenderableMarkdown(entry, canonicalMap);
  assert.deepEqual(renderable, {
    sourceId: "canonical-pilot",
    label: "Canonical pilot markdown",
    path: "/tmp/canonical.md",
  });
});

test("should fall back to official markdown before wiki markdown", () => {
  const entry = {
    documentId: "doc-2",
    issueCode: "39/2018/TT-BCT",
    title: "Thông tư kiểm tra xác minh xuất xứ hàng hóa xuất khẩu",
    formType: "Văn bản pháp luật chung về C/O",
    issuingUnit: "Bộ Công Thương",
    issuedDate: "20/04/2018",
    discovery: {
      sourceType: "ecosys-documentview",
      listingUrl: "https://ecosys.gov.vn/Homepage/DocumentView.aspx",
      mirroredFileUrl: "https://ecosys.gov.vn/Documents/example.rar",
      discoveredFromPage: "ecosys-page-2",
    },
    rawBinarySource: {
      localPath: "/tmp/example.rar",
      fileExtension: ".rar",
      sizeBytes: 456,
    },
    textCandidates: [
      {
        sourceId: "official-text",
        extractedMarkdownPath: "/tmp/official.md",
        pageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=133209",
        qualityGate: {
          passed: true,
        },
      },
    ],
    extractionAudit: {
      quality: "usable",
      issues: [],
    },
    sourceClassification: {
      sourceType: "official_html",
      rationale: "official_text_source_is_preferred",
    },
    preferredTextSource: {
      sourceId: "official-text",
      status: "resolved",
      rationale: "official_text_source_resolved",
    },
  };

  const renderable = resolveRenderableMarkdown(entry, new Map());
  assert.deepEqual(renderable, {
    sourceId: "official-text",
    label: "Official markdown",
    path: "/tmp/official.md",
  });
});

test("should not render rejected official markdown when policy prefers TVPL", () => {
  const entry = {
    documentId: "doc-2b",
    issueCode: "04/2024/TT-BCT",
    title: "Thông tư sửa đổi công thức xuất xứ",
    formType: "Văn bản pháp luật chung về C/O",
    issuingUnit: "Bộ Công Thương",
    issuedDate: "15/01/2024",
    discovery: {
      sourceType: "ecosys-documentview",
      listingUrl: "https://ecosys.gov.vn/Homepage/DocumentView.aspx",
      mirroredFileUrl: "https://ecosys.gov.vn/Documents/example.docx",
      discoveredFromPage: "ecosys-page-2b",
    },
    rawBinarySource: {
      localPath: "/tmp/example.docx",
      fileExtension: ".docx",
      sizeBytes: 457,
    },
    textCandidates: [
      {
        sourceId: "official-text",
        extractedMarkdownPath: "/tmp/official.md",
        qualityGate: {
          passed: false,
        },
      },
      {
        sourceId: "tvpl",
        extractedMarkdownPath: "/tmp/tvpl.md",
        qualityGate: {
          passed: true,
        },
      },
    ],
    extractionAudit: {
      quality: "usable",
      issues: [],
    },
    sourceClassification: {
      sourceType: "third_party_text",
      rationale: "tvpl_fallback_is_current_preferred_text_source",
    },
    preferredTextSource: {
      sourceId: "tvpl",
      status: "resolved",
      rationale: "fallback_text_source_passed_quality_gate_after_official_failed",
    },
  };

  const renderable = resolveRenderableMarkdown(entry, new Map());
  assert.deepEqual(renderable, {
    sourceId: "tvpl",
    label: "TVPL markdown",
    path: "/tmp/tvpl.md",
  });
});

test("should build a view model with provenance and quality metadata", () => {
  const entry = {
    documentId: "doc-3",
    issueCode: "2412/QĐ-BCT",
    title: "Quyết định về việc ban hành quy trình cấp giấy chứng nhận xuất xứ hàng hóa ưu đãi qua Internet",
    formType: "Quy trình cấp C/O",
    issuingUnit: "Bộ Công Thương",
    issuedDate: "15/06/2016",
    discovery: {
      sourceType: "ecosys-documentview",
      listingUrl: "https://ecosys.gov.vn/Homepage/DocumentView.aspx",
      mirroredFileUrl: "https://ecosys.gov.vn/Documents/2412-QD-BCT.pdf",
      discoveredFromPage: "ecosys-page-3",
    },
    rawBinarySource: {
      localPath: "/tmp/2412.pdf",
      fileExtension: ".pdf",
      sizeBytes: 789,
    },
    textCandidates: [
      {
        sourceId: "ocr-recovery",
        extractionPath: "/tmp/2412-ocr.json",
      },
    ],
    extractionAudit: {
      quality: "empty",
      issues: ["empty_artifacts"],
    },
    sourceClassification: {
      sourceType: "official_pdf_scan",
      rationale: "official_pdf_scan_requires_ocr_fallback",
    },
    preferredTextSource: {
      sourceId: "ocr-recovery",
      status: "temporary",
      rationale: "ocr_recovery_is_current_best_available_text_source",
    },
  };

  const viewModel = buildLegalDocumentViewModel(entry, new Map([
    ["2412/QĐ-BCT", "/tmp/2412-canonical.md"],
  ]));

  assert.equal(viewModel.routeSlug, buildDocumentRouteSlug(entry));
  assert.equal(viewModel.routeSlug, "2412-q-bct");
  assert.equal(viewModel.renderSource.label, "Canonical pilot markdown");
  assert.equal(viewModel.preferredTextSourceLabel, "eCoSys PDF OCR");
  assert.equal(viewModel.sourceClassificationLabel, "Official PDF scan");
  assert.equal(viewModel.qualityLabel, "Empty");
  assert.match(viewModel.notesSummary, /empty_artifacts/);
});

test("should infer official html provenance from cache when official url metadata is polluted", () => {
  const entry = {
    documentId: "doc-3a",
    issueCode: "13/2019/TT-BCT",
    title: "Thông tư sửa đổi",
    formType: "Form AK",
    issuingUnit: "Bộ Công Thương",
    issuedDate: "31/07/2019",
    discovery: {
      sourceType: "ecosys-documentview",
      listingUrl: "https://ecosys.gov.vn/Homepage/DocumentView.aspx",
      mirroredFileUrl: "https://ecosys.gov.vn/Documents/AK/TT%2013-2019.rar",
    },
    rawBinarySource: {
      localPath: "/tmp/TT 13-2019.rar",
      fileExtension: ".rar",
    },
    textCandidates: [
      {
        sourceId: "official-text",
        pageUrl: "https://ecosys.gov.vn/Documents/AK/TT%2013-2019.rar",
        cachedSearchHtmlPath: "/home/vp/workspace/client/barry-CO/data/legal/normalized/ecosys/source-cache/official/vntr/search-html/13-2019.html",
        cachedJsonPath: "/home/vp/workspace/client/barry-CO/data/legal/normalized/ecosys/source-cache/official/vntr/json/13-2019.json",
        extractedMarkdownPath: "/home/vp/workspace/client/barry-CO/data/legal/normalized/ecosys/source-cache/official/vntr/markdown/13-2019.md",
      },
    ],
    sourceClassification: {
      sourceType: "official_html",
    },
    preferredTextSource: {
      sourceId: "official-text",
      status: "resolved",
    },
  };

  const viewModel = buildLegalDocumentViewModel(entry, new Map());

  assert.equal(viewModel.preferredTextSourceLabel, "VNTR HTML");
  assert.equal(viewModel.officialPageUrl, "https://ecosys.gov.vn/Documents/AK/TT%2013-2019.rar");
});

test("should label archived eCoSys text as mix when attachments span multiple formats", () => {
  const entry = {
    documentId: "doc-3b",
    issueCode: "44/2023/TT-BCT",
    title: "Thông tư sửa đổi",
    formType: "Quy tắc xuất xứ",
    issuingUnit: "Bộ Công Thương",
    issuedDate: "29/12/2023",
    discovery: {
      sourceType: "ecosys-documentview",
      mirroredFileUrl: "https://ecosys.gov.vn/Documents/TT44.2023.TT.BCT.rar",
    },
    rawBinarySource: {
      localPath: "/tmp/TT44.2023.TT.BCT.rar",
      fileExtension: ".rar",
    },
    attachmentFiles: [
      { label: "TT44.2023.TT.BCT.docx", path: "/tmp/TT44.2023.TT.BCT.docx" },
      { label: "Phu-luc-I.pdf", path: "/tmp/Phu-luc-I.pdf" },
    ],
    preferredTextSource: {
      sourceId: "ecosys-extracted",
      status: "temporary",
    },
  };

  const viewModel = buildLegalDocumentViewModel(entry, new Map());

  assert.equal(viewModel.preferredTextSourceLabel, "eCoSys MIX (DOCX + PDF)");
});

test("should build compare-source links for available provenance assets", () => {
  const links = buildSourceLinkModels({
    routeSlug: "44-2023-tt-bct",
    discovery: {
      listingUrl: "https://ecosys.gov.vn/Homepage/DocumentView.aspx",
      mirroredFileUrl: "https://ecosys.gov.vn/Documents/TT44.2023.TT.BCT.rar",
    },
    renderSource: {
      path: "/tmp/rendered.md",
    },
    officialPageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=164845",
    officialMarkdownPath: "/tmp/official.md",
    officialHtmlPath: "/tmp/official.html",
    officialSearchHtmlPath: "/tmp/search.html",
    extractionPath: "/tmp/extracted.json",
    ocrPath: "/tmp/ocr.json",
    rawBinarySource: {
      localPath: "/home/vp/workspace/client/barry-CO/data/legal/official-mirror/example.rar",
    },
  }, "vi");

  assert.deepEqual(links.map((link) => link.id), [
    "official-page",
    "ecosys-listing",
    "ecosys-file-url",
    "raw-binary",
  ]);
  assert.equal(links[0].external, true);
  assert.match(links[0].label, /VBPL/);
  assert.equal(links[0].note, "vbpl.vn");
  assert.match(links[3].href, /\/source\/44-2023-tt-bct\/raw-binary/);
  assert.match(links.at(-1).href, /\/source\/44-2023-tt-bct\/raw-binary/);
});

test("should suppress official page links when official text metadata points to an ecosys binary", () => {
  const links = buildSourceLinkModels({
    routeSlug: "13-2019-tt-bct",
    issueCode: "13/2019/TT-BCT",
    officialSourceProvider: "vntr",
    discovery: {
      listingUrl: "https://ecosys.gov.vn/Homepage/DocumentView.aspx",
      mirroredFileUrl: "https://ecosys.gov.vn/Documents/AK/TT%2013-2019.rar",
    },
    officialPageUrl: "https://ecosys.gov.vn/Documents/AK/TT%2013-2019.rar",
    officialSearchUrl: "https://vntr.moit.gov.vn/legal-documents?doc_code=13%2F2019%2FTT-BCT&page=agreements",
    officialMarkdownPath: "/home/vp/workspace/client/barry-CO/data/legal/normalized/ecosys/source-cache/official/vntr/markdown/13-2019.md",
    officialSearchHtmlPath: "/home/vp/workspace/client/barry-CO/data/legal/normalized/ecosys/source-cache/official/vntr/search-html/13-2019.html",
    rawBinarySource: {
      localPath: "/home/vp/workspace/client/barry-CO/data/legal/official-mirror/example.rar",
    },
  }, "vi");

  assert.deepEqual(links.map((link) => link.id), [
    "official-search-page",
    "ecosys-listing",
    "ecosys-file-url",
    "raw-binary",
  ]);
  assert.match(links[0].label, /VNTR · Trang tra cứu chính thức/);
  assert.match(links[0].href, /vntr\.moit\.gov\.vn\/legal-documents\?doc_code=13%2F2019%2FTT-BCT&page=agreements/);
  assert.doesNotMatch(links.map((link) => link.label).join("\n"), /eCoSys · Trang toàn văn chính thức/);
});

test("should rewrite absolute canonical markdown links to local document routes", () => {
  const html = `
    <table>
      <tr>
        <td><a href="//home/vp/workspace/client/barry-CO/docs/legal/canonical/pilot/05-2018-tt-bct-thong-tu-quy-dinh-ve-xuat-xu-hang-hoa.md">05/2018</a></td>
      </tr>
    </table>
  `;

  const rewritten = rewriteRenderedMarkdownLinks(html, new Map([
    ["/home/vp/workspace/client/barry-CO/docs/legal/canonical/pilot/05-2018-tt-bct-thong-tu-quy-dinh-ve-xuat-xu-hang-hoa.md", "/doc/05-2018-tt-bct"],
  ]), "en");

  assert.match(rewritten, /href="\/doc\/05-2018-tt-bct\?lang=en"/);
  assert.doesNotMatch(rewritten, /href="\/\/home\//);
});

test("should select non-empty appendix artifacts as supplemental content", () => {
  const artifacts = selectSupplementalArtifacts([
    { label: "Thông tư số 44.2023.TT.BCT.pdf", body: "" },
    { label: "Phụ lục I.pdf", body: "HS code    Criteria\n0101.21   CC" },
    { label: "Appendix II.pdf", body: "Lookup table body" },
    { label: "readme.txt", body: "misc" },
  ]);

  assert.deepEqual(artifacts, [
    { label: "Phụ lục I.pdf", body: "HS code    Criteria\n0101.21   CC" },
    { label: "Appendix II.pdf", body: "Lookup table body" },
  ]);
});

test("should serve home and search as separate surfaces", async () => {
  const documents = [
    {
      routeSlug: "05-2018-tt-bct",
      issueCode: "05/2018/TT-BCT",
      title: "Thông tư quy định về xuất xứ hàng hóa",
      issuedDate: "03/04/2018",
      issuingUnit: "Bộ Công Thương",
      formType: "Văn bản pháp luật chung về C/O",
      preferredTextSource: { sourceId: "official-text" },
      officialPageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=164845",
      renderSource: { sourceId: "official-text", label: "Official markdown" },
      extractionAudit: { quality: "usable" },
      qualityClassName: "quality-usable",
    },
  ];
  const counts = {
    documents: 1,
    preferredOfficialText: 1,
    temporaryEcosysExtraction: 0,
    bySourceType: {
      official_html: 1,
      official_pdf_text: 0,
      official_pdf_scan: 0,
      official_binary_legacy_doc: 0,
    },
  };
  const server = createLegalLookupServer({
    documents,
    counts,
    documentMap: new Map(),
    documentPathMap: new Map(),
  });

  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();

  assert.ok(address && typeof address === "object");

  try {
    const homeResponse = await fetch(`http://127.0.0.1:${address.port}/`);
    const homeHtml = await homeResponse.text();
    assert.match(homeHtml, /Kho văn bản C\/O/);
    assert.match(homeHtml, /href="\/search"/);
    assert.doesNotMatch(homeHtml, /<form class="search"/);
    assert.doesNotMatch(homeHtml, /<th>Nhóm \/ form<\/th>/);

    const searchResponse = await fetch(`http://127.0.0.1:${address.port}/search?q=05`);
    const searchHtml = await searchResponse.text();
    assert.match(searchHtml, /Tra cứu văn bản/);
    assert.match(searchHtml, /<form class="search" method="get" action="\/search">/);
    assert.match(searchHtml, /05\/2018\/TT-BCT/);
  } finally {
    await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  }
});

test("should expose compare-source links and raw source routes on document pages", async () => {
  const documents = [
    {
      routeSlug: "44-2023-tt-bct",
      issueCode: "44/2023/TT-BCT",
      title: "Thông tư sửa đổi",
      issuedDate: "29/12/2023",
      issuingUnit: "Bộ Công Thương",
      formType: "Quy tắc xuất xứ",
      discovery: {
        listingUrl: "https://ecosys.gov.vn/Homepage/DocumentView.aspx",
        mirroredFileUrl: "https://ecosys.gov.vn/Documents/TT44.2023.TT.BCT.rar",
      },
      preferredTextSource: { sourceId: "official-text" },
      renderSource: { sourceId: "official-text", label: "Official markdown", path: "/tmp/legal-rendered.md" },
      officialPageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=164845",
      officialHtmlPath: "/tmp/legal-official.html",
      attachmentFiles: [{ label: "Phụ lục I.pdf", path: "/tmp/legal-attachment.pdf" }],
      extractionPath: "/tmp/legal-extraction.json",
      extractionAudit: { quality: "noisy" },
      qualityClassName: "quality-noisy",
      rawBinarySource: { localPath: "/home/vp/workspace/client/barry-CO/data/legal/official-mirror/test/legal-binary.pdf" },
    },
  ];
  const counts = {
    documents: 1,
    preferredOfficialText: 1,
    temporaryEcosysExtraction: 0,
    bySourceType: {
      official_html: 1,
      official_pdf_text: 0,
      official_pdf_scan: 0,
      official_binary_legacy_doc: 0,
    },
  };

  await fs.mkdir("/home/vp/workspace/client/barry-CO/data/legal/official-mirror/test", { recursive: true });
  await Promise.all([
    fs.writeFile("/tmp/legal-rendered.md", "# Rendered\n"),
    fs.writeFile("/tmp/legal-official.html", "<div>official html</div>"),
    fs.writeFile("/tmp/legal-attachment.pdf", "attachment"),
    fs.writeFile("/tmp/legal-extraction.json", JSON.stringify({ artifacts: [{ label: "Phụ lục I.pdf", body: "0101.21 CC\f0101.29 CC" }] })),
    fs.writeFile("/home/vp/workspace/client/barry-CO/data/legal/official-mirror/test/legal-binary.pdf", "pdf"),
  ]);

  const server = createLegalLookupServer({
    documents,
    counts,
    documentMap: new Map([["44-2023-tt-bct", documents[0]]]),
    documentPathMap: new Map(),
  });

  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();

  assert.ok(address && typeof address === "object");

  try {
    const detailResponse = await fetch(`http://127.0.0.1:${address.port}/doc/44-2023-tt-bct`);
    const detailHtml = await detailResponse.text();
    assert.match(detailHtml, /Nguồn gốc/);
    assert.match(detailHtml, /Nhãn nguồn luôn đi theo nguồn và loại text đang render/);
    assert.match(detailHtml, /eCoSys PDF OCR/);
    assert.match(detailHtml, /eCoSys MIX \(DOCX \+ PDF\)/);
    assert.match(detailHtml, /VBPL · Trang toàn văn chính thức/);
    assert.match(detailHtml, /vbpl\.vn/);
    assert.match(detailHtml, /\/source\/44-2023-tt-bct\/raw-binary/);
    assert.match(detailHtml, /\/source\/44-2023-tt-bct\/attachment\/0/);
    assert.match(detailHtml, /File con mirror local/);
    assert.match(detailHtml, /Trạng thái dữ liệu phụ lục/);
    assert.match(detailHtml, /class="topnav topnav-compact"/);
    assert.doesNotMatch(detailHtml, /class="topnav-tabs"/);
    assert.match(detailHtml, /href="\/doc\/44-2023-tt-bct\?lang=en"/);
    assert.match(detailHtml, /Đang xem từ:<\/span> VBPL HTML/);

    const rawResponse = await fetch(`http://127.0.0.1:${address.port}/source/44-2023-tt-bct/extraction-json`);
    const rawHtml = await rawResponse.text();
    assert.match(rawHtml, /legal-extraction\.json/);
    assert.match(rawHtml, /Phụ lục I\.pdf/);

    const attachmentResponse = await fetch(`http://127.0.0.1:${address.port}/source/44-2023-tt-bct/attachment/0`);
    assert.equal(attachmentResponse.status, 200);
  } finally {
    await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
    await Promise.allSettled([
      fs.unlink("/tmp/legal-rendered.md"),
      fs.unlink("/tmp/legal-official.html"),
      fs.unlink("/tmp/legal-attachment.pdf"),
      fs.unlink("/tmp/legal-extraction.json"),
      fs.unlink("/home/vp/workspace/client/barry-CO/data/legal/official-mirror/test/legal-binary.pdf"),
    ]);
  }
});
