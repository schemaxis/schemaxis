// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
// Dialogs: the local folder chooser, the filename pattern editor with a live
// preview of what each pattern extracts, and a confirmation prompt.

import {h, icon, iconButton, textButton, clear, fill} from './dom.mjs';
import {browse} from './host.mjs';
import {formatValue} from './names.mjs';
import {captureNames, compileRule, applyRule, slug, exportRules, importRules} from './rules.mjs';

const LAST_DIRECTORY = 'artifact.explorer.lastDirectory';
const PREVIEW_ROWS = 1500;

const EXAMPLES = [
  {name: 'Slice axis and number', pattern: '[sS]lices[._-]([XYZ])[._-]([0-9]+)',
    columns: [{index: 1, key: 'axis', type: 'text'}, {index: 2, key: 'number', type: 'number'}]},
  {name: 'Dot-separated tags', pattern: '-tags-([^-]+)-', columns: [{index: 1, key: 'tags', type: 'tags', separator: '.'}]},
  {name: 'Named groups', pattern: '(?<case>[A-Za-z]+)_(?<step>[0-9]+)', columns: [{index: 2, key: 'step', type: 'number'}]},
  {name: 'Last number in the name', pattern: '([0-9]+(?:\\.[0-9]+)?)\\.[A-Za-z0-9]+$', columns: [{index: 1, key: 'last', type: 'number'}]},
  {name: 'Contains "error"', pattern: 'error', ignoreCase: true, columns: []}
];

function modal(className, onEscape) {
  const dialog = h('div', {class: `dialog ${className}`, role: 'dialog', 'aria-modal': 'true'});
  const backdrop = h('div', {class: 'dialog-backdrop'}, dialog);
  const keydown = function keydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onEscape();
    }
  };
  backdrop.addEventListener('keydown', keydown);
  backdrop.addEventListener('pointerdown', event => {
    if (event.target === backdrop) onEscape();
  });
  document.body.append(backdrop);
  return {dialog, close: () => backdrop.remove()};
}

export function confirmDialog(title, text, confirm = 'OK') {
  return new Promise(resolve => {
    const done = value => {
      close();
      resolve(value);
    };
    const {dialog, close} = modal('', () => done(false));
    const ok = textButton(confirm, () => done(true), {class: 'button primary'});
    dialog.append(h('header', {}, h('h2', {}, title)), h('div', {class: 'body'}, text),
      h('footer', {}, h('div', {class: 'spacer'}), textButton('Cancel', () => done(false)), ok));
    ok.focus();
  });
}

export function folderDialog(app, {replace, recursive}) {
  return new Promise(resolve => {
    const done = value => {
      close();
      resolve(value);
    };
    const {dialog, close} = modal('', () => done(null));
    let current = null, chosen = null;
    const path = h('input', {type: 'text', class: 'mono', 'aria-label': 'Folder path', spellcheck: 'false', onKeydown: event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        go(path.value.trim());
      }
    }});
    const list = h('div', {class: 'folder-list', role: 'listbox'});
    const error = h('div', {class: 'error-text'});
    const subfolders = h('input', {type: 'checkbox', checked: recursive});
    const action = textButton(replace ? 'Open' : 'Add', () => accept(), {class: 'button primary'});
    const label = function label() {
      const target = chosen || current?.directory || '';
      const name = target.split('/').filter(Boolean).at(-1) || target;
      action.textContent = `${replace ? 'Open' : 'Add'} “${name}”`;
    };
    const accept = function accept() {
      const target = chosen || current?.directory;
      if (!target) return;
      try {
        localStorage.setItem(LAST_DIRECTORY, JSON.stringify(current?.directory || target));
      } catch {
        error.textContent = '';
      }
      done({paths: [target], recursive: subfolders.checked});
    };
    const go = async function go(directory) {
      error.textContent = '';
      try {
        current = await browse(directory || undefined);
      } catch (failure) {
        error.textContent = failure.message;
        return;
      }
      chosen = null;
      path.value = current.directory;
      clear(list);
      if (!current.folders.length) list.append(h('div', {class: 'sidebar-note'}, 'No subfolders. Choose this folder with the button below.'));
      for (const folder of current.folders) {
        const row = h('button', {type: 'button', role: 'option', title: 'Double-click to open this folder in the chooser',
          onClick: () => {
            for (const other of list.children) other.classList.remove('chosen');
            row.classList.add('chosen');
            chosen = folder.path;
            label();
          },
          onDblclick: () => go(folder.path)}, icon('folder'), folder.name);
        list.append(row);
      }
      label();
    };
    dialog.append(
      h('header', {}, h('h2', {}, replace ? 'Open folder' : 'Add folder'), iconButton('close', 'Cancel', () => done(null))),
      h('div', {class: 'body'},
        h('div', {class: 'folder-path'}, iconButton('up', 'Parent folder', () => current && go(current.parent)), path),
        list, error,
        h('label', {class: 'check'}, subfolders, 'Show files in subfolders too'),
        h('p', {class: 'note'}, replace ? 'Opening replaces what is shown now. ' : 'Adding keeps what is shown now and appends this folder. ',
          'Files are read in place on this computer; nothing is copied or uploaded.')),
      h('footer', {}, h('div', {class: 'spacer'}), textButton('Cancel', () => done(null)), action));
    let start = null;
    try {
      start = JSON.parse(localStorage.getItem(LAST_DIRECTORY) || 'null');
    } catch {
      start = null;
    }
    go(start).then(() => path.focus());
  });
}

function highlighted(text, match) {
  if (!match) return [text];
  const parts = [];
  const indices = match.indices || [[match.index, match.index + match[0].length]];
  const [start, end] = indices[0];
  const groups = indices.slice(1).filter(Boolean).sort((a, b) => a[0] - b[0]);
  parts.push(text.slice(0, start));
  let cursor = start;
  for (const [a, b] of groups) {
    if (a < cursor) continue;
    parts.push(h('mark', {}, text.slice(cursor, a)), h('mark', {class: 'g'}, text.slice(a, b)));
    cursor = b;
  }
  parts.push(h('mark', {}, text.slice(cursor, end)), text.slice(end));
  return parts;
}

export function patternsDialog(app) {
  return new Promise(resolve => {
    let rules = structuredClone(app.rules);
    let currentId = rules[0]?.id || null;
    let onlyMatches = false;
    const finish = apply => {
      close();
      if (apply) app.setRules(rules);
      resolve(apply);
    };
    const {dialog, close} = modal('wide', () => finish(false));
    const listNode = h('div', {class: 'rule-list'});
    const editor = h('div', {class: 'rule-editor'});
    const fileInput = h('input', {type: 'file', accept: '.json,application/json', hidden: true, onChange: async () => {
      const file = fileInput.files[0];
      fileInput.value = '';
      if (!file) return;
      try {
        const imported = importRules(JSON.parse(await file.text()));
        rules = [...rules, ...imported];
        currentId = imported[0]?.id || currentId;
        render();
      } catch (error) {
        app.toast(error.message, true);
      }
    }});
    const current = () => rules.find(rule => rule.id === currentId) || null;
    const create = template => {
      const rule = {id: `rule-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, name: template?.name || 'New pattern',
        enabled: true, pattern: template?.pattern || '', ignoreCase: !!template?.ignoreCase, target: 'name',
        columns: structuredClone(template?.columns || [])};
      rules.push(rule);
      currentId = rule.id;
      render();
      editor.querySelector('[aria-label="Pattern"]')?.focus();
    };
    const hits = function hits(rule) {
      try {
        const compiled = compileRule(rule);
        return app.collection.items.filter(item => applyRule(compiled, item)).length;
      } catch {
        return null;
      }
    };
    const renderList = function renderList() {
      fill(listNode,
        textButton('New pattern', () => create(), {class: 'button small primary'}),
        h('select', {'aria-label': 'Add an example', onChange: event => {
          const example = EXAMPLES[Number(event.target.value)];
          if (example) create(example);
        }}, h('option', {value: ''}, 'Add an example…'), EXAMPLES.map((example, index) => h('option', {value: index}, example.name))),
        ...rules.map(rule => {
          const count = rule.pattern ? hits(rule) : null;
          return h('div', {class: 'rule-item' + (rule.id === currentId ? ' current' : '') + (rule.enabled ? '' : ' disabled'),
            onClick: () => {
              currentId = rule.id;
              render();
            }},
            h('input', {type: 'checkbox', checked: rule.enabled, title: 'Use this pattern', onClick: event => event.stopPropagation(),
              onChange: event => {
                rule.enabled = event.target.checked;
                renderList();
              }}),
            h('span', {class: 'name'}, rule.name),
            h('span', {class: 'hits'}, count === null ? (rule.pattern ? 'error' : '') : count));
        }),
        rules.length ? null : h('div', {class: 'sidebar-note'}, 'A pattern pulls values out of filenames, which then work like any other property: filter, group, order and play by them.'),
        h('div', {class: 'spacer'}),
        h('div', {class: 'group'},
          textButton('Import…', () => fileInput.click(), {class: 'button small'}),
          textButton('Export', () => {
            const blob = new Blob([JSON.stringify(exportRules(rules), null, 2)], {type: 'application/json'});
            const link = h('a', {href: URL.createObjectURL(blob), download: 'filename-patterns.json'});
            link.click();
            setTimeout(() => URL.revokeObjectURL(link.href), 1000);
          }, {class: 'button small', disabled: !rules.length})),
        fileInput);
    };
    const renderEditor = function renderEditor() {
      const rule = current();
      clear(editor);
      if (!rule) {
        editor.append(h('div', {class: 'empty-state'}, icon('pattern'), 'Create a pattern or start from an example.',
          h('div', {class: 'cheatsheet'}, cheatsheet())));
        return;
      }
      const patternInput = h('input', {type: 'text', class: 'mono', value: rule.pattern, 'aria-label': 'Pattern', spellcheck: 'false',
        placeholder: 'e.g. slice([XYZ])_([0-9]+)', onInput: event => {
          rule.pattern = event.target.value;
          refresh();
        }});
      const error = h('div', {class: 'error-text'});
      const captures = h('div', {class: 'captures'});
      const previewHead = h('div', {class: 'preview-head'});
      const previewWrap = h('div', {class: 'preview-table-wrap'});
      editor.append(
        h('div', {class: 'rule-fields'},
          h('label', {}, 'Name'), h('input', {type: 'text', value: rule.name, 'aria-label': 'Pattern name', onInput: event => {
            rule.name = event.target.value;
            renderList();
            refresh();
          }}),
          h('label', {}, 'Regular expression'), patternInput,
          h('span'), h('div', {class: 'group'},
            h('label', {class: 'check'}, h('input', {type: 'checkbox', checked: rule.ignoreCase, onChange: event => {
              rule.ignoreCase = event.target.checked;
              refresh();
            }}), 'Ignore case'),
            h('label', {class: 'check'}, h('input', {type: 'checkbox', checked: rule.target === 'path', onChange: event => {
              rule.target = event.target.checked ? 'path' : 'name';
              refresh();
            }}), 'Match the folder path too')),
          h('span'), error),
        h('div', {class: 'cheatsheet'}, cheatsheet()),
        captures, previewHead, previewWrap);
      const refresh = function refresh() {
        error.textContent = '';
        patternInput.classList.remove('invalid');
        let compiled = null, preview = null;
        try {
          compiled = rule.pattern ? compileRule(rule) : null;
          preview = rule.pattern ? new RegExp(rule.pattern, 'd' + (rule.ignoreCase ? 'i' : '')) : null;
        } catch (failure) {
          error.textContent = failure.message.replace(/^Invalid regular expression: /, '');
          patternInput.classList.add('invalid');
        }
        renderCaptures(captures, rule, compiled, refresh);
        const items = app.collection.items;
        const rows = [];
        let count = 0;
        for (const item of items) {
          const subject = rule.target === 'path' ? item.path : item.name;
          const hit = compiled ? applyRule(compiled, item) : null;
          if (hit) count++;
          if (onlyMatches && !hit) continue;
          if (rows.length < PREVIEW_ROWS) rows.push({subject, hit, match: hit && preview ? preview.exec(subject) : null});
        }
        rows.sort((a, b) => (b.hit ? 1 : 0) - (a.hit ? 1 : 0));
        const keys = compiled ? (compiled.columns.length ? compiled.columns.map(column => column.key) : [compiled.key]) : [];
        fill(previewHead, h('strong', {}, compiled ? `${count} of ${items.length} files match` : 'Preview'),
          h('label', {class: 'check'}, h('input', {type: 'checkbox', checked: onlyMatches, onChange: event => {
            onlyMatches = event.target.checked;
            refresh();
          }}), 'Only matching files'));
        fill(previewWrap, h('table', {class: 'preview-table'},
          h('thead', {}, h('tr', {}, h('th', {}, rule.target === 'path' ? 'Path' : 'File name'), keys.map(key => h('th', {}, key)))),
          h('tbody', {}, rows.map(row => h('tr', {class: row.hit ? '' : 'miss'},
            h('td', {}, highlighted(row.subject, row.match)),
            keys.map(key => h('td', {}, row.hit && row.hit.values[key] !== undefined ? formatValue(row.hit.values[key]) : '')))))));
        renderListCounts();
      };
      refresh();
    };
    const renderListCounts = function renderListCounts() {
      const rule = current();
      const node = listNode.querySelector('.rule-item.current .hits');
      if (rule && node) {
        const count = rule.pattern ? hits(rule) : null;
        node.textContent = count === null ? (rule.pattern ? 'error' : '') : count;
      }
    };
    const render = function render() {
      renderList();
      renderEditor();
    };
    dialog.append(
      h('header', {}, h('h2', {}, 'Filename patterns'), iconButton('close', 'Close without applying', () => finish(false))),
      h('div', {class: 'body'}, h('div', {class: 'patterns'}, listNode, editor)),
      h('footer', {},
        textButton('Delete pattern', () => {
          rules = rules.filter(rule => rule.id !== currentId);
          currentId = rules[0]?.id || null;
          render();
        }, {class: 'button danger'}),
        h('div', {class: 'spacer'}),
        h('span', {class: 'note'}, 'Extracted values appear under Filters, Group by and Order by.'),
        textButton('Cancel', () => finish(false)),
        textButton('Apply', () => finish(true), {class: 'button primary'})));
    render();
  });
}

function cheatsheet() {
  return ['Parentheses capture a value: ', h('code', {}, '([XYZ])'), ' · named: ', h('code', {}, '(?<axis>[XYZ])'),
    ' · digits ', h('code', {}, '[0-9]+'), ' · letters ', h('code', {}, '[A-Z]+'), ' · anything ', h('code', {}, '.*'),
    ' · a literal dot ', h('code', {}, '\\.'), '. Without parentheses, the matched text itself becomes the value.'];
}

function renderCaptures(host, rule, compiled, refresh) {
  clear(host);
  const captures = captureNames(rule.pattern);
  if (!rule.pattern) return;
  if (!captures.length) {
    host.append(h('div', {class: 'note'}, `No capture groups: matching files get the property “${slug(rule.name)}” with the matched text as its value.`));
    return;
  }
  host.append(h('div', {class: 'note'}, 'Each capture group becomes a property:'));
  for (const capture of captures) {
    let column = (rule.columns || []).find(entry => entry.index === capture.index);
    if (!column) {
      column = {index: capture.index, key: '', type: 'text'};
      rule.columns = [...(rule.columns || []), column];
    }
    const resolved = compiled?.columns.find(entry => entry.index === capture.index);
    host.append(h('div', {class: 'capture-row'},
      h('span', {class: 'idx'}, `$${capture.index}`),
      h('input', {type: 'text', value: column.key, placeholder: resolved?.key || capture.name || 'property name', 'aria-label': `Name for capture ${capture.index}`,
        onChange: event => {
          column.key = event.target.value.trim();
          refresh();
        }}),
      h('select', {'aria-label': `Type for capture ${capture.index}`, onChange: event => {
        column.type = event.target.value;
        refresh();
      }}, [['text', 'Text'], ['number', 'Number'], ['tags', 'List of tags']].map(([value, text]) =>
        h('option', {value, selected: (column.type || 'text') === value}, text))),
      column.type === 'tags' ? h('input', {type: 'text', value: column.separator || '.', 'aria-label': 'Tag separator', title: 'Separator',
        onChange: event => {
          column.separator = event.target.value || '.';
          refresh();
        }}) : h('span')));
  }
}
