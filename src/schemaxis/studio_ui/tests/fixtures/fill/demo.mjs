import {createJsonEditor} from '../../../editor/editor.mjs';
const schema = await (await fetch('../../../../../../docs/generated/paraview.authored.schema.json')).json();
document.documentElement.dataset.theme = new URLSearchParams(location.search).get('theme') || 'light';
const initial = {
  version: 'schemaxis/1',
  nodes: [{id: 'source', filter: 'wavelet'}, {id: 'slice', filter: 'slice',
    inputs: {input: {$fill: 'source', label: 'Data source', type: 'nodeRef', required: true}},
    options: {origin: {$fill: 'origin', label: 'Slice origin', type: 'vector3', required: true}}}],
  settings: {
    count: {$fill: 'count', label: 'Slices per axis', type: 'integer', minimum: 1, maximum: 50, required: true},
    prefix: {$fill: 'prefix', label: 'ID prefix', type: 'id', required: false},
  },
  scenes: [],
};
const catalogue = {functions: {
  boundsCentre: {arguments: {bounds: {type: 'array', minItems: 6, maxItems: 6, required: true}},
    result: {type: 'array', minItems: 3, maxItems: 3}},
  vectorLength: {arguments: {vector: {type: 'array', minItems: 3, maxItems: 3, required: true}}, result: {type: 'number'}},
}, analytics: ['linear', 'values', 'orbit']};
const editor = createJsonEditor(document.getElementById('demo-editor'), {
  schema, value: JSON.stringify(initial, null, 2), getFunctions: async () => catalogue,
});
window.demo = {editor, initial, ready: true};
editor.startFill();
