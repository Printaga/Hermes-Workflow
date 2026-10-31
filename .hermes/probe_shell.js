const { launch, requiredToken } = require('./probe_browser');
const BASE = process.env.BASE || 'http://127.0.0.1:9119';
const TOKEN = requiredToken();

const probe = () => {
  const shell = document.querySelector('.vw-shell');
  const app = document.querySelector('.vw-app');
  const main = document.querySelector('.vw-main');
  const wrap = document.querySelector('.vw-wrap');
  const dump = (el, name) => el ? ({
    name,
    inline: el.getAttribute('style'),
    h: +el.getBoundingClientRect().height.toFixed(1),
    css: ['height', 'min-height', 'flex', 'align-self', 'overflow'].map(p => p + '=' + getComputedStyle(el).getPropertyValue(p)).join(' '),
    parentInline: el.parentElement ? el.parentElement.getAttribute('style') : null,
    parentH: el.parentElement ? +el.parentElement.getBoundingClientRect().height.toFixed(1) : null,
  }) : { name, missing: true };
  return [dump(shell, 'shell'), dump(app, 'app'), dump(main, 'main'), dump(wrap, 'wrap')];
};

(async () => {
  const browser = await launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript((token) => {
    window.__HERMES_SESSION_TOKEN__ = token;
  }, TOKEN);
  const page = await ctx.newPage();
  await page.goto(BASE + '/workflows', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.vw-shell', { state: 'attached', timeout: 15000 });
  await page.waitForFunction(
    () => (document.querySelector('.vw-shell')?.getBoundingClientRect().height || 0) > 0,
    null, { timeout: 10000 },
  );
  for (const row of await page.evaluate(probe)) console.log('before', JSON.stringify(row));
  const node = page.locator('[data-vw="canvas"] g').filter({ has: page.locator('rect') }).first();
  await node.waitFor({ state: 'visible', timeout: 15000 });
  await node.click();
  await page.waitForFunction(
    () => (document.querySelector('.vw-wrap')?.getBoundingClientRect().height || 0) > 0,
    null, { timeout: 5000 },
  ).catch(() => {});
  for (const row of await page.evaluate(probe)) console.log('after ', JSON.stringify(row));
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
