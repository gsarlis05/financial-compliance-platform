// Live end-to-end check against the local stack (make e2e-login): real Keycloak sign-in with
// TOTP enrolment, the app's single MFA retry, then /api/me. Local development only.
const { chromium } = require('playwright');
const crypto = require('crypto');

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
const nextWindow = () => new Promise(r => setTimeout(r, 1000 * (31 - (Math.floor(Date.now() / 1000) % 30))));

async function passwordStep(page) {
  const user = page.locator('#username');
  if ((await user.count()) && (await user.isEditable())) await user.fill('e2e.owner');
  await page.fill('#password', 'Local-dev-only-pass-1');
  await page.click('#kc-login');
}

(async () => {
  const browser = await chromium.launch();
  const result = {};
  let page;
  try {
    // First sign-in: enrol TOTP during the flow.
    page = await browser.newPage();
    await page.goto('http://localhost:8000/auth/login?next=/api/me');
    await passwordStep(page);
    await page.waitForSelector('#totp', { timeout: 15000 });
    const manual = page.locator('#mode-manual, a:has-text("Unable to scan")');
    if (await manual.count()) await manual.first().click();
    const secret = await page.locator('#kc-totp-secret-key').innerText();
    await page.fill('#totp', totp(secret));
    if (await page.locator('#userLabel').count()) await page.fill('#userLabel', 'e2e device');
    await page.click('#saveTOTPBtn, input[type=submit], button[type=submit]');
    // Either straight into the app, or the app's single MFA retry asks to sign in again.
    await page.waitForURL(/localhost:8000\/api\/me|realms\/fcp-dev\/.*(login|auth)/, { timeout: 15000 });
    result.first_login_path = [];
    for (let i = 0; i < 3 && !page.url().includes('localhost:8000/api/me'); i++) {
      await page.waitForSelector('#password, #otp', { timeout: 15000 }).catch(() => {});
      if (await page.locator('#password').count()) { result.first_login_path.push('password'); await passwordStep(page); await page.waitForLoadState('load'); }
      if (await page.locator('#otp').count()) {
        result.first_login_path.push('otp');
        await nextWindow();
        await page.fill('#otp', totp(secret));
        await page.click('#kc-login');
      }
      await page.waitForLoadState('load');
    }
    result.first_url = page.url();
    result.first_me = JSON.parse(await page.locator('body').innerText());

    // Second sign-in in a fresh browser: password + OTP.
    const ctx2 = await browser.newContext();
    page = await ctx2.newPage();
    await page.goto('http://localhost:8000/auth/login?next=/api/me');
    await passwordStep(page);
    await page.waitForSelector('#otp', { timeout: 15000 });
    await nextWindow();
    await page.fill('#otp', totp(secret));
    await page.click('#kc-login');
    await page.waitForURL(/localhost:8000\/api\/me/, { timeout: 15000 });
    result.second_me = JSON.parse(await page.locator('body').innerText());
    const session = (await ctx2.cookies('http://localhost:8000')).find(c => c.name === '__Host-fcp_session');
    result.cookie = session && { httpOnly: session.httpOnly, secure: session.secure, sameSite: session.sameSite };
  } catch (e) {
    result.error = String(e).slice(0, 300);
    result.url = page && page.url();
    result.body = page && (await page.locator('body').innerText()).slice(0, 400);
  }
  console.log(JSON.stringify(result, null, 2));
  await browser.close();
})();
