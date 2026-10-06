// Only run inside isolated PID/mount/network namespaces as an unprivileged user.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.argv[2]);
(async () => {
  assert.notEqual(process.getuid(), 0);
  assert.equal(process.env.DISPLAY, undefined);
  assert.equal(process.env.DBUS_SESSION_BUS_ADDRESS, undefined);
  assert.equal(fs.readdirSync(process.env.HOME).length, 0, 'first-use HOME must be empty');
  const executable = path.join(process.argv[3], 'browser/chromium/chrome-headless-shell-linux64/chrome-headless-shell');
  const browser = await chromium.launch({ executablePath: executable, headless: true,
    chromiumSandbox: true, args: ['--disable-dev-shm-usage', '--disable-gpu'] });
  try {
    const page = await browser.newPage();
    await page.goto('data:text/html,<title>D14 offline first use</title><h1>Bundled Chromium</h1>');
    assert.equal(await page.title(), 'D14 offline first use');
    assert.equal(await page.locator('h1').textContent(), 'Bundled Chromium');
    const screenshot = await page.screenshot();
    assert.equal(screenshot.subarray(1, 4).toString(), 'PNG');
    const children = [];
    for (const pid of fs.readdirSync('/proc').filter(p => /^\d+$/.test(p))) {
      try {
        const cmd = fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8').split('\0').filter(Boolean);
        if (!cmd[0] || !cmd.some(p => p.includes('chrome-headless-shell'))) continue;
        const command = cmd.join(' ');
        assert(!/(?:^| )--no-sandbox(?: |$)/.test(command));
        assert(!/(?:^| )--disable-setuid-sandbox(?: |$)/.test(command));
        const status = fs.readFileSync(`/proc/${pid}/status`, 'utf8');
        children.push({ pid: Number(pid), type: /(?:^| )(--type=[^ ]+)/.exec(command)?.[1] || 'browser',
          seccomp: /^Seccomp:\s+(\d+)$/m.exec(status)?.[1],
          noNewPrivileges: /^NoNewPrivs:\s+(\d+)$/m.exec(status)?.[1] });
      } catch (e) { if (e.code !== 'ENOENT') throw e; }
    }
    console.log(JSON.stringify({ version: browser.version(), title: await page.title(),
      screenshotBytes: screenshot.length, chromiumSandbox: true, children }, null, 2));
    assert(children.some(p => p.type === '--type=renderer' && p.seccomp === '2' && p.noNewPrivileges === '1'));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
