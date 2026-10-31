/**
 * Layout probe: does selecting a node open an empty band above the canvas?
 *
 * Measures the node bar (and the gap between it and the svg) before and after a node is
 * selected, on whichever bundle the dashboard is serving.
 */
const os = require('os');
const path = require('path');
const { launch, requiredToken } = require('./probe_browser');

const BASE = process.env.BASE || 'http://127.0.0.1:9119';
const SHOT_DIR = process.env.SHOT_DIR || os.tmpdir();
const TOKEN = requiredToken();

const measure = () => {
  const bar = document.querySelector('.vw-kit') || document.querySelector('#kit');
  const svg = document.querySelector('svg[data-vw="canvas"]') || document.querySelector('svg');
  const app = document.querySelector('.vw-app') || document.querySelector('#app');
  const insp = document.querySelector('.vw-inspector') || document.querySelector('#inspector');
  const r = el => (el ? el.getBoundingClientRect() : null);
  const b = r(bar), s = r(svg);
  if (!app) return { error: 'app-shell-not-found', kitHeight: null, gapAboveCanvas: null };
  // Every block between the shell top and the canvas, so an "empty band" has a name.
  const stack = Array.from(app.children).map(el => {
    const rr = r(el);
    return {
      tag: el.tagName.toLowerCase(),
      cls: (el.className || el.id || '').toString().slice(0, 30),
      top: +rr.top.toFixed(1), height: +rr.height.toFixed(1),
      text: (el.innerText || '').trim().slice(0, 26),
    };
  });
  const wrap = document.querySelector('.vw-canvaswrap') || document.querySelector('#canvaswrap');
  return {
    appHeight: app ? +r(app).height.toFixed(1) : null,
    wrapHeight: wrap ? +r(wrap).height.toFixed(1) : null,
    stack: stack,
    kitHeight: b ? +b.height.toFixed(1) : null,
    kitBottom: b ? +b.bottom.toFixed(1) : null,
    svgTop: s ? +s.top.toFixed(1) : null,
    gapAboveCanvas: b && s ? +(s.top - b.bottom).toFixed(1) : null,
    svgHeight: s ? +s.height.toFixed(1) : null,
    inspectorWidth: insp ? +r(insp).width.toFixed(1) : null,
    appClass: app ? app.className : null,
    kitFlex: bar ? getComputedStyle(bar).flex : null,
  };
};

(async () => {
  const browser = await launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript((token) => {
    window.__HERMES_SESSION_TOKEN__ = token;
  }, TOKEN);
  const page = await ctx.newPage();
  await page.goto(BASE + '/workflows', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('[data-vw="canvas"] g.node, svg[data-vw="canvas"] g', { timeout: 15000 });

  console.log('before selection :', JSON.stringify(await page.evaluate(measure)));
  await page.screenshot({ path: path.join(SHOT_DIR, 'layout-before.png') });

  // Click the trigger node the way a user does.
  const node = page.locator('[data-vw="canvas"] g.node').first();
  if (await node.count()) {
    await node.waitFor({ state: 'visible', timeout: 15000 });
    await node.click();
  } else {
    const fallback = page.locator('svg g').first();
    if (await fallback.count()) await fallback.click({ timeout: 5000 });
    else throw new Error('probe: no canvas node found (both selectors empty)');
  }
  await page.waitForSelector(
    '.vw-inspector:not(:empty), g.node.selected, g.node[data-selected="true"]',
    { timeout: 5000 },
  ).catch(() => {});

  console.log('after  selection :', JSON.stringify(await page.evaluate(measure)));
  await page.screenshot({ path: path.join(SHOT_DIR, 'layout-after.png') });

  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
