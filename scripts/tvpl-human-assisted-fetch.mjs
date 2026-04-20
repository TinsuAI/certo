import { promises as fs } from "node:fs";
import path from "node:path";
import { stdout as output } from "node:process";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";

import puppeteer from "puppeteer";

import {
  buildTvplBrowserLaunchOptions,
  classifySearchResponse,
  extractTvplContentFragment,
  extractTvplSearchEntriesFromHtml,
} from "./lib/legal-source-resolution.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const NORMALIZED_ROOT = path.join(ROOT, "data", "legal", "normalized", "ecosys");
const MANUAL_CACHE_DIR = path.join(NORMALIZED_ROOT, "manual-browser-cache", "tvpl");

function sanitizeFileName(value) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120) || "tvpl-page";
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

async function waitForResolvablePage(page, targetUrl) {
  const timeoutMs = Number(process.env.TVPL_MANUAL_TIMEOUT_MS || 300000);
  const pollIntervalMs = Number(process.env.TVPL_MANUAL_POLL_INTERVAL_MS || 1000);
  const startedAt = Date.now();

  while ((Date.now() - startedAt) < timeoutMs) {
    if (page.isClosed()) {
      return {
        status: "aborted",
        blocker: "browser_closed_by_user",
        url: targetUrl,
        title: null,
        html: null,
      };
    }

    const html = await page.content();
    const state = classifySearchResponse(html);
    if (state.status !== "blocked") {
      return {
        status: state.status,
        blocker: state.blocker || null,
        url: page.url(),
        title: await page.title(),
        html,
      };
    }

    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }

  return {
    status: "blocked",
    blocker: "manual_timeout",
    url: page.url(),
    title: await page.title(),
    html: await page.content(),
  };
}

async function main() {
  const targetUrl = process.argv[2] || process.env.TVPL_URL;
  if (!targetUrl) {
    throw new Error("Provide a TVPL URL as argv[2] or TVPL_URL.");
  }

  await ensureDir(MANUAL_CACHE_DIR);

  const browser = await puppeteer.launch({
    ...buildTvplBrowserLaunchOptions(
      {
        ...process.env,
        TVPL_BROWSER_MODE: process.env.TVPL_BROWSER_MODE || "headful",
      },
      process.platform,
      existsSync,
    ),
    defaultViewport: { width: 1440, height: 1000 },
  });

  const page = await browser.newPage();
  await page.setUserAgent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36");
  await page.setExtraHTTPHeaders({
    "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
  });
  await page.goto(targetUrl, {
    waitUntil: "domcontentloaded",
    timeout: 30000,
  });

  output.write(`Opened TVPL browser at:\n${targetUrl}\n`);
  output.write("Interact in the browser window. The script will capture automatically once the page leaves the challenge state.\n");
  output.write("Close the browser window to abort.\n");

  const capture = await waitForResolvablePage(page, targetUrl);
  const html = capture.html || "";
  const searchEntries = html ? extractTvplSearchEntriesFromHtml(html) : [];
  const contentHtml = html ? extractTvplContentFragment(html) : null;
  const slug = sanitizeFileName(`${new URL(targetUrl).pathname}-${Date.now()}`);
  const htmlPath = path.join(MANUAL_CACHE_DIR, `${slug}.html`);

  if (html) {
    await fs.writeFile(htmlPath, html);
  }

  console.log(JSON.stringify({
    status: capture.status,
    blocker: capture.blocker || null,
    url: capture.url,
    title: capture.title,
    htmlPath: html ? htmlPath : null,
    searchEntryCount: searchEntries.length,
    hasContentFragment: Boolean(contentHtml),
  }, null, 2));

  await browser.close();
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
