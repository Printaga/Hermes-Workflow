/**
 * Item 2 diagnosis: which ancestor loses its height when a node is selected?
 */
const { launch, requiredToken } = require('./probe_browser');

const BASE = process.env.BASE || 'http://127.0.0.1:9119';
const TOKEN = requiredToken();

const chain = () => {
  let el = document.querySelector('.vw-app');
  if (!el) throw new Error('.vw-app not found — the page failed to load or auth failed');
  const out = [];
  while (el && out.length < 9) {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    out.push({
      tag: el.tagName.toLowerCase(),
      // SVG elements expose className as an SVGAnimatedString, so read the attribute.
      cls: String(el.getAttribute('class') || el.id || '').slice(0, 34),
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
  const browser = await launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript((token) => {
    window.__HERMES_SESSION_TOKEN__ = token;
  }, TOKEN);
  const page = await ctx.newPage();
  await page.goto(BASE + '/workflows', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.vw-app', { timeout: 15000 });

  console.log('--- BEFORE selection ---');
  for (const x of await page.evaluate(chain)) console.log(JSON.stringify(x));

  // The dashboard draws each node as g.vw-node[data-id]; selecting it thickens the rect stroke
  // to 2, which is the deterministic signal that the re-render has happened.
  const node = page.locator('.vw-app svg g.vw-node[data-id]').first();
  await node.waitFor({ state: 'visible', timeout: 15000 });
  await node.click();
  await page.waitForFunction(
    () => !!document.querySelector('.vw-app svg g.vw-node rect[stroke-width="2"]'),
    null, { timeout: 5000 },
  ).catch(() => {});

  console.log('--- AFTER selection ---');
  for (const x of await page.evaluate(chain)) console.log(JSON.stringify(x));

  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
