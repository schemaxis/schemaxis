// Copyright (C) 2026 David L. F. Gaden.
// Real Chromium: every library route reviews whole-input replacement, every dismissal
// leaves the input untouched, and an approved prepared edit commits once with one Undo.
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {launch} from './fixtures/editor/cdp.mjs';

const ROOT = fileURLToPath(new URL('../', import.meta.url));
const REVIEW = '.library-replace-review';
const STALE = 'The input changed while this replacement was open for review. Nothing was replaced; '
  + 'choose the item again to review the current input.';
const text = (value) => JSON.stringify(value, null, 2) + '\n';

async function open(format = 'json') {
  const session = await launch({root: ROOT, width: 1440, height: 960});
  await session.open(`/tests/fixtures/library/replace.html${format === 'yaml' ? '?format=yaml' : ''}`);
  await session.wait('window.replaceDemo', 'replacement fixture');
  return session;
}

async function mouse(session, x, y) {
  await session.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x, y});
  await session.send('Input.dispatchMouseEvent', {type: 'mousePressed', x, y, button: 'left', clickCount: 1});
  await session.send('Input.dispatchMouseEvent', {type: 'mouseReleased', x, y, button: 'left', clickCount: 1});
}

/** Click the centre of an enabled, visible element that is the topmost hit at that point. */
async function click(session, selector) {
  const target = await session.evaluate(`(() => {
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
  await mouse(session, target.x, target.y);
}

/**
 * Public editor contract setup, not a hover gesture: rest the real pointer on the open review,
 * wait until the browser reports it there and two frames have rendered, then show a
 * conflicting preview through editor.preview.
 */
async function competingPreview(session, editor, request) {
  const target = await session.evaluate(`(() => {
    const surface = document.querySelector('.library-replace-review .library-replace-body');
    if (!surface) return {ok: false, reason: 'missing'};
    const rect = surface.getBoundingClientRect();
    const x = rect.x + rect.width / 2, y = rect.y + Math.min(rect.height / 2, 24);
    const hit = document.elementFromPoint(x, y);
    return {x, y, ok: rect.width > 0 && rect.height > 0 && Boolean(hit?.closest('.library-replace-review')),
      hit: hit?.outerHTML?.slice(0, 300)};
  })()`);
  if (!target.ok) throw new Error(`Review surface is not the topmost target: ${JSON.stringify(target)}`);
  await session.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: target.x, y: target.y});
  await session.wait(`document.querySelector('.library-replace-review').matches(':hover')`, 'pointer resting on review');
  await session.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  return session.evaluate(`(() => {
    const plan = ${editor}.preview(${JSON.stringify(request)});
    return {planned: Boolean(plan), text: plan?.text ?? '', effects: (plan?.summaries || []).map((entry) => entry.effect),
      ghost: Boolean(document.querySelector('.sx-ed-previewing'))};
  })()`);
}

async function snapshot(session) {
  return session.evaluate(`(() => {
    const editor = replaceDemo.editor;
    return {source: editor.getValue(), version: editor.getTextVersion(), format: editor.getOption('format') || 'json',
      selection: [editor.textarea.selectionStart, editor.textarea.selectionEnd],
      recent: JSON.parse(localStorage.getItem('schemaxis.studio.library') || '{}').recent || [],
      errors: replaceDemo.errors.slice(), dialogs: document.querySelectorAll(${JSON.stringify(REVIEW)}).length};
  })()`);
}

async function diagnostics(session) {
  return session.evaluate(`(() => ({focused: document.activeElement?.outerHTML?.slice(0, 300),
    dialogs: [...document.querySelectorAll('.dialog')].map((dialog) => dialog.textContent.slice(0, 600)),
    errors: window.replaceDemo?.errors, source: window.replaceDemo?.editor.getValue()}))()`);
}

async function review(session) {
  await session.wait(`document.querySelectorAll(${JSON.stringify(REVIEW)}).length === 1`, 'replacement review');
  return session.evaluate(`(() => {
    const dialog = document.querySelector(${JSON.stringify(REVIEW)});
    return {title: dialog.querySelector('h3').textContent, text: dialog.textContent,
      buttons: [...dialog.querySelectorAll('.dialog-footer button')].map((button) => button.textContent),
      cancelFocused: document.activeElement === dialog.querySelector('.dialog-footer button')};
  })()`);
}

async function closed(session) {
  await session.wait(`!document.querySelector(${JSON.stringify(REVIEW)})`, 'review closed');
}

async function backdrop(session) {
  const point = await session.evaluate(`(() => {
    const backdrop = document.querySelector(${JSON.stringify(REVIEW)}).parentElement;
    return document.elementFromPoint(4, 4) === backdrop;
  })()`);
  assert.equal(point, true, 'review backdrop is the topmost target');
  await mouse(session, 4, 4);
}

test('every library route reviews root replacement; all dismissals and ordinary insertions keep their behaviour', {timeout: 120000}, async () => {
  const session = await open();
  try {
    const initial = await snapshot(session);
    await click(session, '.wb-library [data-library="append"]');
    await session.wait('replaceDemo.editor.getValue().includes(\'"café"\')', 'ordinary append');
    const appended = await snapshot(session);
    assert.equal(appended.dialogs, 0);
    assert.ok(appended.version > initial.version);
    assert.equal(appended.source, text({version: 'fixture/1', label: 'Ünïcode — café', settings: {level: 1},
      nodes: [{id: 'keep', filter: 'source'}, {id: 'café', filter: 'source'}]}));
    assert.ok(appended.recent.includes('fixture:append'));

    const cancel = async () => click(session, `${REVIEW} .dialog-footer button:not(.danger)`);
    const routes = [
      ['main card click / Cancel', null, async () => click(session, '.wb-library [data-library="starter"]'), cancel],
      ['main card Enter / Escape', null, async () => {
        await session.wait('document.activeElement?.dataset?.library === "starter"', 'card focus restored');
        await session.key('Enter');
      }, async () => session.key('Escape')],
      ['tray click / X', null, async () => {
        await click(session, '.library-more');
        await click(session, '.library-tray [data-category="general"]');
        await click(session, '.library-popover [data-library="reset"]');
      }, async () => click(session, `${REVIEW} .dialog-header button[aria-label="Close"]`)],
      ['tray keyboard / backdrop', null, async () => {
        await click(session, '.library-tray [data-category="general"]');
        await session.wait('document.activeElement === document.querySelector(".library-popover input")', 'popover search');
        for (let step = 0; step < 4 && await session.evaluate('document.activeElement?.dataset?.library !== "reset"'); step += 1) {
          await session.key('ArrowDown');
        }
        await session.wait('document.activeElement?.dataset?.library === "reset"', 'reset popover card');
        await session.key('Enter');
      }, async () => backdrop(session)],
      ['Ctrl+K command / Cancel', null, async () => {
        await session.key('k', 2);
        await session.wait('document.querySelector(".palette input")', 'command palette');
        await session.type('Reset document');
        await session.key('Enter');
      }, cancel],
      ['contextual section / Cancel', async () => {
        // Setup through the public editor API; the shortcut itself is clicked.
        await session.evaluate('replaceDemo.editor.revealPointer("/nodes/0"); replaceDemo.library.updateSection()');
        await session.wait('[...document.querySelectorAll(".library-section:not([hidden]) button")].some((b) => b.textContent === "Compose and add")', 'section shortcut');
      }, async () => {
        const index = await session.evaluate('[...document.querySelectorAll(".library-section button")].findIndex((b) => b.textContent === "Compose and add")');
        await click(session, `.library-section button:nth-of-type(${index + 1})`);
      }, cancel],
    ];
    for (const [label, setup, start, dismiss] of routes) {
      await setup?.();
      const before = await snapshot(session);
      await start();
      const dialog = await review(session);
      assert.equal(dialog.title, 'Replace input?', label);
      assert.deepEqual(dialog.buttons, ['Cancel', 'Replace input'], label);
      assert.equal(dialog.cancelFocused, true, label);
      assert.match(dialog.text, /replaces the entire input/, label);
      assert.match(dialog.text, /Changed text now: \d+ lines? from line \d+/, label);
      assert.match(dialog.text, /Changed text after replacement:/, label);
      if (label.startsWith('main card')) assert.match(dialog.text, /Changes document version from fixture\/1 to fixture\/2/, label);
      if (label.startsWith('contextual')) assert.match(dialog.text, /Replace the entire input.*Add 1 at \/nodes\/-/s, label);
      else assert.match(dialog.text, /Keeps document version fixture\/1|Changes document version/, label);
      await dismiss();
      await closed(session);
      const after = await snapshot(session);
      assert.deepEqual(after, before, label);
    }

    await click(session, '.wb-library [data-library="tune"]');
    await session.wait('replaceDemo.editor.getDocument().settings.level === 2', 'root merge without review');
    assert.equal((await snapshot(session)).dialogs, 0);
    await session.evaluate('replaceDemo.editor.focus()');
    await session.key('z', 2);
    await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(appended.source)}`, 'merge undone');
    await session.key('z', 2);
    await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(initial.source)}`, 'prior append undone after cancellations');

    const before = await snapshot(session);
    await click(session, '.wb-library [data-library="starter"]');
    await review(session);
    const shots = process.env.STUDIO_SCREENSHOTS;
    if (shots) {
      await mkdir(shots, {recursive: true});
      await session.screenshot(join(shots, 'studio-library-replace-review.png'));
    }
    await click(session, `${REVIEW} .dialog-footer button.danger`);
    await closed(session);
    const candidate = text(replaceDemo().metadata.templates[0].document);
    await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(candidate)}`, 'approved replacement');
    const approved = await snapshot(session);
    assert.ok(approved.version > before.version);
    assert.ok(approved.recent.includes('fixture:starter'));
    assert.deepEqual(approved.errors, []);
    await session.evaluate('replaceDemo.editor.focus()');
    await session.key('z', 2);
    await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(initial.source)}`, 'one Undo restores exact input');
    await session.evaluate('replaceDemo.editor.redo()');
    await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(candidate)}`, 'one Redo restores exact replacement');
    assert.deepEqual(await session.evaluate('replaceDemo.errors'), []);
    assert.deepEqual(session.exceptions, []);
  } catch (error) {
    console.error(JSON.stringify(await diagnostics(session)));
    throw error;
  } finally {
    await session.close();
  }
});

function replaceDemo() {
  return {metadata: {templates: [{document: {version: 'fixture/2', nodes: [{id: 'fresh', filter: 'source'}]}}]}};
}

test('prepared replacement refuses stale, foreign, reused and destroyed decisions without editing', {timeout: 120000}, async () => {
  const session = await open();
  try {
    const contract = await session.evaluate(`(() => {
      const editor = replaceDemo.editor;
      const request = {inserts: [{at: '/nodes/-', values: [{id: 'z'}]}], fields: {}};
      const other = replaceDemo.createJsonEditor(document.body.appendChild(document.createElement('div')), {value: editor.getValue()});
      const token = editor.prepareInsert(request);
      const result = {frozen: Object.isFrozen(token) && Object.isFrozen(token.summaries[0]) && Object.isFrozen(token.fields),
        forged: editor.commitPrepared({...token}), foreign: other.commitPrepared(token), source: editor.getValue()};
      editor.setReadOnly(true);
      result.readOnly = editor.commitPrepared(token);
      editor.setReadOnly(false);
      result.replayed = editor.commitPrepared(token);
      result.after = editor.getValue();
      const owned = other.prepareInsert(request);
      other.destroy();
      result.destroyed = other.commitPrepared(owned);
      result.prepareDestroyed = other.prepareInsert(request);
      return result;
    })()`);
    const initial = await snapshot(session);
    assert.deepEqual(contract, {frozen: true, forged: false, foreign: false, source: initial.source, readOnly: false,
      replayed: false, after: initial.source, destroyed: false, prepareDestroyed: null});

    const stale = async (label, change, restore = async () => {}) => {
      await click(session, '.wb-library [data-library="reset"]');
      await review(session);
      const before = await change();
      await click(session, `${REVIEW} .dialog-footer button.danger`);
      await closed(session);
      await session.wait(`replaceDemo.errors.length === ${before.errors.length + 1}
        && replaceDemo.errors.at(-1) === ${JSON.stringify(STALE)}`, `${label} refusal`);
      const after = await snapshot(session);
      assert.equal(after.source, before.source, label);
      assert.equal(after.version, before.version, label);
      await restore();
    };
    await stale('edit then Undo to identical text', async () => {
      const start = await snapshot(session);
      await session.evaluate('replaceDemo.editor.focus()');
      await session.type('x');
      await session.wait(`replaceDemo.editor.getValue() !== ${JSON.stringify(start.source)}`, 'typed');
      await session.key('z', 2);
      await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(start.source)}`, 'typing undone');
      const before = await snapshot(session);
      assert.equal(before.version, start.version + 2);
      return before;
    });
    await stale('format-only change (editor API contract)', async () => {
      await session.evaluate('replaceDemo.editor.setFormat("yaml")');
      return snapshot(session);
    }, async () => session.evaluate('replaceDemo.editor.setFormat("json")'));
    await stale('indentation change (editor API contract)', async () => {
      await session.evaluate('replaceDemo.editor.setOption("indent", "    ")');
      return snapshot(session);
    }, async () => session.evaluate('replaceDemo.editor.setOption("indent", "  ")'));

    const composeBefore = await snapshot(session);
    await session.key('k', 2);
    await session.wait('document.querySelector(".palette input")', 'command palette');
    await session.type('Compose and add');
    await session.key('Enter');
    await review(session);
    await session.evaluate('replaceDemo.editor.revealOffset(0)');
    await click(session, `${REVIEW} .dialog-footer button.danger`);
    await closed(session);
    await session.wait(`replaceDemo.errors.at(-1) === ${JSON.stringify(STALE)} && replaceDemo.errors.length === 4`, 'caret-sensitive refusal');
    assert.equal((await snapshot(session)).source, composeBefore.source);

    const literalBefore = await snapshot(session);
    await click(session, '.wb-library [data-library="reset"]');
    await review(session);
    await session.evaluate(`replaceDemo.editor.revealOffset(${literalBefore.source.indexOf('"nodes"')})`);
    const competing = await competingPreview(session, 'replaceDemo.editor',
      {inserts: [{at: '', values: [{version: 'fixture/9', nodes: [{id: 'ghost', filter: 'source'}]}]}], fields: {}});
    assert.equal(competing.planned, true);
    assert.deepEqual(competing.effects, ['replace']);
    assert.match(competing.text, /ghost/);
    assert.equal(competing.ghost, true);
    await click(session, `${REVIEW} .dialog-footer button.danger`);
    await closed(session);
    const reset = text({version: 'fixture/1', nodes: []});
    await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(reset)}`, 'approved prepared edit, not the ghost');
    assert.equal(await session.evaluate('Boolean(document.querySelector(".sx-ed-previewing"))'), false);
    assert.equal((await snapshot(session)).errors.length, 4);
    await session.evaluate('replaceDemo.editor.focus()');
    await session.key('z', 2);
    await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(literalBefore.source)}`, 'one Undo after literal replacement');

    const second = await snapshot(session);
    await click(session, '.wb-library [data-library="reset"]');
    await review(session);
    await session.key('k', 2);
    await session.wait('document.querySelector(".palette input")', 'palette over review');
    await session.type('Compose and add');
    await session.key('Enter');
    await session.wait(`document.querySelectorAll(${JSON.stringify(REVIEW)}).length === 1
      && document.querySelector(${JSON.stringify(REVIEW)}).textContent.includes('Compose and add')`, 'second invocation replaces review');
    await click(session, `${REVIEW} .dialog-footer button:not(.danger)`);
    await closed(session);
    assert.deepEqual({...(await snapshot(session)), selection: null}, {...second, selection: null});

    const metadata = await snapshot(session);
    await click(session, '.wb-library [data-library="reset"]');
    await review(session);
    await session.evaluate('replaceDemo.library.update(replaceDemo.metadata)');
    await closed(session);
    assert.deepEqual(await snapshot(session), metadata);

    await session.evaluate('replaceDemo.editor.setValue(\'{"version": \')');
    const invalid = await snapshot(session);
    await click(session, '.wb-library [data-library="reset"]');
    await session.wait('replaceDemo.errors.length === 5', 'invalid input refusal');
    const refused = await snapshot(session);
    assert.equal(refused.errors.at(-1), 'Repair source syntax before structured editing');
    assert.equal(refused.dialogs, 0);
    assert.equal(refused.source, invalid.source);
    await session.evaluate(`replaceDemo.editor.setValue(${JSON.stringify(initial.source)})`);

    await click(session, '.wb-library [data-library="reset"]');
    await review(session);
    await session.evaluate('replaceDemo.library.destroy(); replaceDemo.editor.destroy()');
    await closed(session);
    assert.equal(await session.evaluate('replaceDemo.errors.length'), 5);
    assert.deepEqual(session.exceptions, []);
  } catch (error) {
    console.error(JSON.stringify(await diagnostics(session)));
    throw error;
  } finally {
    await session.close();
  }
});

test('YAML root replacement reviews, commits once and restores exact source with one Undo/Redo', {timeout: 90000}, async () => {
  const session = await open('yaml');
  try {
    const initial = await snapshot(session);
    assert.equal(initial.format, 'yaml');
    await click(session, '.wb-library [data-library="append"]');
    await session.wait('replaceDemo.editor.getDocument().nodes.length === 2', 'ordinary YAML append');
    assert.equal((await snapshot(session)).dialogs, 0);
    assert.match(await session.evaluate('replaceDemo.editor.getValue()'), /# authored note/);
    await session.evaluate('replaceDemo.editor.focus()');
    await session.key('z', 2);
    await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(initial.source)}`, 'append undone');

    await click(session, '.wb-library [data-library="starter"]');
    const dialog = await review(session);
    assert.match(dialog.text, /Changes document version from fixture\/1 to fixture\/2/);
    await click(session, `${REVIEW} .dialog-header button[aria-label="Close"]`);
    await closed(session);
    assert.equal(await session.evaluate('replaceDemo.editor.getValue()'), initial.source);

    await click(session, '.wb-library [data-library="starter"]');
    await review(session);
    await click(session, `${REVIEW} .dialog-footer button.danger`);
    await closed(session);
    await session.wait(`replaceDemo.editor.getValue() !== ${JSON.stringify(initial.source)}`, 'YAML replacement');
    const candidate = await session.evaluate('replaceDemo.editor.getValue()');
    assert.deepEqual(await session.evaluate('replaceDemo.editor.getDocument()'),
      {version: 'fixture/2', nodes: [{id: 'fresh', filter: 'source'}]});
    await session.evaluate('replaceDemo.editor.focus()');
    await session.key('z', 2);
    await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(initial.source)}`, 'YAML Undo');
    await session.evaluate('replaceDemo.editor.redo()');
    await session.wait(`replaceDemo.editor.getValue() === ${JSON.stringify(candidate)}`, 'YAML Redo');
    assert.deepEqual(await session.evaluate('replaceDemo.errors'), []);
    assert.deepEqual(session.exceptions, []);
  } catch (error) {
    console.error(JSON.stringify(await diagnostics(session)));
    throw error;
  } finally {
    await session.close();
  }
});
