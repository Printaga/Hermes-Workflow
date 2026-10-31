/**
 * Who makes the canvas band tall before a selection, and who takes it away after?
 * Logs the wrap's children, their heights, and the svg's own attributes both ways.
 */
const { launch, requiredToken } = require('./probe_browser');

const BASE = process.env.BASE || 'http://127.0.0.1:9119';
const TOKEN = requiredToken();

const probe = () => {
  const wrap = document.querySelector('.vw-wrap');
  const kids = wrap ? Array.from(wrap.children).map(el => {
    const r = el.getBoundingClientRect();
    return { tag: el.tagName.toLowerCase(), h: +r.height.toFixed(1), w: +r.width.toFixed(1), attrs: el.tagName.toLowerCase() === 'svg' ? { width: el.getAttribute('width'), height: el.getAttribute('height'), viewBox: el.getAttribute('viewBox') } : {} };
  }) : [];
  const cs = wrap ? getComputedStyle(wrap) : null;
  return {
    wrapH: wrap ? +wrap.getBoundingClientRect().height.toFixed(1) : null,
    wrapClientH: wrap ? wrap.clientHeight : null,
    wrapScrollH: wrap ? wrap.scrollHeight : null,
    wrapAlignSelf: cs && cs.alignSelf,
    kids,
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
  await page.waitForSelector('.vw-wrap', { state: 'attached', timeout: 15000 });
  console.log('before', JSON.stringify(await page.evaluate(probe)));
  const node = page.locator('[data-vw="canvas"] g').filter({ has: page.locator('rect') }).first();
  await node.waitFor({ state: 'visible', timeout: 15000 });
  await node.click();
  await page.waitForFunction(
    () => (document.querySelector('.vw-wrap')?.getBoundingClientRect().height || 0) > 0,
    null, { timeout: 5000 },
  ).catch(() => {});
  console.log('after ', JSON.stringify(await page.evaluate(probe)));
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
