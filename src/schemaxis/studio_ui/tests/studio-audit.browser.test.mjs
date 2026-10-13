import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFile} from 'node:fs/promises';
import {launch} from './harness.mjs';

test('native names, nonduplicated navigation and line placement edit one undoable options value', {timeout: 120000}, async () => {
  const session = await launch({provider: 'paraview'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async () => {
      const ctx = window.studio;
      const record = await ctx.api.post('/api/documents', {action:'new', provider:'paraview', name:'Audit',
        document:{version:'schemaxis/1',nodes:[{id:'flow',filter:'wavelet'},
          {id:'seeds',filter:'line'}, {id:'speed',filter:'calculator',inputs:{input:'flow'}, options:{expression:'RTData/255',result:'speed'}}],
          scenes:[{id:'view',geometry:['flow']} ]}});
      await ctx.refresh();ctx.windows.open('workbench',{document:record.id});
    })()`);
    await session.wait('window.studio.windows.active().window.store?.get().schema', 'schema');
    assert.equal(await session.evaluate(`document.querySelectorAll('.wb-outline [data-pointer^="/nodes/"]').length`), 0);
    await session.clickSelector('.wb-comprehension [data-pointer="/nodes/2"]');
    assert.match(await session.evaluate(`document.querySelector('.wb-properties').textContent`), /Function \(equation\).*Calculator.Function/s);
    await session.clickSelector('.wb-comprehension [data-pointer="/nodes/1"]');
    await session.evaluate(`[...document.querySelectorAll('.wb-properties button')].find(b=>b.textContent==='Place line endpoints…').click()`);
    await session.wait(`document.querySelector('.line-selector')`, 'selector');
    await session.evaluate(`(() => {
      for(const [label,value] of Object.entries({'X min':10,'X max':30,'Y min':-8,'Y max':4,'Z min':100,'Z max':140})) {
        const input=document.querySelector('[aria-label="'+label+'"]'); input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));
      }
      const plane=document.querySelector('[aria-label="Selection plane"]');plane.value='XZ';plane.dispatchEvent(new Event('change',{bubbles:true}));
      const canvas=document.querySelector('.line-selector-plane'), box=canvas.getBoundingClientRect();
      canvas.dispatchEvent(new MouseEvent('click',{clientX:box.left+box.width/2,clientY:box.top+box.height/2,bubbles:true}));
      const picked=[...document.querySelectorAll('[aria-label^="Start "]')].map(input=>Number(input.value));
      if(Math.abs(picked[0]-20)>.15 || Math.abs(picked[2]-120)>.15) throw Error('Plane centre pick: '+JSON.stringify(picked));
      for(const [label,value] of Object.entries({'Start X':15,'Start Y':-2,'Start Z':110,'End X':25,'End Y':-2,'End Z':130})) {
        const input=document.querySelector('[aria-label="'+label+'"]');input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));
      }
    })()`);
    await session.screenshot('/tmp/schemaxis-line-selector.png');
    await session.evaluate(`[...document.querySelectorAll('.dialog-footer button')].find(b=>b.textContent==='Use endpoints').click()`);
    await session.wait(`JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes[1].options?.start?.[0]===15`, 'applied endpoints');
    const options = await session.evaluate(`JSON.parse(window.studio.windows.active().window.editor.getValue()).nodes[1].options`);
    assert.deepEqual(options, {start:[15,-2,110],end:[25,-2,130]});
    await session.clickSelector('[data-add=sources]');
    await session.evaluate(`(() => {const input=document.querySelector('[aria-label="Search Add Source"]');input.value='line';input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await session.clickSelector('[data-library="operation:line"]');
    await session.wait(`document.querySelector('.operation-form')`, 'line form');
    assert.match(await session.evaluate(`document.querySelector('.operation-form').textContent`), /Place line endpoints/);
    await session.evaluate(`[...document.querySelectorAll('.operation-form button')].find(b=>b.textContent==='Place line endpoints…').click()`);
    await session.wait(`document.querySelectorAll('.dialog-backdrop').length===2`, 'nested selector');
    await session.key('Escape');
    assert.equal(await session.evaluate(`document.querySelectorAll('.dialog-backdrop').length`), 1);
    assert.ok(await session.evaluate(`document.querySelector('.operation-form')!==null`));
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('preview bounds retain dataset identity and 3D surfaces provide world coordinates', {timeout: 120000}, async () => {
  const session = await launch({provider: 'paraview'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    const mesh = JSON.parse(await readFile(new URL('./fixtures/viewers/mesh.json', import.meta.url), 'utf8'));
    mesh.objects = mesh.objects.slice(0, 1);
    mesh.observations = {preview: {points: 100, bounds: [-100, 100, -50, 50, -10, 80]}};
    await session.evaluate(`(async () => {
      const {selectLine}=await import('/windows/workbench/line-selector.mjs');
      window.lineResult='pending';
      selectLine({getContext:async()=>({data:${JSON.stringify(mesh)},label:'Native preview · saved revision 3 · draft has unsaved changes'})})
        .then(result=>{window.lineResult=result;});
    })()`);
    await session.evaluate(`[...document.querySelectorAll('.line-selector button')].find(b=>b.textContent==='Load preview bounds').click()`);
    await session.wait(`!document.querySelector('[aria-label="Bounds source"]').hidden`, 'loaded bounds');
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="X min"]').value`), '-65');
    assert.match(await session.evaluate(`document.querySelector('.line-selector [role=status]').textContent`), /saved revision 3 · draft has unsaved changes/);
    await session.evaluate(`(() => {const source=document.querySelector('[aria-label="Bounds source"]');source.value='dataset:preview';source.dispatchEvent(new Event('change'));})()`);
    assert.equal(await session.evaluate(`document.querySelector('[aria-label="X min"]').value`), '-100');
    await session.evaluate(`(() => {const mode=document.querySelector('[aria-label="Coordinate view"]');mode.value='3d';mode.dispatchEvent(new Event('change'));})()`);
    await session.wait(`document.querySelector('.line-selector-3d canvas')?.clientHeight>0`, '3D canvas');
    await session.clickSelector('.line-selector-3d .vw-canvas');
    await session.wait(`document.querySelector('[aria-label="Start X"]').value!==''`, 'surface point');
    const point=await session.evaluate(`['X','Y','Z'].map(axis=>Number(document.querySelector('[aria-label="Start '+axis+'"]').value))`);
    assert.ok(point[0]>=-65.001 && point[0]<=-24.999 && point[1]>=-20.001 && point[1]<=20.001 && point[2]>=-.001 && point[2]<=40.001);
    assert.ok(point.some((value,i)=>Math.min(Math.abs(value-[-65,-20,0][i]),Math.abs(value-[-25,20,40][i]))<.001), 'point lies on a box surface');
    await session.screenshot('/tmp/schemaxis-line-selector-3d.png');
    await session.key('Escape');
    await session.wait('window.lineResult===null', 'selector cancelled');
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});
