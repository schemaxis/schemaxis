// Copyright (C) 2026 David L F Gaden
import {parse, documentValue} from '../../editor/json-parse.mjs';
import {dumpYaml} from '../../editor/yaml-parse.mjs';
// Designer dialogs: new operation, template export, rename and confirmation helpers.

import {h, icon, mount} from '../../lib/dom.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {avatar, identity} from '../../shell/providers.mjs';
import {uniqueId} from './geometry.mjs';
import {expandFields, markers} from '../../editor/insert-fields.mjs';
import {templateGallery} from '../template-gallery.mjs';

export const ID_PATTERN = /^[A-Za-z][A-Za-z0-9_-]*$/;
export const TEMPLATE_ID_PATTERN = /^[A-Za-z][A-Za-z0-9_.-]*$/;

function pretty(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

/** Validate a new operation ID; returns an error message or ''. */
export function operationIdError(value, existing) {
  if (!value) {
    return 'Enter an instance ID.';
  }
  if (!ID_PATTERN.test(value)) {
    return 'Start with a letter; use letters, digits, - or _.';
  }
  if (existing.includes(value)) {
    return 'Another operation already uses this ID.';
  }
  return '';
}

function faultText(fault) {
  const location = fault.location ? ` (${fault.location})` : '';
  return `${fault.message || fault.code}${location}`;
}

/**
 * Ask for an instance ID and starting document, then add the operation.
 * Server faults (for example an empty document that does not plan) stay inside the dialog.
 */
export async function newOperationDialog(ctx, model, adaptorId, position) {
  const adaptor = ctx.adaptor(adaptorId);
  if (!adaptor) {
    ctx.notify.warn('Unknown adaptor', {body: `No adaptor "${adaptorId}" is registered.`});
    return null;
  }
  const info = identity(adaptorId);
  const existing = (model.store.get().projection?.nodes || []).map((node) => node.id);
  const idInput = h('input', {class: 'input', name: 'id', value: uniqueId(adaptorId, existing),
    'aria-describedby': 'dz-new-id-hint', autocomplete: 'off', spellcheck: 'false'});
  const idError = h('div', {class: 'error-text', role: 'alert'});
  const start = h('select', {class: 'select', name: 'start'},
    h('option', {value: ''}, 'Empty document'),
    (adaptor.templates || []).map((template) => h('option', {value: template.id}, template.title)));
  const source = h('textarea', {class: 'textarea mono dz-json-input', rows: '10', spellcheck: 'false',
    'aria-label': 'Operation document source'});
  source.value = pretty(adaptor.emptyDocument || {version: adaptor.version});
  let syntax = 'json';
  const sourceFormat = h('select', {'aria-label': 'Operation source format', onChange: event => {
    const ast = parse(source.value, syntax);
    if (ast.diagnostics.length) { event.target.value = syntax; return; }
    syntax = event.target.value;
    const value = documentValue(ast);
    source.value = syntax === 'yaml' ? dumpYaml(value) : pretty(value);
  }}, h('option', {value: 'json'}, 'JSON'), h('option', {value: 'yaml'}, 'YAML'));
  const present = value => syntax === 'yaml' ? dumpYaml(value) : pretty(value);
  const sourceError = h('div', {class: 'error-text', role: 'alert'});
  const templateHint = h('div', {class: 'hint'}, 'The starting document of this operation. Edit it here, or later '
    + 'in the Adaptor Workbench. The design validates it immediately.');

  start.addEventListener('change', async () => {
    sourceError.textContent = '';
    if (!start.value) {
      source.value = present(adaptor.emptyDocument || {version: adaptor.version});
      return;
    }
    const studio = await ctx.call(() => ctx.api.get('/api/studio/adaptor', {id: adaptorId}),
      {title: 'Starter templates unavailable'});
    const template = studio && studio.templates.find((item) => item.id === start.value);
    if (template) {
      source.value = present(expandFields(template.document, template.fields || {}));
    }
  });
  idInput.addEventListener('input', () => {
    idError.textContent = operationIdError(idInput.value.trim(), existing);
    idInput.setAttribute('aria-invalid', String(Boolean(idError.textContent)));
  });

  const content = h('div', {class: 'dz-dialog-grid'},
    h('div', {class: 'dz-dialog-adaptor'}, avatar(adaptorId, {large: true}),
      h('div', {}, h('div', {class: 'title'}, info.name), h('div', {class: 'subtitle'}, adaptor.scope || ''))),
    h('div', {class: 'dz-two'},
      h('div', {class: 'field'}, h('label', {}, 'Instance ID'), idInput,
        h('div', {class: 'hint', id: 'dz-new-id-hint'}, 'Unique within the design. Letters, digits, - and _.'),
        idError),
      h('div', {class: 'field'}, h('label', {}, 'Start from'), start)),
    templateGallery(start, adaptor.templates || []).element,
    h('div', {class: 'field'}, h('label', {}, 'Document'), sourceFormat, source, templateHint, sourceError));

  return openDialog({
    title: `New ${info.name} operation`,
    wide: true,
    content,
    initialFocus: 'input[name="id"]',
    actions: [
      {label: 'Cancel', run: () => null},
      {label: 'Add operation', primary: true, run: async () => {
        const id = idInput.value.trim();
        const problem = operationIdError(id, existing);
        if (problem) {
          idError.textContent = problem;
          idInput.focus();
          return false;
        }
        let document;
        try {
          const ast = parse(source.value, syntax);
          if (ast.diagnostics.length) throw Error(ast.diagnostics[0].message);
          document = documentValue(ast);
        } catch (error) {
          sourceError.textContent = `Not valid ${syntax.toUpperCase()}: ${error.message}`;
          return false;
        }
        const result = await model.action('add_operation', {id, document, position}, {quiet: true});
        if (!result) {
          return false;
        }
        if (result.fault) {
          sourceError.textContent = `The design rejected this document: ${faultText(result.fault)}`;
          return false;
        }
        model.select({kind: 'nodes', ids: [id]});
        ctx.notify.ok(`Added ${id}`, {body: `${info.name} operation added to the design.`});
        if (markers(document).length) {
          await ctx.windows.open('workbench', {document: model.documentId, operation: id, fill: true});
        }
        return id;
      }},
    ],
  });
}

/** Export the design as a template bundle; shows the written paths. */
export async function exportTemplateDialog(ctx, model) {
  const name = model.store.get().name || 'design';
  const slug = uniqueId(name.toLowerCase(), []);
  const workspace = (ctx.store.get().server && ctx.store.get().server.workspace) || '';
  const directory = h('input', {class: 'input mono', name: 'directory',
    value: workspace ? `${workspace}/templates/${slug}` : `templates/${slug}`, spellcheck: 'false'});
  const templateId = h('input', {class: 'input', name: 'templateId', value: slug, spellcheck: 'false'});
  const title = h('input', {class: 'input', name: 'title', value: name});
  const error = h('div', {class: 'error-text', role: 'alert'});
  const result = h('div');
  let done = false;
  const content = h('div', {class: 'dz-dialog-grid'},
    h('p', {class: 'secondary-text'}, 'Writes template.json, workflow.json and cases/example.json into a new or '
      + 'empty directory. Exposed unfinished fields remain in the example case for the user to fill. '
      + 'Cases with supplied values are checked by binding.'),
    h('div', {class: 'field'}, h('label', {}, 'Directory'), directory),
    h('div', {class: 'dz-two'},
      h('div', {class: 'field'}, h('label', {}, 'Template ID'), templateId),
      h('div', {class: 'field'}, h('label', {}, 'Title'), title)),
    error, result);
  return openDialog({
    title: 'Export template',
    content,
    actions: [
      {label: 'Close', run: () => null},
      {label: 'Export', primary: true, run: async (close) => {
        if (done) {
          close(true);
          return true;
        }
        error.textContent = '';
        if (!TEMPLATE_ID_PATTERN.test(templateId.value.trim())) {
          error.textContent = 'Template IDs start with a letter and use letters, digits, ., - or _.';
          return false;
        }
        const response = await model.action('export_template', {directory: directory.value.trim(),
          templateId: templateId.value.trim(), title: title.value.trim() || templateId.value.trim()}, {quiet: true});
        if (!response) {
          return false;
        }
        if (response.fault) {
          error.textContent = faultText(response.fault);
          return false;
        }
        const written = response.export;
        const needsValues = written.requiresValues?.length;
        mount(result, h('div', {class: 'dz-export-result'},
          h('div', {class: 'dz-export-ok'}, icon('check'), `Template ${written.id} revision ${written.revision} `
            + (needsValues ? 'exported · fill the example case before planning' : 'exported and verified')),
          h('dl', {class: 'kv'},
            h('dt', {}, 'Template'), h('dd', {class: 'mono'}, written.template),
            h('dt', {}, 'Workflow'), h('dd', {class: 'mono'}, written.workflow),
            h('dt', {}, 'Example case'), h('dd', {class: 'mono'}, written.case),
            h('dt', {}, 'Digest'), h('dd', {class: 'mono'}, written.digest.slice(0, 23)))));
        ctx.notify.ok('Template exported', {body: written.directory});
        done = true;
        const primary = content.closest('.dialog').querySelector('.dialog-footer .button.primary');
        primary.textContent = 'Done';
        return false;
      }},
    ],
  });
}

/** Ask for a new ID (rename / duplicate). Returns the ID or null. */
export async function idDialog({title, label, value, existing, confirm}) {
  const input = h('input', {class: 'input', name: 'id', value, spellcheck: 'false', autocomplete: 'off'});
  const error = h('div', {class: 'error-text', role: 'alert'});
  return openDialog({
    title,
    content: h('div', {class: 'field'}, h('label', {}, label), input, error),
    actions: [
      {label: 'Cancel', run: () => null},
      {label: confirm, primary: true, run: () => {
        const problem = operationIdError(input.value.trim(), existing);
        if (problem) {
          error.textContent = problem;
          return false;
        }
        return input.value.trim();
      }},
    ],
  });
}
