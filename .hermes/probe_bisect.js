/** Which child of .vw-main owns its 911px height before a selection? Hide each and re-measure. */
const { chromium } = require('/home/lenovo/.hermes/hermes-agent/node_modules/playwright');
const BASE = 'http://127.0.0.1:9119';
const TOKEN = 'probe-token-9119';

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/google-chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript(`window.__HERMES_SESSION_TOKEN__ = ${JSON.stringify(TOKEN)};`);
  const page = await ctx.newPage();
  await page.goto(BASE + '/workflows', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  const out = await page.evaluate(() => {
    const main = document.querySelector('.vw-main');
    const wrap = document.querySelector('.vw-wrap');
    const insp = document.querySelector('.vw-inspector');
    const rows = [];
    const m = (label) => rows.push(label + ' main=' + main.getBoundingClientRect().height.toFixed(1) + ' wrap=' + wrap.getBoundingClientRect().height.toFixed(1) + ' insp=' + insp.getBoundingClientRect().height.toFixed(1));
    m('as-is');
    insp.style.display = 'none'; m('inspector hidden');
    insp.style.display = '';
    wrap.style.display = 'none'; m('wrap hidden');
    wrap.style.display = '';
    document.querySelector('.vw-app').style.height = '400px'; m('app forced 400');
    document.querySelector('.vw-app').style.height = '';
    return rows;
  });
  for (const r of out) console.log(r);
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
