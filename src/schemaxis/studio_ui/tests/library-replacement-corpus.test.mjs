// Copyright (C) 2026 David L. F. Gaden.
// Reconciles every projected library surface (the real StudioApplication.studio_adaptor
// route filter) and a declarative plugin-shaped library with the shared replacement
// classifier. Authoring metadata only: no native workflow is executed.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {parse} from '../editor/json-parse.mjs';
import {applyEdit, planInserts} from '../editor/insert.mjs';
import {libraryRequest, scopeReplacements, scopeRequest} from '../editor/insert-fields.mjs';

const REPOSITORY = fileURLToPath(new URL('../../../../', import.meta.url));
const DUMP = `
import json, sys, tempfile
from schemaxis.adaptors import registry
from schemaxis.console_session import AdaptorConsoleSession
from schemaxis.studio_server import StudioApplication
from schemaxis.studio_library import load_library
surfaces = []
owners = [('schemaxis.workflow/1', 'workflow'), ('schemaxis.workflow-design/2', 'workflow-design')]
with tempfile.TemporaryDirectory() as directory:
    session = AdaptorConsoleSession(directory, provider='workflow-design')
    try:
        app = StudioApplication(session)
        routes = [(version, name) for version, (name, route) in registry.routes().items()]
        for version, name in routes + owners:
            library = app.studio_adaptor(name, version)
            surfaces.append({'provider': name, 'route': version, 'runtime': name in registry.ADAPTORS,
                             'templates': library.get('templates', []), 'snippets': library.get('snippets', [])})
    finally:
        session.close()
plugin = [load_library('fixture-plugin', path) for path in sys.argv[1:]]
print('CORPUS' + json.dumps({'providers': len(registry.ADAPTORS), 'faults': len(registry.PLUGIN_FAULTS),
                             'surfaces': surfaces, 'plugin': plugin}))
`;

const LEGACY = {version: 'schemaxis.studio-adaptor/1', templates: [{id: 'starter', title: 'Starter',
  document: {version: 'plugin.fixture/1', nodes: []}}], snippets: [{id: 'reset', title: 'Reset',
  insert: {at: '', values: [{version: 'plugin.fixture/1', nodes: [{id: 'fresh'}]}]}}]};
const CURRENT = {version: 'schemaxis.studio-adaptor/2', categories: [{id: 'general', title: 'General'}],
  templates: [{id: 'empty', title: 'Empty', document: {}}], snippets: [
    {id: 'compose', title: 'Compose', category: 'general', complexity: 'composite', inserts: [
      {at: '', values: [{version: 'plugin.fixture/2', nodes: []}]}, {at: '/nodes/-', values: [{id: 'added'}]}]},
    {id: 'tune', title: 'Tune', category: 'general', inserts: [{at: '', merge: {settings: {level: 2}}}]},
    {id: 'here', title: 'Here', category: 'general', testCursor: '/settings',
      inserts: [{at: '@cursor', values: [{level: 3}]}]},
    {id: 'append', title: 'Append', category: 'general', inserts: [{at: '/nodes/-', values: [{id: 'more'}]}]}]};

function corpus() {
  const directories = [LEGACY, CURRENT].map((library) => {
    const directory = mkdtempSync(join(tmpdir(), 'schemaxis-plugin-library-'));
    writeFileSync(join(directory, 'studio.json'), JSON.stringify(library));
    return directory;
  });
  try {
    const output = execFileSync('python3', ['-B', '-c', DUMP, ...directories], {cwd: REPOSITORY, encoding: 'utf8',
      maxBuffer: 256 * 1024 * 1024, env: {...process.env, PYTHONPATH: join(REPOSITORY, 'src'), SCHEMAXIS_ADAPTOR_PLUGINS: 'off'}});
    return JSON.parse(output.split('\n').find((line) => line.startsWith('CORPUS')).slice('CORPUS'.length));
  } finally {
    directories.forEach((directory) => rmSync(directory, {recursive: true, force: true}));
  }
}

const inserts = (item) => (item.document ? [{at: '', values: [item.document]}] : item.inserts || [item.insert]);

function classify(item) {
  const list = inserts(item);
  if (list.some((entry) => entry.at === '' && Object.hasOwn(entry, 'values'))) return 'root';
  if (list.some((entry) => entry.at === '' && Object.hasOwn(entry, 'merge'))) return 'merge';
  if (list.some((entry) => entry.at === '@cursor')) return 'cursor';
  return 'other';
}

const populated = (route) => ({version: route, label: 'Ünïcode — keep', settings: {}, nodes: [{id: 'keep', filter: 'existing'}]});
const workflow = (document) => ({version: 'schemaxis.workflow/1', operations: [{id: 'a', document: structuredClone(document)},
  {id: 'b', document: structuredClone(document)}]});
const BASE = '/operations/0/document';
const rootIndices = (item) => inserts(item).flatMap((entry, index) => entry.at === '' && Object.hasOwn(entry, 'values') ? [index] : []);
const cursorReplacements = (item) => inserts(item).flatMap((entry, index) => entry.at === '@cursor' && Object.hasOwn(entry, 'values') ? [index] : []);

/**
 * Workbench (local root) and Schema Editor (nested operation) classification of one item.
 * Ordinary corpus targets are classified from their literal pointers only, so arbitrary
 * adaptor paths are not planned against a synthetic document.
 */
function mechanism(item, route, {planOthers = false} = {}) {
  const kind = classify(item);
  if (kind === 'other' && !planOthers) return {kind};
  const document = populated(route);
  const source = JSON.stringify(document, null, 2);
  const outer = workflow(document);
  const outerSource = JSON.stringify(outer, null, 2);
  const local = libraryRequest(item, document);
  const scoped = scopeRequest(libraryRequest(item, document), {base: BASE, root: outer});
  if (kind === 'cursor') {
    const caret = source.indexOf('"settings": ') + '"settings": '.length;
    const nestedCaret = outerSource.indexOf('"document": ') + '"document": '.length;
    const plain = planInserts(parse(source), local.inserts, {caret});
    const nested = planInserts(parse(outerSource), scoped.inserts, {caret: nestedCaret});
    return {kind, local: scopeReplacements(plain.summaries, ''), nested: scopeReplacements(nested.summaries, BASE),
      sibling: JSON.parse(applyEdit(outerSource, nested)).operations[1], outer: outer.operations[1]};
  }
  const plain = planInserts(parse(source), local.inserts);
  const nested = planInserts(parse(outerSource), scoped.inserts);
  return {kind, local: scopeReplacements(plain.summaries, ''), nested: scopeReplacements(nested.summaries, BASE),
    sibling: JSON.parse(applyEdit(outerSource, nested)).operations[1], outer: outer.operations[1],
    effects: plain.summaries.map((entry) => entry.effect)};
}

test('every projected library surface maps root values, root merges and @cursor through one classifier', () => {
  const data = corpus();
  assert.equal(data.faults, 0);
  const runtime = data.surfaces.filter((surface) => surface.runtime);
  assert.equal(data.providers, 51);
  assert.equal(new Set(runtime.map((surface) => surface.provider)).size, 51);
  assert.equal(runtime.length, 62);
  assert.equal(data.surfaces.length, 64);
  assert.deepEqual(data.surfaces.filter((surface) => !surface.runtime).map((surface) => surface.route),
    ['schemaxis.workflow/1', 'schemaxis.workflow-design/2']);
  assert.deepEqual(data.surfaces.filter((surface) => !surface.templates.length && !surface.snippets.length)
    .map((surface) => `${surface.provider}|${surface.route}`).sort(),
  ['blender|schemaxis.blender.render/1', 'inkscape|schemaxis.inkscape/1']);
  const counts = {root: 0, merge: 0, cursor: 0, other: 0, templates: 0, snippets: 0, cursorValues: 0, appearances: 0};
  const unique = new Set();
  for (const surface of data.surfaces) {
    for (const [group, items] of [['templates', surface.templates], ['snippets', surface.snippets]]) {
      for (const item of items) {
        counts.appearances += 1;
        const label = `${surface.provider}|${surface.route}|${group}|${item.id}`;
        const result = mechanism(item, surface.route);
        counts[result.kind] += 1;
        if (result.kind === 'root') {
          counts[group] += 1;
          unique.add(`${surface.provider}|${group}|${item.id}`);
          assert.deepEqual(result.local, rootIndices(item), label);
          assert.deepEqual(result.nested, rootIndices(item), label);
          assert.deepEqual(result.sibling, result.outer, label);
        } else if (result.kind === 'merge') {
          assert.deepEqual(result.local, [], label);
          assert.deepEqual(result.nested, [], label);
          assert.ok(result.effects.includes('merge'), label);
        } else if (result.kind === 'cursor') {
          const values = cursorReplacements(item);
          if (values.length) counts.cursorValues += 1;
          assert.deepEqual(result.local, [], label);
          assert.deepEqual(result.nested, values, label);
          assert.deepEqual(result.sibling, result.outer, label);
        } else {
          assert.ok(inserts(item).every((entry) => typeof entry.at === 'string' && entry.at.startsWith('/')), label);
        }
      }
    }
  }
  assert.deepEqual(counts, {root: 328, merge: 9, cursor: 12, other: 308, templates: 279, snippets: 49,
    cursorValues: 10, appearances: 657});
  assert.equal(unique.size, 307);
});

test('a declarative plugin-shaped library, including migrated singular inserts, uses the same mechanism', () => {
  const [legacy, current] = corpus().plugin;
  assert.deepEqual(legacy.snippets[0].inserts, [{at: '', values: [{version: 'plugin.fixture/1', nodes: [{id: 'fresh'}]}]}]);
  const items = [...legacy.templates, ...legacy.snippets, ...current.templates, ...current.snippets];
  const results = Object.fromEntries(items.map((item) => [item.id, mechanism(item, 'plugin.fixture/2', {planOthers: true})]));
  assert.deepEqual(Object.fromEntries(Object.entries(results).map(([id, result]) => [id, [result.kind, result.local, result.nested]])), {
    starter: ['root', [0], [0]], reset: ['root', [0], [0]], empty: ['root', [0], [0]], compose: ['root', [0], [0]],
    tune: ['merge', [], []], here: ['cursor', [], [0]], append: ['other', [], []]});
  assert.deepEqual(results.compose.effects, ['replace', 'insert']);
  for (const result of Object.values(results)) assert.deepEqual(result.sibling, result.outer);
});
