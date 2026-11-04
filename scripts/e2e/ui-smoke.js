// End-to-end UI smoke test against the local stack (make e2e-ui). Local development only.
// Signs in through real Keycloak (TOTP enrolment + the app's single MFA retry), then in the SPA:
// creates a personal workspace, applies the chart template, creates FY2026, enters and posts a
// transaction, and checks the trial balance. Screenshots go to $SCREENSHOT_DIR (default /tmp).
const { chromium } = require('playwright');
const crypto = require('crypto');
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
  for (let i = 0; i < 4 && !page.url().startsWith(`${SPA}/`) ; i++) {
    await page.waitForSelector('#password, #otp', { timeout: 15000 }).catch(() => {});
    if (await page.locator('#password').count()) { await passwordStep(page); await page.waitForLoadState('load'); }
    if (await page.locator('#otp').count()) { await nextWindow(); await page.fill('#otp', totp(secret)); await page.click('#kc-login'); }
    await page.waitForLoadState('load');
  }
  await page.getByRole('heading', { name: 'Your workspaces' }).waitFor({ timeout: 15000 });
}

// Main navigation is grouped (M2-11): open the group, then follow the link.
async function go(page, group, name) {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: group }).click();
  await page.getByRole('link', { name, exact: true }).click();
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
  const steps = [];
  try {
    await signIn(page);
    steps.push('signed in with MFA');

    await page.getByLabel('Workspace name').fill('My finances');
    await page.getByLabel('Workspace type').selectOption('PERSONAL');
    await page.getByRole('button', { name: 'Create workspace' }).click();
    await page.getByRole('heading', { name: 'Journal entries' }).waitFor();
    steps.push('created personal workspace');

    await go(page, 'Setup', 'Chart of accounts');
    await page.getByLabel('Apply template').selectOption('personal');
    await page.getByRole('button', { name: 'Apply template' }).click();
    await page.getByRole('cell', { name: 'Groceries' }).waitFor();
    steps.push('applied personal chart of accounts');

    await go(page, 'Setup', 'Periods');
    await page.getByLabel('Start date').fill('2026-01-01');
    await page.getByRole('button', { name: 'Create fiscal year' }).click();
    await page.getByRole('heading', { name: /2026/ }).waitFor();
    steps.push('created FY2026');

    await go(page, 'Bookkeeping', 'Journal entries');
    await page.getByRole('link', { name: 'New entry' }).click();
    await page.getByLabel('Accounting date').fill('2026-03-15');
    await page.getByLabel('Description').fill('Weekly groceries');
    await page.getByLabel('Account 1').selectOption({ label: '6100 · Groceries' });
    await page.getByLabel('Debit 1').fill('84.30');
    await page.getByLabel('Account 2').selectOption({ label: '1100 · Current account' });
    await page.getByLabel('Credit 2').fill('84.20');
    await page.getByText('Difference: 0.10').waitFor();
    const blocked = await page.getByRole('button', { name: 'Save and submit' }).isDisabled();
    await page.screenshot({ path: path.join(OUT, 'ui-entry-unbalanced.png') });
    await page.getByLabel('Credit 2').fill('84.30');
    await page.getByText('Balanced').waitFor();
    steps.push(`unbalanced entry blocked: ${blocked}`);
    await page.getByRole('button', { name: 'Save and submit' }).click();
    await page.getByText('Submitted').first().waitFor();
    await page.getByRole('button', { name: 'Post' }).click();
    await page.getByText('Posted entries cannot be changed').waitFor();
    await page.screenshot({ path: path.join(OUT, 'ui-entry-posted.png') });
    steps.push('posted entry (read-only, reverse only)');

    await go(page, 'Reports', 'Trial balance');
    await page.getByLabel('As of').fill('2026-12-31');
    await page.getByRole('cell', { name: 'Groceries' }).waitFor();
    const totals = await page.locator('tfoot td.amount').allInnerTexts();
    await page.screenshot({ path: path.join(OUT, 'ui-trial-balance.png') });
    steps.push(`trial balance totals: ${totals.join(' / ')}`);

    await page.getByLabel('Language').selectOption('el');
    await page.getByRole('heading', { name: 'Ισοζύγιο' }).waitFor();
    await page.screenshot({ path: path.join(OUT, 'ui-trial-balance-el.png') });
    steps.push('Greek interface');
    console.log(JSON.stringify({ ok: true, steps }, null, 2));
  } catch (e) {
    await page.screenshot({ path: path.join(OUT, 'ui-failure.png') }).catch(() => {});
    console.log(JSON.stringify({ ok: false, steps, error: String(e).slice(0, 400), url: page.url() }, null, 2));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
