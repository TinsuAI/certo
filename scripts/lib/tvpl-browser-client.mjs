import puppeteer from "puppeteer";
import { existsSync } from "node:fs";

import {
  buildTvplBrowserLaunchOptions,
  buildTvplBrowserConnectionConfig,
  classifySearchResponse,
  extractTvplContentFragment,
  extractTvplSearchEntriesFromHtml,
} from "./legal-source-resolution.mjs";

const DEFAULT_TIMEOUT_MS = 15000;
const CHALLENGE_SETTLE_TIMEOUT_MS = 5000;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForChallengeToSettle(page, timeoutMs = CHALLENGE_SETTLE_TIMEOUT_MS) {
  const startedAt = Date.now();

  while ((Date.now() - startedAt) < timeoutMs) {
    const html = await page.content();
    const state = classifySearchResponse(html);
    if (state.status !== "blocked") {
      return {
        html,
        state,
      };
    }

    await sleep(1000);
  }

  const html = await page.content();
  return {
    html,
    state: classifySearchResponse(html),
  };
}

export class TvplBrowserClient {
  constructor() {
    this.browser = null;
    this.page = null;
  }

  async open() {
    if (this.browser) {
      return;
    }

    const connectionConfig = buildTvplBrowserConnectionConfig(process.env);
    if (connectionConfig.mode === "connect") {
      this.browser = await puppeteer.connect({
        browserURL: connectionConfig.browserURL,
      });
    } else {
      this.browser = await puppeteer.launch(
        buildTvplBrowserLaunchOptions(process.env, process.platform, existsSync),
      );
    }

    this.page = await this.browser.newPage();
    await this.page.setUserAgent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36");
    await this.page.setExtraHTTPHeaders({
      "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    });
    await this.page.setViewport({ width: 1440, height: 1200 });
  }

  async close() {
    if (!this.browser) {
      return;
    }

    const connectionConfig = buildTvplBrowserConnectionConfig(process.env);
    if (connectionConfig.mode === "connect") {
      await this.page.close();
      await this.browser.disconnect();
    } else {
      await this.browser.close();
    }
    this.browser = null;
    this.page = null;
  }

  async goto(url) {
    await this.open();
    await this.page.goto(url, {
      waitUntil: "domcontentloaded",
      timeout: DEFAULT_TIMEOUT_MS,
    });
    return waitForChallengeToSettle(this.page);
  }

  async search(searchTerm) {
    const url = `https://thuvienphapluat.vn/page/tim-van-ban.aspx?keyword=${encodeURIComponent(searchTerm)}&match=True&area=0`;
    const { html, state } = await this.goto(url);

    if (state.status === "blocked") {
      return {
        status: "blocked",
        blocker: state.blocker,
        searchTerm,
      };
    }

    return {
      status: "ok",
      searchTerm,
      entries: extractTvplSearchEntriesFromHtml(html),
      html,
    };
  }

  async fetchPage(pageUrl) {
    const { html, state } = await this.goto(pageUrl);

    if (state.status === "blocked") {
      return {
        status: "blocked",
        blocker: state.blocker,
        pageUrl,
      };
    }

    return {
      status: "ok",
      pageUrl,
      html,
      contentHtml: extractTvplContentFragment(html),
    };
  }
}
