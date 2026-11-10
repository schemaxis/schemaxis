// Copyright (C) 2026 David L. F. Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {blockName, entriesOf, matchesOf, selectedNames} from '../windows/workbench/reader-selection.mjs';

const BLOCKS = ['internalMesh', 'WT_inlet', 'WT_floor', 'wheels_FL_Tyre', 'wheels_FL_movingPatch', 'wheels_RR_Tyre',
  'body_upper', 'body_diffuser', 'procBoundary0to2', 'underfloor_floor'];

test('block entries round-trip selectors, patterns and exclusions', () => {
  assert.deepEqual(entriesOf(['//internalMesh', {pattern: '^wheels_'}, {exclude: '^WT_'}]), [
    {text: '//internalMesh', regex: false}, {text: '^wheels_', regex: true}, {text: '^WT_', regex: true, exclude: true}]);
  assert.deepEqual(entriesOf({$fill: 'selectors'}), []);
  assert.equal(blockName('//internalMesh'), 'internalMesh');
  assert.equal(blockName('/Root/boundary/body_upper'), 'body_upper');
  assert.deepEqual(matchesOf({text: '/Root/boundary/body_upper', regex: false}, BLOCKS, true), ['body_upper']);
  assert.deepEqual(matchesOf({text: '//body_upper', regex: false}, BLOCKS), []);
});

test('a block list resolves as the application does: patterns add, exclusions remove, exclusions alone start from all', () => {
  assert.deepEqual(selectedNames(entriesOf([{pattern: '^wheels_[FR][RL]_T'}]), BLOCKS, true), ['wheels_FL_Tyre', 'wheels_RR_Tyre']);
  assert.deepEqual(selectedNames(entriesOf([{exclude: '^(WT_|wheels_|procBoundary|internalMesh$|underfloor_floor$)'}]), BLOCKS, true),
    ['body_upper', 'body_diffuser']);
  assert.deepEqual(selectedNames(entriesOf(['//internalMesh', {pattern: '^body'}, {exclude: 'diffuser'}]), BLOCKS, true),
    ['internalMesh', 'body_upper']);
  assert.deepEqual(selectedNames(entriesOf(['internalMesh', {pattern: '^patch/'}]), ['internalMesh', 'patch/a', 'patch/b']),
    ['internalMesh', 'patch/a', 'patch/b']);
  assert.deepEqual(selectedNames([], BLOCKS, true), BLOCKS);
});
