/** Widget copy of the layout probe: node bar height and canvas band before/after a selection. */
const { chromium } = require('/home/lenovo/.hermes/hermes-agent/node_modules/playwright');

const WIDGET = 'file:///home/lenovo/Development/Hermes-Workflow/widgets/designer.html';

const measure = () => {
  const kit = document.querySelector('#kit');
  const wrap = document.querySelector('#canvaswrap');
  const svg = document.querySelector('#canvas');
  const app = document.querySelector('#app');
  const r = el => (el ? +el.getBoundingClientRect().height.toFixed(1) : null);
  return {
    app: r(app),
    kit: r(kit),
    wrap: r(wrap),
    svg: r(svg),
    gapAboveCanvas: kit && wrap ? +(wrap.getBoundingClientRect().top - kit.getBoundingClientRect().bottom).toFixed(1) : null,
    appClass: app ? app.className : null,
    kitFlex: kit ? getComputedStyle(kit).flex : null,
  };
};

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/google-chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(WIDGET);
  await page.waitForTimeout(400);
  console.log('before', JSON.stringify(await page.evaluate(measure)));
  await page.locator('#canvas g.node').first().click({ force: true });
  await page.waitForTimeout(400);
  console.log('after ', JSON.stringify(await page.evaluate(measure)));
  await page.screenshot({ path: '/tmp/widget-after-select.png' });
  console.log('console errors:', JSON.stringify(errors.filter(e => !/api\/plugins/.test(e))));
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
