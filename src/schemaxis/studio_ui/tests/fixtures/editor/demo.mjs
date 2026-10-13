// Smoke-test page: mounts the JSON editor with real Schemaxis schemas.
// Query: ?doc=paraview|workflow|empty&theme=light|dark

import {createJsonEditor} from '../../../editor/editor.mjs';
import {SchemaRegistry} from '../../../editor/schema.mjs';

const GENERATED = new URL('../../../../../../docs/generated/', import.meta.url);
const FILES = {
  'schemaxis/1': 'paraview',
  'schemaxis.workflow/1': 'workflow',
  'schemaxis.freecad/1': 'freecad',
  'schemaxis.gmsh/1': 'gmsh',
  'schemaxis.blender/1': 'blender',
  'schemaxis.calc/1': 'calc',
};

const DOCUMENTS = {
  paraview: {
    version: 'schemaxis/1',
    nodes: [
      {id: 'source', filter: 'wavelet'},
      {id: 'cut', filter: 'slice', inputs: {input: 'source'}, options: {origin: {$axis: 'height'}, normal: [0, 0, 1]}},
      {id: 'iso', filter: 'contour', inputs: {input: 'source'}, options: {crinkle: 'yes'}},
    ],
    scenes: [],
  },
  workflow: {
    version: 'schemaxis.workflow/1',
    operations: [
      {id: 'mesh', document: {version: 'schemaxis.gmsh/1', units: 'mm', nodes: [], output: 'mesh'}},
    ],
  },
};

const params = new URLSearchParams(location.search);
document.documentElement.dataset.theme = params.get('theme') === 'dark' ? 'dark' : 'light';
const kind = params.get('doc') || 'paraview';
const status = document.getElementById('demo-status');

const registry = new SchemaRegistry(async (version) => {
  const file = FILES[version];
  if (!file) {
    return null;
  }
  const response = await fetch(new URL(`${file}.authored.schema.json`, GENERATED));
  return response.ok ? response.json() : null;
}, {versions: Object.keys(FILES)});

const initial = kind === 'empty' ? '' : JSON.stringify(DOCUMENTS[kind], null, 2);
const editor = createJsonEditor(document.getElementById('demo-editor'), {value: initial, registry});
const rootVersion = DOCUMENTS[kind]?.version;

editor.onChange(() => {
  const cursor = editor.getCursor();
  status.textContent = `Ln ${cursor.line}, Col ${cursor.column} · ${cursor.pointer || '/'}`;
});
editor.onDiagnostics((list) => {
  status.textContent = list.length ? `${list.length} problem(s): ${list[0].message}` : 'No problems';
});
document.getElementById('demo-suggestions').addEventListener('change', (event) => {
  editor.setOption('suggestions', event.target.checked);
});
document.getElementById('demo-format').addEventListener('click', () => editor.format());
document.getElementById('demo-preview').addEventListener('click', () => {
  editor.preview({at: '/nodes/-', values: [
    {id: 'sliceX', filter: 'slice', inputs: {input: 'source'}, options: {normal: 'x+'}},
  ]});
});
document.getElementById('demo-commit').addEventListener('click', () => editor.commitPreview());

const ready = rootVersion ? registry.schemaFor(rootVersion) : Promise.resolve(null);
const nested = kind === 'workflow' ? registry.schemaFor('schemaxis.gmsh/1') : Promise.resolve(null);
window.demo = {editor, registry, ready: false};
Promise.all([ready, nested]).then(() => {
  document.getElementById('demo-schema').textContent = rootVersion ? `schema: ${rootVersion}` : 'no schema';
  window.demo.ready = true;
});
