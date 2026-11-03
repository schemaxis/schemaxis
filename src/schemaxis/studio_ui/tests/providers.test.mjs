// Copyright (C) 2026 David L F Gaden
// Adaptor display identities: built-in table, manifest `display` metadata and a
// generated fallback for external adaptor packages the Studio has never seen.

import assert from 'node:assert/strict';
import {test} from 'node:test';
import {generated, identity, registerIdentities} from '../shell/providers.mjs';

test('built-in identities are unchanged without registered metadata', () => {
  registerIdentities([]);
  assert.deepEqual(identity('paraview'), {name: 'ParaView', mark: 'PV', colour: '#3a6fc4'});
});

test('unknown providers get a stable, readable generated identity', () => {
  registerIdentities([]);
  const first = identity('acme_flow');
  assert.equal(first.name, 'Acme Flow');
  assert.equal(first.mark, 'AF');
  assert.match(first.colour, /^#[0-9a-f]{6}$/);
  assert.deepEqual(identity('acme_flow'), first);
  assert.deepEqual(generated('acme_flow'), first);
  assert.notEqual(generated('another').colour, undefined);
  assert.equal(identity('solver').mark, 'So');
});

test('served display metadata takes precedence and invalid parts fall back', () => {
  registerIdentities([
    {id: 'acme', display: {name: 'Acme Solver', mark: 'AS', colour: '#123abc'}},
    {id: 'paraview', display: {name: 'ParaView (site build)'}},
    {id: 'partial', display: {name: 'Partial Tool', colour: 'red'}},
    {id: 'ignored', display: {name: '   '}},
  ]);
  assert.deepEqual(identity('acme'), {name: 'Acme Solver', mark: 'AS', colour: '#123abc'});
  assert.equal(identity('paraview').name, 'ParaView (site build)');
  assert.equal(identity('paraview').mark, 'PS');
  assert.equal(identity('partial').colour, generated('partial').colour);
  assert.equal(identity('ignored').name, 'Ignored');
  registerIdentities([]);
  assert.equal(identity('acme').name, 'Acme');
});
