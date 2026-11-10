// Copyright (C) 2026 David L F Gaden
import assert from 'node:assert/strict';
import test from 'node:test';
import {validate} from '../editor/schema-validate.mjs';

test('incompatible closed field sets get a whole-object diagnostic without guessing a branch', () => {
  const choice = {type: 'object', properties: {sources: {anyOf: [
    {type: 'object', properties: {items: {}}, required: ['items'], additionalProperties: false},
    {type: 'object', properties: {folder: {}}, required: ['folder'], additionalProperties: false},
  ]}}};
  for (const sources of [{items: []}, {folder: {}}]) assert.deepEqual(validate(choice, {sources}), []);
  assert.deepEqual(validate(choice, {sources: {items: [], folder: {}}}), [{pointer: '/sources',
    message: 'Properties cannot be combined in one object alternative', severity: 'warning'}]);
  assert.deepEqual(validate(choice, {sources: {}}), [], 'missing choices stay conservative');
  assert.deepEqual(validate(choice, {sources: {$document: '/source'}}), [], 'composition markers stay deferred');
  const open = {anyOf: [...choice.properties.sources.anyOf, {type: 'object'}]};
  assert.deepEqual(validate(open, {items: [], folder: {}}), [], 'an open alternative can admit the fields');
});

// Synthetic schemas shaped like heterogeneous alternatives: tagged constructor branches (if/then/else:false on `type`)
// beside an untagged closed branch, optionally wrapped with composition-marker branches. Nothing names an adaptor.
const marker = {type: 'object', properties: {$document: {type: 'string'}}, required: ['$document']};
const numberOrMarker = (bounds) => ({anyOf: [{type: 'number', ...bounds}, marker]});
const tagged = (tag, optionProperties) => ({
  if: {properties: {type: {const: tag}}, required: ['type']},
  then: {type: 'object', additionalProperties: false, required: ['id', 'type', 'options'], properties: {
    id: {type: 'string'}, type: {const: tag},
    options: {type: 'object', additionalProperties: false, properties: optionProperties}}},
  else: false,
});
const sourced = {
  type: 'object', additionalProperties: false, required: ['id', 'source', 'mounts'],
  properties: {
    id: {type: 'string'},
    source: {anyOf: [{type: 'string', minLength: 1}, {type: 'object', required: ['$artifact'], properties: {$artifact: {type: 'string'}}}]},
    mounts: {type: 'object', additionalProperties: {type: 'object', additionalProperties: false, properties: {
      position: {type: 'array', minItems: 3, maxItems: 3, items: numberOrMarker({minimum: -100, maximum: 100})},
      z: {enum: ['+X', '-X', '+Y', '-Y', '+Z', '-Z']}}}},
  },
};
const parts = {
  type: 'array', maxItems: 3,
  items: {anyOf: [{anyOf: [
    tagged('box', {length: numberOrMarker({minimum: 1, maximum: 100}), width: {type: 'number', minimum: 1}}),
    tagged('cylinder', {radius: {type: 'number', minimum: 1}, height: {type: 'number', minimum: 1}}),
    sourced]}, marker]},
};
const root = {type: 'object', properties: {parts}};
const report = (value, schema = root) => validate(schema, value).map(({pointer, message}) => `${pointer}: ${message}`);
const part = (item) => ({parts: [item]});

test('a tagged branch that is positively selected reports its own errors beside an untagged closed branch', () => {
  assert.deepEqual(report(part({id: 'a', type: 'box', options: {length: 0, width: 5}})),
    ['/parts/0/options/length: Must be at least 1']);
  assert.deepEqual(report(part({id: 'a', type: 'cylinder', options: {radius: 5, height: 0}})),
    ['/parts/0/options/height: Must be at least 1']);
  assert.deepEqual(report(part({id: 'a', type: 'box', options: {length: 5, colour: 1}})),
    ['/parts/0/options/colour: Property "colour" is not allowed']);
  assert.deepEqual(report(part({id: 'a', type: 'box', option: {}})).filter((line) => line.includes('not allowed')),
    ['/parts/0/option: Property "option" is not allowed'], 'a misspelled key of the selected branch is still reported');
  assert.deepEqual(report(part({id: 'a', type: 'box', source: '/x', mounts: {t: {}}})).filter((line) => line.includes('not allowed')),
    ['/parts/0/source: Property "source" is not allowed', '/parts/0/mounts: Property "mounts" is not allowed']);
});

test('without a discriminator, a closed branch that forbids a present field leaves the applicable alternative', () => {
  assert.deepEqual(report(part({id: 'p', source: '/x/model', mounts: {top: {z: 'up'}}})),
    ['/parts/0/mounts/top/z: Expected one of "+X", "-X", "+Y", "-Y", "+Z", "-Z"']);
  assert.deepEqual(report(part({id: 'p', source: '/x/model', mounts: {top: {position: [0, 0]}}})),
    ['/parts/0/mounts/top/position: Expected at least 3 items']);
  assert.deepEqual(report(part({id: 'p', source: '/x/model', mounts: {top: {flavour: 1}}})),
    ['/parts/0/mounts/top/flavour: Property "flavour" is not allowed']);
  assert.deepEqual(report(part({id: 'p', source: '/x/model', mounts: {top: {position: [0, 0, 500]}}})),
    ['/parts/0/mounts/top/position/2: Must be at most 100']);
  assert.deepEqual(report(part({id: 'p', source: '', mounts: {}})), ['/parts/0/source: Expected at least 1 character']);
});

test('an unknown discriminator value is reported once the untagged branch cannot take the field', () => {
  assert.deepEqual(report(part({id: 'a', type: 'sphere', options: {}})), ['/parts/0/type: Unknown type "sphere"']);
});

test('genuinely ambiguous partial or conflicting forms stay silent', () => {
  // No `type` yet: options fit both box and cylinder shapes, so nothing is attributed.
  assert.deepEqual(report(part({id: 'a', options: {length: 0}})), []);
  assert.deepEqual(report(part({id: 'a', options: {radius: 0}})), []);
  // Every alternative forbids something that is present.
  assert.deepEqual(report(part({id: 'p', source: '/x', mounts: {}, extra: 1})), []);
  assert.deepEqual(report(part({})), []);
  // An empty array of unrelated shapes and an unrecognised key set do not produce guesses.
  assert.deepEqual(report({parts: [{zzz: 1}]}), []);
});

test('valid parts, composition markers and fill markers produce no diagnostics', () => {
  assert.deepEqual(report({parts: [
    {id: 'a', type: 'box', options: {length: 5, width: 5}},
    {id: 'b', type: 'cylinder', options: {radius: 2, height: {$document: '/h'}}},
    {id: 'c', source: {$artifact: 'producer', index: 2}, mounts: {top: {position: [0, 0, {$document: '/t'}], z: '+Z'}}},
  ]}), []);
  assert.deepEqual(report(part({id: 'a', type: 'box', options: {length: {$fill: 'length', type: 'number'}}})), []);
  assert.deepEqual(report(part({id: 'p', source: {$fill: 'source', type: 'string'}, mounts: {top: {z: {$fill: 'z'}}}})), []);
  assert.deepEqual(report(part({$document: '/whole'})), []);
  assert.deepEqual(report(part({id: 'p', source: '/x', mounts: {top: {z: {$expr: 'axis'}}}})), []);
});

test('array limits still apply around heterogeneous alternatives', () => {
  const four = Array.from({length: 4}, (_, index) => ({id: `p${index}`, type: 'box', options: {length: 5}}));
  assert.deepEqual(report({parts: four}), ['/parts: Expected at most 3 items']);
});

test('closed alternatives without conditionals are told apart by the fields they forbid', () => {
  const schema = {oneOf: [
    {type: 'object', additionalProperties: false, properties: {a: {type: 'integer', maximum: 5}}},
    {type: 'object', additionalProperties: false, properties: {b: {type: 'string', minLength: 2}}},
  ]};
  assert.deepEqual(report({a: 9}, schema), ['/a: Must be at most 5']);
  assert.deepEqual(report({b: 'x'}, schema), ['/b: Expected at least 2 characters']);
  assert.deepEqual(report({a: 1}, schema), []);
  assert.deepEqual(report({}, schema), []);
  assert.deepEqual(report({a: 9, b: 'x'}, schema), [': Properties cannot be combined in one object alternative'],
    'the impossible field combination is known without attributing either value to a branch');
});

test('declared keys anywhere in a branch tree are never treated as forbidden', () => {
  // `y` is declared only through allOf/$ref beside a closed node; the editor stays conservative and does not exclude it.
  const schema = {$defs: {base: {type: 'object', properties: {y: {type: 'integer', maximum: 3}}}}, anyOf: [
    {type: 'object', additionalProperties: false, properties: {x: {type: 'integer'}}, allOf: [{$ref: '#/$defs/base'}]},
    {type: 'object', additionalProperties: false, properties: {z: {type: 'integer'}}},
  ]};
  assert.ok(report({y: 9}, schema).includes('/y: Must be at most 3'), 'the allOf member still applies to y');
  assert.ok(!report({y: 9}, schema).some((line) => line.startsWith('/z')));
  // An open branch (no additionalProperties:false, or patternProperties) is never excluded by a present key.
  const open = {anyOf: [
    {type: 'object', properties: {x: {type: 'integer'}}},
    {type: 'object', additionalProperties: false, properties: {z: {type: 'integer', maximum: 1}}},
  ]};
  assert.deepEqual(report({z: 9}, open), [], 'the open branch may also describe it');
  const patterned = {anyOf: [
    {type: 'object', additionalProperties: false, patternProperties: {'^k': {type: 'integer'}}},
    {type: 'object', additionalProperties: false, properties: {z: {type: 'integer', maximum: 1}}},
  ]};
  assert.deepEqual(report({z: 9}, patterned), []);
});

test('closed branches reached through $ref and conditional then/else are excluded only when they must forbid the field', () => {
  const schema = {$defs: {plain: {type: 'object', additionalProperties: false, properties: {name: {type: 'string', maxLength: 3}}}},
    anyOf: [
      {$ref: '#/$defs/plain'},
      {if: {properties: {kind: {const: 'n'}}, required: ['kind']},
        then: {type: 'object', additionalProperties: false, properties: {kind: {}, count: {type: 'integer', maximum: 2}}},
        else: {type: 'object', additionalProperties: false, properties: {kind: {}, label: {type: 'string', maxLength: 2}}}},
    ]};
  // `name` only fits the $ref branch: the conditional branch forbids it whichever side of the condition applies.
  assert.deepEqual(report({name: 'abcd'}, schema), ['/name: Expected at most 3 characters']);
  // A positively selected `then` reports its own error; the $ref branch forbids `kind` and `count`.
  assert.deepEqual(report({kind: 'n', count: 9}, schema), ['/count: Must be at most 2']);
  // Else side selected.
  assert.deepEqual(report({kind: 'm', label: 'abc'}, schema), ['/label: Expected at most 2 characters']);
  // Without `kind` the condition fails, so the `else` side applies and `count` is genuinely not allowed there.
  assert.deepEqual(report({count: 9}, schema), ['/count: Property "count" is not allowed']);
  // Undecided condition where either side could take the field stays quiet.
  assert.deepEqual(report({kind: 7}, schema), []);
});

test('a single plausible alternative keeps reporting its closed-object errors as before', () => {
  const schema = {anyOf: [{type: 'string'}, {type: 'object', additionalProperties: false, properties: {a: {type: 'integer'}}}]};
  assert.deepEqual(report({b: 1}, schema), ['/b: Property "b" is not allowed']);
  assert.deepEqual(report({a: 'x'}, schema), ['/a: Expected integer, found string']);
  assert.deepEqual(report('fine', schema), []);
});

test('an object carrying a composition-marker key is never judged, whatever else it holds', () => {
  assert.deepEqual(report(part({id: 'p', source: '/x', mounts: {top: {z: 'up'}}, $note: 1})), []);
  assert.deepEqual(report(part({id: 'a', type: 'box', options: {length: 0}, $document: '/p'})), []);
});

test('a pattern-keyed branch is never excluded by a present field, even when it fails for another reason', () => {
  // The patterned branch is not satisfied (required `q` is absent) and the closed branch is not either (z > 1),
  // so both stay plausible; only the closed branch could be excluded by `z` if pattern keys were ignored.
  const schema = {anyOf: [
    {type: 'object', additionalProperties: false, required: ['q'], patternProperties: {'^q': {type: 'integer'}}},
    {type: 'object', additionalProperties: false, properties: {z: {type: 'integer', maximum: 1}}},
  ]};
  assert.deepEqual(report({z: 9}, schema), []);
});

test('several positively selected branches that all conflict stay silent instead of guessing a tag error', () => {
  const alternative = (extraKey) => ({
    if: {properties: {type: {const: 'a'}}, required: ['type']},
    then: {type: 'object', additionalProperties: false, properties: {type: {}, [extraKey]: {type: 'integer'}}},
    else: false,
  });
  const schema = {anyOf: [alternative('first'), alternative('second')]};
  assert.deepEqual(report({type: 'a', other: 1}, schema), []);
});

test('closure reached through nested alternatives and allOf is judged conservatively', () => {
  const closed = (key, bounds) => ({type: 'object', additionalProperties: false, properties: {[key]: {type: 'integer', ...bounds}}});
  // A wrapper alternative is only excluded when every one of its own alternatives forbids the field.
  const wrapped = {anyOf: [{anyOf: [closed('a', {maximum: 5}), closed('b', {})]}, closed('c', {})]};
  assert.deepEqual(report({a: 9}, wrapped), ['/a: Must be at most 5']);
  // Closure inside allOf applies to the branch as a whole.
  const viaAllOf = {anyOf: [{allOf: [closed('a', {})]}, closed('b', {maximum: 1})]};
  assert.deepEqual(report({b: 9}, viaAllOf), ['/b: Must be at most 1']);
});

test('an untagged branch that can take the tag field keeps an unrecognised tag from being called unknown', () => {
  const schema = {anyOf: [
    {if: {properties: {type: {const: 'box'}}, required: ['type']}, then: {type: 'object', properties: {type: {}}}, else: false},
    {type: 'object', additionalProperties: false, properties: {type: {type: 'string'}, extra: {type: 'integer', maximum: 1}}},
  ]};
  assert.deepEqual(report({type: 'other', extra: 9}, schema), ['/extra: Must be at most 1']);
});

// A tag condition is "pure" only when it is `required: [key]` plus `properties` with exactly that key (a const, an enum, or the
// const-or-marker form generated schemas use) and nothing else that could fail. Anything else is not allowed to say "Unknown".
const closedObject = (properties) => ({type: 'object', additionalProperties: false, properties});
const untaggedSource = closedObject({source: {type: 'string'}});
const taggedBranch = (condition, then = {type: 'object', properties: {type: {}, options: {type: 'object', properties: {n: {type: 'integer', maximum: 1}}}}}) => (
  {if: condition, then, else: false});

test('a known tag is never called unknown because another field in the condition failed', () => {
  const schema = {anyOf: [
    taggedBranch({required: ['type'], properties: {type: {const: 'box'}, options: {type: 'object'}}}),
    untaggedSource,
  ]};
  // The tag is known; `options` is the problem, so no unknown-tag claim and no guess at the untagged branch.
  assert.deepEqual(report({type: 'box', options: 'oops'}, schema), []);
  // A selected branch still reports its own real error.
  assert.deepEqual(report({type: 'box', options: {n: 9}}, schema), ['/options/n: Must be at most 1']);
  // A separate non-properties constraint in the condition is just as impure.
  const guarded = {anyOf: [
    taggedBranch({required: ['type'], properties: {type: {const: 'box'}}, not: {required: ['legacy']}}),
    untaggedSource,
  ]};
  assert.deepEqual(report({type: 'box', legacy: 1}, guarded), []);
  const sized = {anyOf: [
    taggedBranch({required: ['type'], properties: {type: {const: 'box'}}, minProperties: 3}),
    untaggedSource,
  ]};
  assert.deepEqual(report({type: 'box', options: {}}, sized), []);
});

test('an impure tagged condition keeps the same silence in an all-tagged union', () => {
  const schema = {anyOf: [
    taggedBranch({required: ['type'], properties: {type: {const: 'box'}, options: {type: 'object'}}}),
    taggedBranch({required: ['type'], properties: {type: {const: 'cylinder'}, options: {type: 'object'}}}),
  ]};
  assert.deepEqual(report({type: 'box', options: 'oops'}, schema), []);
});

test('genuine unknown tags are still reported for every shape of pure tag condition', () => {
  const pure = {
    const: {required: ['type'], properties: {type: {const: 'box'}}},
    enum: {required: ['type'], properties: {type: {enum: ['box', 'crate']}}},
    // The shape generated schemas emit: object-typed condition, const-or-marker value, annotations beside it.
    generated: {type: 'object', required: ['type'], 'x-studio-guide': {status: 'reviewed'},
      properties: {type: {anyOf: [{const: 'box'}, {type: 'object'}]}}},
  };
  for (const [name, condition] of Object.entries(pure)) {
    const schema = {anyOf: [taggedBranch(condition), untaggedSource]};
    assert.deepEqual(report({type: 'sphere', options: {}}, schema), ['/type: Unknown type "sphere"'], name);
    assert.deepEqual(report({type: 'box', options: {n: 9}}, schema), ['/options/n: Must be at most 1'], name);
  }
  const allTagged = {anyOf: [
    taggedBranch(pure.generated),
    taggedBranch({type: 'object', required: ['type'], properties: {type: {anyOf: [{const: 'cylinder'}, {type: 'object'}]}}}),
  ]};
  assert.deepEqual(report({type: 'sphere'}, allTagged), ['/type: Unknown type "sphere"']);
});

test('INTENTIONAL: a positively selected tagged branch takes precedence over a plausible untagged branch that also admits the tag', () => {
  // When no whole branch matches, the instance declared its tag, so the tagged branch's errors are reported rather than
  // treating the two as ambiguous. This is a precedence rule, not ambiguity handling.
  const schema = {anyOf: [
    taggedBranch({required: ['type'], properties: {type: {const: 'box'}}}, closedObject({type: {}, size: {type: 'integer'}})),
    {type: 'object', properties: {type: {type: 'string'}, extra: {type: 'integer', maximum: 1}}},
  ]};
  assert.deepEqual(report({type: 'box', extra: 9}, schema), ['/extra: Property "extra" is not allowed']);
  // Without the tag the untagged branch is the only one that can apply and reports its own bound.
  assert.deepEqual(report({extra: 9}, schema), ['/extra: Must be at most 1']);
});

test('a tag whose value constraint is not a plain value set is not used to claim an unknown value', () => {
  const schema = {anyOf: [
    taggedBranch({required: ['type'], properties: {type: {type: 'string', minLength: 5}}}),
    untaggedSource,
  ]};
  assert.deepEqual(report({type: 'abc', options: {}}, schema), []);
});

test('pure tags written as an enum inside the const-or-marker form are still recognised', () => {
  const schema = {anyOf: [
    taggedBranch({type: 'object', required: ['type'], properties: {type: {anyOf: [{enum: ['box', 'crate']}, {type: 'object'}]}}}),
    untaggedSource,
  ]};
  assert.deepEqual(report({type: 'sphere', options: {}}, schema), ['/type: Unknown type "sphere"']);
});

test('an impure tagged branch says nothing when the instance does not carry its tag', () => {
  const schema = {anyOf: [
    taggedBranch({required: ['type'], properties: {type: {const: 'box'}, options: {type: 'object'}}}, closedObject({type: {}, options: {}})),
    untaggedSource,
  ]};
  // No tag: only the untagged branch can apply, so its own error is reported as usual.
  assert.deepEqual(report({source: 5}, schema), ['/source: Expected string, found number']);
});

test('a condition that requires more than the tag is not treated as a tag condition', () => {
  const schema = {anyOf: [
    taggedBranch({required: ['type', 'extra'], properties: {type: {const: 'box'}}}),
    untaggedSource,
  ]};
  assert.ok(!report({type: 'sphere', options: {}}, schema).some((line) => line.includes('Unknown type')));
});

test('an ordinary if/then/else with a real else branch is not mistaken for a tag condition', () => {
  const schema = {anyOf: [
    {if: {required: ['type'], properties: {type: {const: 'box'}, options: {type: 'object'}}},
      then: closedObject({type: {}, options: {type: 'object'}}),
      else: closedObject({type: {}, options: {type: 'string', maxLength: 2}})},
    untaggedSource,
  ]};
  // The condition fails, so the else side applies and its own bound is reported.
  assert.deepEqual(report({type: 'box', options: 'toolong'}, schema), ['/options: Expected at most 2 characters']);
});

test('a const-selected closed alternative retains value and unknown-key diagnostics', () => {
  const node = (filter, options) => ({type: 'object', additionalProperties: false,
    required: ['filter', 'options'], properties: {filter: {const: filter},
      options: {type: 'object', properties: options, additionalProperties: false}}});
  const schema = {oneOf: [node('box', {length: {type: 'number', exclusiveMinimum: 0}}),
    node('sphere', {radius: {type: 'number', exclusiveMinimum: 0}})]};
  const value = {filter: 'box', options: {length: -1}, inptus: []};
  assert.deepEqual(validate(schema, value).map(({pointer, message}) => [pointer, message]), [
    ['/options/length', 'Must be greater than 0'],
    ['/inptus', 'Property "inptus" is not allowed'],
  ]);
});
