import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

test('Placed Body starter authors world layout, refuses a nonorthogonal frame and undoes atomically',
  {timeout:120000},async()=>{
  const s=await launch({provider:'freecad'});
  const editor='window.studio.windows.active().window.editor';
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    const initial={version:'schemaxis.freecad/1',nodes:[{id:'stock',filter:'box'}],output:'stock'};
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'freecad',name:'Placed editable Body',document:${JSON.stringify(initial)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-add=all]")','Workbench ready');
    const saved=await s.evaluate('window.studio.windows.active().window.store.get().record');
    await s.evaluate(`document.querySelector('.library-more[aria-expanded=false]')?.click()`);
    await s.clickSelector('[data-category="templates"]');
    await s.wait('document.querySelector("[data-library=placed-body]")','Packaged placed Body starter');
    await s.evaluate('document.querySelector("[data-library=placed-body]").scrollIntoView({block:"center"})');
    await s.clickSelector('[data-library="placed-body"]');
    const popover='.sx-fill-popover:not([hidden])';
    const values={'Plate thickness (mm)':'9','Body world X (mm)':'-23',
      'Body world Y (mm)':'31','Body world Z (mm)':'47'};
    const seen=[];
    for(let i=0;i<4;i++) {
      await s.wait(`document.querySelector('${popover} .sx-fill-heading strong')`,'Starter field');
      const label=await s.evaluate(`document.querySelector('${popover} .sx-fill-heading strong').textContent`);
      assert.ok(Object.hasOwn(values,label),`Unexpected starter field ${label}`);seen.push(label);
      await s.evaluate(`(()=>{const e=document.querySelector('${popover} [aria-label="Value"]');
        e.value=${JSON.stringify(values[label])};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      await s.wait(`document.querySelector('${popover} .button.primary:not(:disabled)')`,'Valid starter field');
      await s.clickSelector(`${popover} .button.primary`);
    }
    assert.equal(new Set(seen).size,4);
    await s.wait(`!${editor}.getValue().includes('"$fill"')`,'All starter fields filled');
    const text=await s.evaluate(`${editor}.getValue()`);const authored=JSON.parse(text);
    assert.equal(authored.parameters.thickness.value,9);
    assert.deepEqual(authored.nodes[0].options.frame,{origin:[-23,31,47],xAxis:[.6,.8,0],normal:[.48,-.36,.8]});
    assert.equal(authored.nodes[0].filter,'body');
    assert.ok(!authored.nodes.some(n=>n.filter==='bodySeed'),'Ordinary placed Body needs no imported seed');
    const validate=async(value)=>s.evaluate(`window.studio.api.post('/api/validate',
      {provider:'freecad',source:${JSON.stringify(JSON.stringify(value))}})`);
    assert.equal((await validate(authored)).valid,true);

    // The real source editor exposes the complete frame, beyond the starter's
    // origin fields. Each edit is one undo transaction, not a silent save.
    const turned=structuredClone(authored);
    turned.nodes[0].options.frame={origin:[-23,31,47],xAxis:[0,-1,0],normal:[1,0,0]};
    for(const measured of turned.measurements.filter(m=>m.edges))
      measured.edges.where.parallelTo=[0,-1,0];
    await s.evaluate(`${editor}.setValue(${JSON.stringify(JSON.stringify(turned,null,2))},{preserveUndo:true})`);
    await s.clickSelector('[data-action="validate"]');
    assert.equal((await validate(turned)).valid,true);
    const invalid=structuredClone(turned);invalid.nodes[0].options.frame.normal=[0,-1,0];
    await s.evaluate(`${editor}.setValue(${JSON.stringify(JSON.stringify(invalid,null,2))},{preserveUndo:true})`);
    const refused=await validate(invalid);assert.equal(refused.valid,false);
    assert.ok(refused.diagnostics.some(d=>d.code==='INVALID_FRAME'),JSON.stringify(refused));
    const jobs=await s.evaluate('window.studio.store.get().server.jobs.length');
    await s.clickSelector('[data-action="preview"]');
    await s.wait(`${editor}.getDiagnostics().some(d=>d.code==='INVALID_FRAME')`,'Located frame refusal');
    assert.deepEqual(JSON.parse(await s.evaluate(`${editor}.getValue()`)),invalid,'Validation does not replace invalid axes');
    const unchanged=await s.evaluate('window.studio.windows.active().window.store.get().record');
    assert.equal(unchanged.revision,saved.revision);assert.equal(unchanged.source,saved.source);
    assert.equal(await s.evaluate('window.studio.store.get().server.jobs.length'),jobs,'Invalid preview launches no native job');
    await s.evaluate(`${editor}.focus()`);await s.key('z',{modifiers:2});
    await s.wait(`JSON.parse(${editor}.getValue()).nodes[0].options.frame.normal[0]===1`,'Invalid frame undo');
    assert.deepEqual(JSON.parse(await s.evaluate(`${editor}.getValue()`)),turned);
    await s.key('z',{modifiers:2});await s.wait(`${editor}.getValue()===${JSON.stringify(text)}`,'Whole valid frame edit undo');
    assert.equal((await validate(JSON.parse(await s.evaluate(`${editor}.getValue()`)))).valid,true,'Starter remains usable after refusal');
    assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
