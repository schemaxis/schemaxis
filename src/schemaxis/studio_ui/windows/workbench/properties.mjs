// Forms and browsable schema built from the selected node's actual authored schema.

import {conceptHelp, nativeBinding} from './concept-help.mjs';
import {h, mount} from '../../lib/dom.mjs';
import {fieldsAt, parseField, valueAt} from './model.mjs';
import {selectLine} from './line-selector.mjs';
import {inputBrowser} from './input-browser.mjs';
import {referenceControl} from './pipeline-picker.mjs';
import {blockControl} from './block-picker.mjs';
import {openDialog} from '../../shell/dialog.mjs';
import {dependentNodes} from './pipeline-edit.mjs';

function valueText(field) {
  if (field.value === undefined) {
    return '';
  }
  return typeof field.value === 'object' ? JSON.stringify(field.value) : String(field.value);
}

function typeLabel(field) {
  return field.choices.length ? field.choices.join(' | ') : field.type === 'undefined' ? 'value' : field.type;
}

export function createProperties({ctx, onEdit, onReveal, onFillRequired, getSpatialContext, getDocument, getOperationKinds}) {
  const element = h('section', {class: 'wb-properties'});
  const schemaElement = h('section', {class: 'wb-schema', 'aria-label': 'Selected node schema'});
  let currentDocument;

  function control(field) {
    if (field.schema['x-studio-reference']) {
      const owner = field.pointer.split('/inputs/')[0];
      const node = valueAt(currentDocument, owner);
      const scope = valueAt(currentDocument, owner.replace(/\/nodes\/\d+$/, '')) || currentDocument;
      const excluded = dependentNodes(scope, node?.id);
      const picker = referenceControl({documentValue: {...scope,
        nodes: scope.nodes?.filter(item => !excluded.has(item?.id))},
        reference: field.schema['x-studio-reference'], initial: field.value, label: field.pointer,
        kinds: getOperationKinds?.(), allowPort: JSON.stringify(field.schema).includes('"port"') || JSON.stringify(field.schema).includes('dataReference'),
        onChange: value => { if (value !== undefined) onEdit(field.pointer, value); }});
      return h('div', {class: 'wb-property'}, h('span', {class: 'wb-property-label'}, field.schema.title || field.name), picker.element);
    }
    if (field.schema['x-studio-control']?.kind === 'blocks') {
      const snapshot = currentDocument, owner = field.pointer.split('/options/')[0], node = valueAt(snapshot, owner);
      const scope = valueAt(snapshot, owner.replace(/\/nodes\/\d+$/, '')) || snapshot;
      return h('div', {class: 'wb-property'}, h('span', {class: 'wb-property-label'}, field.schema.title || field.name),
        h('small', {}, Array.isArray(field.value) ? `${field.value.length} block selections` : 'No blocks selected'),
        h('button', {class: 'button small', onClick: () => ctx.call(async () => {
          const picker = blockControl({initial: field.value, getInput: () => node?.inputs?.[field.schema['x-studio-control'].input],
            inspect: async source => {
              const provider = ctx.store.get().adaptors.find(adaptor => adaptor.routes.includes(scope.version))?.id;
              const request = await ctx.api.post('/api/inspect-input', {provider, input: scope,
                node: typeof source === 'string' ? source : source.node, port: source.port || 0});
              return (await ctx.api.waitForJob(request.job)).result;
            }});
          const result = await openDialog({title: 'Choose blocks to extract', wide: true, content: picker.element,
            actions: [{label: 'Cancel', run: () => null}, {label: 'Use selected blocks', primary: true, run: () => picker.read().length ? picker.read() : false}]});
          if (result) {
            if (JSON.stringify(getDocument()) !== JSON.stringify(snapshot)) throw Error('The pipeline changed. Reopen the block chooser.');
            onEdit(field.pointer, result);
          }
        }, {title: 'Could not choose blocks'})}, 'Choose blocks…'));
    }
    const choices = field.type === 'boolean' ? [true, false] : field.choices;
    const input = choices.length && (field.value === undefined || typeof field.value !== 'object')
      ? h('select', {class: 'input', 'aria-label': field.pointer},
        field.value === undefined ? h('option', {value: ''}, 'Not set') : null,
        choices.map((value) => h('option', {value: JSON.stringify(value), selected: value === field.value},
          String(value))))
      : h(field.type === 'object' || field.type === 'array' ? 'textarea' : 'input', {
        class: ['input', (field.type === 'object' || field.type === 'array') && 'mono'],
        value: valueText(field), 'aria-label': field.pointer, rows: 2,
        placeholder: field.schema.default !== undefined ? JSON.stringify(field.schema.default) : 'Not set',
      });
    input.addEventListener('change', () => ctx.call(async () => {
      const value = choices.length && input.tagName === 'SELECT'
        ? JSON.parse(input.value) : parseField(input.value, field);
      onEdit(field.pointer, value);
    }, {title: `Could not change ${field.name}`}));
    return h('div', {class: 'wb-property'},
      h('span', {class: 'wb-property-label'}, field.schema.title || field.name,
        field.required ? h('span', {class: 'wb-required', title: 'Required'}, ' *') : null), input, nativeBinding(field.schema['x-studio-guide']),
      field.schema.description ? h('small', {class: 'wb-help'}, field.schema.description) : null,
      field.schema['x-studio-file'] && field.type === 'string' ? inputBrowser(ctx, input, field.pointer, field.schema['x-studio-file'].extensions) : null,
      field.schema['x-studio-guide'] ? h('details', {}, h('summary', {}, 'Conceptual help'), conceptHelp(field.schema['x-studio-guide'], field.name, ctx)) : null);
  }

  function groupForm(group) {
    const fields = group.fields.filter((field) => !['nodes', 'scenes', 'components', '$defs'].includes(field.name));
    const primary = fields.filter((field) => field.value !== undefined || field.required);
    const optional = fields.filter((field) => field.value === undefined && !field.required);
    const missing = fields.filter((field) => field.required && field.value === undefined);
    const pointer = group.pointer || '';
    return h('fieldset', {}, h('legend', {}, group.label), missing.length && onFillRequired
      ? h('button', {class: 'button small', onClick: () => onFillRequired(pointer)}, 'Fill required properties') : null,
    primary.map(control), optional.length
      ? h('details', {class: 'wb-optional'}, h('summary', {}, `Additional properties (${optional.length})`),
        optional.map(control)) : null);
  }

  return {element, schemaElement,
    update(schema, documentValue, pointer) {
      currentDocument = documentValue;
      const node = valueAt(documentValue, pointer);
      const title = node?.id || (pointer ? pointer.split('/').at(-1) : 'Document');
      const fields = pointer && (node === null || typeof node !== 'object')
        ? fieldsAt(schema, documentValue, pointer.slice(0, pointer.lastIndexOf('/'))).filter(field => field.pointer === pointer)
        : fieldsAt(schema, documentValue, pointer);
      const groups = [{label: title, pointer, fields: fields.filter((field) => !['options', 'inputs'].includes(field.name))}];
      const inputs = fields.find(field => field.name === 'inputs');
      if (inputs) groups.push({label: 'Inputs', pointer: inputs.pointer, fields: fieldsAt(schema, documentValue, inputs.pointer)});
      const options = fields.find((field) => field.name === 'options');
      if (options) {
        const nested = fieldsAt(schema, documentValue, options.pointer);
        groups.push({label: 'Options', pointer: options.pointer, fields: nested.length ? nested : [options]});
      }
      mount(element, h('h3', {class: 'wb-section-title'}, 'Properties'),
        h('button', {class: 'wb-pointer mono', onClick: () => onReveal(pointer)}, pointer || '/'),
        options?.schema['x-studio-control']?.kind === 'line' ? h('button', {class: 'button small', onClick: () => ctx.call(async () => {
          const widget = options.schema['x-studio-control'];
          const result = await selectLine({start: node?.options?.[widget.start], end: node?.options?.[widget.end], getContext: getSpatialContext});
          if (!result) return;
          if (getDocument && getDocument() !== documentValue) throw Error('The input changed while placing endpoints. Reopen the selector.');
          onEdit(options.pointer, {...node?.options, [widget.start]: result.start, [widget.end]: result.end});
        }, {title: 'Could not place line'})}, 'Place line endpoints…') : null,
        ...groups.map(groupForm),
        !documentValue ? h('p', {class: 'wb-help'}, 'Repair JSON syntax to edit properties.') : null);
      mount(schemaElement, h('div', {class: 'wb-schema-heading'},
        h('h3', {}, `${title} schema`), h('p', {class: 'wb-help'},
          'Select a pipeline node or document section to browse its properties. Required fields are marked *.')),
      ...groups.flatMap((group) => group.fields).map((field) => h('details', {class: 'wb-schema-row'},
        h('summary', {}, h('span', {class: 'mono'}, field.pointer),
          h('span', {class: 'badge'}, typeLabel(field)), field.required ? ' *' : ''),
        field.schema.description ? h('p', {}, field.schema.description) : null,
        h('pre', {class: 'mono'}, JSON.stringify(field.schema, null, 2)))));
    }};
}
