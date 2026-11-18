// Copyright (C) 2026 David L. F. Gaden.
// Plugin-shaped library fixture for whole-input replacement review: templates,
// root snippets, a root+append composite, a root merge and an ordinary append.
import {createJsonEditor} from '../../../editor/editor.mjs';
import {createLibrary} from '../../../windows/workbench/library.mjs';
import {Commands, openPalette} from '../../../shell/palette.mjs';

const format = new URLSearchParams(location.search).get('format') === 'yaml' ? 'yaml' : 'json';
const initial = {version: 'fixture/1', label: 'Ünïcode — café', settings: {level: 1}, nodes: [{id: 'keep', filter: 'source'}]};
const source = format === 'yaml'
  ? '# authored note\nversion: fixture/1\nlabel: Ünïcode — café # keep label\nsettings:\n  level: 1\nnodes:\n  - id: keep\n    filter: source\n'
  : JSON.stringify(initial, null, 2) + '\n';
const metadata = {id: 'fixture', categories: [{id: 'general', title: 'General', icon: 'layers'}],
  templates: [{id: 'starter', title: 'Starter template', description: 'Begin from a fresh input.', fields: {},
    document: {version: 'fixture/2', nodes: [{id: 'fresh', filter: 'source'}]}}],
  snippets: [
    {id: 'reset', title: 'Reset document', category: 'general', description: 'Replace with an empty input.', fields: {},
      inserts: [{at: '', values: [{version: 'fixture/1', nodes: []}]}]},
    {id: 'compose', title: 'Compose and add', category: 'general', complexity: 'composite', fields: {},
      inserts: [{at: '', values: [{version: 'fixture/1', nodes: []}]}, {at: '/nodes/-', values: [{id: 'added', filter: 'source'}]}]},
    {id: 'tune', title: 'Tune settings', category: 'general', fields: {}, inserts: [{at: '', merge: {settings: {level: 2}}}]},
    {id: 'append', title: 'Append node', category: 'general', fields: {},
      inserts: [{at: '/nodes/-', values: [{id: 'café', filter: 'source'}]}]},
  ]};
const editor = createJsonEditor(document.getElementById('editor'), {value: source, format});
const errors = [];
const commands = new Commands();
const library = createLibrary({ctx: {call: async (action) => {
  try {
    return await action();
  } catch (error) {
    errors.push(error.message);
    return undefined;
  }
}}, editor, getDocument: () => editor.getDocument()});
document.getElementById('bar').append(library.bar, library.section);
document.getElementById('library').append(library.element);
library.update(metadata);
library.registerCommands(commands);
document.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    openPalette({commands, role: 'dev'});
  }
});
window.replaceDemo = {editor, library, commands, errors, metadata, source, format, createJsonEditor};
