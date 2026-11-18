// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {entriesOf, selectedNames, sortedNames, toggledName} from '../windows/workbench/reader-selection.mjs';

test('offered names use natural case-insensitive order with deterministic exact ties', () => {
  const names = ['wall10', 'wall2', 'inlet', 'Wall2', 'Inlet', 'wall02', 'wall1'];
  assert.deepEqual(sortedNames(names), ['Inlet', 'inlet', 'wall1', 'Wall2', 'wall02', 'wall2', 'wall10']);
  assert.deepEqual(names, ['wall10', 'wall2', 'inlet', 'Wall2', 'Inlet', 'wall02', 'wall1'], 'source order is unchanged');
  const entries = entriesOf(['//wall10', '//wall1', {pattern: '^wall'}]);
  selectedNames(entries, sortedNames(names), true);
  assert.deepEqual(entries, entriesOf(['//wall10', '//wall1', {pattern: '^wall'}]), 'authored selectors are not reordered');
});

test('exact choices toggle on and off without leaking exclusion-only selections', () => {
  const available = ['internalMesh', 'wall', 'Inlet'];
  assert.deepEqual(selectedNames([], available, true), []);
  const added = toggledName([], 'wall', available, {blocks:true});
  assert.deepEqual(added.entries, entriesOf(['//wall']));
  assert.deepEqual(toggledName(added.entries, 'wall', available, {blocks:true}).entries, []);
  const remaining = toggledName(entriesOf(['/Root/A/wall', '/Root/B/wall', '//Inlet']), 'wall', available, {blocks:true});
  assert.deepEqual(remaining.entries, entriesOf(['//Inlet']));
  const excluded = entriesOf(['//Inlet', {exclude:'wall'}]);
  assert.deepEqual(toggledName(excluded, 'Inlet', available, {blocks:true}).entries, []);
  assert.deepEqual(excluded, entriesOf(['//Inlet', {exclude:'wall'}]), 'input is not mutated');
});

test('pattern-selected blocks toggle individually, retaining the dynamic pattern and other names', () => {
  const available = ['wall.X', 'wallY', 'Inlet'];
  const initial = entriesOf([{pattern:'^wall'}]);
  const off = toggledName(initial, 'wall.X', available, {blocks:true});
  assert.deepEqual(off.entries, entriesOf([{pattern:'^wall'}, {exclude:'^wall\\.X$'}]));
  assert.deepEqual(selectedNames(off.entries, available, true), ['wallY']);
  const on = toggledName(off.entries, 'wall.X', available, {blocks:true});
  assert.deepEqual(on.entries, initial);
  assert.deepEqual(selectedNames(on.entries, [...available, 'wallZ'], true), ['wall.X', 'wallY', 'wallZ']);
});

test('exclusion-only block selections retain the implicit all baseline when a name is restored', () => {
  const available = ['wall.X', 'wallY', 'Inlet'];
  for (const initial of [entriesOf([{exclude:'^wall\\.X$'}]), entriesOf([{exclude:'^wall'}])]) {
    const on = toggledName(initial, 'wall.X', available, {blocks:true});
    assert.deepEqual(new Set(selectedNames(on.entries, available, true)),
      new Set(initial[0].text === '^wall' ? ['Inlet', 'wall.X'] : available));
  }
});

test('reader All and affected pattern matches become exact choices on individual deselection', () => {
  const available = ['U', 'UMean', 'p', 'other'];
  const all = toggledName([], 'U', available, {all:true});
  assert.equal(all.all, false);
  assert.equal(all.materialized, true);
  assert.deepEqual(all.entries, entriesOf(['UMean','p','other']));
  const pattern = toggledName(entriesOf([{pattern:'^U'},'p']), 'U', available);
  assert.equal(pattern.materialized, true);
  assert.deepEqual(pattern.entries, entriesOf(['UMean','p']));
  assert.deepEqual(toggledName(pattern.entries, 'U', available).entries, entriesOf(['UMean','p','U']));
  const incomplete = toggledName(entriesOf([{pattern:'['},{pattern:'^U'},'p']), 'U', available);
  assert.deepEqual(incomplete.entries, entriesOf([{pattern:'['},'UMean','p']), 'unrelated unfinished patterns stay editable');
});
