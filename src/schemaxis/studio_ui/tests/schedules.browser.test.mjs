// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {readFile, access} from 'node:fs/promises';
import {join} from 'node:path';
import {test} from 'node:test';
import {launch} from './harness.mjs';

const BOX = {version: 'schemaxis.freecad/1', nodes: [{id: 'body', filter: 'box'}], output: 'body'};

async function button(session, label) {
  const query = `[...document.querySelectorAll('.settings button')].find(item => item.textContent.trim() === ${JSON.stringify(label)})`;
  await session.wait(query, `${label} button`);
  await session.evaluate(`${query}.click()`);
}

async function field(session, label, value) {
  await session.evaluate(`(() => {
    const element = document.querySelector('[aria-label="${label}"]');
    element.value = ${JSON.stringify(value)};
    element.dispatchEvent(new Event('change', {bubbles: true}));
  })()`);
}

test('Schedules UI previews, captures a saved revision, pauses/resumes without launching worker',
  {timeout: 90000}, async () => {
    const session = await launch();
    try {
      await session.wait('window.studio?.store.get().server', 'Studio state');
      const document = await session.evaluate(`(async () => {
        const record = await window.studio.api.post('/api/documents', {action: 'new', provider: 'freecad',
          name: 'Scheduled box', document: ${JSON.stringify(BOX)}});
        await window.studio.refresh();
        return {id: record.id, revision: record.revision};
      })()`);
      await session.key('k', {modifiers: 2});
      await session.wait('document.querySelector(".palette")', 'command palette');
      await session.type('Open Schedules');
      await session.key('Enter');
      await session.wait('document.querySelector("[aria-label=Objective]")', 'schedule form');
      await field(session, 'Document to schedule', document.id);
      await field(session, 'Objective', 'Browser scheduled publication');
      await field(session, 'Trigger', 'interval');
      await field(session, 'Start time', '2099-01-01T09:00');
      await field(session, 'Interval in seconds', '3600');
      await button(session, 'Preview times');
      await session.wait('document.querySelector(".settings pre").textContent.length > 0', 'preview times');
      assert.match(await session.evaluate('document.querySelector(".settings pre").textContent'), /2099/);
      let index = await session.evaluate(`window.studio.api.post('/api/schedules', {action: 'list'})`);
      assert.equal(index.schedules.length, 0);
      await button(session, 'Register schedule');
      await session.wait('document.querySelector(".settings .card strong")?.textContent === "Browser scheduled publication"', 'registered schedule');
      index = await session.evaluate(`window.studio.api.post('/api/schedules', {action: 'list'})`);
      assert.equal(index.schedules.length, 1);
      assert.deepEqual(index.schedules[0].spec.document, BOX);
      assert.equal(index.workerRequired, true);
      await session.evaluate('document.querySelector(".settings details summary").click()');
      assert.equal(await session.evaluate(`document.querySelector('[aria-label="Schedule worker command"]').textContent`),
        `schemaxis schedule --workspace '${index.workspace}' serve`);
      await button(session, 'Pause');
      await session.wait('document.querySelector(".settings .card p")?.textContent.startsWith("paused")', 'paused schedule');
      await button(session, 'Resume');
      await session.wait('document.querySelector(".settings .card p")?.textContent.startsWith("active")', 'resumed schedule');
      const captured = index.schedules[0];
      const stale = await session.evaluate(`(async () => {
        await window.studio.api.post('/api/documents', {action: 'rename', id: ${JSON.stringify(document.id)},
          revision: ${document.revision}, name: 'Changed saved revision'});
        try {
          await window.studio.api.post('/api/schedules', {action: 'create', document: ${JSON.stringify(document.id)},
            documentRevision: ${document.revision}, spec: {objective: 'stale request', trigger: {kind: 'once', at: '2099-01-01T00:00:00Z'}}});
          return {accepted: true};
        } catch (error) { return {accepted: false, code: error.fault?.code || error.code, message: error.message}; }
      })()`);
      assert.equal(stale.accepted, false);
      assert.match(JSON.stringify(stale), /STALE_REVISION|document changed/i);
      await button(session, 'Details');
      await session.wait('document.querySelectorAll(".settings pre")[1]?.textContent.includes("occurrences")', 'retained schedule details');
      const persisted = JSON.parse(await readFile(join(session.workspace, 'schedules', 'scheduler.json'), 'utf8'));
      const record = persisted.state.schedules[captured.id];
      assert.equal(record.status, 'active');
      assert.equal(record.revision, 3);
      assert.deepEqual(persisted.state.occurrences, {});
      await assert.rejects(access(join(session.workspace, 'schedules', 'scheduler-owner.lock')));
      assert.deepEqual(session.exceptions, []);
    } finally {
      await session.close();
    }
  });
