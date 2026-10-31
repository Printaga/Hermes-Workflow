/**
 * Widget copy of the layout probe: node bar height and canvas band before/after a selection.
 *
 * WIDGET_URL / SHOT may override the defaults; the widget is loaded from this checkout.
 */
const os = require('os');
const path = require('path');
const { pathToFileURL } = require('url');
const { launch } = require('./probe_browser');

const WIDGET = process.env.WIDGET_URL ||
  pathToFileURL(path.resolve(__dirname, '..', 'widgets', 'designer.html')).href;
const SHOT = process.env.SHOT || path.join(os.tmpdir(), 'widget-after-select.png');

const measure = () => {
  const kit = document.querySelector('#kit');
  const wrap = document.querySelector('#canvaswrap');
  const svg = document.querySelector('#canvas');
  const app = document.querySelector('#app');
  if (!kit || !wrap || !svg || !app) {
    throw new Error('missing probe selectors: ' + JSON.stringify({
      kit: !!kit, wrap: !!wrap, svg: !!svg, app: !!app,
    }));
  }
  const r = (el) => +el.getBoundingClientRect().height.toFixed(1);
  return {
    app: r(app),
    kit: r(kit),
    wrap: r(wrap),
    svg: r(svg),
    gapAboveCanvas: +(wrap.getBoundingClientRect().top - kit.getBoundingClientRect().bottom).toFixed(1),
    appClass: app.className,
    kitFlex: getComputedStyle(kit).flex,
  };
};

(async () => {
  const errors = [];
  const browser = await launch();
  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

    await page.goto(WIDGET, { waitUntil: 'load' });
    await page.waitForSelector('#canvas g.node', { state: 'visible', timeout: 15000 });
    console.log('before', JSON.stringify(await page.evaluate(measure)));

    // No force click: a node that is covered or hidden is a defect, not something to click
    // through.
    await page.locator('#canvas g.node').first().click();
    await page.waitForFunction(
      () => document.querySelector('#inspector')?.textContent.trim().length > 0,
      null, { timeout: 5000 },
    ).catch(() => {});
    await page.waitForTimeout(200); // let the inspector's layout settle before measuring

    console.log('after ', JSON.stringify(await page.evaluate(measure)));
    await page.screenshot({ path: SHOT });

    const realErrors = errors.filter((e) => !/api\/plugins/.test(e));
    console.log('console errors:', JSON.stringify(realErrors));
    if (realErrors.length) throw new Error(`widget console errors: ${realErrors.join('\n')}`);
  } finally {
    await browser.close().catch(() => {});
  }
})().catch((e) => {
  console.error('PROBE FAILED', e);
  process.exit(1);
});
