export function shouldResolveFallbackTextSource({ officialTextResolved }) {
  return !officialTextResolved;
}

export function classifySearchResponse(html) {
  if (
    html.includes("window._cf_chl_opt") ||
    html.includes("Just a moment...") ||
    html.includes("/cdn-cgi/challenge-platform/")
  ) {
    return {
      status: "blocked",
      blocker: "cloudflare_challenge",
    };
  }

  return {
    status: "ok",
  };
}

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

export function extractTvplSearchEntriesFromHtml(html) {
  const entries = [];
  const seen = new Set();
  const pattern = /<a[^>]+href="(https:\/\/thuvienphapluat\.vn\/van-ban\/[^"]+)"[^>]*>([\s\S]*?)<\/a>/g;

  for (const match of html.matchAll(pattern)) {
    const url = decodeHtml(match[1]).split("?")[0];
    if (seen.has(url)) {
      continue;
    }
    seen.add(url);

    entries.push({
      url,
      title: decodeHtml(match[2]).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(),
    });
  }

  return entries;
}

export function extractTvplContentFragment(html) {
  const marker = 'class="content1"';
  const markerIndex = html.indexOf(marker);
  if (markerIndex === -1) {
    return null;
  }

  const start = html.lastIndexOf("<div", markerIndex);
  if (start === -1) {
    return null;
  }

  let depth = 0;
  let index = start;

  while (index < html.length) {
    const nextOpen = html.indexOf("<div", index);
    const nextClose = html.indexOf("</div>", index);

    if (nextClose === -1) {
      return null;
    }

    if (nextOpen !== -1 && nextOpen < nextClose) {
      depth += 1;
      index = nextOpen + 4;
      continue;
    }

    depth -= 1;
    index = nextClose + 6;
    if (depth === 0) {
      return html.slice(start, index);
    }
  }

  return null;
}

export function buildTvplBrowserConnectionConfig(env = process.env) {
  const browserURL = env.TVPL_REMOTE_DEBUGGING_URL?.trim();
  if (browserURL) {
    return {
      mode: "connect",
      browserURL,
      headless: false,
    };
  }

  const forcedMode = env.TVPL_BROWSER_MODE?.trim().toLowerCase();
  return {
    mode: "launch",
    browserURL: null,
      headless: forcedMode === "headful" ? false : true,
    };
}

const WINDOWS_EDGE_EXECUTABLES = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];

const WINDOWS_CHROME_EXECUTABLES = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];

export function resolveWindowsBrowserExecutable(preferredBrowser = "edge", pathExists = () => false) {
  const normalizedBrowser = preferredBrowser.trim().toLowerCase() === "chrome"
    ? "chrome"
    : "edge";

  const preferredCandidates = normalizedBrowser === "chrome"
    ? WINDOWS_CHROME_EXECUTABLES
    : WINDOWS_EDGE_EXECUTABLES;

  const fallbackCandidates = normalizedBrowser === "chrome"
    ? WINDOWS_EDGE_EXECUTABLES
    : WINDOWS_CHROME_EXECUTABLES;

  for (const candidate of [...preferredCandidates, ...fallbackCandidates]) {
    if (pathExists(candidate)) {
      return candidate;
    }
  }

  return preferredCandidates[0];
}

export function buildTvplBrowserLaunchOptions(
  env = process.env,
  platform = process.platform,
  pathExists = () => false,
) {
  const connectionConfig = buildTvplBrowserConnectionConfig(env);
  const launchOptions = {
    headless: connectionConfig.headless,
    args: platform === "win32"
      ? []
      : [
        "--no-sandbox",
        "--disable-setuid-sandbox",
      ],
  };

  const configuredExecutable = env.TVPL_BROWSER_EXECUTABLE?.trim();
  if (configuredExecutable) {
    return {
      ...launchOptions,
      executablePath: configuredExecutable,
    };
  }

  if (platform === "win32") {
    return {
      ...launchOptions,
      executablePath: resolveWindowsBrowserExecutable(
        env.TVPL_WINDOWS_BROWSER || "edge",
        pathExists,
      ),
    };
  }

  return launchOptions;
}

export function buildPreferredTextSource({
  officialTextCandidate,
  fallbackTextCandidate,
  ocrTextCandidate,
  binaryExtractionCandidate,
}) {
  if (officialTextCandidate?.status === "resolved") {
    return {
      sourceId: officialTextCandidate.sourceId,
      status: "resolved",
      rationale: "official_text_source_resolved",
    };
  }

  if (fallbackTextCandidate?.status === "resolved") {
    return {
      sourceId: fallbackTextCandidate.sourceId,
      status: "resolved",
      rationale: "fallback_text_source_resolved_before_official_text_source",
    };
  }

  if (ocrTextCandidate?.status === "resolved") {
    return {
      sourceId: ocrTextCandidate.sourceId,
      status: "temporary",
      rationale: "ocr_recovery_is_current_best_available_text_source",
    };
  }

  if (binaryExtractionCandidate?.status === "resolved") {
    return {
      sourceId: binaryExtractionCandidate.sourceId,
      status: "temporary",
      rationale: "raw_binary_extraction_is_only_available_text_source",
    };
  }

  return {
    sourceId: null,
    status: "unresolved",
    rationale: "no_text_source_resolved",
  };
}
