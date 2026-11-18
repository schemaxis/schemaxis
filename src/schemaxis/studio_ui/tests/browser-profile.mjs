// Copyright (C) 2026 David L. F. Gaden.
// Disposable browser-test profiles must not accumulate in the home directory.
import {existsSync} from 'node:fs';
import {mkdir, mkdtemp, rm} from 'node:fs/promises';
import {homedir, tmpdir} from 'node:os';
import {join} from 'node:path';

export async function createBrowserProfile(prefix) {
  // Snap Chromium has a private /tmp and cannot read arbitrary hidden home
  // directories. Its common directory is accessible to other browsers too.
  const snapCommon = join(homedir(), 'snap', 'chromium', 'common');
  const root = existsSync(snapCommon) ? join(snapCommon, 'schemaxis-test-profiles') : tmpdir();
  await mkdir(root, {recursive: true});
  return mkdtemp(join(root, prefix));
}

export async function cleanupLaunch({socket, browser, server, profile, workspace}) {
  if (socket) {
    try {
      if (socket.readyState === 1) {
        socket.send(JSON.stringify({id: 999999, method: 'Browser.close'}));
      }
      if (socket.readyState !== 3) {
        await new Promise((resolve) => {
          const timer = setTimeout(done, 1000);
          function done() {
            clearTimeout(timer);
            socket.removeEventListener('close', done);
            resolve();
          }
          socket.addEventListener('close', done, {once: true});
        });
      }
      socket.close();
      // Snap's launcher can exit before Chromium finishes flushing its profile.
      await new Promise((resolve) => setTimeout(resolve, 300));
    } catch {
      // The browser may already have closed the connection.
    }
  }
  for (const child of [browser, server]) {
    if (!child || child.exitCode !== null || child.signalCode !== null) continue;
    try {
      await new Promise((resolve) => {
        const timer = setTimeout(done, 1000);
        function done() {
          clearTimeout(timer);
          child.removeListener('exit', done);
          resolve();
        }
        child.once('exit', done);
        try { child.kill('SIGTERM'); } catch { done(); }
      });
    } catch {
      // A Snap launcher can deny signals after handing off to Chromium.
    }
  }
  for (const directory of [profile, workspace]) {
    if (directory) await rm(directory, {recursive: true, force: true, maxRetries: 10, retryDelay: 100});
  }
}
