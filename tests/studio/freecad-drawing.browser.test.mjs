import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

test('FreeCAD drawing starter has checked geometry, geometric dimensions and reviewed typed help',{timeout:120000},async()=>{
  const s=await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    const library=await s.evaluate(`window.studio.api.get('/api/studio/adaptor',{id:'freecad'})`);
    const template=library.templates.find(t=>t.id==='technical-drawing');
    assert.ok(template?.document);assert.equal(template.document.version,'schemaxis.freecad.drawing/1');
    const filled=JSON.parse(JSON.stringify(template.document,(key,value)=>value && typeof value.$fill==='string' ? template.fields[value.$fill].default : value));
    const checked=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(filled))}})`);
    assert.equal(checked.valid,true,JSON.stringify(checked.diagnostics));
    assert.ok(filled.dimensioning.length>=2);assert.equal(filled.source.units,'inch');
    const wrong=structuredClone(filled);wrong.source.units='mm';
    const refused=await s.evaluate(`window.studio.api.post('/api/validate',{provider:'freecad',source:${JSON.stringify(JSON.stringify(wrong))}})`);
    assert.equal(refused.valid,false);assert.ok(refused.diagnostics.some(d=>d.code==='UNIT_MISMATCH'));
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',{action:'new',provider:'freecad',name:'Editable drawing',document:${JSON.stringify(filled)}});await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('window.studio.windows.active()?.window?.editor?.getValue','Drawing source opened');
    const actual=JSON.parse(await s.evaluate('window.studio.windows.active().window.editor.getValue()'));
    assert.deepEqual(actual,filled);assert.ok(actual.views.includes('isometric'));
    assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
