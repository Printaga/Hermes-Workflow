/**
 * Live probe: the Run button must always leave a persistent, visible verdict.
 *
 * Case A — an unsaved draft: Run must refuse locally with a banner, no 404 POST.
 * Case B — a saved design: Run must reach the backend and the outcome must be in the banner.
 */
const { chromium } = require('/home/lenovo/.hermes/hermes-agent/node_modules/playwright');

const BASE = 'http://127.0.0.1:9119';
const TOKEN = 'probe-token-9119';

function report(label, state) {
  console.log(`\n=== ${label} ===`);
  console.log(JSON.stringify(state, null, 2));
}

(async () => {
  const logs = [];
  const network = [];
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/google-chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript(`window.__HERMES_SESSION_TOKEN__ = ${JSON.stringify(TOKEN)};`);
  const page = await ctx.newPage();
  page.on('console', m => logs.push(`[${m.type()}] ${m.text()}`));
  page.on('pageerror', e => logs.push(`[pageerror] ${e.message}`));
  page.on('response', async r => {
    const u = r.url();
    if (!/\/api\/plugins\//.test(u)) return;
    let body = '';
    try { body = (await r.text()).slice(0, 220); } catch (e) { body = `<unreadable>`; }
    network.push(`${r.status()} ${r.request().method()} ${u.replace(BASE, '')} ${body}`);
  });

  const bannerOf = () => page.evaluate(() => {
    const b = document.querySelector('[data-vw="banner"]');
    if (!b) return '(no banner element)';
    return { hidden: b.hidden, cls: b.className, live: b.getAttribute('aria-live'), text: b.innerText.trim() };
  });

  await page.goto(BASE + '/workflows', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  // ---- Case A: the draft is called "untitled" and was never saved.
  network.length = 0;
  await page.locator('[data-vw="run-now"]').click();
  await page.waitForTimeout(1500);
  report('A. Run on an unsaved draft', {
    banner: await bannerOf(),
    runBox: (await page.locator('[data-vw="run"]').innerText()).trim().slice(0, 200),
    apiCalls: network,
  });

  // ---- Case B: pick the saved hello-world design and run it.
  const select = page.locator('select').first();
  await select.selectOption('hello-world');
  await page.waitForTimeout(1200);
  network.length = 0;
  await page.locator('[data-vw="run-now"]').click();
  await page.waitForTimeout(4000);
  report('B. Run on the saved hello-world', {
    banner: await bannerOf(),
    runBox: (await page.locator('[data-vw="run"]').innerText()).trim().slice(0, 400),
    apiCalls: network,
  });

  console.log('\n=== console ===');
  for (const line of logs) console.log(line);
  await page.screenshot({ path: '/tmp/item1.png', fullPage: false });
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
