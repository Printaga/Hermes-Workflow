/** Which child of .vw-main owns its 911px height before a selection? Hide each and re-measure. */
const { launch, requiredToken } = require('./probe_browser');
const BASE = process.env.BASE || 'http://127.0.0.1:9119';
const TOKEN = requiredToken();

(async () => {
  const browser = await launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript((token) => {
    window.__HERMES_SESSION_TOKEN__ = token;
  }, TOKEN);
  const page = await ctx.newPage();
  await page.goto(BASE + '/workflows', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.vw-main', { timeout: 15000 });

  const out = await page.evaluate(() => {
    const main = document.querySelector('.vw-main');
    const wrap = document.querySelector('.vw-wrap');
    const insp = document.querySelector('.vw-inspector');
    if (!main || !wrap || !insp) {
      throw new Error('missing probe selectors: ' + JSON.stringify({
        hasMain: !!main, hasWrap: !!wrap, hasInsp: !!insp,
      }));
    }
    const rows = [];
    const m = (label) => rows.push(label + ' main=' + main.getBoundingClientRect().height.toFixed(1) + ' wrap=' + wrap.getBoundingClientRect().height.toFixed(1) + ' insp=' + insp.getBoundingClientRect().height.toFixed(1));
    m('as-is');
    insp.style.display = 'none'; m('inspector hidden');
    insp.style.display = '';
    wrap.style.display = 'none'; m('wrap hidden');
    wrap.style.display = '';
    const app = document.querySelector('.vw-app');
    if (!app) throw new Error('.vw-app not found');
    app.style.height = '400px'; m('app forced 400');
    app.style.height = '';
    return rows;
  });
  for (const r of out) console.log(r);
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
