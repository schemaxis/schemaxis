// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {requiredTemplate} from '../windows/workbench/operation-form.mjs';
import {validate} from '../editor/schema-validate.mjs';
import {parse as parseJson} from '../editor/json-parse.mjs';
import {resolveDiagnostics} from '../editor/diagnostics.mjs';

test('required skeleton retains constants and markers, omits optional defaults', () => {
  const schema = {type:'object', required:['id','filter','inputs'], properties:{
    id:{type:'string'}, filter:{const:'slice'}, inputs:{type:'object', required:['input'], properties:{input:{type:'string'}}},
    options:{$ref:'#/$defs/options'}}};
  const defs = {options:{type:'object', properties:{crinkle:{type:'boolean',default:false}}}};
  const value = requiredTemplate(schema, defs, 'slice');
  assert.equal(value.filter, 'slice'); assert.ok(value.id.$fill); assert.ok(value.inputs.input.$fill);
  assert.equal(value.options, undefined);
  assert.deepEqual(validate({...schema,$defs:defs}, value), []);
});

test('diagnostic coordinates handle Unicode and retain missing-key pointers', () => {
  const text = '{\n "name": "🧭",\n "nodes": [{"id":"cut"}]\n}';
  const ast = parseJson(text);
  const [result] = resolveDiagnostics(ast, [{location:'/nodes/0/options/normal',message:'Missing required normal'}], 'external');
  assert.equal(result.pointer, '/nodes/0/options/normal'); assert.equal(result.line, 3);
  assert.ok(result.column > 1);
  const [syntax] = resolveDiagnostics(ast, [{code:'INVALID_JSON',location:'$',offset:Array.from(text.slice(0,text.indexOf('"nodes"'))).length,message:'Bad'}], 'external');
  assert.equal(syntax.from, text.indexOf('"nodes"'));
});

test('choosing a proxy variant fixes its sole discriminator value', () => {
  assert.deepEqual(requiredTemplate({type:'object',required:['type'],properties:{type:{enum:['Box']}}}, {}, 'clip'), {type:'Box'});
});
