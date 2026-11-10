import assert from 'node:assert/strict';
import {test} from 'node:test';
import {entries, scopes, reference, saveEntry, removeEntry, preview} from '../windows/variables/model.mjs';

const root = () => ({version: 'schemaxis.workflow-design/2', workflow: {version: 'schemaxis.workflow/1',
  dimensions: {distance: 10}, operations: [
    {id: 'a', document: {version: 'schemaxis.freecad/1', dimensions: {distance: 2}}},
    {id: 'b', document: {version: 'schemaxis.blender/1'}}]}, parameters: {}});

test('scope-aware references distinguish shared and operation-local names', () => {
  const document = root(), [shared, local] = entries(document), [, a, b] = scopes(document);
  assert.deepEqual(reference(shared, b), {$document: '/dimensions/distance', scope: 'workflow'});
  assert.deepEqual(reference(local, b), {$document: '/dimensions/distance', operation: 'a'});
  assert.equal(preview(document, reference(shared, b), b), 10);
  assert.equal(preview(document, reference(local, a), a), 2);
});

test('creation is immutable, rejects collisions, and declares parameters before operations', () => {
  const document = root(); document.workflow.operations = [];
  const result = saveEntry(document, {base: '/workflow', group: 'settings', name: 'gap', value: 3.5,
    parameter: true, units: 'mm', help: 'Clearance'});
  assert.equal(document.workflow.settings, undefined);
  assert.equal(result.parameters.gap.kind, 'number');
  assert.deepEqual(result.parameters.gap.target, {scope: 'workflow', pointer: '/settings/gap'});
  assert.throws(() => saveEntry(result, {base: '/workflow', group: 'settings', name: 'gap', value: 4}), /exists/);
  assert.throws(() => saveEntry(result, {base: '/workflow', group: 'settings', name: 'bad', value: {$expr: {}}, parameter: true}), /literal/);
});

test('deletion protects shared references and parameters; preview detects cycles', () => {
  const document = root(), entry = entries(document)[0];
  document.workflow.operations[0].document.radius = reference(entry, scopes(document)[1]);
  assert.throws(() => removeEntry(document, entry), /in use/);
  document.workflow.operations[0].document.radius = {scope: 'workflow', $document: '/dimensions/distance'};
  assert.throws(() => removeEntry(document, entry), /in use/, 'JSON property order does not change reference identity');
  delete document.workflow.operations[0].document.radius;
  assert.equal(removeEntry(document, entry).workflow.dimensions.distance, undefined);
  document.workflow.dimensions.distance = {$document: '/dimensions/distance'};
  assert.throws(() => preview(document, document.workflow.dimensions.distance, scopes(document)[0]), /Circular/);
  document.parameters.local = {target: {scope: 'workflow', pointer: '/operations/0/document/dimensions/distance'}};
  assert.throws(() => removeEntry(document, entries(document).find(e => e.operation === 'a')), /parameter/);
});

test('static calculation previews preserve scope and reject nonnumeric or infinite arithmetic', () => {
  const document = root(), scope = scopes(document)[1];
  const expression = {$expr: {op: 'divide', args: [{$document: '/dimensions/distance', scope: 'workflow'}, 2]}};
  assert.equal(preview(document, expression, scope), 5);
  expression.$expr.args[1] = 0;
  assert.throws(() => preview(document, expression, scope), /finite/);
  expression.$expr.args = ['10', 2];
  assert.throws(() => preview(document, expression, scope), /numbers/);
});

test('editing a parameter preserves its declared kind and constraints', () => {
  const document = root();
  document.workflow.dimensions.direction = [0, 0, 1];
  document.parameters.direction = {label: 'Direction', kind: 'vector', default: [0, 0, 1], units: 'm', help: 'Old help',
    constraints: {length: 3, minimum: -10, maximum: 10}, target: {scope: 'workflow', pointer: '/dimensions/direction'}};
  const previous = entries(document).find(entry => entry.name === 'direction');
  const changed = saveEntry(document, {base: previous.base, name: previous.name, group: previous.group,
    value: [1, 0, 0], parameter: true, units: '', help: ''}, previous);
  assert.deepEqual(changed.parameters.direction.constraints, document.parameters.direction.constraints);
  assert.equal(changed.parameters.direction.label, 'Direction');
  assert.equal(changed.parameters.direction.units, undefined);
  assert.equal(changed.parameters.direction.help, undefined);
});
