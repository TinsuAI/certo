function decodeHtml(value) {
  return value
    .replace(/&#(\d+);/g, (_, num) => String.fromCharCode(Number(num)))
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ");
}

export const OFFICIAL_VBPL_SEEDS = {
  "23/2025/TT-BCT": {
    sourceType: "vbpl-toanvan",
    pageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=177442&dvid=13",
  },
  "39/2018/TT-BCT": {
    sourceType: "vbpl-toanvan",
    pageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=133209",
  },
  "44/2023/TT-BCT": {
    sourceType: "vbpl-toanvan",
    pageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=164845",
  },
  "41/2022/TT-BCT": {
    sourceType: "vbpl-toanvan",
    pageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=163216",
  },
  "37/2022/TT-BCT": {
    sourceType: "vbpl-toanvan",
    pageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=181555",
  },
  "04/2024/TT-BCT": {
    sourceType: "vbpl-toanvan",
    pageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=166295",
  },
  "02/2024/TT-BCT": {
    sourceType: "vbpl-toanvan",
    pageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=164927",
  },
  "01/2024/TT-BCT": {
    sourceType: "vbpl-toanvan",
    pageUrl: "https://vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=164895",
  },
};

function stripTags(value) {
  return decodeHtml(value).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function normalizeIssueCode(value) {
  return value
    .replace(/[đĐ]/g, "d")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

export function buildVntrSearchUrl(document) {
  return `https://vntr.moit.gov.vn/legal-documents?doc_code=${encodeURIComponent(document.issueCode)}&page=agreements`;
}

export function extractVntrCsrfToken(html) {
  const match = html.match(/<meta name="csrf-token" content="([^"]+)"/i);
  return match ? match[1] : null;
}

export function extractVntrSearchEntriesFromHtml(html) {
  const entries = [];
  const rowPattern = /<tr\b[^>]*class="[^"]*tr-measures[^"]*"[^>]*>[\s\S]*?showDocument\((\d+)\)[\s\S]*?<\/tr>/g;

  for (const rowMatch of html.matchAll(rowPattern)) {
    const rowHtml = rowMatch[0];
    const detailId = Number(rowMatch[1]);
    const docType = rowHtml.match(/<td class="docType"[^>]*>([\s\S]*?)<\/td>/);
    const issueCode = rowHtml.match(/<td[^>]*class="docCode"[^>]*>([\s\S]*?)<\/td>/);
    const title = rowHtml.match(/<td class="docName"[^>]*>([\s\S]*?)<\/td>/);
    const issuingAgency = rowHtml.match(/<td class="docAgent"[^>]*>([\s\S]*?)<\/td>/);
    const issuedDate = rowHtml.match(/<td class="docDate"[^>]*>([\s\S]*?)<\/td>/);

    if (!docType || !issueCode || !title || !issuingAgency || !issuedDate) {
      continue;
    }

    entries.push({
      detailId,
      docType: stripTags(docType[1]),
      issueCode: stripTags(issueCode[1]),
      title: stripTags(title[1]),
      issuingAgency: stripTags(issuingAgency[1]),
      issuedDate: stripTags(issuedDate[1]),
    });
  }

  return entries;
}

export function pickBestVntrSearchEntry(document, entries) {
  const expected = normalizeIssueCode(document.issueCode);
  return entries.find((entry) => normalizeIssueCode(entry.issueCode) === expected) || null;
}

export function getOfficialVbplSeed(document) {
  return OFFICIAL_VBPL_SEEDS[document.issueCode] || null;
}

export function extractHtmlElementById(html, elementId) {
  const openTagPattern = new RegExp(`<([a-z0-9]+)([^>]*\\sid=["'])${elementId}(["'][^>]*)>`, "i");
  const match = openTagPattern.exec(html);
  if (!match) {
    return null;
  }

  const tagName = match[1].toLowerCase();
  let depth = 1;
  let cursor = match.index + match[0].length;

  while (cursor < html.length) {
    const nextOpen = html.slice(cursor).match(new RegExp(`<${tagName}(\\s|>)`, "i"));
    const nextClose = html.slice(cursor).match(new RegExp(`</${tagName}>`, "i"));

    if (!nextClose) {
      return null;
    }

    const nextOpenIndex = nextOpen ? cursor + nextOpen.index : Number.POSITIVE_INFINITY;
    const nextCloseIndex = cursor + nextClose.index;

    if (nextOpenIndex < nextCloseIndex) {
      depth += 1;
      cursor = nextOpenIndex + nextOpen[0].length;
      continue;
    }

    depth -= 1;
    cursor = nextCloseIndex + nextClose[0].length;
    if (depth === 0) {
      return html.slice(match.index, cursor);
    }
  }

  return null;
}

export function extractVbplContentFragment(html) {
  return extractHtmlElementById(html, "toanvancontent");
}
