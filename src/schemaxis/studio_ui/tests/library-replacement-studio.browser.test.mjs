// Copyright (C) 2026 David L. F. Gaden.
// Real Studio: the Shotcut whole-input snippet is reviewed on every Workbench route and
// in a nested Schema Editor operation; stale owners, scopes and lifetimes cannot commit.
// Public window/editor APIs are used only for setup and labelled contract changes.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

const REVIEW = '.library-replace-review';
const ACTIVE = 'window.studio.windows.active().window';
const FAILURE = 'Could not insert the library item';
const fixture = {version: 'schemaxis.shotcut/1', nodes: [{id: 'MyOrderedTimeline', filter: 'editTimeline', options: {
  assets: [{name: 'second', file: '/clips/second — Ünïcode.mkv'}, {name: 'first', file: '/clips/first.mkv'}],
  clips: [{asset: 'first', startFrame: 3, frameCount: 3}, {asset: 'second', startFrame: 0, frameCount: 2},
    {asset: 'first', startFrame: 3, frameCount: 3}], fps: 25, width: 32, height: 24, threads: 1}}]};

/** Click the centre of an enabled, visible element that is the topmost hit at that point. */
async function click(s, selector) {
  const target = await s.evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return {ok: false, reason: 'missing'};
    element.scrollIntoView({block: 'center'});
    const rect = element.getBoundingClientRect();
    const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
    const hit = document.elementFromPoint(x, y);
    return {x, y, ok: !element.disabled && rect.width > 0 && rect.height > 0 && (hit === element || element.contains(hit)),
      hit: hit?.outerHTML?.slice(0, 300)};
  })()`);
  if (!target.ok) throw new Error(`Not an enabled unobstructed target: ${selector} ${JSON.stringify(target)}`);
  await s.click(target.x, target.y);
}

/** Click the enabled, unobstructed button whose text is exactly `label`. */
async function clickButton(s, selector, label) {
  const target = await s.evaluate(`(() => {
    const element = [...document.querySelectorAll(${JSON.stringify(selector)})].find((item) => item.textContent.trim() === ${JSON.stringify(label)});
    if (!element) return {ok: false, reason: 'missing'};
    element.scrollIntoView({block: 'center'});
    const rect = element.getBoundingClientRect();
    const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
    const hit = document.elementFromPoint(x, y);
    return {x, y, ok: !element.disabled && rect.width > 0 && (hit === element || element.contains(hit)), hit: hit?.outerHTML?.slice(0, 300)};
  })()`);
  if (!target.ok) throw new Error(`Not an enabled unobstructed button: ${label} ${JSON.stringify(target)}`);
  await s.click(target.x, target.y);
}

/**
 * Public editor contract setup, not a hover gesture: rest the real pointer on the open review,
 * wait until the browser reports it there and two frames have rendered, then show a
 * conflicting preview through editor.preview.
 */
async function competingPreview(s, editor, request) {
  const target = await s.evaluate(`(() => {
    const surface = document.querySelector('.library-replace-review .library-replace-body');
    if (!surface) return {ok: false, reason: 'missing'};
    const rect = surface.getBoundingClientRect();
    const x = rect.x + rect.width / 2, y = rect.y + Math.min(rect.height / 2, 24);
    const hit = document.elementFromPoint(x, y);
    return {x, y, ok: rect.width > 0 && rect.height > 0 && Boolean(hit?.closest('.library-replace-review')),
      hit: hit?.outerHTML?.slice(0, 300)};
  })()`);
  if (!target.ok) throw new Error(`Review surface is not the topmost target: ${JSON.stringify(target)}`);
  await s.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: target.x, y: target.y});
  await s.wait(`document.querySelector('.library-replace-review').matches(':hover')`, 'pointer resting on review');
  await s.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  return s.evaluate(`(() => {
    const plan = ${editor}.preview(${JSON.stringify(request)});
    return {planned: Boolean(plan), text: plan?.text ?? '', effects: (plan?.summaries || []).map((entry) => entry.effect),
      ghost: Boolean(document.querySelector('.sx-ed-previewing'))};
  })()`);
}

async function snapshot(s) {
  return s.evaluate(`(() => {
    const editor = ${ACTIVE}.editor;
    return {source: editor.getValue(), version: editor.getTextVersion(),
      selection: [editor.textarea.selectionStart, editor.textarea.selectionEnd],
      recent: JSON.parse(localStorage.getItem('schemaxis.studio.library') || '{}').recent || [],
      failures: window.studio.notify.store.get().log.filter((entry) => entry.title === ${JSON.stringify(FAILURE)}).length,
      dialogs: document.querySelectorAll(${JSON.stringify(REVIEW)}).length};
  })()`);
}

async function diagnostics(s) {
  return s.evaluate(`(() => ({focused: document.activeElement?.outerHTML?.slice(0, 300),
    dialogs: [...document.querySelectorAll('.dialog')].map((dialog) => dialog.textContent.slice(0, 800)),
    log: window.studio?.notify.store.get().log.slice(-6),
    cursor: (() => { try { return ${ACTIVE}.editor.getCursor(); } catch { return null; } })(),
    source: (() => { try { return ${ACTIVE}.editor.getValue(); } catch { return null; } })()}))()`);
}

async function review(s) {
  await s.wait(`document.querySelectorAll(${JSON.stringify(REVIEW)}).length === 1`, 'replacement review');
  return s.evaluate(`(() => {
    const dialog = document.querySelector(${JSON.stringify(REVIEW)});
    return {title: dialog.querySelector('h3').textContent, text: dialog.textContent,
      buttons: [...dialog.querySelectorAll('.dialog-footer button')].map((button) => button.textContent),
      cancelFocused: document.activeElement === dialog.querySelector('.dialog-footer button')};
  })()`);
}

const closed = (s) => s.wait(`!document.querySelector(${JSON.stringify(REVIEW)})`, 'review closed');
const cancel = (s) => click(s, `${REVIEW} .dialog-footer button:not(.danger)`);
const approve = (s) => click(s, `${REVIEW} .dialog-footer button.danger`);

async function command(s, title) {
  await s.key('k', {modifiers: 2});
  await s.wait('document.querySelector(".palette input")', 'command palette');
  await s.type(title);
  await s.wait(`document.querySelector('.palette-results [aria-selected="true"]')?.textContent.includes(${JSON.stringify(title)})`,
    `${title} selected`);
  await s.key('Enter');
}

async function refused(s, before) {
  await s.wait(`window.studio.notify.store.get().log.filter((entry) => entry.title === ${JSON.stringify(FAILURE)}
    && entry.body.includes('Nothing was replaced')).length === ${before.failures + 1}`, 'stale review refusal');
}

/** An earlier stale refusal stays in the notification stack while the next review is decided. */
async function staleToast(s) {
  assert.equal(await s.evaluate(`[...document.querySelectorAll('.toasts .toast.error')]
    .some((toast) => toast.textContent.includes('Nothing was replaced'))`), true, 'stale refusal toast still shown');
}

async function backdrop(s) {
  assert.equal(await s.evaluate(`document.elementFromPoint(4, 4) === document.querySelector(${JSON.stringify(REVIEW)}).parentElement`), true);
  await s.click(4, 4);
}

function expectedSnippet(item, names = {assets: 'assets', clips: 'clips'}) {
  const value = structuredClone(item.inserts[0].values[0]);
  value.nodes[0].options.assets = {...item.fields.assets, $fill: names.assets};
  value.nodes[0].options.clips = {...item.fields.clips, $fill: names.clips};
  return value;
}

test('Shotcut Workbench reviews whole-input replacement on every route and commits only fresh approvals', {timeout: 240000}, async () => {
  const s = await launch({provider: 'shotcut'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    const initial = JSON.stringify(fixture, null, 2) + '\n';
    const id = await s.evaluate(`(async () => {
      const ctx = window.studio;
      const record = await ctx.api.post('/api/documents', {action: 'new', provider: 'shotcut', name: 'Replacement review',
        source: ${JSON.stringify(initial)}, format: 'json'});
      await ctx.refresh();
      window.__workbench = ctx.windows.open('workbench', {document: record.id});
      return record.id;
    })()`);
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(initial)}
      && window.studio.commands.items.has('snippet:shotcut:edit-timeline')`, 'Workbench and Shotcut library');
    const item = await s.evaluate(`${ACTIVE}.store.get().metadata.snippets.find((entry) => entry.id === 'edit-timeline')`);

    const owner = await snapshot(s);
    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    const external = structuredClone(fixture);
    external.nodes[0].options.threads = 2;
    const saved = JSON.stringify(external, null, 2) + '\n';
    await s.evaluate(`(async () => {
      const ctx = window.studio;
      const record = ${ACTIVE}.store.get().record;
      await ctx.api.post('/api/authoring', {action: 'source', document: record.id, revision: record.revision,
        source: ${JSON.stringify(saved)}, format: 'json'});
      await ctx.refresh();
    })()`);
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(saved)}`, 'external revision loaded under review');
    assert.equal((await snapshot(s)).dialogs, 1);
    await approve(s);
    await closed(s);
    await refused(s, owner);
    assert.equal(await s.evaluate(`${ACTIVE}.editor.getValue()`), saved);

    await s.evaluate(`${ACTIVE}.editor.revealOffset(1)`);
    await s.type(' ');
    const edited = saved.slice(0, 1) + ' ' + saved.slice(1);
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(edited)}`, 'prior ordinary edit');

    const routes = [
      ['Templates card click / Cancel', async () => click(s, '[data-sidebar="library"]'),
        async () => click(s, '.wb-library [data-library="edit-timeline"]'), async () => cancel(s)],
      ['template card click / Escape', null, async () => click(s, '.wb-library [data-library="trim-reorder"]'),
        async () => s.key('Escape')],
      ['tray click / X', null, async () => {
        await click(s, '.library-more');
        await click(s, '.library-tray [data-category="timeline"]');
        await click(s, '.library-popover [data-library="edit-timeline"]');
      }, async () => click(s, `${REVIEW} .dialog-header button[aria-label="Close"]`)],
      ['tray keyboard / backdrop', null, async () => {
        await click(s, '.library-tray [data-category="timeline"]');
        await s.wait('document.activeElement === document.querySelector(".library-popover input")', 'popover search');
        await s.key('ArrowDown');
        await s.wait('document.activeElement?.dataset?.library === "edit-timeline"', 'popover card focus');
        await s.key('Enter');
      }, async () => backdrop(s)],
      ['Ctrl+K command / Cancel', null, async () => command(s, 'Insert snippet: Trim and arrange clips'), async () => cancel(s)],
    ];
    for (const [label, setup, start, dismiss] of routes) {
      await setup?.();
      const before = await snapshot(s);
      await start();
      const dialog = await review(s);
      assert.equal(dialog.title, 'Replace input?', label);
      assert.deepEqual(dialog.buttons, ['Cancel', 'Replace input'], label);
      assert.equal(dialog.cancelFocused, true, label);
      assert.match(dialog.text, /replaces the entire input/, label);
      assert.match(dialog.text, /Keeps document version schemaxis\.shotcut\/1/, label);
      assert.match(dialog.text, label.startsWith('template') ? /Afterwards, fill: Source video\./
        : /Afterwards, fill: Named local videos, Ordered source ranges\./, label);
      assert.match(dialog.text, /Changed text now: \d+ lines? from line \d+/, label);
      await dismiss();
      await closed(s);
      assert.deepEqual(await snapshot(s), before, label);
    }

    const second = await snapshot(s);
    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    await cancel(s);
    await closed(s);
    assert.deepEqual({...(await snapshot(s)), selection: null}, {...second, selection: null});

    const hidden = await snapshot(s);
    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    await command(s, 'Go to Start');
    await closed(s);
    await s.evaluate('window.studio.windows.activate(window.__workbench)');
    await s.wait(`window.studio.windows.active().key === window.__workbench`, 'Workbench reactivated');
    const shown = await snapshot(s);
    assert.equal(shown.source, hidden.source);
    assert.equal(shown.version, hidden.version);
    assert.equal(shown.failures, hidden.failures);

    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    await s.evaluate(`${ACTIVE}.editor.focus()`);
    const aba = await snapshot(s);
    await s.type('x');
    await s.wait(`${ACTIVE}.editor.getValue() !== ${JSON.stringify(edited)}`, 'typed under review');
    await s.key('z', {modifiers: 2});
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(edited)}`, 'typing undone to identical text');
    const abaAfter = await snapshot(s);
    assert.equal(abaAfter.version, aba.version + 2);
    await staleToast(s);
    await approve(s);
    await closed(s);
    await refused(s, abaAfter);
    assert.equal(await s.evaluate(`${ACTIVE}.editor.getValue()`), edited);
    assert.equal(await s.evaluate(`${ACTIVE}.editor.getTextVersion()`), abaAfter.version);

    await s.evaluate(`${ACTIVE}.editor.focus()`);
    await s.key('z', {modifiers: 2});
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(saved)}`, 'prior edit still undoes after reviews');

    const indent = await s.evaluate(`${ACTIVE}.editor.getOption('indent')`);
    const candidate = JSON.stringify(expectedSnippet(item), null, indent) + '\n';
    const before = await snapshot(s);
    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    const competing = await competingPreview(s, `${ACTIVE}.editor`, {inserts: [{at: '', values: [{version: 'schemaxis.shotcut/1',
      nodes: [{id: 'GhostTimeline', filter: 'editTimeline', options: {threads: 9}}]}]}], fields: {}});
    assert.equal(competing.planned, true);
    assert.deepEqual(competing.effects, ['replace']);
    assert.match(competing.text, /GhostTimeline/);
    assert.equal(competing.ghost, true);
    await staleToast(s);
    await approve(s);
    await closed(s);
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(candidate)}`, 'approved snippet replaces input');
    await s.wait('document.querySelector(".sx-fill-popover:not([hidden])")', 'fill starts after approval');
    const approved = await snapshot(s);
    assert.ok(approved.version > before.version);
    assert.equal(approved.failures, before.failures);
    assert.ok(approved.recent.includes('shotcut:edit-timeline'));
    assert.equal(await s.evaluate('Boolean(document.querySelector(".sx-ed-previewing"))'), false);

    const unfilled = await snapshot(s);
    await command(s, 'Insert snippet: Trim and arrange clips');
    assert.match((await review(s)).text, /replaces the entire input/);
    await s.key('Escape');
    await closed(s);
    assert.deepEqual({...(await snapshot(s)), selection: null}, {...unfilled, selection: null});

    await s.evaluate(`${ACTIVE}.editor.stopFill()`);
    await click(s, '.wb-editor-tools button[title="Undo draft edit (Ctrl+Z)"]');
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(saved)}`, 'one Undo restores exact input');
    await click(s, '.wb-editor-tools button[title="Redo draft edit (Ctrl+Shift+Z)"]');
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(candidate)}`, 'one Redo restores exact replacement');
    await click(s, '.wb-editor-tools button[title="Undo draft edit (Ctrl+Z)"]');
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(saved)}`, 'Undo again');

    const metadataOnly = '{\n  "version": "schemaxis.shotcut/1"\n}\n';
    await s.evaluate(`${ACTIVE}.editor.setValue(${JSON.stringify(metadataOnly)})`);
    const minimal = await snapshot(s);
    await command(s, 'Insert snippet: Trim and arrange clips');
    assert.match((await review(s)).text, /Keeps document version schemaxis\.shotcut\/1/);
    await cancel(s);
    await closed(s);
    assert.deepEqual({...(await snapshot(s)), selection: null}, {...minimal, selection: null});

    // Replacement coverage is complete; dismiss the retained refusal toasts before the unrelated legacy Add form.
    const history = () => s.evaluate(`window.studio.notify.store.get().log.map((entry) => [entry.level, entry.title, entry.body])`);
    const recorded = await history();
    assert.equal(recorded.filter(([level, title, body]) => level === 'error' && title === FAILURE
      && body.includes('Nothing was replaced')).length, 2);
    await staleToast(s);
    const beforeDismiss = await snapshot(s);
    const live = await s.evaluate(`document.querySelectorAll('.toasts .toast').length`);
    assert.ok(live >= 1 && live <= 4, `live toasts ${live}`);
    for (let index = 0; index < live && await s.evaluate(`document.querySelectorAll('.toasts .toast').length`) > 0; index += 1) {
      await click(s, '.toasts .toast [aria-label="Dismiss"]');
    }
    assert.equal(await s.evaluate(`document.querySelectorAll('.toasts .toast').length`), 0);
    assert.deepEqual(await history(), recorded);
    assert.deepEqual(await snapshot(s), beforeDismiss);

    await s.evaluate(`${ACTIVE}.editor.replaceDocument({version: 'schemaxis.shotcut/1', nodes: []})`);
    await click(s, '[data-add="sources"]');
    await s.wait(`document.querySelector('[data-library="operation:editTimeline"]')`, 'timeline Add card');
    await click(s, '[data-library="operation:editTimeline"]');
    await s.wait('document.querySelector(".operation-form")', 'Add form');
    for (const [label, value] of [['editTimeline.id', 'MyTimeline'], ['editTimeline.options.assets[0].name', 'camera'],
      ['editTimeline.options.assets[0].file', '/clips/caméra.mkv'], ['editTimeline.options.clips[0].asset', 'camera'],
      ['editTimeline.options.clips[0].frameCount', '2']]) {
      await s.evaluate(`(() => { const e = document.querySelector(${JSON.stringify(`[aria-label="${label}"]`)});
        e.value = ${JSON.stringify(value)}; e.dispatchEvent(new Event('input', {bubbles: true})); })()`);
    }
    await clickButton(s, '.dialog-footer button', 'Add operation');
    await s.wait(`JSON.parse(${ACTIVE}.editor.getValue()).nodes.length === 1`, 'ordinary Add commits without review');
    assert.equal(await s.evaluate(`Boolean(document.querySelector(${JSON.stringify(REVIEW)}))`), false);
    assert.equal(await s.evaluate(`JSON.parse(${ACTIVE}.editor.getValue()).nodes[0].options.assets[0].file`), '/clips/caméra.mkv');
    await s.evaluate(`${ACTIVE}.editor.setValue(${JSON.stringify(saved)})`);
    await s.wait(`!${ACTIVE}.isDirty()`, 'input matches the saved revision');

    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    await s.evaluate('window.studio.windows.close(window.__workbench)');
    await closed(s);
    await s.wait('!window.studio.windows.instances.has(window.__workbench)', 'Workbench disposed');
    const record = await s.evaluate(`window.studio.api.get('/api/document', {id: ${JSON.stringify(id)}})`);
    assert.equal(record.source, saved);
    assert.deepEqual(s.exceptions, []);
    assert.deepEqual(s.consoleErrors, []);
  } catch (error) {
    console.error(JSON.stringify({diagnostics: await diagnostics(s), exceptions: s.exceptions, consoleErrors: s.consoleErrors}));
    throw error;
  } finally {
    await s.close();
  }
});

test('nested Schema Editor replaces only its operation input and refuses same-text scope changes', {timeout: 180000}, async () => {
  const s = await launch({provider: 'shotcut'});
  try {
    await s.wait('window.studio?.store.get().adaptors.length > 0', 'Studio');
    const sibling = structuredClone(fixture);
    sibling.nodes[0].id = 'SecondTimeline';
    const design = {version: 'schemaxis.workflow-design/2', workflow: {version: 'schemaxis.workflow/1',
      definitions: {label: 'Défini'}, operations: [{id: 'first', document: structuredClone(fixture)},
        {id: 'second', document: sibling}, {id: 'third', document: {version: 'schemaxis.ffmpeg/1', nodes: []}}]},
    ports: {}, connections: [], controllers: {}, parameters: {}, outputs: {}, naming: {}, layout: {nodes: {}}};
    const initial = JSON.stringify(design, null, 2) + '\n';
    const id = await s.evaluate(`(async () => {
      const ctx = window.studio;
      const original = ctx.api.get.bind(ctx.api);
      window.__loadedSchemas = [];
      ctx.api.get = async (path, body) => {
        const result = await original(path, body);
        if (path === '/api/schema') window.__loadedSchemas.push(body.version);
        return result;
      };
      const record = await ctx.api.post('/api/documents', {action: 'new', provider: 'workflow-design', name: 'Nested replacement',
        source: ${JSON.stringify(initial)}, format: 'json'});
      await ctx.refresh();
      window.__schema = ctx.windows.open('schema-editor', {document: record.id});
      return record.id;
    })()`);
    await s.wait(`${ACTIVE}.editor?.getValue() === ${JSON.stringify(initial)}
      && ['schemaxis.workflow-design/2', 'schemaxis.shotcut/1', 'schemaxis.ffmpeg/1'].every((version) => window.__loadedSchemas.includes(version))`,
    'Schema Editor and nested schemas');
    const item = await s.evaluate(`window.studio.api.get('/api/studio/adaptor', {id: 'shotcut', version: 'schemaxis.shotcut/1'})
      .then((library) => library.snippets.find((entry) => entry.id === 'edit-timeline'))`);
    const base = '/workflow/operations/0/document';
    const focus = async (pointer, provider) => {
      await s.evaluate(`${ACTIVE}.editor.revealPointer(${JSON.stringify(pointer)})`);
      await s.wait(`[...window.studio.commands.items.keys()].some((key) => key.startsWith('snippet:${provider}:'))`, `${provider} library`);
    };

    await focus(`${base}/nodes/0/id`, 'shotcut');
    const first = await snapshot(s);
    await command(s, 'Insert snippet: Trim and arrange clips');
    const dialog = await review(s);
    assert.equal(dialog.title, 'Replace operation input?');
    assert.deepEqual(dialog.buttons, ['Cancel', 'Replace operation input']);
    assert.equal(dialog.cancelFocused, true);
    assert.match(dialog.text, /replaces the entire operation input at \/workflow\/operations\/0\/document/);
    assert.match(dialog.text, /Keeps document version schemaxis\.shotcut\/1/);
    await cancel(s);
    await closed(s);
    assert.deepEqual({...(await snapshot(s)), selection: null}, {...first, selection: null});

    const scope = await snapshot(s);
    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    await s.evaluate(`${ACTIVE}.editor.revealPointer('/workflow/operations/1/document/nodes/0/id')`);
    await s.wait(`${ACTIVE}.editor.getCursor().pointer.startsWith('/workflow/operations/1/document/')`, 'caret in sibling operation');
    assert.equal((await snapshot(s)).source, initial);
    assert.equal((await snapshot(s)).dialogs, 1);
    await approve(s);
    await closed(s);
    await refused(s, scope);
    assert.equal(await s.evaluate(`${ACTIVE}.editor.getValue()`), initial);
    assert.equal(await s.evaluate(`${ACTIVE}.editor.getTextVersion()`), scope.version);

    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    await s.evaluate(`${ACTIVE}.editor.revealPointer('/workflow/operations/2/document/version')`);
    await closed(s);
    await s.wait(`[...window.studio.commands.items.keys()].some((key) => key.startsWith('snippet:ffmpeg:'))`, 'other provider library');
    assert.equal(await s.evaluate(`${ACTIVE}.editor.getValue()`), initial);

    await focus(`${base}/nodes/0/id`, 'shotcut');
    const before = await snapshot(s);
    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    await staleToast(s);
    await approve(s);
    await closed(s);
    await s.wait(`${ACTIVE}.editor.getValue() !== ${JSON.stringify(initial)}`, 'nested replacement');
    const approved = await s.evaluate(`${ACTIVE}.editor.getValue()`);
    const value = JSON.parse(approved);
    assert.deepEqual(value.workflow.operations[0].document, expectedSnippet(item));
    const expected = structuredClone(design);
    expected.workflow.operations[0].document = expectedSnippet(item);
    assert.deepEqual(value, expected);
    const prefix = initial.slice(0, initial.indexOf('"document": ') + '"document": '.length);
    const suffix = initial.slice(initial.indexOf('"id": "second"'));
    assert.ok(approved.startsWith(prefix));
    assert.ok(approved.endsWith(suffix));
    const after = await snapshot(s);
    assert.ok(after.version > before.version);
    assert.equal(after.failures, before.failures);
    await s.wait('document.querySelector(".sx-fill-popover:not([hidden])")', 'nested fill starts after approval');

    await s.evaluate(`${ACTIVE}.editor.stopFill(); ${ACTIVE}.editor.focus()`);
    await s.key('z', {modifiers: 2});
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(initial)}`, 'one Undo restores the workflow');
    await s.evaluate(`${ACTIVE}.editor.redo()`);
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(approved)}`, 'one Redo restores the replacement');
    await s.evaluate(`${ACTIVE}.editor.focus()`);
    await s.key('z', {modifiers: 2});
    await s.wait(`${ACTIVE}.editor.getValue() === ${JSON.stringify(initial)}`, 'Undo again');

    await focus(`${base}/nodes/0/id`, 'shotcut');
    await command(s, 'Insert snippet: Trim and arrange clips');
    await review(s);
    await s.evaluate('window.studio.windows.close(window.__schema)');
    await closed(s);
    await s.wait('!window.studio.windows.instances.has(window.__schema)', 'Schema Editor disposed');
    const record = await s.evaluate(`window.studio.api.get('/api/document', {id: ${JSON.stringify(id)}})`);
    assert.equal(record.source, initial);
    assert.deepEqual(s.exceptions, []);
    assert.deepEqual(s.consoleErrors, []);
  } catch (error) {
    console.error(JSON.stringify({diagnostics: await diagnostics(s), exceptions: s.exceptions, consoleErrors: s.consoleErrors}));
    throw error;
  } finally {
    await s.close();
  }
});
