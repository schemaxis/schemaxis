// Copyright (C) 2026 David L F Gaden
import {createJsonEditor} from '../../../editor/editor.mjs';
import {createLibrary} from '../../../windows/workbench/library.mjs';
import {Commands, openPalette} from '../../../shell/palette.mjs';

const initial = {version: 'schemaxis/1', nodes: [{id: 'source', filter: 'pvWavelet'}],
  scenes: [{id: 'main', visible: {source: {opacity: 1}}}]};
const item = {id: 'xyz-slices', title: 'X, Y and Z slice arrays', category: 'slicing', icon: 'layers',
  description: 'Three orthogonal slices, a shared axis and scene visibility.', complexity: 'composite',
  fields: {source: {label: 'Data source', type: 'nodeRef', required: true},
    count: {label: 'Slices per axis', type: 'integer', minimum: 1, maximum: 50, required: true},
    prefix: {label: 'ID prefix', type: 'id', default: 'cut'}}, inserts: [
    {at: '/nodes/-', values: ['X', 'Y', 'Z'].map((axis) => ({id: '${prefix}' + axis, filter: 'slice',
      inputs: {input: {$fill: 'source'}}, options: {normal: axis.toLowerCase() + '+'}}))},
    {at: '/axes/-', values: [{name: 'height', values: [{$fill: 'count'}]}]},
    {at: '/scenes/0/visible', merge: {source: {opacity: 0.6}, cutX: {}, cutY: {}, cutZ: {}}},
  ]};
const editor = createJsonEditor(document.getElementById('editor'), {value: JSON.stringify(initial, null, 2)});
const errors = [];
const commands = new Commands();
const library = createLibrary({ctx: {call: async (action) => { try { await action(); } catch (error) {
  errors.push(error.message);
} }}, editor, getDocument: () => JSON.parse(editor.getValue())});
document.getElementById('bar').append(library.bar);
document.getElementById('library').append(library.element);
library.update({id: 'paraview', categories: [{id: 'slicing', title: 'Slicing & clipping', icon: 'layers'},
  {id: 'sources', title: 'Sources', icon: 'adaptor'}], templates: [], snippets: [item,
  {id: 'wavelet', title: 'Wavelet source', category: 'sources', description: 'Add a procedural volume.', fields: {},
    inserts: [{at: '/nodes/-', values: [{id: 'source', filter: 'pvWavelet'}]}]}]});
library.registerCommands(commands);
document.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    openPalette({commands, role: 'dev'});
  }
});
window.libraryDemo = {editor, library, initial, errors, commands};
