// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {readdirSync, statSync} from 'node:fs';
import {join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {naturalCompare, parseSchemaxisName, companionBase, fileKind} from '../../src/schemaxis_viewer/explorer/names.mjs';
import {detectSequences} from '../../src/schemaxis_viewer/explorer/sequences.mjs';
import {compileRule, applyRule, captureNames, extractRuleProperties, importRules, exportRules} from '../../src/schemaxis_viewer/explorer/rules.mjs';
import {Collection, groupItems, commonChips, facets, matchesFilters, spatialFromMetadata, metadataProblem, METADATA_VERIFIED} from '../../src/schemaxis_viewer/explorer/collection.mjs';

const fixture = fileURLToPath(new URL('../../examples/viewer-test/', import.meta.url));

function walk(directory, found = []) {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (name === '.output-index') continue;
    if (statSync(path).isDirectory()) walk(path, found);
    else found.push(relative(fixture, path));
  }
  return found;
}

function sequencesOf(names) {
  const result = detectSequences(names.map((name, index) => ({id: String(index), folder: 'f', name})));
  return names.map((name, index) => result.get(String(index)) || null);
}

test('natural order puts file10 after file2', () => {
  const names = ['file10.png', 'file2.png', 'file1.png', 'file11.png', 'file3.png'];
  assert.deepEqual(names.sort(naturalCompare), ['file1.png', 'file2.png', 'file3.png', 'file10.png', 'file11.png']);
});

test('numbered sequences, including embedded and padded numbers', () => {
  const [a, b, c, d] = sequencesOf(['file1.png', 'file10.png', 'file2.png', 'file11.png']);
  assert.equal(a.family, b.family);
  assert.deepEqual([a, c, b, d].map(entry => entry.rank), [0, 1, 2, 3]);
  const embedded = sequencesOf(['filename1-outputU.png', 'filename2-outputU.png', 'filename3-outputU.png']);
  assert.equal(new Set(embedded.map(entry => entry.family)).size, 1);
  assert.equal(embedded[0].label, 'filename[1–3]-outputU.png');
  const padded = sequencesOf(['shot-001.png', 'shot-010.png', 'shot-002.png']);
  assert.deepEqual(padded.map(entry => entry.values[0]), [1, 10, 2]);
});

test('different letters after the number are different sequences', () => {
  const [p, u] = sequencesOf(['file1outP.png', 'file2outU.png']);
  assert.equal(p, null);
  assert.equal(u, null);
  const same = sequencesOf(['file1outU.png', 'file2outU.png']);
  assert.equal(same[0].family, same[1].family);
});

test('lettered sequences and letters that step with a number', () => {
  const letters = sequencesOf(['fileA.png', 'fileB.png', 'fileZ.png', 'fileAA.png']);
  assert.equal(new Set(letters.map(entry => entry.family)).size, 1);
  assert.deepEqual(letters.map(entry => entry.rank), [0, 1, 2, 3]);
  const stepped = sequencesOf(['file-AAA-0-name.png', 'file-AAB-1-name.png', 'file-AAC-2-name.png']);
  assert.equal(stepped[0].label, 'file-[AAA–AAC]-[0–2]-name.png');
  assert.deepEqual(sequencesOf(['Slices.X.001.png', 'Slices.Y.003.png', 'Slices.Z.010.png']), [null, null, null]);
  assert.deepEqual(sequencesOf(['fileA.png', 'fileB.png']), [null, null]);
});

test('negative and decimal numbers order numerically', () => {
  const entries = sequencesOf(['x_-0.05.png', 'x_0.1.png', 'x_-0.2.png']);
  assert.deepEqual(entries.map(entry => entry.rank), [1, 2, 0]);
});

test('Schemaxis key-value names decode lists, escapes and worker suffixes', () => {
  const parsed = parseSchemaxisName('000070.20__kind_image__var_wall.x5F.shear__related_list_A_.x31.1__normal_list_-2.1_1.0_3.png');
  assert.equal(parsed.ordinal, '000070');
  assert.equal(parsed.worker, '20');
  assert.equal(parsed.properties.var, 'wall_shear');
  assert.deepEqual(parsed.properties.related, ['A', '11']);
  assert.deepEqual(parsed.properties.normal, [-2.1, 1, 3]);
  assert.equal(parseSchemaxisName('000099__var_U__var_p.png'), null);
  assert.equal(parseSchemaxisName('velocity_x_001.png'), null);
  assert.equal(companionBase('a.png.metadata.json'), 'a.png');
  assert.equal(companionBase('a.png.schemaxis-meta'), 'a.png');
  assert.equal(fileKind('model.STL'), 'mesh');
});

test('filename patterns: captures, named groups, tags and whole matches', () => {
  assert.deepEqual(captureNames('a(b)(?:c)(?<name>d)[(]\\(e'), [{index: 1, name: null}, {index: 2, name: 'name'}]);
  const slices = compileRule({name: 'Slices', pattern: '[sS]lices[._-]([XYZ])[._-]([0-9]+)',
    columns: [{index: 1, key: 'axis'}, {index: 2, key: 'number', type: 'number'}]});
  assert.deepEqual(applyRule(slices, {name: 'Slices.Y.003.png'}).values, {axis: 'Y', number: 3});
  assert.equal(applyRule(slices, {name: 'model.png'}), null);
  const tags = compileRule({name: 'Tags', pattern: '-tags-([^-]+)-', columns: [{index: 1, key: 'tags', type: 'tags', separator: '.'}]});
  assert.deepEqual(applyRule(tags, {name: 'file-AAD-3-tags-DOT.SEPERATED.TAGS-enclosedByDashes-name.png'}).values.tags, ['DOT', 'SEPERATED', 'TAGS']);
  const named = compileRule({name: 'Named', pattern: '(?<case>[a-z]+)_(?<step>[0-9]+)'});
  assert.deepEqual(applyRule(named, {name: 'cavity_12.png'}).values, {case: 'cavity', step: '12'});
  const whole = compileRule({name: 'Has error', pattern: 'error', ignoreCase: true});
  assert.deepEqual(applyRule(whole, {name: 'ERROR.log'}).values, {'Has-error': 'ERROR'});
  assert.throws(() => compileRule({name: 'Bad', pattern: '(x', columns: []}));
  const {errors} = extractRuleProperties([{id: '1', name: 'x'}], [{id: 'r', enabled: true, name: 'Bad', pattern: '(x'}]);
  assert.ok(errors.has('r'));
  const round = importRules(exportRules([{name: 'Slices', enabled: true, pattern: 'a(b)', columns: [{index: 1, key: 'b'}]}]));
  assert.equal(round[0].pattern, 'a(b)');
});

test('fixture groups into sequences by filename properties, without folder names', () => {
  const files = walk(fixture);
  const records = files.map((path, index) => ({id: String(index), relativePath: path, root: 'r', rootLabel: 'viewer-test', size: 1, url: path}));
  const collection = new Collection(records);
  assert.ok(collection.items.every(item => !item.name.endsWith('.metadata.json')));
  assert.ok(collection.items.filter(item => item.companion).length >= 50);
  const groups = groupItems(collection.items, ['@sequence']);
  const slices = groups.filter(group => group.items[0].props.kind === 'slice');
  assert.equal(slices.length, 12);
  for (const group of slices) {
    assert.equal(group.orderKey, 'pos');
    assert.deepEqual(group.items.map(item => item.props.pos), [0.1, 0.4, 0.9]);
  }
  const {common} = commonChips(groups);
  assert.ok(common.some(([key]) => key === 'view'));
  const byKeys = groupItems(collection.items.filter(item => item.props.kind === 'slice'), ['var', 'axis']);
  assert.equal(byKeys.length, 6);
  assert.deepEqual(byKeys[0].vary, ['model']);
  const lettered = groups.find(group => group.label === 'phase-[A–AA].png');
  assert.deepEqual(lettered.items.map(item => item.name), ['phase-A.png', 'phase-B.png', 'phase-Z.png', 'phase-AA.png']);
});

test('filters: any value within a property, every property across them', () => {
  const records = ['000000__var_U__axis_X.png', '000001__var_p__axis_X.png', '000002__var_U__axis_Y.png']
    .map((name, index) => ({id: String(index), relativePath: name, root: 'r', size: 1, url: name}));
  const collection = new Collection(records);
  const filters = new Map([['var', new Set(['"U"', '"p"'])], ['axis', new Set(['"X"'])]]);
  assert.deepEqual(collection.items.filter(item => matchesFilters(item, filters)).map(item => item.id), ['0', '1']);
  const counts = facets(collection.items, new Map([['axis', new Set(['"X"'])]]));
  const variable = counts.find(facet => facet.key === 'var');
  assert.deepEqual(variable.values.map(value => [value.value, value.count]), [['p', 1], ['U', 1]]);
});

test('spatial placement needs four known, finite corners', () => {
  const placed = spatialFromMetadata({spatial: {state: 'known', corners: [[0, 0, 1], [0, 1, 1], [0, 1, 0], [0, 0, 0]]}});
  assert.deepEqual(placed.normal.map(Math.abs), [1, 0, 0]);
  assert.equal(spatialFromMetadata({spatial: {state: 'inferred', corners: [[0, 0, 1], [0, 1, 1], [0, 1, 0], [0, 0, 0]]}}), null);
  assert.equal(spatialFromMetadata({spatial: {state: 'known', corners: [[0, 0, 1], [0, 1, 1], [0, 1, 0]]}}), null);
});

test('companion metadata applies only when it names the file and its SHA-256 matched', () => {
  const name = '000000__var_U.png';
  const collection = new Collection([{id: '0', relativePath: name, root: 'r', size: 1, url: name}]);
  const [item] = collection.items;
  const metadata = {version: 'schemaxis.artifact-metadata/1', artifact: {file: name, sha256: 'a'.repeat(64)},
    properties: {case: 'cavity'}, spatial: {state: 'known', corners: [[0, 0, 1], [0, 1, 1], [0, 1, 0], [0, 0, 0]]}};
  assert.equal(metadataProblem(item, metadata), null);
  assert.match(metadataProblem(item, {...metadata, version: 'other'}), /not Schemaxis/);
  assert.match(metadataProblem(item, {...metadata, artifact: {file: 'other.png', sha256: 'a'.repeat(64)}}), /different file/);
  assert.match(metadataProblem(item, {...metadata, artifact: {file: name}}), /SHA-256/);
  collection.setMetadata(item, metadata, 'SHA-256 does not match the file; not applied');
  assert.equal(item.spatial, null);
  assert.equal(item.props.case, undefined);
  collection.setMetadata(item, metadata, METADATA_VERIFIED);
  assert.ok(item.spatial);
  assert.equal(item.props.case, 'cavity');
});
