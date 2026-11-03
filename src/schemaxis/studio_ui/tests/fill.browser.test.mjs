// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {launch, findChromium} from './fixtures/editor/cdp.mjs';

const ROOT = fileURLToPath(new URL('../../../../', import.meta.url));
const PAGE = '/src/schemaxis/studio_ui/tests/fixtures/fill/demo.html';
const shots = process.env.STUDIO_SCREENSHOTS || process.env.EDITOR_SCREENSHOTS;
const visible = 'document.querySelector(".sx-fill-popover:not([hidden])")';
const current = (session) => session.evaluate(`${visible}?.querySelector('.sx-fill-heading strong')?.textContent`);
const value = (session) => session.evaluate('JSON.parse(window.demo.editor.getValue())');
const select = (session, label, value) => session.evaluate(`(() => {
  const element = document.querySelector('[aria-label=${JSON.stringify(label)}]');
  element.value = ${JSON.stringify(value)};
  element.dispatchEvent(new Event('change', {bubbles: true}));
})()`);
const input = (session, label, text) => session.evaluate(`(() => {
  const element = document.querySelector('[aria-label=${JSON.stringify(label)}]');
  element.value = ${JSON.stringify(text)};
  element.dispatchEvent(new Event('input', {bubbles: true}));
})()`);

test('expression references omit draft identities and discriminator follow-ups survive remaining fields',
  {skip: findChromium() ? false : 'Chromium not available'}, async () => {
    const session = await launch({root: ROOT, width: 1150, height: 860});
    try {
      await session.open(PAGE);
      await session.wait('window.demo?.ready', 'fill ready');
      const choices = await session.evaluate(`(async () => {
        const {createExpressionForm} = await import('/src/schemaxis/studio_ui/editor/fill-expressions.mjs');
        const schema = await (await fetch('/docs/generated/paraview.authored.schema.json')).json();
        const value = structuredClone(window.demo.initial);
        value.nodes.push(null, {id: {$fill: 'next'}}, {id: 7}, {id: ''});
        value.axes = [{name: 'height'}, null, {name: {$fill: 'axis'}}, {name: false}, {name: ''}];
        return ['$observe', '$sample', '$axis'].map((kind) => {
          const form = createExpressionForm({schema, value, pointer: '/nodes/1/options/origin', kind,
            onChange: () => {}});
          return [...form.element.querySelector('select').options].map((option) => option.value);
        });
      })()`);
      assert.deepEqual(choices, [['source', 'slice'], ['source', 'slice'], ['height', 'Create an axis…']]);
      for (const theme of ['light', 'dark']) {
        await session.evaluate(`(() => {
          document.documentElement.dataset.theme = ${JSON.stringify(theme)};
          const filter = (name) => ({$fill: name, label: name, type: 'enum', values: ['slice'], default: 'slice'});
          const value = {version: 'schemaxis/1', nodes: [
            {id: 'first', filter: filter('First filter')}, {id: 'second', filter: filter('Second filter')}],
            settings: {count: {$fill: 'count', label: 'Count', type: 'integer', default: 3}}};
          window.demo.editor.stopFill();
          window.demo.editor.setValue(JSON.stringify(value, null, 2));
          window.demo.editor.setOption('commonProperties', () => ['origin']);
          window.demo.editor.startFill();
        })()`);
        for (const label of ['First filter', 'Second filter', 'Count']) {
          assert.equal(await current(session), label);
          await session.key('Enter');
        }
        assert.match(await session.evaluate(`${visible}.textContent`), /Add properties for this choice.*origin/);
        if (shots) await session.screenshot(join(shots, `fill-followup-${theme}.png`));
        await session.key('Enter');
        assert.equal(await current(session), 'origin');
        assert.equal((await value(session)).nodes[0].options.origin.$fill, 'origin');
        await session.type('[0,0,0]');
        await session.key('Enter');
        // Filling the first queued options must not discard the second follow-up.
        assert.match(await session.evaluate(`${visible}.textContent`), /Add properties for this choice.*origin/);
        await session.key('Enter');
        assert.equal((await value(session)).nodes[1].options.origin.$fill, 'origin');
        await session.type('[1,2,3]');
        await session.key('Enter');
        assert.equal(await session.evaluate('document.querySelector(".sx-fill-popover").hidden'), true);
        assert.deepEqual((await value(session)).nodes.map((node) => node.options.origin), [[0, 0, 0], [1, 2, 3]]);
      }
      assert.deepEqual(session.exceptions, []);
    } finally {
      await session.close();
    }
  });

test('linked XYZ fields navigate and count once while all occurrences fill atomically within scope',
  {skip: findChromium() ? false : 'Chromium not available'}, async () => {
    const session = await launch({root: ROOT, width: 1150, height: 860});
    try {
      await session.open(PAGE);
      await session.wait('window.demo?.ready', 'fill ready');
      const occurrences = await session.evaluate(`(async () => {
        const {libraryRequest, markers} = await import('/src/schemaxis/studio_ui/editor/insert-fields.mjs');
        const library = await (await fetch('/src/schemaxis/adaptors/paraview/studio.json')).json();
        const recipe = library.snippets.find((entry) => entry.id === 'xyz-slice-arrays');
        const base = {version: 'schemaxis/1', nodes: [{id: 'source', filter: 'wavelet'}], axes: [], scenes: []};
        const request = libraryRequest(recipe, base);
        for (const insert of request.inserts) base[insert.at.split('/')[1]].push(...insert.values);
        const pointers = markers(base).map((entry) => entry.pointer);
        // A same-identity marker outside the insertion remains independently editable.
        base.settings = {outside: {...recipe.fields.source, $fill: 'source'}};
        window.demo.editor.stopFill();
        window.demo.editor.setValue(JSON.stringify(base, null, 2));
        window.demo.editor.startFill({pointers});
        window.demo.linked = {base, pointers, markers};
        return pointers.length;
      })()`);
      assert.equal(occurrences, 25); // Names and ID prefixes are assigned automatically.
      const badge = () => session.evaluate('document.querySelector(".sx-fill-badge").textContent');
      const heading = () => session.evaluate(`${visible}.querySelector('.sx-fill-heading span').textContent`);
      assert.equal(await badge(), '2 values to fill');
      assert.equal(await current(session), 'Data source');
      assert.equal(await heading(), '1 of 2 · required');
      await session.key('Tab');
      assert.equal(await current(session), 'Slices per axis');
      assert.equal(await heading(), '2 of 2 · required');
      await session.key('Tab');
      assert.equal(await current(session), 'Data source');
      await session.key('Tab', 8);
      assert.equal(await current(session), 'Slices per axis');
      await session.key('Tab');
      await session.key('Enter');
      assert.equal(await current(session), 'Slices per axis');
      assert.equal(await heading(), '1 of 1 · required');
      assert.equal(await badge(), '2 values to fill'); // The out-of-scope source is still unfilled.
      assert.deepEqual(await session.evaluate(`window.demo.linked.markers(JSON.parse(window.demo.editor.getValue()))
        .filter(({marker}) => marker.$fill === 'source').map(({pointer}) => pointer)`), ['/settings/outside']);
      await session.evaluate('window.demo.editor.stopFill(); window.demo.editor.focus()');
      await session.key('z', 2);
      await session.wait(`window.demo.linked.markers(JSON.parse(window.demo.editor.getValue())).length === 26`,
        'one undo restores all linked source markers');
      await session.evaluate('window.demo.editor.startFill({pointers: window.demo.linked.pointers})');
      assert.equal(await current(session), 'Data source');
      await session.key('Escape');
      await session.wait('document.querySelectorAll(".sx-fill-quiet").length > 0',
        'linked markers retain quiet decorations');
      await session.evaluate('document.querySelector(".sx-fill-badge").click()');
      for (const label of ['Data source', 'Slices per axis']) {
        assert.equal(await current(session), label);
        await session.key('Enter');
      }
      assert.equal(await session.evaluate('document.querySelector(".sx-fill-badge").hidden'), true);
      assert.equal(await session.evaluate('document.querySelector(".sx-fill-popover").hidden'), true);
      assert.deepEqual(await session.evaluate(
        'window.demo.linked.markers(JSON.parse(window.demo.editor.getValue()))'), []);
      assert.equal((await value(session)).settings.outside, 'source');
      assert.deepEqual(session.exceptions, []);
    } finally {
      await session.close();
    }
  });

test('fill keyboard navigation, persisted markers, typed expressions and both themes',
  {skip: findChromium() ? false : 'Chromium not available'}, async () => {
    const session = await launch({root: ROOT, width: 1150, height: 860});
    try {
      await session.open(`${PAGE}?theme=light`);
      await session.wait('window.demo?.ready', 'fill ready');
      assert.equal(await current(session), 'Data source');
      assert.equal(await session.evaluate('document.querySelector(".sx-fill-badge").textContent'), '4 values to fill');
      await session.key('ArrowDown');
      assert.equal(await session.evaluate('document.activeElement.getAttribute("aria-label")'), 'Choose a value');
      await session.key('ArrowDown');
      await session.key('Enter');
      await session.wait(`JSON.parse(window.demo.editor.getValue()).nodes[1].inputs.input === 'source'`,
        'source chosen');
      assert.equal(await current(session), 'Slice origin');
      await session.type('[1, 2]');
      assert.match(await session.evaluate(`${visible}.querySelector('.sx-fill-message').textContent`), /3 numbers/);
      await session.key('Enter');
      assert.equal(await current(session), 'Slice origin');
      await input(session, 'Value', '[1, 2, 3]');
      await session.key('Tab');
      assert.deepEqual((await value(session)).nodes[1].options.origin, [1, 2, 3]);
      assert.equal(await current(session), 'Slices per axis');
      await session.type('5');
      await session.key('Enter');
      assert.equal((await value(session)).settings.count, 5);
      assert.equal(await current(session), 'ID prefix');
      await session.key('Escape');
      assert.equal((await value(session)).settings.prefix.$fill, 'prefix');
      assert.equal(await session.evaluate('document.querySelector(".sx-fill-popover").hidden'), true);
      await session.evaluate('document.querySelector(".sx-fill-badge").click()');
      assert.equal(await current(session), 'ID prefix');

      await session.evaluate(`window.demo.editor.setValue(JSON.stringify(window.demo.initial, null, 2));
        window.demo.editor.startFill()`);
      await session.key('Tab');
      assert.equal(await current(session), 'Slice origin');
      await session.key('Tab', 8);
      assert.equal(await current(session), 'Data source');
      await session.key('Tab');
      await session.key('ArrowUp');
      assert.equal(await session.evaluate('document.activeElement.getAttribute("aria-label")'), 'Value or expression');
      await select(session, 'Value or expression', '$value');
      assert.ok(await session.evaluate(`document.querySelector('[aria-label="bounds argument"]') !== null`));
      await input(session, 'bounds argument', '[0, 1]');
      assert.equal(await session.evaluate(`${visible}.querySelector('.primary').disabled`), true);
      await input(session, 'bounds argument', '[0, 1, 0, 1, 0, 1]');
      assert.equal(await session.evaluate(`${visible}.querySelector('.primary').disabled`), false);
      if (shots) await session.screenshot(join(shots, 'fill-light.png'));
      await session.evaluate(`${visible}.querySelector('.primary').click()`);
      assert.deepEqual((await value(session)).nodes[1].options.origin,
        {$value: 'boundsCentre', args: {bounds: [0, 1, 0, 1, 0, 1]}});

      await session.open(`${PAGE}?theme=dark`);
      await session.wait('window.demo?.ready', 'dark fill ready');
      await session.key('Tab');
      await select(session, 'Value or expression', '$analytic');
      await select(session, 'Analytic type', 'linear');
      await input(session, 'Count', '0');
      assert.equal(await session.evaluate(`${visible}.querySelector('.primary').disabled`), true);
      await input(session, 'Count', '5');
      if (shots) await session.screenshot(join(shots, 'fill-dark.png'));
      await session.evaluate(`${visible}.querySelector('.primary').click()`);
      assert.equal((await value(session)).nodes[1].options.origin.$analytic.type, 'linear');
      // Every admitted expression has an editable, schema-checked form.
      const resetOrigin = async () => {
        await session.evaluate(`window.demo.editor.setValue(JSON.stringify(window.demo.initial, null, 2));
          window.demo.editor.startFill({pointers: ['/nodes/1/options/origin']})`);
      };
      for (const kind of ['$document', '$expr', '$observe', '$sample', '$calc', '$call']) {
        await resetOrigin();
        await select(session, 'Value or expression', kind);
        if (kind === '$sample') await input(session, 'Field name', 'pressure');
        if (kind === '$call') await input(session, 'bounds argument', '[0,1,0,1,0,1]');
        assert.equal(await session.evaluate(`${visible}.querySelector('.primary').disabled`), false, kind);
        await session.evaluate(`${visible}.querySelector('.primary').click()`);
        assert.ok(Object.hasOwn((await value(session)).nodes[1].options.origin, kind));
      }
      await resetOrigin();
      await select(session, 'Value or expression', '$axis');
      await input(session, 'New axis name', 'height');
      await input(session, 'New axis values (JSON)', '[0, 1, 2]');
      await session.evaluate(`${visible}.querySelector('.primary').click()`);
      assert.deepEqual((await value(session)).axes, [{name: 'height', values: [0, 1, 2]}]);
      assert.deepEqual((await value(session)).nodes[1].options.origin, {$axis: 'height'});
      await session.evaluate('window.demo.editor.stopFill(); window.demo.editor.focus()');
      await session.key('z', 2);
      await session.wait('JSON.parse(window.demo.editor.getValue()).axes === undefined',
        'one undo removes axis and binding');
      assert.equal((await value(session)).nodes[1].options.origin.$fill, 'origin');

      await session.evaluate(`window.demo.editor.stopFill();
        window.demo.editor.setValue('{"version":"schemaxis/1","nodes":[{"id":"cut","filter":"slice"}]}');
        window.demo.editor.fillRequired('/nodes/0')`);
      assert.equal((await value(session)).nodes[0].inputs.$fill, 'inputs');
      assert.equal(await current(session), 'inputs');
      await session.key('Escape');
      await session.wait('document.querySelectorAll(".sx-fill-quiet").length > 0', 'quiet markers render');
      await session.evaluate(`window.demo.editor.setOption('commonProperties', () => ['origin', 'normal']);
        window.demo.editor.offerFollowup('/nodes/0/options')`);
      assert.match(await session.evaluate(`${visible}.textContent`), /origin.*normal/);
      await session.key('Enter');
      assert.equal((await value(session)).nodes[0].options.origin.$fill, 'origin');
      assert.equal((await value(session)).nodes[0].options.normal.$fill, 'normal');
      assert.equal(await current(session), 'origin');
      assert.deepEqual(session.exceptions, []);
    } finally {
      await session.close();
    }
  });
