/**
 * Live probe: the Run button must always leave a persistent, visible verdict.
 *
 * Case A — an unsaved draft: Run must refuse locally with a banner, no 404 POST.
 * Case B — a saved design: Run must reach the backend and the outcome must be in the banner.
 *
 * TOK=<dashboard session token> node .hermes/probe_item1.js
 */
const os = require('os');
const path = require('path');
const { launch, requiredToken } = require('./probe_browser');

const BASE = process.env.BASE || 'http://127.0.0.1:9119';
const TOKEN = requiredToken();
const SHOT = process.env.SHOT || path.join(os.tmpdir(), 'item1.png');

(async () => {
  const logs = [];
  const network = [];
  const pending = [];
  // Tag every response with the case that was active when it arrived; do NOT reset the
  // shared array, or a slow body read from case A lands in case B.
  let caseId = 'A';
  const browser = await launch();
  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await ctx.addInitScript((token) => {
      window.__HERMES_SESSION_TOKEN__ = token;
    }, TOKEN);
    const page = await ctx.newPage();
    page.on('console', (m) => logs.push(`[${m.type()}] ${m.text()}`));
    page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}`));
    page.on('response', (r) => {
      const u = r.url();
      if (!/\/api\/plugins\//.test(u)) return;
      const entry = {
        case: caseId,
        status: r.status(),
        method: r.request().method(),
        url: u.replace(BASE, ''),
        body: '',
      };
      network.push(entry);
      pending.push(r.text().then((text) => {
        entry.body = text.slice(0, 220);
      }).catch(() => {
        entry.body = '<unreadable>';
      }));
    });

    const bannerOf = () => page.evaluate(() => {
      const b = document.querySelector('[data-vw="banner"]');
      if (!b) return '(no banner element)';
      return {
        hidden: b.hidden,
        cls: b.className,
        live: b.getAttribute('aria-live'),
        text: b.innerText.trim(),
      };
    });

    // A verdict is the banner becoming visible with text; wait for that instead of sleeping.
    const waitVerdict = (timeout) => page.waitForFunction(() => {
      const b = document.querySelector('[data-vw="banner"]');
      return !!b && !b.hidden && (b.innerText || '').trim().length > 0;
    }, null, { timeout }).catch(() => {});

    async function report(label, state, id) {
      await Promise.allSettled(pending);
      console.log(`\n=== ${label} ===`);
      console.log(JSON.stringify({
        ...state,
        apiCalls: network.filter((x) => x.case === id),
      }, null, 2));
    }

    await page.goto(BASE + '/workflows', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('[data-vw="run-now"]', { timeout: 15000 });
    const runButton = page.locator('[data-vw="run-now"]').first();

    // ---- Case A: the draft is called "untitled" and was never saved.
    caseId = 'A';
    await runButton.click();
    await waitVerdict(12000);
    await report('A. Run on an unsaved draft', {
      banner: await bannerOf(),
      runBox: (await page.locator('[data-vw="run"]').innerText()).trim().slice(0, 200),
    }, 'A');

    // ---- Case B: open a saved design (or save a template), then Run immediately. The
    // save→run sequence is the one whose cached name list used to refuse a fresh design.
    caseId = 'B';
    const saved = page.locator('select').first();
    const savedValues = await saved.locator('option').evaluateAll(
      (options) => options.map((o) => o.value).filter(Boolean));
    let name = savedValues.includes('hello-world') ? 'hello-world' : savedValues[0];
    if (name) {
      await saved.selectOption(name);
    } else {
      const templates = page.locator('select').nth(1);
      // Templates are fetched after the page renders; give the picker its options.
      await page.waitForFunction(
        () => (document.querySelectorAll('select')[1]?.options.length || 0) > 1,
        null, { timeout: 10000 },
      ).catch(() => {});
      if ((await templates.locator('option').count()) <= 1) {
        throw new Error('no saved design and no template to run');
      }
      await templates.selectOption({ index: 1 });
      await page.waitForFunction(
        () => (document.querySelector('[data-vw="canvas"]')?.childElementCount || 0) > 0,
        null, { timeout: 10000 },
      );
      name = `probe-item1-${Date.now()}`;
      await page.locator('[data-vw="name"]').fill(name);
      await page.locator('[data-vw="save"]').click();
      await page.waitForFunction(() => {
        const b = document.querySelector('[data-vw="banner"]');
        return /saved/i.test(b?.innerText || '');
      }, null, { timeout: 20000 });
    }
    await page.waitForFunction(
      (wanted) => (document.querySelector('[data-vw="name"]')?.value || '') === wanted,
      name, { timeout: 10000 },
    ).catch(() => {});
    await runButton.click();
    await waitVerdict(30000);
    await report('B. Run on a saved design', {
      name,
      banner: await bannerOf(),
      runBox: (await page.locator('[data-vw="run"]').innerText()).trim().slice(0, 400),
    }, 'B');

    console.log('\n=== console ===');
    for (const line of logs) console.log(line);
    await page.screenshot({ path: SHOT, fullPage: false });
  } finally {
    // Any failed await above must not leak a headless Chrome process.
    await browser.close().catch(() => {});
  }
})().catch((e) => {
  console.error('PROBE FAILED', e);
  process.exit(1);
});
