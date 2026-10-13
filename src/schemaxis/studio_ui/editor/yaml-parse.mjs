// YAML 1.2 source adapter. The shared schema/pointer services consume this AST.
import {parseAllDocuments, isMap, isSeq, isAlias, stringify} from './vendor/yaml.mjs';

export function parseYaml(text) {
  const documents = parseAllDocuments(text, {version: '1.2', schema: 'core', uniqueKeys: true, keepSourceTokens: true});
  const doc = documents[0];
  if (doc?.directives?.yaml?.version && doc.directives.yaml.version !== '1.2') doc.errors.push({message: 'Only YAML 1.2 is supported', pos: [0, 1]});
  const diagnostics = (doc?.errors || []).map(error => ({from: error.pos?.[0] || 0,
    to: error.pos?.[1] || 1, message: error.message, severity: 'error'}));
  const report = (node, message) => diagnostics.push({from: node?.range?.[0] || 0,
    to: node?.range?.[1] || 1, message, severity: 'error'});
  for (const match of text.matchAll(/^%[^\n]*/gm)) {
    if (!/^%YAML\s+1\.2(?:\s*(?:#.*)?)?$/.test(match[0])) diagnostics.push({from: match.index,
      to: match.index + match[0].length, message: 'Only the YAML 1.2 version directive is supported', severity: 'error'});
  }
  if (documents.length !== 1) report(null, 'Use exactly one YAML document');
  let budget = 100000;
  function convert(node, depth = 0) {
    if (--budget < 0 || depth > 128) { report(node, 'Document limit exceeded'); return null; }
    const from = node?.range?.[0] || 0, to = node?.range?.[1] ?? from;
    const common = {from, to, closed: true};
    if (node?.tag || node?.anchor || isAlias(node)) report(node, 'Tags, anchors and aliases are not supported');
    if (isMap(node)) return {...common, type: 'object', members: node.items.map(pair => {
      if (typeof pair.key?.value !== 'string') report(pair.key, 'Mapping keys must be strings');
      if (pair.key?.value === '<<') report(pair.key, 'Merge keys are not supported');
      const key = {...convert(pair.key, depth+1), value: String(pair.key?.value ?? ''),
        quoted: /^['"]/.test(text.slice(pair.key?.range?.[0] || 0)), closed: true};
      const value = convert(pair.value, depth+1);
      const colon = text.indexOf(':', key.to);
      return {key, value, colon, from: key.from, to: value?.to ?? key.to};
    })};
    if (isSeq(node)) return {...common, type: 'array', items: node.items.map(item => convert(item, depth+1))};
    const value = node?.value ?? null;
    if (typeof value === 'number' && !Number.isFinite(value)) report(node, 'Numbers must be finite');
    return {...common, type: typeof value === 'string' ? 'string' : typeof value === 'number' ? 'number' : 'literal', value};
  }
  const root = doc ? convert(doc.contents) : null;
  return {text, format: 'yaml', yamlDocument: doc, root, diagnostics};
}

export function yamlPointerAt(ast, offset) {
  const esc = key => String(key).replace(/~/g, '~0').replace(/\//g, '~1');
  function visit(node, pointer, parentPointer = null) {
    if (node?.type === 'object') {
      const keys = node.members.map(member => member.key.value);
      for (const member of node.members) {
        const path = pointer + '/' + esc(member.key.value);
        if (offset >= member.key.from && offset <= member.key.to) return {position: 'key', pointer: path,
          parentPointer: pointer, keyPrefix: ast.text.slice(member.key.from + (member.key.quoted ? 1 : 0), offset),
          range: {from: member.key.from, to: member.key.to}, hasColon: member.colon >= 0,
          node: member.value, existingKeys: keys.filter(key => key !== member.key.value)};
        const newline = ast.text.indexOf('\n', member.colon);
        if ((!member.value || member.value.from === 0 && member.value.to === 0) && offset > member.colon
            && offset <= (newline < 0 ? ast.text.length : newline)) return {position: 'value', pointer: path,
          parentPointer: pointer, range: {from: offset, to: offset}, valuePrefix: '', node: null};
        if (member.value && offset >= member.value.from && offset <= member.value.to) return visit(member.value, path, pointer);
      }
      return {position: 'key', pointer: null, parentPointer: pointer, keyPrefix: '',
        range: {from: offset, to: offset}, hasColon: false, node: null, existingKeys: keys};
    }
    if (node?.type === 'array') {
      for (let i = 0; i < node.items.length; i++) {
        const item = node.items[i];
        if (item && offset >= item.from && offset <= item.to) return visit(item, `${pointer}/${i}`, pointer);
      }
      return {position: 'value', pointer: `${pointer}/${node.items.length}`, parentPointer: pointer,
        range: {from: offset, to: offset}, valuePrefix: '', node: null};
    }
    return {position: 'value', pointer, parentPointer, range: {from: node?.from ?? offset, to: node?.to ?? offset},
      valuePrefix: ast.text.slice(node?.from ?? offset, offset), node};
  }
  return visit(ast.root, '');
}

export function yamlInsert(ast, pointer, values, options = {}) {
  if (ast.diagnostics.length) throw Error('Repair YAML syntax before structured editing');
  const doc = ast.yamlDocument.clone();
  const segments = pointer ? pointer.slice(1).split('/').map(s => s.replace(/~1/g, '/').replace(/~0/g, '~')) : [];
  const last = segments.pop();
  const parent = doc.getIn(segments, true);
  if (isSeq(parent)) {
    const at = last === '-' ? parent.items.length : Number(last);
    if (!Number.isInteger(at) || at < 0 || at > parent.items.length) throw Error('Invalid array index');
    parent.items.splice(at, 0, ...values.map(value => doc.createNode(value)));
  } else if (last === undefined) doc.contents = doc.createNode(values[0]);
  else {
    const old = doc.getIn([...segments, last], true);
    const replacement = doc.createNode(values[0]);
    if (old) { replacement.comment = old.comment; replacement.commentBefore = old.commentBefore; }
    doc.setIn([...segments, last], replacement);
  }
  const text = yamlRender(ast, doc.toJS(), options.indent || '  ');
  return {from: 0, to: ast.text.length, text, select: {from: 0, to: text.length}};
}

export function dumpYaml(value) {
  return stringify(value, {version: '1.2', schema: 'core'});
}

export function yamlRender(ast, value, indent = '  ') {
  if (ast.diagnostics.length) throw Error('Repair YAML syntax before structured editing');
  const doc = ast.yamlDocument.clone();
  function update(node, value) {
    if (isMap(node) && value && typeof value === 'object' && !Array.isArray(value)) {
      for (const pair of [...node.items]) if (!Object.hasOwn(value, pair.key.value)) node.delete(pair.key.value);
      for (const [key, child] of Object.entries(value)) {
        if (node.has(key)) node.set(key, update(node.get(key, true), child));
        else node.set(key, doc.createNode(child));
      }
      return node;
    }
    if (isSeq(node) && Array.isArray(value)) {
      const identities = new Map(node.items.filter(isMap).map(item => [item.get('id'), item]).filter(([id]) => typeof id === 'string'));
      node.items = value.map((item, index) => update(item && typeof item === 'object' && !Array.isArray(item)
        ? identities.get(item.id) || node.items[index] : node.items[index], item));
      return node;
    }
    if (node && !isMap(node) && !isSeq(node) && (value === null || typeof value !== 'object')) {
      node.value = value;
      return node;
    }
    const replacement = doc.createNode(value);
    if (node) { replacement.comment = node.comment; replacement.commentBefore = node.commentBefore; }
    return replacement;
  }
  doc.contents = update(doc.contents, value);
  return doc.toString({indent: indent.length});
}
