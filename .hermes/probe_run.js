/**
 * Live probe: what really happens when Run is clicked on the dashboard tab.
 *
 * Drives real Chromium against the running dashboard, records every console message,
 * every /api/plugins/* response, and the visible text afterwards.
 */
const { chromium } = require('/home/lenovo/.hermes/hermes-agent/node_modules/playwright');

const BASE = process.env.BASE || 'http://127.0.0.1:9119';
const TOKEN = process.env.TOK || 'probe-token-9119';

(async () => {
  const console_ = [];
  const network = [];
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/google-chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript(`window.__HERMES_SESSION_TOKEN__ = ${JSON.stringify(TOKEN)};`);
  const page = await ctx.newPage();

  page.on('console', m => console_.push(`[${m.type()}] ${m.text()}`));
  page.on('pageerror', e => console_.push(`[pageerror] ${e.message}`));
  page.on('requestfailed', r => console_.push(`[requestfailed] ${r.url()} ${r.failure()?.errorText}`));
  page.on('response', async r => {
    const u = r.url();
    if (!/\/api\/(plugins|dashboard)/.test(u)) return;
    let body = '';
    try { body = (await r.text()).slice(0, 500); } catch (e) { body = `<unreadable ${e.message}>`; }
    network.push({ status: r.status(), method: r.request().method(), url: u, body });
  });

  await page.goto(BASE + '/workflows', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  console.log('=== url / title ===');
  console.log(page.url(), '|', await page.title());

  const controls = await page.evaluate(() => Array.from(
    document.querySelectorAll('button,select,input')).map(el => ({
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.value || '').trim().slice(0, 34),
      dvw: el.getAttribute('data-vw') || '',
      disabled: !!el.disabled,
      visible: !!(el.offsetWidth || el.offsetHeight),
    })));
  console.log('=== controls ===');
  for (const c of controls) console.log(JSON.stringify(c));

  const run = page.locator('[data-vw="run-now"]').first();
  const n = await run.count();
  if (!n) { console.log('!! no [data-vw="run-now"] button found'); await browser.close(); return; }
  console.log('=== run button ===', JSON.stringify(await run.innerText()), 'visible=', await run.isVisible());

  console.log('=== banner before ===', JSON.stringify(await page.evaluate(
    () => document.querySelector('[data-vw="banner"]')?.innerText ?? '(none)')));

  await run.click();
  await page.waitForTimeout(3500);

  const after = await page.evaluate(() => {
    const b = document.querySelector('[data-vw="banner"]');
    const status = document.querySelector('[data-vw="status"]');
    return {
      banner: b ? { hidden: b.hidden, cls: b.className, text: b.innerText } : null,
      status: status ? status.innerText : null,
      body: document.body.innerText.slice(0, 1500),
    };
  });
  console.log('=== after click ===');
  console.log(JSON.stringify(after, null, 2));

  console.log('=== console ===');
  for (const line of console_) console.log(line);
  console.log('=== network ===');
  for (const x of network) console.log(`${x.status} ${x.method} ${x.url}`);

  await page.screenshot({ path: '/tmp/run-click.png' });
  await browser.close();
})().catch(e => { console.error('PROBE FAILED', e); process.exit(1); });
