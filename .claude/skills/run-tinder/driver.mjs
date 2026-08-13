// REPL driver for the tinder frontend (Angular, served via `ng serve`).
// Run from anywhere: `node .claude/skills/run-tinder/driver.mjs`.
// Designed for agents: wrap in tmux, send-keys commands, capture-pane output.
// Adapted from the run skill's Electron REPL pattern, but drives a plain
// Chromium page (via Playwright's `chromium.launch`) instead of `_electron`,
// since this is a regular browser-served web app, not a desktop app.
import { chromium } from 'playwright';
import * as readline from 'node:readline';
import * as fs from 'node:fs';
import * as path from 'node:path';

const SHOT_DIR = process.env.SCREENSHOT_DIR || '/tmp/tinder-shots';
fs.mkdirSync(SHOT_DIR, { recursive: true });

let browser = null;
let page = null;

const COMMANDS = {
  async launch() {
    if (browser) return console.log('already launched');
    browser = await chromium.launch({ headless: true });
    page = await browser.newPage();
    console.log('launched.');
  },

  async nav(url) {
    if (!page) return console.log('ERROR: launch first');
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    console.log('nav ->', url);
  },

  async ss(name) {
    if (!page) return console.log('ERROR: launch first');
    const f = path.join(SHOT_DIR, (name || `ss-${Date.now()}`) + '.png');
    await page.screenshot({ path: f });
    console.log('screenshot:', f);
  },

  // Click via evaluate(), not locator.click() — DOM click sidesteps any
  // coordinate/overlay weirdness and matches the pattern used elsewhere in
  // this repo's driver conventions.
  async click(sel) {
    if (!page) return console.log('ERROR: launch first');
    const r = await page.evaluate((s) => {
      const el = document.querySelector(s);
      if (!el) return 'NOT_FOUND';
      el.click();
      return 'OK';
    }, sel);
    console.log('click', sel, '->', r);
  },

  async 'click-text'(text) {
    if (!page) return console.log('ERROR: launch first');
    const r = await page.evaluate((t) => {
      const els = [...document.querySelectorAll('button, a, [role="button"]')];
      const el = els.find((e) => e.textContent?.trim() === t) ?? els.find((e) => e.textContent?.includes(t));
      if (!el) return 'NOT_FOUND';
      el.click();
      return 'OK: ' + el.tagName;
    }, text);
    console.log('click-text', JSON.stringify(text), '->', r);
  },

  // Angular's reactive forms are controlled inputs — plain DOM `.value =`
  // assignment doesn't fire the events Angular listens for, so the form
  // control never updates. Playwright's `fill()` goes through the real
  // input pipeline (focus, keyboard events, input event) and Angular picks
  // it up correctly.
  async fill(args) {
    if (!page) return console.log('ERROR: launch first');
    const sel = args.slice(0, args.indexOf(' '));
    const value = args.slice(args.indexOf(' ') + 1);
    await page.fill(sel, value);
    console.log('fill', sel, '<-', JSON.stringify(value));
  },

  async type(text) {
    if (page) await page.keyboard.type(text, { delay: 30 });
  },
  async press(key) {
    if (page) await page.keyboard.press(key);
  },

  async wait(sel) {
    if (!page) return console.log('ERROR: launch first');
    try {
      await page.waitForSelector(sel, { timeout: 10_000 });
      console.log('found:', sel);
    } catch {
      console.log('TIMEOUT:', sel);
    }
  },

  // Exact pathname match, not substring — `.includes('/')` is trivially true
  // for every URL (every path contains a slash), which made this report
  // success immediately on the *current* page instead of waiting for an
  // actual navigation. Hit this for real driving Home: it "matched" while
  // still on /login mid "Logging in…", before the redirect had happened.
  async 'wait-url'(targetPath) {
    if (!page) return console.log('ERROR: launch first');
    try {
      await page.waitForURL((u) => new URL(u).pathname === targetPath, { timeout: 10_000 });
      console.log('url now:', page.url());
    } catch {
      console.log('TIMEOUT waiting for pathname:', targetPath, '(currently:', page.url(), ')');
    }
  },

  async eval(expr) {
    if (!page) return console.log('ERROR: launch first');
    try {
      console.log(JSON.stringify(await page.evaluate(expr)));
    } catch (e) {
      console.log('ERROR:', e.message);
    }
  },

  async text(sel) {
    if (!page) return console.log('ERROR: launch first');
    console.log(
      await page.evaluate((s) => (s ? document.querySelector(s) : document.body)?.innerText ?? '(null)', sel || null)
    );
  },

  async console() {
    if (!page) return console.log('ERROR: launch first');
    console.log('(console errors are printed live as they occur — see above)');
  },

  async quit() {
    if (browser) await browser.close().catch(() => {});
    browser = null;
    page = null;
  },
  help() {
    console.log('commands:', Object.keys(COMMANDS).join(', '));
  },
};

// Registered once launch() creates the page — logs any page console error
// or uncaught exception immediately, so a silently-broken page doesn't look
// like a success just because it rendered *something*.
function wireConsole() {
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.log('[console.error]', msg.text());
  });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
}
const origLaunch = COMMANDS.launch;
COMMANDS.launch = async function () {
  await origLaunch();
  if (page) wireConsole();
};

// Plain process.stdin — no need for the Electron-specific /dev/stdin re-open
// trick (that exists because Electron's runtime steals stdin; this is a
// plain Node script with no such conflict).
const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: 'driver> ' });

// Piped/heredoc input delivers every line to readline's 'line' event in one
// burst, before the first command's async work (e.g. launch()'s browser
// startup) has resolved — so without a queue, `nav`/`ss` would race ahead
// of `launch` and hit a still-null `page`. Queuing lines and draining them
// one at a time (awaiting each fully) makes piped input behave the same as
// a human typing commands one at a time interactively.
//
// The queue alone isn't enough, though: piped/heredoc stdin also fires
// 'close' (EOF) right after the last 'line' event — before the queued async
// commands have actually finished. `currentDrain` is a running promise
// chain every queued batch appends onto, so 'close' can `await` it and only
// exit once every command has genuinely completed (see rl.on('close')
// below) instead of killing e.g. a half-started chromium.launch() mid-flight.
const queue = [];
let currentDrain = Promise.resolve();
// readline self-closes the instant piped/heredoc stdin hits EOF — which
// happens well before our queued async commands finish — so a later
// rl.prompt() call on the already-closed interface throws ERR_USE_AFTER_CLOSE.
// This flag (set synchronously in the 'close' listener below, before any
// await) lets the queue skip prompting once that's happened, without
// crashing mid-command.
let rlClosed = false;

function enqueue(line) {
  queue.push(line);
  currentDrain = currentDrain.then(async () => {
    while (queue.length) {
      const l = queue.shift();
      const [cmd, ...rest] = l.trim().split(/\s+/);
      if (!cmd) continue;
      const fn = COMMANDS[cmd];
      if (!fn) {
        console.log('unknown:', cmd, '— try: help');
        continue;
      }
      try {
        await fn(rest.join(' '));
      } catch (e) {
        console.log('ERROR:', e.message);
      }
      if (cmd === 'quit') {
        process.exit(0);
      }
      if (!rlClosed) rl.prompt();
    }
  });
}

rl.on('line', enqueue);
rl.on('close', async () => {
  rlClosed = true;
  await currentDrain; // let any in-flight/queued commands finish first
  await COMMANDS.quit();
  process.exit(0);
});

console.log('tinder frontend driver — "help" for commands, "launch" to start');
rl.prompt();
