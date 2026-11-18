// Copyright (C) 2026 David L. F. Gaden.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {colourRgba} from '../windows/workbench/colour-control.mjs';
const palette=JSON.parse(readFileSync(new URL('../../named_colours.json',import.meta.url))).colours;
test('Studio previews every bundled Matplotlib name and native numeric conventions',()=>{
  for(const [name,rgba] of Object.entries(palette))assert.deepEqual(colourRgba(name,palette),rgba);
  assert.deepEqual(colourRgba([51,102,153]),[0.2,0.4,0.6,1]);
  assert.deepEqual(colourRgba([0.2,0.4,0.6]),[0.2,0.4,0.6,1]);
  assert.deepEqual(colourRgba('#336699'),[0.2,0.4,0.6,1]);
  assert.deepEqual(colourRgba('#abc8'),[170/255,187/255,204/255,136/255]);
  assert.deepEqual(colourRgba('none'),[0,0,0,0]);
  assert.equal(colourRgba('currentColor',palette),null);
  assert.equal(colourRgba([51.5,102,153]),null);
  assert.equal(colourRgba([-1,0,1]),null);
  assert.equal(colourRgba([NaN,0,1]),null);
});
