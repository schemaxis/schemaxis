// Copyright (C) 2026 David L. F. Gaden.
// Read-only selected-element guidance and browsable schema; editing uses the full settings dialog.
import {schemaTree, hierarchyControls} from '../../lib/hierarchy.mjs';
import {conceptHelp, nativeBinding} from './concept-help.mjs';
import {h, mount} from '../../lib/dom.mjs';
import {fieldsAt, valueAt} from './model.mjs';

const typeLabel = field => field.choices.length ? field.choices.join(' | ') : field.type === 'undefined' ? 'value' : field.type;

export function createSelectionGuide({ctx, onReveal}) {
  const element = h('section', {class: 'wb-selection-guide', 'aria-label': 'Selected element guidance'});
  const schemaElement = h('section', {class: 'wb-schema', 'aria-label': 'Selected node schema'});
  return {element, schemaElement, update(schema, documentValue, pointer, operation) {
      const node = valueAt(documentValue, pointer);
      const title = node?.id || (pointer ? pointer.split('/').at(-1) : 'Document');
      const fields = pointer && (node === null || typeof node !== 'object')
        ? fieldsAt(schema, documentValue, pointer.slice(0, pointer.lastIndexOf('/'))).filter(field => field.pointer === pointer)
        : fieldsAt(schema, documentValue, pointer);
      const groups = [{label: title, pointer, fields: fields.filter(field => !['options', 'inputs'].includes(field.name))}];
      for (const name of ['inputs', 'options']) {
        const field = fields.find(field => field.name === name);
        if (field) groups.push({label: name === 'inputs' ? 'Inputs' : 'Options', pointer: field.pointer,
          fields: fieldsAt(schema, documentValue, field.pointer)});
      }
      mount(element, h('h3', {class: 'wb-section-title'}, title),
        h('button', {class: 'wb-pointer mono', onClick: () => onReveal(pointer)}, pointer || '/'),
        operation?.schema?.description ? h('p', {class: 'wb-help'}, operation.schema.description) : null,
        groups.map(group => h('details', {open: group.label === 'Options'}, h('summary', {}, group.label),
          group.fields.map(field => h('details', {class: 'wb-guide-field'},
            h('summary', {}, field.schema.title || field.name, field.required ? ' *' : ''),
            nativeBinding(field.schema['x-studio-guide']),
            field.schema.description ? h('p', {class: 'wb-help'}, field.schema.description) : null,
            field.schema['x-studio-guide'] ? conceptHelp(field.schema['x-studio-guide'], field.name, ctx,
              {shown: field.schema.description}) : null,
            h('p', {class: 'wb-help'}, `Type: ${typeLabel(field)}${field.schema.default === undefined ? '' : ` · Default: ${JSON.stringify(field.schema.default)}`}`))))));
      const schemaBody = h('div', {class: 'wb-schema-body'});
      const search = h('input', {class: 'input', type: 'search', 'aria-label': 'Search schema', placeholder: 'Search selected schema…',
        onInput: () => {
          for (const row of schemaBody.children) { row.hidden = !row.textContent.toLowerCase().includes(search.value.toLowerCase());
            if (!row.hidden && search.value) row.querySelectorAll('details').forEach(item => { item.open = true; }); }
        }});
      const serialized = JSON.stringify(Object.fromEntries(groups.flatMap(g => g.fields).map(f => [f.name, f.schema])), null, 2);
      mount(schemaElement, h('div', {class: 'operation-file-tools'}, search,
        h('button', {class: 'button small', onClick: () => { const range = document.createRange(); range.selectNodeContents(schemaBody);
          const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); }}, 'Select all'),
        h('button', {class: 'button small', onClick: () => ctx.call(() => navigator.clipboard.writeText(serialized))}, 'Copy schema')),
        hierarchyControls(schemaBody), schemaBody);
      mount(schemaBody, h('div', {class: 'wb-schema-heading'},
        h('h3', {}, `${title} schema`), h('p', {class: 'wb-help'},
          'Select a pipeline node or document section to browse its properties. Required fields are marked *.')),
      ...groups.flatMap((group) => group.fields).map((field) => h('details', {class: 'wb-schema-row'},
        h('summary', {}, h('span', {class: 'mono'}, field.pointer),
          h('span', {class: 'badge'}, typeLabel(field)), field.required ? ' *' : ''),
        field.schema.description ? h('p', {}, field.schema.description) : null,
        schemaTree(field.schema, 'Definition'))));
    }};
}
