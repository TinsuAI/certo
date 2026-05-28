import puppeteer from 'puppeteer';
const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
async function login() {
  await page.goto('http://127.0.0.1:8001/clients', { waitUntil: 'networkidle2', timeout: 60000 });
  if (page.url().startsWith('http://127.0.0.1:8754')) {
    await page.type('input[name="email"]', 'admin@data-hub.local');
    await page.type('input[name="password"]', 'admin123');
    await Promise.all([page.click('button[type="submit"]'), page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 })]);
  }
}
await login();
await page.goto('http://127.0.0.1:8001/clients/johnson-vn/co-case/co-case-4e9f5a3b1e9c/origin', { waitUntil: 'networkidle2', timeout: 60000 });
if (page.url().includes('/auth') || page.url().startsWith('http://127.0.0.1:8754')) {
  await login();
  await page.goto('http://127.0.0.1:8001/clients/johnson-vn/co-case/co-case-4e9f5a3b1e9c/origin', { waitUntil: 'networkidle2', timeout: 60000 });
}

// Run 3 timings of /calculate so warm cache vs cold-ish shows up
for (let i = 0; i < 3; i++) {
  const r = await page.evaluate(async () => {
    const t0 = performance.now();
    const r = await fetch('/clients/johnson-vn/co-case/co-case-4e9f5a3b1e9c/origin/sheet/MAS1230-39/calculate', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({}),
    });
    const text = await r.text();
    return { status: r.status, ms: Math.round(performance.now() - t0), bytes: text.length };
  });
  console.log(`run ${i+1}: ${r.status} ${r.ms}ms ${r.bytes}B`);
}
await browser.close();
