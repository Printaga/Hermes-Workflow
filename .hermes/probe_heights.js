/**
 * Layout probe: who owns the height above the canvas? Walk the ancestor chain before and
 * after selecting a node, so the empty band has a visible owner instead of a guess.
 */
const { launch, requiredToken } = require('./probe_browser');

const BASE = process.env.BASE || 'http://127.0.0.1:9119';
const TOKEN = requiredToken();

const chain = () => {
  const svg = document.querySelector('svg[data-vw="canvas"]');
  const out = [];
  let el = svg;
  while (el && el !== document.documentElement) {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    out.push({
      // The slice applies to the whole selector, not just the class suffix.
      sel: (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
        (el.className && typeof el.className === 'string'
          ? '.' + el.className.trim().split(/\s+/).join('.')
          : '')).slice(0, 40),
      height: +r.height.toFixed(1),
      display: cs.display,
      flex: cs.flex,
      minHeight: cs.minHeight,
      overflow: cs.overflowY,
    });
    el = el.parentElement;
  }
  return out;
};

(async () => {
  const browser = await launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript((token) => {
    window.__HERMES_SESSION_TOKEN__ = token;
  }, TOKEN);
  const page = await ctx.newPage();
  await page.goto(BASE + '/workflows', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('svg[data-vw="canvas"]', { state: 'visible', timeout: 15000 });
  console.log('--- before ---');
  for (const row of await page.evaluate(chain)) console.log(JSON.stringify(row));
  const node = page.locator('[data-vw="canvas"] g').filter({ has: page.locator('rect') }).first();
  await node.waitFor({ state: 'visible', timeout: 15000 });
  await node.click();
  await page.waitForFunction(
    () => document.querySelector('svg[data-vw="canvas"]')?.getBoundingClientRect().height > 0,
    null, { timeout: 5000 },
  ).catch(() => {});
  console.log('--- after ---');
  for (const row of await page.evaluate(chain)) console.log(JSON.stringify(row));
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
