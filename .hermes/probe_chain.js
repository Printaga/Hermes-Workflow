/**
 * Item 2 diagnosis: which ancestor loses its height when a node is selected?
 */
const { chromium } = require('/home/lenovo/.hermes/hermes-agent/node_modules/playwright');

const BASE = process.env.BASE || 'http://127.0.0.1:9119';
const TOKEN = process.env.TOK || 'probe-token-9119';

const chain = () => {
  let el = document.querySelector('.vw-app');
  const out = [];
  while (el && out.length < 9) {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    out.push({
      tag: el.tagName.toLowerCase(),
      cls: String(el.className || el.id || '').slice(0, 34),
      h: +r.height.toFixed(1),
      cssH: cs.height,
      display: cs.display,
      flex: cs.flex,
      minH: cs.minHeight,
      overflow: cs.overflow,
    });
    el = el.parentElement;
  }
  return out;
};

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/google-chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript(`window.__HERMES_SESSION_TOKEN__ = ${JSON.stringify(TOKEN)};`);
  const page = await ctx.newPage();
  await page.goto(BASE + '/workflows', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  console.log('--- BEFORE selection ---');
  for (const x of await page.evaluate(chain)) console.log(JSON.stringify(x));

  await page.locator('svg g').first().click({ force: true });
  await page.waitForTimeout(900);

  console.log('--- AFTER selection ---');
  for (const x of await page.evaluate(chain)) console.log(JSON.stringify(x));

  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
