import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

test('Checked STEP snippet authors units, orientation, expectations and linked refinement through Studio', {timeout:120000}, async()=>{
  const document={version:'schemaxis.freecad/1',nodes:[{id:'block',filter:'box'}],output:'block'};
  const source=fileURLToPath(new URL('../../examples/schemaxis/freecad-import-step-bracket.step',import.meta.url));
  const values={
    'Feature ID':'importedPart', 'Source .step file':source, 'Unit the file declares':'"inch"',
    'File axis that becomes +Z':'"+Y"', 'File axis that becomes +X':'"+X"',
    'Position (mm)':'[100,50,0]', 'Expected volume (mm³)':'10840',
    'Expected centre of mass in the part frame (mm)':'[-0.8081180811808119,-0.24354243542435425,5]',
    'Merge coplanar faces (Part::Refine)':'true',
  };
  const s=await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server','Studio ready');
    await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'freecad',name:'Checked supplier part',document:${JSON.stringify(document)}});
      await c.refresh();c.windows.open('workbench',{document:r.id});})()`);
    await s.wait('document.querySelector("[data-category=io]")','Import category');
    await s.clickSelector('[data-category="io"]');
    await s.wait('document.querySelector("[data-library=add-importSTEP]")','Checked import snippet');
    const editor='window.studio.windows.active().window.editor';
    const original=await s.evaluate(`${editor}.getValue()`);
    await s.evaluate('document.querySelector("[data-library=add-importSTEP]").dispatchEvent(new MouseEvent("mouseenter"))');
    assert.equal(await s.evaluate(`${editor}.getValue()`),original,'preview must not edit input');
    await s.clickSelector('[data-library="add-importSTEP"]');
    const popover='.sx-fill-popover:not([hidden])';
    for(let count=0;count<12;count++) {
      if(!await s.evaluate(`${editor}.getValue().includes('"$fill"')`))break;
      await s.wait(`document.querySelector('${popover} .sx-fill-heading strong')`,'snippet field');
      const label=await s.evaluate(`document.querySelector('${popover} .sx-fill-heading strong').textContent`);
      assert.ok(Object.hasOwn(values,label),`Unexpected fill field: ${label}`);
      await s.evaluate(`(()=>{const e=document.querySelector('${popover} [aria-label="Value"]');
        e.value=${JSON.stringify(values[label])};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
      await s.wait(`document.querySelector('${popover} .button.primary:not(:disabled)')`,'valid field value');
      await s.clickSelector(`${popover} .button.primary`);
    }
    const text=await s.evaluate(`${editor}.getValue()`);
    assert.equal(text.includes('"$fill"'),false);
    const authored=JSON.parse(text);
    assert.deepEqual(authored.nodes[0],document.nodes[0]);
    // The library resolves a unique default ID when it inserts the snippet.
    assert.equal(authored.output,'importedPart');
    assert.deepEqual(authored.nodes[1],{id:'importedPart',filter:'importSTEP',options:{file:source,units:'inch',
      orientation:{z:'+Y',x:'+X'},placement:{position:[100,50,0],clocking:0},
      expect:{volume:{value:10840},centreOfMass:{value:[-0.8081180811808119,-0.24354243542435425,5]}},refine:true}});
    const validate=async(value)=>s.evaluate(`window.studio.api.post('/api/validate',
      {provider:'freecad',source:${JSON.stringify(JSON.stringify(value))}})`);
    const valid=await validate(authored);assert.equal(valid.valid,true);assert.deepEqual(valid.diagnostics,[]);
    authored.nodes[1].options.units='mm';
    const invalid=await validate(authored);assert.equal(invalid.valid,false);
    assert.match(invalid.diagnostics[0].message,/unit/i);
    assert.equal(invalid.diagnostics[0].pointer,'/nodes/1/options/units');
    assert.deepEqual(s.exceptions,[]);
  } finally {await s.close();}
});
