// Copyright (C) 2026 David L F Gaden
// Dependency-free browser harness: starts a real Studio server on a fresh
// workspace, launches headless Chromium and drives it over the DevTools protocol.

import {spawn} from 'node:child_process';
import {mkdtemp, rm, writeFile} from 'node:fs/promises';
import {homedir, tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

const REPOSITORY = fileURLToPath(new URL('../../../..', import.meta.url));
export const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Browser tests share the machine with servers, native applications and often the
// Python suite. Protocol calls get a generous ceiling; STUDIO_TEST_TIMEOUT_SCALE
// stretches every harness timeout on slow or heavily loaded hosts.
const SCALE = Math.max(1, Number(process.env.STUDIO_TEST_TIMEOUT_SCALE) || 1);
const CDP_TIMEOUT = 60000 * SCALE;

function waitForLine(stream, pattern, timeout = 30000 * SCALE) {
  let output = '';
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Timed out waiting for ${pattern}: ${output}`)), timeout);
    stream.on('data', (data) => {
      output += data;
      const match = output.match(pattern);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
    stream.on('end', () => {
      clearTimeout(timer);
      reject(new Error(`Stream ended before ${pattern}: ${output}`));
    });
  });
}

/** Start server + browser. Returns a session with evaluate/wait/click/screenshot/close. */
export async function launch({provider = 'freecad', width = 1440, height = 960, theme} = {}) {
  const workspace = await mkdtemp(join(tmpdir(), 'studio-test-'));
  const server = spawn(process.env.STUDIO_PYTHON || 'python3', ['-B', '-m', 'schemaxis', 'console', '--provider', provider,
    '--workspace', workspace, '--web'], {
    cwd: REPOSITORY,
    env: {...process.env, PYTHONPATH: join(REPOSITORY, 'src')},
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const serverErrors = [];
  server.stderr.on('data', (data) => serverErrors.push(String(data)));
  const url = await waitForLine(server.stdout, /Schemaxis Studio: (http:\/\/127\.0\.0\.1:\d+\/\?token=\S+)/);
  const profile = await mkdtemp(join(homedir(), 'schemaxis-studio-test-'));
  const browser = spawn(process.env.CHROMIUM || 'chromium', ['--headless', '--no-sandbox', '--disable-dev-shm-usage',
    '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--remote-debugging-port=0', '--remote-allow-origins=*',
    `--user-data-dir=${profile}`, `--window-size=${width},${height}`, '--no-first-run', '--no-default-browser-check',
    ...(theme === 'dark' ? ['--force-dark-mode'] : []), 'about:blank'], {stdio: ['ignore', 'ignore', 'pipe']});
  const endpoint = await waitForLine(browser.stderr, /DevTools listening on (ws:\/\/\S+)/);
  const origin = endpoint.replace(/^ws:/, 'http:').split('/devtools/')[0];
  const target = await (await fetch(`${origin}/json/new?${encodeURIComponent(url)}`, {method: 'PUT'})).json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  const exceptions = [];
  const consoleErrors = [];
  const pending = new Map();
  let sequence = 0;
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const task = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(task.timer);
      if (message.error) {
        task.reject(new Error(JSON.stringify(message.error)));
      } else {
        task.resolve(message.result);
      }
    } else if (message.method === 'Runtime.exceptionThrown') {
      exceptions.push(message.params.exceptionDetails);
    } else if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      consoleErrors.push(message.params.args.map((arg) => arg.value || arg.description).join(' '));
    } else if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
      consoleErrors.push(`${message.params.entry.text} ${message.params.entry.url || ''}`);
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`CDP timeout: ${method}`));
    }, CDP_TIMEOUT);
    pending.set(id, {resolve, reject, timer});
    socket.send(JSON.stringify({id, method, params}));
  });
  await send('Runtime.enable');
  await send('Log.enable');
  await send('Page.enable');

  const session = {
    url, workspace, exceptions, consoleErrors, send,
    async evaluate(expression) {
      const result = await send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
      if (result.exceptionDetails) {
        throw new Error(JSON.stringify(result.exceptionDetails));
      }
      return result.result.value;
    },
    async wait(expression, description, timeout = 20000) {
      const deadline = Date.now() + timeout * SCALE;
      while (Date.now() < deadline) {
        if (await session.evaluate(expression)) {
          return;
        }
        await delay(80);
      }
      throw new Error(`Timed out: ${description}`);
    },
    async click(x, y, {button = 'left', clickCount = 1} = {}) {
      await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x, y});
      await send('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button, clickCount});
      await send('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button, clickCount});
    },
    async drag(from, to, steps = 8) {
      await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: from[0], y: from[1]});
      await send('Input.dispatchMouseEvent', {type: 'mousePressed', x: from[0], y: from[1], button: 'left', clickCount: 1});
      for (let step = 1; step <= steps; step += 1) {
        const x = from[0] + ((to[0] - from[0]) * step) / steps;
        const y = from[1] + ((to[1] - from[1]) * step) / steps;
        await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x, y, button: 'left', buttons: 1});
      }
      await send('Input.dispatchMouseEvent', {type: 'mouseReleased', x: to[0], y: to[1], button: 'left', clickCount: 1});
    },
    /** Click the centre of the first element matching a CSS selector. */
    async clickSelector(selector) {
      const box = await session.evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
        if (!e) return null; const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`);
      if (!box) {
        throw new Error(`No element for ${selector}`);
      }
      await session.click(box[0], box[1]);
    },
    async type(text) {
      await send('Input.insertText', {text});
    },
    async key(key, {code, modifiers = 0} = {}) {
      const codes = {Enter: 13, Escape: 27, Backspace: 8, Tab: 9, ArrowDown: 40, ArrowUp: 38, Delete: 46};
      const params = {key, code: code || key, modifiers, windowsVirtualKeyCode: codes[key] || key.toUpperCase().charCodeAt(0)};
      await send('Input.dispatchKeyEvent', {type: 'keyDown', ...params});
      await send('Input.dispatchKeyEvent', {type: 'keyUp', ...params});
    },
    async screenshot(path) {
      const shot = await send('Page.captureScreenshot', {format: 'png'});
      await writeFile(path, Buffer.from(shot.data, 'base64'));
    },
    async close() {
      try {
        await send('Browser.close');
      } catch {
        // The debugging connection may close before Chromium acknowledges it.
      }
      try {
        socket.close();
      } catch {
        // Already closed.
      }
      for (const task of pending.values()) {
        clearTimeout(task.timer);
        task.reject(new Error('Browser session closed'));
      }
      pending.clear();
      try {
        browser.kill('SIGTERM');
      } catch {
        // Snap wrappers can forbid signals; Browser.close above owns cleanup.
      }
      try {
        server.kill('SIGTERM');
      } catch {
        // The server may have already exited after a failed test.
      }
      await delay(300);
      await rm(profile, {recursive: true, force: true, maxRetries: 10, retryDelay: 100});
      await rm(workspace, {recursive: true, force: true, maxRetries: 10, retryDelay: 100});
      return serverErrors.join('');
    },
  };
  return session;
}
