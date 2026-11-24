// V1-4 (#210): the end-to-end walk-through in a real browser. Local development only.
//
//   node walkthrough.js signin STATE      sign in through Keycloak with MFA, save the session
//   node walkthrough.js walk STATE DEMO   walk every module of the demo year (DEMO: the JSON the
//                                         demo wrote) and check the figures shown agree
//
// Run through scripts/e2e/walkthrough.sh (make e2e-walkthrough), which resets the e2e user, signs
// in, loads the demo year shared with that user and walks it. Screenshots go to $SCREENSHOT_DIR.
const { chromium } = require('playwright');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const SPA = process.env.SPA_URL || 'http://localhost:5173';
const OUT = process.env.SCREENSHOT_DIR || '/tmp';

function totp(secretBase32) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const c of secretBase32.replace(/\s+/g, '').toUpperCase()) bits += alphabet.indexOf(c).toString(2).padStart(5, '0');
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i + 8), 2));
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 1000 / 30)));
  const h = crypto.createHmac('sha1', Buffer.from(bytes)).update(msg).digest();
  const o = h[h.length - 1] & 0xf;
  return ((h.readUInt32BE(o) & 0x7fffffff) % 1000000).toString().padStart(6, '0');
}
const nextWindow = () => new Promise((r) => setTimeout(r, 1000 * (31 - (Math.floor(Date.now() / 1000) % 30))));

async function passwordStep(page) {
  await page.waitForSelector('#password', { timeout: 15000 });
  const user = page.locator('#username');
  if ((await user.count()) && (await user.isEditable())) await user.fill('e2e.owner');
  await page.fill('#password', 'Local-dev-only-pass-1');
  await page.click('#kc-login');
}

async function signIn(page) {
  await page.goto(`${SPA}/`);
  await page.getByRole('link', { name: 'Sign in' }).click();
  await passwordStep(page);
  await page.waitForSelector('#totp', { timeout: 15000 });
  const manual = page.locator('#mode-manual, a:has-text("Unable to scan")');
  if (await manual.count()) await manual.first().click();
  const secret = await page.locator('#kc-totp-secret-key').innerText();
  await page.fill('#totp', totp(secret));
  if (await page.locator('#userLabel').count()) await page.fill('#userLabel', 'e2e device');
  await page.click('#saveTOTPBtn, input[type=submit], button[type=submit]');
  for (let i = 0; i < 4 && !page.url().startsWith(`${SPA}/`); i++) {
    await page.waitForSelector('#password, #otp', { timeout: 15000 }).catch(() => {});
    if (await page.locator('#password').count()) { await passwordStep(page); await page.waitForLoadState('load'); }
    if (await page.locator('#otp').count()) { await nextWindow(); await page.fill('#otp', totp(secret)); await page.click('#kc-login'); }
    await page.waitForLoadState('load');
  }
  await page.getByRole('heading', { name: 'Your workspaces' }).waitFor({ timeout: 15000 });
}

/** An amount as the screens show it in English: thousands separated, two decimals. */
function money(value) {
  const [whole, cents = '00'] = String(value).replace('-', '').split('.');
  const sign = String(value).startsWith('-') ? '-' : '';
  return `${sign}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${cents.padEnd(2, '0').slice(0, 2)}`;
}

async function walk(statePath, demoPath) {
  const demo = JSON.parse(fs.readFileSync(demoPath, 'utf8'));
  const failed = demo.agreements.filter((a) => !a.ok);
  if (failed.length) throw new Error(`the demo's own checks failed: ${JSON.stringify(failed)}`);
  const bs = demo.statements.balance_sheet;
  const pl = demo.statements.profit_and_loss;
  const cash = money(bs['BS.CASH']);
  const base = `${SPA}/w/${demo.slug}/e/${demo.entity_id}`;
  const browser = await chromium.launch();
  const context = await browser.newContext({ storageState: statePath, viewport: { width: 1360, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const steps = [];
  let n = 0;
  async function screen(name, route, act, expectations) {
    await page.goto(`${base}/${route}`);
    if (act) await act();
    for (const text of expectations) {
      // Only text a person can see counts (charts also describe their figures to screen readers).
      await page.getByText(text, { exact: false }).locator('visible=true').first().waitFor({ timeout: 30000 });
    }
    n += 1;
    await page.screenshot({ path: path.join(OUT, `walk-${String(n).padStart(2, '0')}-${route.split('?')[0].replace(/\//g, '-')}.png`), fullPage: true });
    steps.push(`${name}: ${expectations.join(' · ')}`);
  }
  try {
    await screen('Trial balance at 31 December', 'trial-balance', async () => {
      await page.getByLabel('As of').fill('2026-12-31');
    }, [cash]);
    await screen('Statements for the year', 'statements', async () => {
      await page.getByLabel('From').fill('2026-01-01');
      await page.getByLabel('To').fill('2026-12-31');
      await page.getByText(money(pl['PL.RESULT'])).first().waitFor({ timeout: 30000 });
      steps.push(`Profit and loss: profit ${money(pl['PL.RESULT'])}`);
      await page.getByRole('tab', { name: 'Balance sheet' }).click();
    }, [cash, money(bs['BS.TOTAL_ASSETS'])]);
    await screen('Cash forecast (13 weeks)', 'cash-forecast', null, [money(demo.forecast_opening)]);
    await screen('CFO dashboard, year to date', 'dashboard', async () => {
      await page.getByLabel('Period').selectOption('YTD');
      await page.getByLabel('Ending in').fill('2026-12');
    }, ['Gross margin', '45']);
    await screen('Fixed assets: register and ledger', 'fixed-assets', async () => {
      await page.getByLabel('Values at').fill('2027-01-31');
    }, ['The register agrees with the ledger']);
    await screen('Projection', 'projections', null, [cash]);
    await screen('Report pack, December, with its KPI section', 'report-packs', async () => {
      await page.getByRole('button', { name: /Management pack, December 2026/ }).click();
    }, ['Gross margin', cash]);
    await screen('VAT return, first quarter', 'vat', async () => {
      await page.getByRole('button', { name: 'Open' }).first().click();
    }, ['Box', 'DEMO-0001']);
    console.log(JSON.stringify({ ok: true, steps }, null, 2));
  } catch (e) {
    await page.screenshot({ path: path.join(OUT, 'walk-failure.png'), fullPage: true }).catch(() => {});
    console.log(JSON.stringify({ ok: false, steps, error: String(e).slice(0, 600), url: page.url() }, null, 2));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

(async () => {
  const [mode, statePath, demoPath] = process.argv.slice(2);
  if (mode === 'signin') {
    const browser = await chromium.launch();
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      await signIn(page);
      await context.storageState({ path: statePath });
      console.log(JSON.stringify({ ok: true, steps: ['signed in with MFA'] }));
    } catch (e) {
      await page.screenshot({ path: path.join(OUT, 'walk-signin-failure.png') }).catch(() => {});
      console.log(JSON.stringify({ ok: false, error: String(e).slice(0, 400), url: page.url() }));
      process.exitCode = 1;
    } finally {
      await browser.close();
    }
  } else if (mode === 'walk') {
    await walk(statePath, demoPath);
  } else {
    console.error('usage: walkthrough.js signin STATE | walk STATE DEMO');
    process.exitCode = 2;
  }
})();
