// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFile} from 'node:fs/promises';
import {blocks, cells, contextTopic, diagram, searchTopics, slug, decodePage} from '../windows/help/model.mjs';

const index = JSON.parse(await readFile(new URL('../help/index.json', import.meta.url)));

test('Help prose matches word prefixes without unrelated embedded words', () => {
  const entries = [
    {title: 'rect', search: 'replaces a rectangle through image pixels'},
    {title: 'importImage', search: 'place image artwork into an existing cel'},
    {title: 'pvClip', search: 'cliptype clipping planes $document values'},
  ];
  assert.deepEqual(searchTopics(entries, 'place image').map(item => item.title), ['importImage']);
  assert.deepEqual(searchTopics(entries, 'clip').map(item => item.title), ['pvClip']);
  assert.deepEqual(searchTopics(entries, '$document').map(item => item.title), ['pvClip']);
  assert.deepEqual(searchTopics(entries, '[image]'), []);
});

test('declared native identifiers are found exactly and case-insensitively without matching prose prefixes', () => {
  const entries = [
    {title: 'locate', search: 'photo location altitude reference distance to a point', nativeTerms: ['compareto', 'media']},
    {title: 'compareMetadata', search: 'compare photo metadata of two files'},
    {title: 'legacy', search: 'an older entry without the optional field'},
  ];
  const titles = (query) => searchTopics(entries, query).map(item => item.title);
  assert.deepEqual(titles('compareTo'), ['locate']);
  assert.deepEqual(titles('COMPARETO'), ['locate']);
  assert.deepEqual(titles('compareto'), ['locate']);
  // A prose word that is only the leading part of an identifier does not match it.
  assert.deepEqual(titles('compare'), ['compareMetadata']);
  assert.deepEqual(titles('compare photo metadata'), ['compareMetadata']);
  assert.deepEqual(titles('compareT'), []);
  assert.deepEqual(titles('medi'), []);
  // Identifier terms combine with prose terms, and title substring matching is unchanged.
  assert.deepEqual(titles('compareTo altitude'), ['locate']);
  assert.deepEqual(titles('compareTo compare'), []);
  assert.deepEqual(titles('metadata'), ['compareMetadata']);
  assert.deepEqual(titles('older field'), ['legacy']);
  assert.deepEqual(searchTopics(entries, 'compareTo', 'Other'), []);
  assert.deepEqual(searchTopics([{title: 'x', search: 'y', nativeTerms: 'compareto'}], 'compareTo'), []);
});

test('packaged help finds an operation by its declared native name but not by a prose prefix of it', () => {
  const found = (query) => searchTopics(index.entries, query).map((entry) => entry.capabilityId);
  assert.ok(found('compareTo').includes('operation/exiftool/locate'));
  assert.ok(found('compareto').includes('operation/exiftool/locate'));
  assert.ok(!found('compare photos').includes('operation/exiftool/locate'));
  assert.ok(found('compare photos').includes('operation/exiftool/compareMetadata'));
  // Every declared identifier finds its own operation.
  const withNames = index.entries.filter((entry) => entry.nativeTerms);
  assert.ok(withNames.length > 100);
  for (const entry of withNames) {
    for (const term of entry.nativeTerms) {
      assert.ok(searchTopics([entry], term).length === 1, `${entry.title}: ${term}`);
    }
  }
});

test('packaged help searches native options and dollar syntax, and resolves adaptor context', () => {
  assert.equal(index.entries.filter((entry) => entry.provider === 'paraview' && entry.operation).length, 645);
  assert.equal(searchTopics(index.entries, 'pvClip')[0].title, 'pvClip');
  assert.ok(searchTopics(index.entries, 'ClipType').some((entry) => entry.title === 'pvClip'));
  assert.ok(searchTopics(index.entries, '$document').some((entry) => entry.id === index.shared));
  assert.equal(contextTopic(index, {provider: 'paraview', operation: 'slice'}).title, 'slice');
  assert.equal(contextTopic(index, {provider: 'freecad', operation: 'box'}).title, 'box');
  // The accepted primary FreeCAD guide is declared by studio.json helpGuide and the route's readiness guide.
  assert.equal(contextTopic(index, {provider: 'freecad'}).source, 'docs/freecad-part-design.md');
  assert.equal(contextTopic(index, {provider: 'freecad'}).id, index.guides.freecad);
  // The broader CAD and mesh workflow guide stays packaged as a searchable topic, but is no longer the default.
  assert.ok(index.entries.some((entry) => entry.source === 'docs/cad-and-mesh-workflows.md'));
  assert.equal(contextTopic(index, {provider: 'workflow'}).source, 'docs/workflow-authoring.md');
  assert.equal(contextTopic(index, {provider: 'paraview'}).id, index.paraview);
  assert.equal(searchTopics(index.entries, 'no-match-here-491631').length, 0);
});

test('Markdown tables preserve escaped pipes and headings ignore code blocks', () => {
  assert.deepEqual(cells('| a | `x\\|y` |'), ['a', '`x|y`']);
  const result = blocks('# Title\n\n```json\n{"s":"## not heading"}\n```\n## Keys\n\n| Name | Value |\n| --- | --- |\n| x | 1 |\n## Keys');
  assert.deepEqual(result.filter((item) => item.type === 'heading').map((item) => item.anchor), ['title', 'keys', 'keys-1']);
  assert.equal(result.find((item) => item.type === 'table').rows[0][1], '1');
  assert.equal(slug('`$document`: pointer reuse'), 'document-pointer-reuse');
});

test('flow charts retain branches, loops and authored labels', () => {
  const result = diagram('flowchart TD\n A[Start] --> B{Changed?}\n B -->|yes| C[Update]\n B -->|no| D[Reuse]\n C --> A');
  assert.equal(result.nodes.length, 4);
  assert.equal(result.nodes.find((item) => item.id === 'B').decision, true);
  assert.deepEqual(result.edges.map((item) => item.label), ['', 'yes', 'no', '']);
  assert.equal(result.edges.at(-1).to, 'A');
});

test('every indexed topic and local navigation target is packaged', async () => {
  const ids = new Set(index.entries.map((entry) => entry.id));
  for (const entry of index.entries) {
    const page = await decodePage(JSON.parse(await readFile(new URL(`../help/${entry.id}.json`, import.meta.url))));
    assert.equal(page.id, entry.id);
    for (const target of Object.values(page.links)) assert.ok(ids.has(target.id));
    if (page.format === 'md') {
      assert.deepEqual(blocks(page.body).filter((item) => item.type === 'heading').map((item) => item.anchor), page.headings.map((item) => item.anchor));
    }
  }
});

test('Help starts with Studio and covers every packaged application reference', () => {
  assert.equal(index.entries.find(entry => entry.id === index.home).source, 'docs/studio-guide.md');
  for (const provider of ['paraview','freecad','blender','gmsh','qgis','godot','aseprite','ffmpeg','octave','cantera','ngspice','calc']) {
    assert.ok(index.entries.some(entry => entry.provider === provider && entry.operation), provider);
  }
});
