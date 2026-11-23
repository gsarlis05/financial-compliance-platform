// Version 1 on the owner's computer (V1-3): a real browser signs in through the local stack.
// Usage: node scripts/local/smoke.js first <email> <temporary-password> <new-password> <state-file>
//        node scripts/local/smoke.js again <email> <password> <state-file>
// "first" changes the temporary password, enrols the authenticator and creates a workspace;
// "again" signs in with password and code and lists the workspaces. Prints JSON.
const { chromium } = require('playwright');
const crypto = require('crypto');
const fs = require('fs');
const APP = 'http://localhost:8088';

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

async function api(page, method, path, body) {
  return page.evaluate(async ([method, path, body]) => {
    const csrf = (document.cookie.split('; ').find(c => c.startsWith('__Host-fcp_csrftoken=')) || '').split('=')[1] || '';
    const r = await fetch('/api' + path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: await r.json().catch(() => null) };
  }, [method, path, body]);
}

(async () => {
  const [mode, email, password, ...rest] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const result = { mode };
  try {
    await page.goto(`${APP}/auth/login?next=/`);
    const [newPassword, stateFile] = mode === 'first' ? rest : [password, rest[0]];
    let secret = mode === 'first' ? null : JSON.parse(fs.readFileSync(stateFile, 'utf8')).secret;
    let current = password;
    // Keycloak shows its screens in its own order (sign-in, authenticator set-up, new password,
    // one-time code) and the app asks once for a fresh sign-in: answer whichever screen appears.
    for (let i = 0; i < 8 && !page.url().startsWith(APP); i++) {
      await page.waitForSelector('#password-new, #totp, #otp, #password', { timeout: 20000 });
      if (await page.locator('#password-new').count()) {
        await page.fill('#password-new', newPassword);
        await page.fill('#password-confirm', newPassword);
        current = newPassword;
        await page.click('input[type=submit], button[type=submit]');
      } else if (await page.locator('#totp').count()) {
        const manual = page.locator('#mode-manual, a:has-text("Unable to scan")');
        if (await manual.count()) await manual.first().click();
        secret = (await page.locator('#kc-totp-secret-key').innerText()).trim();
        fs.writeFileSync(stateFile, JSON.stringify({ secret }), { mode: 0o600 });
        await page.fill('#totp', totp(secret));
        if (await page.locator('#userLabel').count()) await page.fill('#userLabel', 'smoke');
        await page.click('#saveTOTPBtn, input[type=submit], button[type=submit]');
      } else if (await page.locator('#otp').count()) {
        await nextWindow();
        await page.fill('#otp', totp(secret));
        await page.click('#kc-login');
      } else {
        const user = page.locator('#username');
        if ((await user.count()) && (await user.isEditable())) await user.fill(email);
        await page.fill('#password', current);
        await page.click('#kc-login');
      }
      await page.waitForLoadState('load');
    }
    await page.waitForURL(u => u.toString().startsWith(APP), { timeout: 20000 });
    const me = await api(page, 'GET', '/me');
    result.me = { status: me.status, email: me.body && me.body.email };
    if (mode === 'first') {
      const made = await api(page, 'POST', '/workspaces', { name: 'Smoke Trading', kind: 'BUSINESS', entity_name: 'Smoke Trading Ltd' });
      result.created = made.status;
    }
    const list = await api(page, 'GET', '/workspaces');
    result.workspaces = (list.body || []).map(w => w.name);
  } catch (e) {
    result.error = String(e).slice(0, 300);
    result.url = page.url();
    result.text = (await page.locator('body').innerText().catch(() => '')).slice(0, 300);
  }
  console.log(JSON.stringify(result));
  await browser.close();
  process.exit(result.error ? 1 : 0);
})();
