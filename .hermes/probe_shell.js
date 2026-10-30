const { chromium } = require('/home/lenovo/.hermes/hermes-agent/node_modules/playwright');
const BASE = 'http://127.0.0.1:9119';
const TOKEN = 'probe-token-9119';

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
  }) : null;
  return [dump(shell, 'shell'), dump(app, 'app'), dump(main, 'main'), dump(wrap, 'wrap')];
};

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/google-chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript(`window.__HERMES_SESSION_TOKEN__ = ${JSON.stringify(TOKEN)};`);
  const page = await ctx.newPage();
  await page.goto(BASE + '/workflows', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  for (const row of await page.evaluate(probe)) console.log('before', JSON.stringify(row));
  await page.locator('[data-vw="canvas"] g').filter({ has: page.locator('rect') }).first().click({ force: true });
  await page.waitForTimeout(900);
  for (const row of await page.evaluate(probe)) console.log('after ', JSON.stringify(row));
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
