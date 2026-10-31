/**
 * Live probe: what really happens when Run is clicked on the dashboard tab.
 *
 * Drives real Chromium against the running dashboard, records every console message,
 * every /api/plugins/* response, and the visible text afterwards.
 *
 * TOK=<dashboard session token> [BASE=...] node .hermes/probe_run.js
 */
const os = require('os');
const path = require('path');
const { launch, requiredToken } = require('./probe_browser');

const BASE = process.env.BASE || 'http://127.0.0.1:9119';
const TOKEN = requiredToken();
const SHOT = process.env.SHOT || path.join(os.tmpdir(), 'run-click.png');

(async () => {
  const messages = [];
  const network = [];
  const pending = [];
  const browser = await launch();
  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await ctx.addInitScript((token) => {
      window.__HERMES_SESSION_TOKEN__ = token;
    }, TOKEN);
    const page = await ctx.newPage();

    page.on('console', (m) => messages.push(`[${m.type()}] ${m.text()}`));
    page.on('pageerror', (e) => messages.push(`[pageerror] ${e.message}`));
    page.on('requestfailed', (r) => messages.push(`[requestfailed] ${r.url()} ${r.failure()?.errorText}`));
    page.on('response', (r) => {
      const u = r.url();
      if (!/\/api\/(plugins|dashboard)/.test(u)) return;
      // Collect the promise so the final print cannot run before the bodies are in.
      const entry = { status: r.status(), method: r.request().method(), url: u, body: '' };
      network.push(entry);
      pending.push(r.text().then((text) => {
        entry.body = text.slice(0, 500);
      }).catch((e) => {
        entry.body = `<unreadable ${e.message}>`;
      }));
    });

    await page.goto(BASE + '/workflows', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('[data-vw="run-now"]', { state: 'visible', timeout: 15000 });

    console.log('=== url / title ===');
    console.log(page.url(), '|', await page.title());

    const controls = await page.evaluate(() => Array.from(
      document.querySelectorAll('button,select,input')).map((el) => ({
        tag: el.tagName.toLowerCase(),
        text: (el.innerText || el.value || '').trim().slice(0, 34),
        dvw: el.getAttribute('data-vw') || '',
        disabled: !!el.disabled,
        visible: !!(el.offsetWidth || el.offsetHeight),
      })));
    console.log('=== controls ===');
    for (const c of controls) console.log(JSON.stringify(c));

    const run = page.locator('[data-vw="run-now"]').first();
    if (!(await run.count())) {
      // A missing control is a failed probe, not a successful no-op.
      throw new Error('no [data-vw="run-now"] button found');
    }
    await run.waitFor({ state: 'visible', timeout: 10000 });
    console.log('=== run button ===', JSON.stringify(await run.innerText()),
      'enabled=', await run.isEnabled());
    console.log('=== banner before ===', JSON.stringify(await page.evaluate(
      () => document.querySelector('[data-vw="banner"]')?.innerText ?? '(none)')));

    await run.click();
    // Wait for the banner to stop saying "Running…" rather than sleeping a fixed span:
    // a refusal lands instantly, an agent run takes as long as it takes.
    await page.waitForFunction(() => {
      const b = document.querySelector('[data-vw="banner"]');
      const text = (b?.innerText || '').trim();
      return !!text && !/^(running|validating|saving)\b/i.test(text);
    }, null, { timeout: 30000 }).catch(() => {});
    await Promise.allSettled(pending);

    const after = await page.evaluate(() => {
      const b = document.querySelector('[data-vw="banner"]');
      const status = document.querySelector('[data-vw="status"]');
      const runBox = document.querySelector('[data-vw="run"]');
      return {
        banner: b ? { hidden: b.hidden, cls: b.className, text: b.innerText } : null,
        status: status ? status.innerText : null,
        run: runBox ? runBox.innerText.slice(0, 600) : null,
        body: document.body.innerText.slice(0, 1500),
      };
    });
    console.log('=== after click ===');
    console.log(JSON.stringify(after, null, 2));

    console.log('=== console ===');
    for (const line of messages) console.log(line);
    console.log('=== network ===');
    for (const x of network) console.log(`${x.status} ${x.method} ${x.url} :: ${x.body}`);

    await page.screenshot({ path: SHOT });
  } finally {
    await browser.close().catch(() => {});
  }
})().catch((e) => {
  console.error('PROBE FAILED', e);
  process.exit(1);
});
