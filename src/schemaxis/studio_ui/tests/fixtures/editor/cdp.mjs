// Copyright (C) 2026 David L F Gaden
// Minimal headless-Chromium driver over the DevTools protocol, using only Node
// built-ins and Python's http.server. Processes are tracked by handle and killed.

import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, rm, writeFile} from 'node:fs/promises';
import {homedir} from 'node:os';
import {join} from 'node:path';

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function findChromium() {
  const candidates = [process.env.CHROMIUM, '/snap/bin/chromium', '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome'];
  return candidates.find((path) => path && existsSync(path)) || null;
}

function waitForLine(stream, pattern, label) {
  let output = '';
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Timed out waiting for ${label}: ${output}`)), 30000);
    stream.on('data', (data) => {
      output += data;
      const match = output.match(pattern);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
  });
}

/** Serve `root` and open `path` in headless Chromium. */
export async function launch({root, path, width = 1280, height = 800}) {
  const handles = {};
  try {
    handles.server = spawn('python3', ['-u', '-m', 'http.server', '0', '--bind', '127.0.0.1', '--directory', root],
      {stdio: ['ignore', 'pipe', 'pipe']});
    const port = await waitForLine(handles.server.stdout, /port (\d+)/, 'http.server');
    const origin = `http://127.0.0.1:${port}`;
    handles.profile = await mkdtemp(join(homedir(), 'schemaxis-editor-test-'));
    handles.browser = spawn(findChromium(), ['--headless', '--no-sandbox', '--disable-dev-shm-usage',
      '--remote-debugging-port=0', '--remote-allow-origins=*', `--user-data-dir=${handles.profile}`,
      `--window-size=${width},${height}`, '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
      '--font-render-hinting=none', 'about:blank'], {stdio: ['ignore', 'ignore', 'pipe']});
    const endpoint = await waitForLine(handles.browser.stderr, /DevTools listening on (ws:\/\/\S+)/, 'Chromium');
    const debuggerOrigin = endpoint.replace(/^ws:/, 'http:').split('/devtools/')[0];
    const target = await (await fetch(`${debuggerOrigin}/json/new?about:blank`, {method: 'PUT'})).json();
    const socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.onopen = resolve;
      socket.onerror = reject;
    });
    handles.socket = socket;
    return createSession(handles, origin, path, {width, height});
  } catch (error) {
    await shutdown(handles);
    throw error;
  }
}

async function createSession(handles, origin, path, size) {
  const socket = handles.socket;
  const pending = new Map();
  const exceptions = [];
  const logs = [];
  let sequence = 0;
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const task = pending.get(message.id);
      if (task) {
        pending.delete(message.id);
        clearTimeout(task.timer);
        if (message.error) {
          task.reject(new Error(JSON.stringify(message.error)));
        } else {
          task.resolve(message.result);
        }
      }
    } else if (message.method === 'Runtime.exceptionThrown') {
      exceptions.push(message.params.exceptionDetails);
    } else if (message.method === 'Runtime.consoleAPICalled') {
      logs.push(message.params.args.map((arg) => arg.value ?? arg.description).join(' '));
    } else if (message.method === 'Log.entryAdded') {
      logs.push(`${message.params.entry.level}: ${message.params.entry.text}`);
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`CDP timeout: ${method}`));
    }, 30000);
    pending.set(id, {resolve, reject, timer});
    socket.send(JSON.stringify({id, method, params}));
  });
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
    if (result.exceptionDetails) {
      throw new Error(`${expression}\n${JSON.stringify(result.exceptionDetails)}`);
    }
    return result.result.value;
  };
  const wait = async (expression, label, timeout = 20000) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) {
        return;
      }
      await delay(50);
    }
    throw new Error(`Timed out: ${label}`);
  };
  const codes = {Enter: 13, Tab: 9, Backspace: 8, Escape: 27, ArrowDown: 40, ArrowUp: 38, ' ': 32, z: 90, y: 89};
  const key = async (name, modifiers = 0, code = undefined) => {
    const params = {key: name, code: code || name, windowsVirtualKeyCode: codes[name] || 0, modifiers};
    await send('Input.dispatchKeyEvent', {type: 'rawKeyDown', ...params});
    await send('Input.dispatchKeyEvent', {type: 'keyUp', ...params});
  };
  const type = async (text) => {
    for (const char of text) {
      await send('Input.insertText', {text: char});
    }
  };
  const screenshot = async (file, clip) => {
    const params = {format: 'png'};
    if (clip) {
      params.clip = {...clip, scale: 1};
    }
    const shot = await send('Page.captureScreenshot', params);
    if (file) {
      await writeFile(file, Buffer.from(shot.data, 'base64'));
    }
    return shot.data;
  };
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Log.enable');
  await send('Emulation.setDeviceMetricsOverride', {width: size.width, height: size.height, deviceScaleFactor: 1,
    mobile: false});
  const open = async (url) => {
    await send('Page.navigate', {url: origin + url});
    await wait('document.readyState === "complete"', 'page load');
  };
  if (path) {
    await open(path);
  }
  return {origin, send, evaluate, wait, key, type, screenshot, open, exceptions, logs, close: () => shutdown(handles)};
}

async function shutdown(handles) {
  const {socket, browser, server, profile} = handles;
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({id: 999999, method: 'Browser.close'}));
    await delay(300);
    socket.close();
  }
  for (const child of [browser, server]) {
    if (child && child.exitCode === null) {
      child.on('error', () => {});
      child.kill();
      await Promise.race([new Promise((resolve) => child.once('exit', resolve)), delay(1000)]);
    }
  }
  if (profile) {
    await rm(profile, {recursive: true, force: true, maxRetries: 3});
  }
}
