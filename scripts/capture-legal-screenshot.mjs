import path from "node:path";
import { promises as fs } from "node:fs";

import puppeteer from "puppeteer";

const targetUrl = process.argv[2];
const outputPath = process.argv[3]
  ? path.resolve(process.argv[3])
  : path.resolve("data", "legal", "screenshots", "legal-view.png");
const width = Number(process.argv[4] || 1440);
const height = Number(process.argv[5] || 2200);
const captureMode = process.argv[6] === "viewport" ? "viewport" : "full";

if (!targetUrl) {
  console.error("Usage: node scripts/capture-legal-screenshot.mjs <url> [outputPath] [width] [height] [full|viewport]");
  process.exit(1);
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });

const browser = await puppeteer.launch({
  headless: "new",
  defaultViewport: {
    width,
    height,
    deviceScaleFactor: 1.25,
  },
});

try {
  const page = await browser.newPage();
  await page.goto(targetUrl, { waitUntil: "networkidle2", timeout: 60_000 });
  await page.screenshot({
    path: outputPath,
    fullPage: captureMode === "full",
  });
  console.log(outputPath);
} finally {
  await browser.close();
}
