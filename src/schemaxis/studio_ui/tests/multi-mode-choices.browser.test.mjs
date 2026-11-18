// Copyright (C) 2026 David L. F. Gaden.
import assert from 'node:assert/strict';
import test from 'node:test';
import {launch} from './harness.mjs';

test('rows-only mode retains input choices and always adds instances from the starting settings', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  const click = (text, scope='.operation-dialog') => s.evaluate(`[...document.querySelectorAll(${JSON.stringify(scope+' button')})]
    .find(button=>button.textContent===${JSON.stringify(text)}).click()`);
  const names = scope => s.evaluate(`[...document.querySelectorAll(${JSON.stringify(scope+' .wb-case-name')})].map(button=>button.textContent)`);
  try {
    await s.wait('window.studio?.store.get().server','Studio');
    await s.evaluate(`(async () => {
      const meta=await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item=meta.addCatalogue.items.find(item=>item.operation==='extractBlock');
      const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
      window.root={version:'schemaxis/1',nodes:[{id:'sourceA',filter:'sphere'},{id:'sourceB',filter:'sphere'}],scenes:[]};
      const headers={available:true,regions:['internalMesh','Inlet']};
      const shared={get:()=>headers,subscribe:()=>()=>{},load:async()=>headers};
      const post=studio.api.post.bind(studio.api),wait=studio.api.waitForJob.bind(studio.api);
      studio.api.post=async(path,body)=>path==='/api/inspect-input'?{job:'choices_'+body.node}:post(path,body);
      studio.api.waitForJob=async id=>id.startsWith('choices_')?{result:{assemblies:{Hierarchy:[
        {depth:1,label:'native_'+id.slice(8),parent:'/Root',selector:'/Root/native'}]}}}:wait(id);
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>root,undefined,
        {selected:'sourceA',caseData:shared}).then(result=>window.result=result);
    })()`);
    await s.wait('document.querySelector(".operation-dialog")','settings');
    assert.deepEqual(await names('.operation-form > .operation-field'),['Inlet','internalMesh']);
    await click('Select All','.operation-form > .operation-field');
    assert.equal(await s.evaluate(`document.querySelectorAll('.operation-form > .operation-field .reader-choices [aria-pressed=true]').length`),2);
    await click('Deselect All','.operation-form > .operation-field');
    // Activate with nothing selected, exactly as reported by the user.
    assert.match(await s.evaluate('document.querySelector(".dialog-header h3").textContent'),/Single instance/);
    await click('Switch to multi-mode');
    assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-row").length'),1);
    assert.match(await s.evaluate('document.querySelector(".dialog-header h3").textContent'),/Multi-mode/);
    assert.equal(await s.evaluate('document.querySelector(".operation-form > .operation-field").hidden'),true);
    assert.equal(await s.evaluate('getComputedStyle(document.querySelector(".operation-top")).display'),'none');
    assert.ok(!await s.evaluate('document.querySelector(".operation-dialog").innerText.toLowerCase().includes("master")'));
    assert.equal(await s.evaluate('document.querySelector(".multi-mode-row-editor").hidden'),false);
    assert.deepEqual(await names('.multi-mode-row'),['Inlet','internalMesh']);
    assert.match(await s.evaluate('document.querySelector(".multi-mode-summary-items").textContent'),/No blocks selected/);
    await click('Select All','.multi-mode-row');
    assert.match(await s.evaluate('document.querySelector(".multi-mode-summary-items").textContent'),/Inlet.*internalMesh/);
    await click('Deselect All','.multi-mode-row');
    assert.match(await s.evaluate('document.querySelector(".multi-mode-summary-items").textContent'),/No blocks selected/);
    await click('internalMesh','.multi-mode-row');
    assert.match(await s.evaluate('document.querySelector(".multi-mode-summary-items").textContent'),/internalMesh/);
    await click('Ask the application','.multi-mode-row');
    await s.wait(`document.querySelector('.multi-mode-row .wb-case-name')?.textContent==='native_sourceA'`,'native choices');
    assert.deepEqual(await names('.multi-mode-row'),['native_sourceA']);
    await click('Load names','.multi-mode-row');
    assert.deepEqual(await names('.multi-mode-row'),['native_sourceA'],'header reload keeps native input choices');
    await click('Add instance');
    assert.deepEqual(await names('.multi-mode-row:nth-child(2)'),['native_sourceA']);
    await click('native_sourceA','.multi-mode-row:nth-child(2)');
    // Full properties stage only this instance; changing its input seeds the
    // appropriate choices and applying returns to the same live quick row.
    await click('Properties…','.multi-mode-row:nth-child(2)');
    await s.wait('document.querySelectorAll(".operation-dialog").length===2','instance properties');
    const properties='.dialog-backdrop:last-child';
    assert.equal(await s.evaluate(`document.querySelector(${JSON.stringify(properties+' .dialog-action small')}).textContent`),'Return to multi-mode');
    await s.evaluate(`(() => {const dialog=document.querySelector(${JSON.stringify(properties)});
      const name=dialog.querySelector('[aria-label="extractBlock.id"]');name.value='secondExtract';
      name.dispatchEvent(new Event('input',{bubbles:true}));
      const input=dialog.querySelector('[aria-label="extractBlock.inputs.input"]');input.value='sourceB';
      input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
    assert.ok(!(await names(properties)).includes('native_sourceA'),'old input choices cleared');
    await click('Ask the application',properties);
    await s.wait(`document.querySelector('.dialog-backdrop:last-child .wb-case-name')?.textContent==='native_sourceB'`,'second input choices');
    await click('Delete',properties+' .reader-entry');
    await click('native_sourceB',properties);
    await click('Apply changes',properties+' .dialog-footer');
    await s.wait('document.querySelectorAll(".operation-dialog").length===1','applied instance properties');
    assert.equal(await s.evaluate('document.querySelectorAll(".multi-mode-summary-name")[1].textContent'),'secondExtract');
    assert.deepEqual(await names('.multi-mode-row:nth-child(2)'),['native_sourceB']);
    assert.deepEqual(await names('.multi-mode-row:nth-child(1)'),['native_sourceA']);
    assert.equal(await s.evaluate('root.nodes.length'),2,'properties are local until the outer batch applies');
    // Changing one instance never changes the defaults of a later addition.
    await click('Add instance');
    assert.deepEqual(await names('.multi-mode-row:nth-child(3)'),['native_sourceA']);
    await click('native_sourceA','.multi-mode-row:nth-child(3)');
    await click('Properties…','.multi-mode-row:nth-child(3)');
    await s.wait('document.querySelectorAll(".operation-dialog").length===2','new instance properties');
    assert.equal(await s.evaluate(`document.querySelector(${JSON.stringify(properties+' [aria-label="extractBlock.inputs.input"]')}).value`),'sourceA');
    await click('Cancel',properties+' .dialog-footer');
    await s.wait('document.querySelectorAll(".operation-dialog").length===1','return to rows');
    await click('Apply instances');
    await s.wait('window.result','saved batch');
    const saved=await s.evaluate('result.inserts.at(-1).values');
    assert.deepEqual(saved.map(node=>node.inputs.input),['sourceA','sourceB','sourceA']);
    assert.deepEqual(saved.map(node=>node.options.selectors),[['//internalMesh'],['//native_sourceB'],['//native_sourceA']]);
    assert.equal(saved[1].id,'secondExtract');
    assert.deepEqual(s.exceptions,[]);
    assert.deepEqual(s.consoleErrors,[]);
  } finally {await s.close();}
});

test('multi-mode gives the available names a generous viewport without trapping the form controls', {timeout:120000}, async () => {
  const s=await launch({provider:'paraview',width:1440,height:960});
  try {
    await s.wait('window.studio?.store.get().server','Studio');
    await s.evaluate(`(async()=>{
      const meta=await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item=meta.addCatalogue.items.find(item=>item.operation==='extractBlock');
      const {configureOperation}=await import('/windows/workbench/operation-form.mjs');
      const headers={available:true,regions:Array.from({length:29},(_,i)=>'wheels_'+i+'_AMI_slider_slave')};
      const shared={get:()=>headers,subscribe:()=>()=>{},load:async()=>headers};
      void configureOperation(studio,item,meta.addCatalogue.definitions,
        ()=>({version:'schemaxis/1',nodes:[{id:'source',filter:'sphere'}],scenes:[]}),undefined,
        {selected:'source',caseData:shared});
    })()`);
    await s.wait('document.querySelector(".operation-dialog")','settings');
    await s.evaluate(`[...document.querySelectorAll('.operation-dialog button')].find(b=>b.textContent==='Switch to multi-mode').click();
      [...document.querySelectorAll('.operation-dialog button')].find(b=>b.textContent==='Add instance').click()`);
    const layout=()=>s.evaluate(`(()=>{
      const row=document.querySelector('.multi-mode-row.expanded'),names=row.querySelector('.reader-choices');
      const panel=row.querySelector('.reader-available'),list=document.querySelector('.multi-mode-rows');
      const rect=names.getBoundingClientRect(),edge=list.getBoundingClientRect();
      return {height:names.clientHeight,contentHeight:names.scrollHeight,panelHeight:panel.clientHeight,
        rowHeight:row.clientHeight,listHeight:list.clientHeight,visible:Math.min(rect.bottom,edge.bottom)-Math.max(rect.top,edge.top),
        count:names.querySelectorAll('.wb-case-name').length,
        footer:document.querySelector('.operation-dialog > .dialog-footer').getBoundingClientRect().bottom};
    })()`);
    await s.evaluate(`document.querySelector('.multi-mode-row.expanded .reader-available').scrollIntoView({block:'center'})`);
    const roomy=await layout();
    assert.equal(roomy.count,29);
    assert.ok(roomy.height>=200 || roomy.height>=roomy.contentHeight,'show every name when the set fits; otherwise reserve a generous viewport');
    assert.ok(roomy.visible>=Math.min(200,roomy.contentHeight),JSON.stringify(roomy));
    assert.ok(roomy.panelHeight>roomy.height+70,'headings do not consume the names viewport');
    assert.ok(roomy.footer<960,'Apply stays inside the viewport');
    if(process.env.SCHEMAXIS_BLOCK_SPACE_SCREENSHOT) await s.screenshot(process.env.SCHEMAXIS_BLOCK_SPACE_SCREENSHOT);
    await s.send('Emulation.setDeviceMetricsOverride',{width:600,height:700,deviceScaleFactor:1,mobile:false});
    await s.evaluate(`document.querySelector('.multi-mode-row.expanded .reader-available').scrollIntoView({block:'center'})`);
    const narrow=await layout();
    assert.ok(narrow.height>=180,JSON.stringify(narrow));
    assert.ok(narrow.visible>=180,JSON.stringify(narrow));
    assert.ok(narrow.contentHeight>narrow.height,'larger sets scroll within the names viewport');
    assert.ok(narrow.footer<700,'Apply remains visible on a shorter screen');
    await s.evaluate(`(()=>{const names=document.querySelector('.multi-mode-row.expanded .reader-choices');names.scrollTop=names.scrollHeight;})()`);
    const last='.multi-mode-row.expanded .reader-choices .wb-case-name:last-child';
    await s.evaluate(`document.querySelector(${JSON.stringify(last)}).scrollIntoView({block:'nearest'})`);
    await s.clickSelector(last);
    assert.equal(await s.evaluate(`document.querySelector(${JSON.stringify(last)}).getAttribute('aria-pressed')`),'true');
    await s.clickSelector('.operation-dialog > .dialog-footer button:first-child');
    await s.wait('!document.querySelector(".operation-dialog")','Cancel remains accessible');
    assert.deepEqual(s.exceptions,[]);
    assert.deepEqual(s.consoleErrors,[]);
  } finally {await s.close();}
});

test('two compact fields share naming while Batch varies just the declared list', {timeout:120000}, async () => {
  const s = await launch({provider: 'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor', {id:'paraview', version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'pvExtractBlock');
      item.authoring = {
        instanceFields: [
          {path:'/options/Assembly', label:'Assembly'},
          {path:'/options/Selectors', label:'Blocks', style:'lastSegment'},
        ],
        naming: {},
        multiMode: {batchPath:'/options/Selectors', rationale:'Vary exact selectors within the given assembly.'},
      };
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'existing', filter:'pvExtractBlock', inputs:{Input:'source'},
        options:{Assembly:'Hierarchy', Selectors:[]}};
      const documentValue = {version:'schemaxis/1', nodes:[{id:'source', filter:'sphere'}, value], scenes:[]};
      void configureOperation(studio, item, meta.addCatalogue.definitions, () => documentValue, undefined,
        {existing:{pointer:'/nodes/1', value}});
    })()`);
    await s.wait('document.querySelector(".operation-dialog")', 'Settings');
    const click = label => s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await click('Switch to multi-mode');
    await s.wait('document.querySelector(\'[aria-label="Row 1.Assembly"]\')', 'Assembly control');
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="Row 1.Assembly"]\').value'), 'Hierarchy');
    await s.evaluate(`(() => {
      const input = document.querySelector('[aria-label="Row 1.Assembly"]');
      input.value = 'Custom';
      input.dispatchEvent(new Event('input', {bubbles:true}));
    })()`);
    await click('Add instance');
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="Row 2.Assembly"]\').value'), 'Hierarchy');
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="Row 2 Name"]\').value'), 'pvExtractBlock_Hierarchy');
    assert.match(await s.evaluate('document.querySelector(".multi-mode-row:first-child .multi-mode-summary-items").textContent'), /Assembly: Custom/);
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="Batch.Assembly"]\')'), null);
  } finally {
    await s.close();
  }
});

test('Threshold creates compact range rows without Batch', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'threshold');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'original',filter:'threshold',inputs:{input:'source'},
        options:{field:['POINTS','pressure'],lower:1,upper:5}};
      const documentValue = {version:'schemaxis/1',nodes:[{id:'source',filter:'sphere'},value],scenes:[]};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/nodes/1',value}}).then(result=>window.thresholdResult=result);
    })()`);
    await s.wait('document.querySelector(".operation-dialog")', 'Threshold Settings');
    const click = label => s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await click('Switch to multi-mode');
    await click('Add instance');
    assert.equal(await s.evaluate('document.querySelector(".multi-mode-batch").hidden'), true);
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="Row 2 Name"]\').value'), 'threshold_1_5');
    assert.match(await s.evaluate('document.querySelector(".multi-mode-row:nth-child(2) .multi-mode-summary-items").textContent'),
      /Lower bound: 1.*Upper bound: 5/);
    await s.evaluate(`(() => {
      const lower = document.querySelector('[aria-label="Row 2.Lower bound"]');
      lower.value = '3';
      lower.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Apply instances');
    await s.wait('window.thresholdResult', 'threshold ranges applied');
    const result = await s.evaluate('thresholdResult.replace.value');
    assert.deepEqual(result.slice(1), [
      {id:'original',filter:'threshold',inputs:{input:'source'},
        options:{field:['POINTS','pressure'],lower:1,upper:5}},
      {id:'threshold_3_5',filter:'threshold',inputs:{input:'source'},
        options:{field:['POINTS','pressure'],lower:3,upper:5}},
    ]);
  } finally {
    await s.close();
  }
});

test('dataset array subsets load one association and preserve selections outside the filter', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'passArrays');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'retained',filter:'passArrays',inputs:{input:'source'},options:{pointArrays:['stale']}};
      const documentValue = {version:'schemaxis/1',nodes:[{id:'source',filter:'sphere'},value],scenes:[]};
      const post = studio.api.post.bind(studio.api);
      const wait = studio.api.waitForJob.bind(studio.api);
      studio.api.post = (path, body) => path === '/api/inspect-input' ? Promise.resolve({job:'array-subset'}) : post(path,body);
      studio.api.waitForJob = id => id === 'array-subset' ? Promise.resolve(
        {result:{observation:{fields:{POINTS:{pressure:{},velocity:{}},CELLS:{density:{}}}}}}) : wait(id);
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/nodes/1',value}}).then(result=>window.arrayResult=result);
    })()`);
    const picker = '[aria-label="Filter passArrays.options.pointArrays"]';
    await s.wait(`document.querySelector(${JSON.stringify(picker)})`, 'point array picker');
    const field = `document.querySelector(${JSON.stringify(picker)}).closest('.operation-field')`;
    await s.evaluate(`[...${field}.querySelectorAll('button')].find(b=>b.textContent==='Load array names').click()`);
    await s.wait(`${field}.querySelector('[data-name="pressure"]')`, 'reported point arrays');
    assert.equal(await s.evaluate(`Boolean(${field}.querySelector('[data-name="density"]'))`), false);
    await s.evaluate(`(() => {
      const input = document.querySelector(${JSON.stringify(picker)});
      input.value = 'velocity';
      input.dispatchEvent(new Event('input',{bubbles:true}));
      [...${field}.querySelectorAll('button')].find(b=>b.textContent==='Select shown').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')].find(b=>b.textContent==='Apply changes').click();
    })()`);
    await s.wait('window.arrayResult', 'array selection applied');
    assert.deepEqual(await s.evaluate('arrayResult.replace.value.options.pointArrays'), ['stale','velocity']);
  } finally {
    await s.close();
  }
});

test('FreeCAD drawing views use the reusable static subset picker', {timeout:120000}, async () => {
  const s = await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.freecad.drawing/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'freecad',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:views');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const documentValue = {version,views:['top']};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/views',value:documentValue.views}}).then(result=>window.viewsResult=result);
    })()`);
    await s.wait('document.querySelector(\'.operation-dialog [data-name="front"]\')', 'declared view choices');
    await s.evaluate(`(() => {
      const picker = document.querySelector('.operation-dialog .scene-subset');
      const search = picker.querySelector('input[type=search]');
      search.value = 'front';
      search.dispatchEvent(new Event('input',{bubbles:true}));
      [...picker.querySelectorAll('button')].find(b=>b.textContent==='Select shown').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')].find(b=>b.textContent==='Apply changes').click();
    })()`);
    await s.wait('window.viewsResult', 'view subset applied');
    assert.deepEqual(await s.evaluate('viewsResult.replace.value'), ['top','front']);
  } finally {
    await s.close();
  }
});

test('FreeCAD box instances inherit the captured height and origin', {timeout:120000}, async () => {
  const s = await launch({provider:'freecad'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.freecad/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'freecad',version});
      const item = meta.addCatalogue.items.find(row => row.operation === 'box');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'original',filter:'box',options:{length:10,width:20,height:30,origin:[1,2,3]}};
      const documentValue = {version,nodes:[value]};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/nodes/0',value}}).then(result=>window.boxResult=result);
    })()`);
    await s.wait('document.querySelector(".operation-dialog")', 'Box Settings');
    const click = label => s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await click('Switch to multi-mode');
    await click('Add instance');
    await s.evaluate(`(() => {
      const length = document.querySelector('[aria-label="Row 2.Length"]');
      length.value = '15';
      length.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Apply instances');
    await s.wait('window.boxResult', 'box instances applied');
    assert.deepEqual(await s.evaluate('boxResult.replace.value.map(node => [node.id, node.options])'), [
      ['original',{length:10,width:20,height:30,origin:[1,2,3]}],
      ['box_15_20_30',{length:15,width:20,height:30,origin:[1,2,3]}],
    ]);
  } finally {
    await s.close();
  }
});

test('Octave output subset chooses existing table nodes in authored order', {timeout:120000}, async () => {
  const s = await launch({provider:'octave'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.octave/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'octave',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:outputs');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const documentValue = {version, nodes:[{id:'first',filter:'sequence'},{id:'second',filter:'wave'}],
        outputs:['second']};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/outputs',value:documentValue.outputs}}).then(result=>window.outputsResult=result);
    })()`);
    await s.wait('document.querySelector(\'.operation-dialog [data-name="first"]\')', 'table outputs');
    await s.evaluate(`(() => {
      document.querySelector('.operation-dialog [data-name="first"]').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')].find(b => b.textContent === 'Apply changes').click();
    })()`);
    await s.wait('window.outputsResult', 'output subset applied');
    assert.deepEqual(await s.evaluate('outputsResult.replace.value'), ['second','first']);
  } finally {
    await s.close();
  }
});

test('native Extract Block keeps full paths scoped to the selected assembly', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'pvExtractBlock');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'extract',filter:'pvExtractBlock',inputs:{Input:'source'},
        options:{Assembly:'Assembly',Selectors:['//other']}};
      const documentValue = {version:'schemaxis/1',nodes:[{id:'source',filter:'sphere'},value],scenes:[]};
      const post = studio.api.post.bind(studio.api);
      const wait = studio.api.waitForJob.bind(studio.api);
      studio.api.post = (path, body) => path === '/api/inspect-input' ? Promise.resolve({job:'block-paths'}) : post(path,body);
      studio.api.waitForJob = id => id === 'block-paths' ? Promise.resolve({result:{assemblies:{
        Assembly:[{depth:2,selector:'/Root/left/wall'},{depth:2,selector:'/Root/right/wall'}],
        Hierarchy:[{depth:1,selector:'/Root/hierarchy'}]}}}) : wait(id);
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/nodes/1',value}}).then(result=>window.extractResult=result);
    })()`);
    const click = label => s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.wait('document.querySelector(".operation-dialog .scene-subset")', 'block path picker');
    await click('Load block paths');
    await s.wait('document.querySelector(\'[data-name="/Root/right/wall"]\')', 'paths in the selected assembly');
    assert.equal(await s.evaluate('Boolean(document.querySelector(\'[data-name="/Root/hierarchy"]\'))'), false);
    await s.evaluate('document.querySelector(\'[data-name="/Root/left/wall"]\').click()');
    await click('Apply changes');
    await s.wait('window.extractResult', 'block selectors applied');
    assert.deepEqual(await s.evaluate('extractResult.replace.value.options'),
      {Assembly:'Assembly', Selectors:['//other','/Root/left/wall']});
  } finally {
    await s.close();
  }
});

test('compact rows leave untouched native defaults omitted', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'pvWarpByVector');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'original',filter:'pvWarpByVector',inputs:{Input:'source'},options:{}};
      const documentValue = {version:'schemaxis/1',nodes:[{id:'source',filter:'sphere'},value],scenes:[]};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/nodes/1',value}}).then(result=>window.warpResult=result);
    })()`);
    const click = label => s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'warp Settings');
    await click('Switch to multi-mode');
    await click('Add instance');
    await click('Apply instances');
    await s.wait('window.warpResult', 'warp instances applied');
    assert.deepEqual(await s.evaluate('warpResult.replace.value.slice(1).map(node => node.options ?? {})'), [{},{}]);
  } finally {
    await s.close();
  }
});

test('generated reader picker offers disabled arrays from the declared native domain', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'pvXMLUnstructuredGridReader');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'reader',filter:'pvXMLUnstructuredGridReader',
        options:{FileName:['/fixtures/input.vtu'],PointArrayStatus:['node_id']}};
      const documentValue = {version:'schemaxis/1',nodes:[value]};
      const post = studio.api.post.bind(studio.api);
      const wait = studio.api.waitForJob.bind(studio.api);
      studio.api.post = (path, body) => path === '/api/inspect-input' ? Promise.resolve({job:'reader-names'}) : post(path,body);
      studio.api.waitForJob = id => id === 'reader-names' ? Promise.resolve({result:{
        readerChoices:{PointArrayStatus:['node_id','displacement']}, observation:{fields:{POINTS:{node_id:{}}}},
      }}) : wait(id);
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/nodes/0',value}}).then(result=>window.readerResult=result);
    })()`);
    const picker = '[aria-label="Filter pvXMLUnstructuredGridReader.options.PointArrayStatus"]';
    await s.wait(`document.querySelector(${JSON.stringify(picker)})`, 'reader array picker');
    const field = `document.querySelector(${JSON.stringify(picker)}).closest('.operation-field')`;
    await s.evaluate(`[...${field}.querySelectorAll('button')].find(b=>b.textContent==='Load array names').click()`);
    await s.wait(`${field}.querySelector('[data-name="displacement"]')`, 'disabled array offered');
    await s.evaluate(`${field}.querySelector('[data-name="displacement"]').click()`);
    await s.evaluate(`[...document.querySelectorAll('.operation-dialog .dialog-footer button')]
      .find(b=>b.textContent==='Apply changes').click()`);
    await s.wait('window.readerResult', 'reader selection applied');
    assert.deepEqual(await s.evaluate('readerResult.replace.value.options.PointArrayStatus'), ['node_id','displacement']);
  } finally {
    await s.close();
  }
});

test('generated file-reader rows edit the source file and retain array selections', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'pvXMLUnstructuredGridReader');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'reader',filter:'pvXMLUnstructuredGridReader',
        options:{FileName:['/fixtures/input.vtu'],PointArrayStatus:['node_id']}};
      const documentValue = {version:'schemaxis/1',nodes:[value]};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/nodes/0',value}}).then(result=>window.fileReaderResult=result);
    })()`);
    const click = label => s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'reader Settings');
    await click('Switch to multi-mode');
    await click('Add instance');
    await s.evaluate(`(() => {
      const file = document.querySelector('[aria-label="Row 2.Source files[0]"]');
      file.value = '/fixtures/next.vtu';
      file.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Apply instances');
    await s.wait('window.fileReaderResult', 'reader sources applied');
    assert.deepEqual(await s.evaluate('fileReaderResult.replace.value.map(node => [node.id,node.options])'), [
      ['reader',{FileName:['/fixtures/input.vtu'],PointArrayStatus:['node_id']}],
      ['pvXMLUnstructuredGridReader_next_vtu',{FileName:['/fixtures/next.vtu'],PointArrayStatus:['node_id']}],
    ]);
  } finally {
    await s.close();
  }
});

test('writer loss choices retain existing acknowledgements and require explicit selection', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'pvWriteCSVWriter');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'csv',node:'source',writer:'pvWriteCSVWriter',acceptLosses:['previous-note']};
      const documentValue = {version:'schemaxis/1',nodes:[{id:'source',filter:'sphere'}],
        scenes:[{id:'main',exports:[value]}]};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/scenes/0/exports/0',value}}).then(result=>window.writerResult=result);
    })()`);
    await s.wait('document.querySelector(\'.operation-dialog [data-name="topology"]\')', 'loss choices');
    assert.equal(await s.evaluate('document.querySelector(\'[data-name="topology"]\').getAttribute("aria-pressed")'), 'false');
    await s.evaluate(`(() => {
      document.querySelector('[data-name="topology"]').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')]
        .find(b=>b.textContent==='Apply changes').click();
    })()`);
    await s.wait('window.writerResult', 'loss acknowledgement applied');
    assert.deepEqual(await s.evaluate('writerResult.replace.value.acceptLosses'), ['previous-note','topology']);
  } finally {
    await s.close();
  }
});

test('multi-input subsets keep explicit port references and input order', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'group');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'combined',filter:'group',inputs:{input:[{node:'left',port:0},'right']}};
      const documentValue = {version:'schemaxis/1',nodes:['left','right','middle'].map(id=>({id,filter:'sphere'})).concat(value)};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/nodes/3',value}}).then(result=>window.groupResult=result);
    })()`);
    await s.wait('document.querySelector(\'.operation-dialog [data-name="middle"]\')', 'offered pipeline input');
    assert.equal(await s.evaluate('document.querySelector(\'[data-name="left:port 0"]\').getAttribute("aria-pressed")'), 'true');
    await s.evaluate(`(() => {
      document.querySelector('[data-name="middle"]').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')]
        .find(b=>b.textContent==='Apply changes').click();
    })()`);
    await s.wait('window.groupResult', 'group inputs applied');
    assert.deepEqual(await s.evaluate('groupResult.replace.value.inputs.input'), [{node:'left',port:0},'right','middle']);
  } finally {
    await s.close();
  }
});

test('compact rows can choose separate upstream datasets and name new filters from their inputs', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'surface');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'saved',filter:'surface',inputs:{input:'left'}};
      const documentValue = {version:'schemaxis/1',nodes:[{id:'left',filter:'sphere'},
        {id:'right',filter:'sphere'},value]};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/nodes/2',value}}).then(result=>window.surfaceResult=result);
    })()`);
    await s.wait('document.querySelector(".operation-dialog")', 'Surface Settings');
    const click = label => s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await click('Switch to multi-mode');
    await click('Add instance');
    await s.evaluate(`(() => {
      const select = document.querySelector('select[aria-label="Row 2.Input"]');
      select.value = 'right';
      select.dispatchEvent(new Event('change',{bubbles:true}));
    })()`);
    assert.equal(await s.evaluate('document.querySelector(\'[aria-label="Row 2 Name"]\').value'), 'surface_right');
    await click('Apply instances');
    await s.wait('window.surfaceResult', 'separate upstream datasets applied');
    const result = await s.evaluate('surfaceResult.replace.value');
    assert.deepEqual(result.slice(2), [
      {id:'saved',filter:'surface',inputs:{input:'left'}},
      {id:'surface_right',filter:'surface',inputs:{input:'right'}},
    ]);
  } finally {
    await s.close();
  }
});

test('file subsets append paths in selection order across folders', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version:'schemaxis/1'});
      const item = meta.addCatalogue.items.find(row => row.operation === 'pvXMLUnstructuredGridReader');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'reader',filter:'pvXMLUnstructuredGridReader',options:{FileName:['/fixtures/start.vtu']}};
      const api = {get: (...args) => {
        if (args[0] !== '/api/input-files') return studio.api.get(...args);
        const directory = args[1].directory;
        const file = (name) => ({name,path:directory+'/'+name,directory:false});
        return Promise.resolve({directory,parent:'/fixtures',entries: directory === '/fixtures'
          ? [file('a.vtu'),file('b.vtu'),{name:'next',path:'/fixtures/next',directory:true}]
          : [file('c.vtu')]});
      }};
      void configureOperation({...studio,api},item,meta.addCatalogue.definitions,
        ()=>({version:'schemaxis/1',nodes:[value]}),undefined,
        {existing:{pointer:'/nodes/0',value}}).then(result=>window.filesResult=result);
    })()`);
    const click = (scope, label) => s.evaluate(`[...document.querySelectorAll(${JSON.stringify(scope+' button')})]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'reader Settings');
    await click('.operation-dialog', 'Browse for several files…');
    await s.wait('document.querySelector(\'[data-name="/fixtures/b.vtu"]\')', 'first folder files');
    await s.evaluate(`(() => {
      document.querySelector('[data-name="/fixtures/b.vtu"]').click();
      document.querySelector('[data-name="/fixtures/a.vtu"]').click();
      document.querySelector('button[title="/fixtures/next"]').click();
    })()`);
    await s.wait('document.querySelector(\'[data-name="/fixtures/next/c.vtu"]\')', 'second folder files');
    await s.evaluate('document.querySelector(\'[data-name="/fixtures/next/c.vtu"]\').click()');
    await click('.file-dialog', 'Add selected files');
    await click('.operation-dialog', 'Apply changes');
    await s.wait('window.filesResult', 'file subset applied');
    assert.deepEqual(await s.evaluate('filesResult.replace.value.options.FileName'),
      ['/fixtures/start.vtu','/fixtures/b.vtu','/fixtures/a.vtu','/fixtures/next/c.vtu']);
  } finally {
    await s.close();
  }
});

test('ExifTool clock assumptions choose names from declared camera groups', {timeout:120000}, async () => {
  const s = await launch({provider:'exiftool'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.exiftool/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'exiftool',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:assumeCorrect');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = ['primary'];
      const documentValue = {version,operation:'reconcileTime',groups:{by:'declared',
        members:[{group:'primary',items:['one']},{group:'secondary',items:['two']}]},assumeCorrect:value};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/assumeCorrect',value}}).then(result=>window.clockResult=result);
    })()`);
    await s.wait('document.querySelector(\'.operation-dialog [data-name="secondary"]\')', 'declared camera groups');
    await s.evaluate(`(() => {
      document.querySelector('.operation-dialog [data-name="secondary"]').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')]
        .find(button => button.textContent === 'Apply changes').click();
    })()`);
    await s.wait('window.clockResult', 'camera groups applied');
    assert.deepEqual(await s.evaluate('clockResult.replace.value'), ['primary','secondary']);
  } finally {
    await s.close();
  }
});

test('Blender graph members use shared multi-mode and preserve the original graph links', {timeout:120000}, async () => {
  const s = await launch({provider:'blender'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.blender.production/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'blender',version});
      const root = meta.addCatalogue.items.find(row => row.id === 'document:production');
      const schema = root.schema.properties.materialGraphs.items;
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {id:'material',nodes:[{id:'original',kind:'value',properties:{value:0.25}},
        {id:'calc',kind:'math'}],links:[{from:{node:'original',socket:'value'},to:{node:'calc',socket:'a'}}]};
      const documentValue = {version,production:{materialGraphs:[value]}};
      void configureOperation(studio,{id:'document:materialGraph',title:'Material graph',schema,at:'/production/materialGraphs/-'},
        meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/production/materialGraphs/0',value}}).then(result=>window.graphResult=result);
    })()`);
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'material graph');
    await click('Create sibling instances…');
    await s.wait('document.querySelector(".multi-mode-row")', 'compact graph member');
    await click('Add instance');
    await s.evaluate(`(() => {
      const input = document.querySelector('[aria-label="Row 2.Value"]');
      input.value = '0.5';
      input.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Use instances');
    await click('Apply changes');
    await s.wait('window.graphResult', 'material graph applied');
    const graph = await s.evaluate('graphResult.replace.value');
    assert.deepEqual(graph.links, [{from:{node:'original',socket:'value'},to:{node:'calc',socket:'a'}}]);
    assert.deepEqual(graph.nodes, [
      {id:'original',kind:'value',properties:{value:0.25}},
      {id:'calc',kind:'math'},
      {id:'value_0_5',kind:'value',properties:{value:0.5}},
    ]);
  } finally {
    await s.close();
  }
});

test('Blender view-layer subsets are scoped to the scene being edited', {timeout:120000}, async () => {
  const s = await launch({provider:'blender'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.blender/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'blender',version});
      const scene = meta.addCatalogue.items.find(row => row.id === 'document:scenes').schema;
      const schema = scene.properties.production.properties.viewLayers;
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = [{id:'details',aovs:['warm']}];
      const documentValue = {version,scenes:[
        {id:'first',production:{renderAovs:[{id:'different',type:'value'}]}},
        {id:'second',production:{renderAovs:[{id:'warm',type:'value'},{id:'cool',type:'value'}],viewLayers:value}},
      ]};
      const at = '/scenes/1/production/viewLayers';
      void configureOperation(studio,{id:'document:viewLayers',title:'View layers',schema,at},
        meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:at,value}}).then(result=>window.viewLayersResult=result);
    })()`);
    await s.wait('document.querySelector(\'.operation-dialog [data-name="cool"]\')', 'second scene AOVs');
    assert.equal(await s.evaluate('!!document.querySelector(\'.operation-dialog [data-name="different"]\')'), false);
    await s.evaluate(`(() => {
      document.querySelector('.operation-dialog [data-name="cool"]').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')]
        .find(button => button.textContent === 'Apply changes').click();
    })()`);
    await s.wait('window.viewLayersResult', 'scene subset applied');
    assert.deepEqual(await s.evaluate('viewLayersResult.replace.value'), [{id:'details',aovs:['warm','cool']}]);
  } finally {
    await s.close();
  }
});

test('Blender sparse attributes keep their typed shape and share Names with UV maps', {timeout:120000}, async () => {
  const s = await launch({provider:'blender'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.blender.production/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'blender',version});
      const root = meta.addCatalogue.items.find(row => row.id === 'document:production');
      const schema = root.schema.properties.meshData.items;
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {object:'panel',attributes:[
        {name:'constant',kind:'float',mode:'constant',domain:'POINT',value:1},
        {name:'edited',kind:'float',mode:'sparse',domain:'POINT',default:1,entries:[{index:0,value:3}]},
      ],uvMaps:[{name:'Float_POINT_2_5',method:'planar'}]};
      const documentValue = {version,production:{meshData:[value]}};
      const at = '/production/meshData/0';
      void configureOperation(studio,{id:'document:meshData',title:'Mesh data',schema,at},
        meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:at,value}}).then(result=>window.meshResult=result);
    })()`);
    await s.wait('document.querySelector(".operation-dialog")', 'mesh settings');
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .filter(button => button.textContent === 'Create sibling instances…')[1].click()`);
    await s.wait('document.querySelector(".multi-mode-row")', 'typed attribute rows');
    await click('Add instance');
    await s.evaluate(`(() => {
      const input = document.querySelector('[aria-label="Row 2.Default"]');
      input.value = '2.5';
      input.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Use instances');
    await click('Apply changes');
    await s.wait('window.meshResult', 'mesh data applied');
    const attributes = await s.evaluate('meshResult.replace.value.attributes');
    assert.deepEqual(attributes[2], {name:'Float_POINT_2_5_2',kind:'float',mode:'sparse',
      domain:'POINT',default:2.5,entries:[{index:0,value:3}]});
  } finally {
    await s.close();
  }
});

test('Workbench opens nested authoring from Edit settings at the selected graph member', {timeout:120000}, async () => {
  const s = await launch({provider:'blender'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const graph = {id:'paint',nodes:[{id:'starting',kind:'value',properties:{value:0.25}},
        {id:'shader',kind:'principled'},{id:'out',kind:'output'}],
        links:[{from:{node:'starting',socket:'value'},to:{node:'shader',socket:'roughness'}},
          {from:{node:'shader',socket:'shader'},to:{node:'out',socket:'surface'}}]};
      const input = {version:'schemaxis.blender.production/1',id:'model',prepareOnly:true,
        cameras:[{direction:[1,-2,1]}],production:{materialGraphs:[graph],
          objects:[{id:'panel',kind:'mesh',material:'paint',vertices:[[0,0,0],[1,0,0],[0,1,0]],faces:[[0,1,2]]}]}};
      const record = await studio.api.post('/api/documents',{action:'new',provider:'blender',name:'Graph settings',document:input});
      await studio.refresh();
      studio.windows.open('workbench',{document:record.id});
    })()`);
    await s.wait('studio.windows.active()?.window.editor.getValue().includes("starting")', 'production input');
    await s.evaluate(`(() => {
      const editor = studio.windows.active().window.editor;
      editor.revealPointer('/production/materialGraphs/0/nodes/0/properties/value');
      editor.focus();
    })()`);
    const settings = '.wb-editor-tools [data-action="edit-settings"]:not(:disabled)';
    await s.wait(`document.querySelector(${JSON.stringify(settings)})`, 'production Settings action');
    await s.clickSelector(settings);
    await s.wait('document.querySelector(".operation-dialog")', 'owning production Settings');
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.evaluate(`(() => {
      const field = document.querySelector('[aria-label="production.materialGraphs[0].nodes[0].id"]');
      const row = field.closest('.operation-array-item');
      for (let parent = row.parentElement; parent; parent = parent.parentElement)
        if (parent.tagName === 'DETAILS') parent.open = true;
      [...row.querySelectorAll('button')].find(button => button.textContent === 'Create sibling instances…').click();
    })()`);
    await s.wait('document.querySelector(".multi-mode-row")', 'compact graph member');
    await click('Add instance');
    await click('Use instances');
    const draft = await s.evaluate(`(() => ({
      errors: [...document.querySelectorAll('[role=alert],.toast')].map(element => element.textContent).filter(Boolean),
      dialogs: [...document.querySelectorAll('.operation-dialog')].map(dialog => dialog.getAttribute('aria-label')),
      names: [...document.querySelectorAll('.operation-dialog input')].filter(input => /Name|\\.id$/.test(input.getAttribute('aria-label') || ''))
        .map(input => [input.getAttribute('aria-label'), input.value])
    }))()`);
    assert.ok(draft.names.some(([, value])=>value === 'value_0_25'), JSON.stringify(draft));
    await click('Apply changes');
    await s.wait('!document.querySelector(".operation-dialog") || document.querySelector(".operation-wizard > .operation-error")?.textContent', 'apply result');
    assert.equal(await s.evaluate('document.querySelector(".operation-wizard > .operation-error")?.textContent || ""'), '');
    const observed = await s.evaluate(`(() => ({
      source: studio.windows.active().window.editor.getDocument(),
      notice: [...document.querySelectorAll('[role=alert],.toast')].map(element => element.textContent).filter(Boolean)
    }))()`);
    const nodes = observed.source.production.materialGraphs[0].nodes;
    assert.equal(nodes.length, 4, JSON.stringify({nodes,notice:observed.notice}));
    assert.equal(nodes[3].id, 'value_0_25');
  } finally {
    await s.close();
  }
});

test('ngspice probes pick from authored circuit terminals and named branches', {timeout:120000}, async () => {
  const s = await launch({provider:'ngspice'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.ngspice/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'ngspice',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:circuit');
      const schema = item.schema.anyOf[1];
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {source:'drive',resistors:[{name:'rload',a:'drive',b:'out',resistance:50}],
        capacitors:[{name:'cfilt',a:'out',b:'0',capacitance:0.001}],probes:['out'],branchProbes:['cfilt']};
      const documentValue = {version,operation:'acSweep',circuit:value};
      void configureOperation(studio,{...item,schema},meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/circuit',value}}).then(result=>window.circuitResult=result);
    })()`);
    await s.wait('document.querySelector(\'.operation-dialog [data-name="rload"]\')', 'declared branch names');
    assert.equal(await s.evaluate('!!document.querySelector(\'.operation-dialog [data-name="0"]\')'), false);
    await s.evaluate(`(() => {
      document.querySelector('.operation-dialog [data-name="drive"]').click();
      document.querySelector('.operation-dialog [data-name="rload"]').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')]
        .find(button => button.textContent === 'Apply changes').click();
    })()`);
    await s.wait('window.circuitResult', 'circuit probes applied');
    const circuit = await s.evaluate('circuitResult.replace.value');
    assert.deepEqual(circuit.probes, ['out','drive']);
    assert.deepEqual(circuit.branchProbes, ['cfilt','rload']);
  } finally {
    await s.close();
  }
});

test('Oracle composite key selection keeps table scope and authored key order', {timeout:120000}, async () => {
  const s = await launch({provider:'oracle'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.oracle/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'oracle',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:tables');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = [
        {name:'first',columns:[{name:'different',type:'number'}],primaryKey:['different']},
        {name:'second',columns:['tenant','entry'].map(name=>({name,type:'number'})),primaryKey:['entry']},
      ];
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>({version,tables:value}),undefined,
        {existing:{pointer:'/tables',value}}).then(result=>window.keysResult=result);
    })()`);
    await s.wait('document.querySelector(\'.operation-dialog [data-name="tenant"]\')', 'table columns');
    await s.evaluate(`(() => {
      document.querySelector('.operation-dialog [data-name="tenant"]').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')]
        .find(button => button.textContent === 'Apply changes').click();
    })()`);
    await s.wait('window.keysResult', 'table keys applied');
    assert.deepEqual(await s.evaluate('keysResult.replace.value.map(table => table.primaryKey)'),
      [['different'], ['entry','tenant']]);
  } finally {
    await s.close();
  }
});

test('SQLite grouping offers only qualified columns from the active tables', {timeout:120000}, async () => {
  const s = await launch({provider:'sqlite'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.sqlite/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'sqlite',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:groupBy');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const table = (name, names) => ({name,columns:names.map(column=>({name:column,type:'TEXT'}))});
      const value = ['sale.date'];
      const documentValue = {version,operation:'summarise',from:'sale',join:{table:'region'},
        tables:[table('sale',['date']),table('region',['district']),table('other',['ignore'])],groupBy:value};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>documentValue,undefined,
        {existing:{pointer:'/groupBy',value}}).then(result=>window.groupByResult=result);
    })()`);
    await s.wait('document.querySelector(\'.operation-dialog [data-name="region.district"]\')', 'active table columns');
    assert.equal(await s.evaluate('!!document.querySelector(\'.operation-dialog [data-name="other.ignore"]\')'), false);
    await s.evaluate(`(() => {
      document.querySelector('.operation-dialog [data-name="region.district"]').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')]
        .find(button => button.textContent === 'Apply changes').click();
    })()`);
    await s.wait('window.groupByResult', 'grouping columns applied');
    assert.deepEqual(await s.evaluate('groupByResult.replace.value'), ['sale.date','region.district']);
  } finally {
    await s.close();
  }
});

test('ngspice component multi-mode is available for sweeps and excluded for RC steps', {timeout:120000}, async () => {
  const s = await launch({provider:'ngspice'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.ngspice/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'ngspice',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:circuit');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const circuit = {source:'in',resistors:[{name:'load',a:'in',b:'out',resistance:50}],
        capacitors:[{name:'filt',a:'out',b:'0',capacitance:0.001}],probes:['out']};
      window.openCircuit = operation => configureOperation(studio,{...item,schema:item.schema.anyOf[0]},
        meta.addCatalogue.definitions,()=>({version,operation,circuit}),undefined,
        {existing:{pointer:'/circuit',value:circuit}});
      void window.openCircuit('dcSweep').then(result=>window.circuitModes=result);
    })()`);
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)} && !button.hidden).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'circuit settings');
    await click('Create sibling instances…');
    await s.wait('document.querySelector(".multi-mode-row")', 'resistor rows');
    await click('Add instance');
    await s.evaluate(`(() => {
      const input = document.querySelector('[aria-label="Row 2.Resistance"]');
      input.value = '100';
      input.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Use instances');
    await click('Apply changes');
    await s.wait('window.circuitModes', 'separate resistors applied');
    assert.deepEqual(await s.evaluate('circuitModes.replace.value.resistors[1]'),
      {name:'r_in_out',a:'in',b:'out',resistance:100});
    await s.evaluate(`void window.openCircuit('rcStep')`);
    await s.wait('document.querySelector(".operation-dialog")', 'RC-step settings');
    assert.equal(await s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .some(button => button.textContent === 'Create sibling instances…')`), false);
  } finally {
    await s.close();
  }
});

test('Premiere coverage requirements combine named track subsets and compact time windows', {timeout:120000}, async () => {
  const s = await launch({provider:'premiere'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.premiere/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'premiere',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:requirements');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = [{name:'Programme coverage',tracks:['Dialogue'],startFrame:0,frameCount:60}];
      const input = {version,tracks:[{name:'Dialogue'},{name:'Music'}],requirements:value};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>input,undefined,
        {existing:{pointer:'/requirements',value}}).then(result=>window.coverageResult=result);
    })()`);
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)} && !button.hidden).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'coverage requirements');
    await click('Create sibling instances…');
    await s.wait('document.querySelector(".multi-mode-row")', 'compact requirements');
    await click('Add instance');
    await s.evaluate(`(() => {
      const row = document.querySelector('.multi-mode-row:nth-child(2)');
      row.querySelector('[data-name="Music"]').click();
      const start = row.querySelector('[aria-label="Row 2.Start frame"]');
      start.value = '15';
      start.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Use instances');
    await click('Apply changes');
    await s.wait('window.coverageResult', 'coverage requirements applied');
    const requirements = await s.evaluate('coverageResult.replace.value');
    assert.equal(requirements[0].name, 'Programme coverage');
    assert.deepEqual(requirements[1], {name:'coverage_Dialogue_Music_15_60',
      tracks:['Dialogue','Music'],startFrame:15,frameCount:60});
  } finally {
    await s.close();
  }
});

test('ExifTool media siblings refuse duplicate file selection within the collection', {timeout:120000}, async () => {
  const s = await launch({provider:'exiftool'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.exiftool/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'exiftool',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:photos');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = [{id:'original',path:'/photos/before.jpg'}];
      const input = {version,photos:value};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>input,undefined,
        {existing:{pointer:'/photos',value}}).then(result=>window.photosResult=result);
    })()`);
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)} && !button.hidden).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'photo list');
    await click('Create sibling instances…');
    await s.wait('document.querySelector(".multi-mode-row")', 'media rows');
    await click('Add instance');
    await click('Use instances');
    await s.wait(`[...document.querySelectorAll('.operation-dialog .operation-error')]
      .some(error => error.textContent === 'Each Source file must be distinct in this collection.')`, 'duplicate source error');
    await s.evaluate(`(() => {
      const input = document.querySelector('[aria-label="Row 2.Source file"]');
      input.value = '/photos/after.jpg';
      input.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Use instances');
    await click('Apply changes');
    await s.wait('window.photosResult', 'separate media paths applied');
    assert.deepEqual(await s.evaluate('photosResult.replace.value'), [
      {id:'original',path:'/photos/before.jpg'},{id:'photo_after_jpg',path:'/photos/after.jpg'},
    ]);
  } finally {
    await s.close();
  }
});

test('Gnuplot series keep their label field across compact rows', {timeout:120000}, async () => {
  const s = await launch({provider:'gnuplot'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.gnuplot/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'gnuplot',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:series');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = [{label:'Measured curve',x:'time',y:'temperature'}];
      const input = {version,series:value};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>input,undefined,
        {existing:{pointer:'/series',value}}).then(result=>window.seriesResult=result);
    })()`);
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)} && !button.hidden).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'plot series');
    await click('Create sibling instances…');
    await s.wait('document.querySelector(".multi-mode-row")', 'series rows');
    await click('Add instance');
    await s.evaluate(`(() => {
      const input = document.querySelector('[aria-label="Row 2.Y"]');
      input.value = 'pressure';
      input.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Use instances');
    await click('Apply changes');
    await s.wait('window.seriesResult', 'plot series applied');
    assert.deepEqual(await s.evaluate('seriesResult.replace.value'), [
      {label:'Measured curve',x:'time',y:'temperature'},
      {label:'series_time_pressure',x:'time',y:'pressure'},
    ]);
  } finally {
    await s.close();
  }
});

test('Oracle column multi-mode resolves referenced schemas and preserves the primary key', {timeout:120000}, async () => {
  const s = await launch({provider:'oracle'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.oracle/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'oracle',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:tables');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = [{name:'records',columns:[{name:'key',type:'number'}],primaryKey:['key']}];
      const input = {version,tables:value};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>input,undefined,
        {existing:{pointer:'/tables',value}}).then(result=>window.columnsResult=result);
    })()`);
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)} && !button.hidden).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'Oracle tables');
    await click('Create sibling instances…');
    await s.wait('document.querySelector(".multi-mode-row")', 'columns');
    await click('Add instance');
    await s.evaluate(`(() => {
      const type = document.querySelector('[aria-label="Row 2.Type"]');
      type.value = [...type.options].find(option => option.textContent === '"varchar2"').value;
      type.dispatchEvent(new Event('change',{bubbles:true}));
      const length = document.querySelector('[aria-label="Row 2.Length"]');
      length.value = '40';
      length.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Use instances');
    await click('Apply changes');
    await s.wait('window.columnsResult', 'table columns applied');
    const table = await s.evaluate('columnsResult.replace.value[0]');
    assert.deepEqual(table.primaryKey, ['key']);
    assert.deepEqual(table.columns, [{name:'key',type:'number'},{name:'column_varchar2_40',type:'varchar2',length:40}]);
  } finally {
    await s.close();
  }
});

test('Graphviz Workbench edits ordinary nodes and keeps lowercase identifiers and edges', {timeout:120000}, async () => {
  const s = await launch({provider:'graphviz'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const input = {version:'schemaxis.graphviz/1',operation:'layout',
        nodes:[{id:'left',label:'Left'},{id:'right',label:'Right'}],
        edges:[{source:'left',target:'right'}]};
      const record=await studio.api.post('/api/documents',{action:'new',provider:'graphviz',name:'Plain graph nodes',document:input});
      await studio.refresh();
      studio.windows.open('workbench',{document:record.id});
    })()`);
    await s.wait('studio.windows.active()?.window.editor.getValue().includes("Left")', 'graph input');
    await s.evaluate(`(() => {
      const editor=studio.windows.active().window.editor;
      editor.revealPointer('/nodes/0/label');
      editor.focus();
    })()`);
    const settings = '.wb-editor-tools [data-action="edit-settings"]:not(:disabled)';
    await s.wait(`document.querySelector(${JSON.stringify(settings)})`, 'graph node Settings');
    await s.clickSelector(settings);
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)} && !button.hidden).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'graph list settings');
    await click('Create sibling instances…');
    await s.wait('document.querySelector(".multi-mode-row")', 'graph instances');
    await click('Add instance');
    await s.evaluate(`(() => {
      const field = document.querySelector('[aria-label="Row 2.Label"]');
      field.value = 'New-Node';
      field.dispatchEvent(new Event('input',{bubbles:true}));
    })()`);
    await click('Use instances');
    await click('Apply changes');
    await s.wait('studio.windows.active()?.window.editor.getDocument().nodes.length===3', 'new node committed');
    const document = await s.evaluate('studio.windows.active().window.editor.getDocument()');
    assert.deepEqual(document.nodes[2], {id:'node_new_node',label:'New-Node'});
    assert.deepEqual(document.edges, [{source:'left',target:'right'}]);
  } finally {
    await s.close();
  }
});

test('Blender publication Batch varies only the objects and keeps the saved export', {timeout:120000}, async () => {
  const s = await launch({provider:'blender'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.blender.production/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'blender',version});
      const root = meta.addCatalogue.items.find(row => row.id === 'document:production');
      const schema = root.schema.properties.exports;
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = [{id:'saved',objects:['left'],format:'ply',frame:5}];
      const input = {version,production:{objects:[{id:'left'},{id:'right'}],exports:value}};
      const at = '/production/exports';
      void configureOperation(studio,{id:'document:exports',title:'Exports',schema,at},
        meta.addCatalogue.definitions,()=>input,undefined,{existing:{pointer:at,value}})
        .then(result=>window.exportsResult=result);
    })()`);
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)} && !button.hidden).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'export settings');
    await click('Create sibling instances…');
    await s.wait('document.querySelector(".multi-mode-batch-picker [data-name=right]")', 'Batch object choices');
    await s.evaluate(`(() => {
      document.querySelector('.multi-mode-batch').open = true;
      document.querySelector('.multi-mode-batch-picker [data-name=right]').click();
    })()`);
    await click('One instance per selected item');
    assert.match(await s.evaluate('document.querySelector(".multi-mode [role=alert]").textContent'), /already uses left/);
    await s.evaluate(`document.querySelector('.multi-mode-batch-picker [data-name=left]').click()`);
    await click('One instance per selected item');
    await click('Use instances');
    await click('Apply changes');
    await s.wait('window.exportsResult', 'distinct exports applied');
    assert.deepEqual(await s.evaluate('exportsResult.replace.value'), [
      {id:'saved',objects:['left'],format:'ply',frame:5},
      {id:'export_right_ply_5',objects:['right'],format:'ply',frame:5},
    ]);
  } finally {
    await s.close();
  }
});

test('ParaView managed writers keep their writer kind and choose independent data inputs', {timeout:120000}, async () => {
  const s = await launch({provider:'paraview'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'paraview',version});
      const scene = meta.addCatalogue.items.find(row => row.id === 'document:scenes').schema;
      const schema = scene.properties.exports;
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = [{id:'saved',writer:'pvWriteXMLPolyDataWriter',node:'left'}];
      const input = {version,nodes:[{id:'left',filter:'sphere'},{id:'right',filter:'sphere'}],
        scenes:[{id:'result',exports:value}]};
      const at = '/scenes/0/exports';
      void configureOperation(studio,{id:'document:exports',title:'Exports',schema,at},
        meta.addCatalogue.definitions,()=>input,undefined,{existing:{pointer:at,value}})
        .then(result=>window.writerRowsResult=result);
    })()`);
    const click = label => s.evaluate(`[...[...document.querySelectorAll('.operation-dialog')].at(-1).querySelectorAll('button')]
      .find(button => button.textContent === ${JSON.stringify(label)} && !button.hidden).click()`);
    await s.wait('document.querySelector(".operation-dialog")', 'writer settings');
    await click('Create sibling instances…');
    await s.wait('document.querySelector(".multi-mode-row")', 'writer instances');
    await click('Add instance');
    await s.evaluate(`(() => {
      const field = document.querySelector('[aria-label="Row 2.Data"]');
      field.value = 'right';
      field.dispatchEvent(new Event('change',{bubbles:true}));
    })()`);
    await click('Use instances');
    await click('Apply changes');
    await s.wait('window.writerRowsResult', 'writer outputs applied');
    assert.deepEqual(await s.evaluate('writerRowsResult.replace.value'), [
      {id:'saved',writer:'pvWriteXMLPolyDataWriter',node:'left'},
      {id:'export_right',writer:'pvWriteXMLPolyDataWriter',node:'right'},
    ]);
  } finally {
    await s.close();
  }
});

test('Blender material regions offer spline IDs only from their selected object', {timeout:120000}, async () => {
  const s = await launch({provider:'blender'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.blender.production/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'blender',version});
      const root = meta.addCatalogue.items.find(row => row.id === 'document:production');
      const schema = root.schema.properties.materialAssignments;
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = [{kind:'layout',id:'layout',object:'outline',slots:[{id:'paint',material:'paint'}],
        defaultSlot:'paint',regions:[{slot:'paint',selection:{kind:'splines',names:['edge']}}]}];
      const input = {version,production:{materialAssignments:value,objects:[
        {id:'outline',kind:'spline',splines:[{id:'edge'},{id:'island'}]},
        {id:'other',kind:'spline',splines:[{id:'different'}]},
      ]}};
      const at = '/production/materialAssignments';
      void configureOperation(studio,{id:'document:assignments',title:'Assignments',schema,at},
        meta.addCatalogue.definitions,()=>input,undefined,{existing:{pointer:at,value}})
        .then(result=>window.materialResult=result);
    })()`);
    await s.wait('document.querySelector(\'.operation-dialog [data-name="island"]\')', 'selected object splines');
    assert.equal(await s.evaluate('!!document.querySelector(\'.operation-dialog [data-name="different"]\')'), false);
    await s.evaluate(`(() => {
      document.querySelector('.operation-dialog [data-name="island"]').click();
      [...document.querySelectorAll('.operation-dialog .dialog-footer button')]
        .find(button => button.textContent === 'Apply changes').click();
    })()`);
    await s.wait('window.materialResult', 'spline region applied');
    assert.deepEqual(await s.evaluate('materialResult.replace.value[0].regions[0].selection.names'), ['edge','island']);
  } finally {
    await s.close();
  }
});

test('HDF5 CSV columns load from the declared input and preserve selection order', {timeout:120000}, async () => {
  const {mkdtemp, writeFile, rm} = await import('node:fs/promises');
  const {tmpdir} = await import('node:os');
  const {join} = await import('node:path');
  const directory = await mkdtemp(join(tmpdir(), 'studio-hdf5-csv-'));
  const file = join(directory, 'readings.csv');
  const other = join(directory, 'other.csv');
  await writeFile(other, 'voltage,current,temp,pressure;kPa\n10,2,20,100\n');
  await writeFile(file, 'sample;"pressure;kPa";temp\n10;100;20\n');
  const s = await launch({provider:'hdf5'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.hdf5/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'hdf5',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:objects');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const type = {class:'int',bits:32};
      const value = [{path:'/observations',type,shape:[1],
        data:{source:'input',input:'samples',columns:['temp']}}];
      const input = {version,operation:'createFile',file:{name:'out.h5'},objects:value,
        inputs:[{id:'samples',path:${JSON.stringify(file)},format:'csv',delimiter:';'},
          {id:'other',path:${JSON.stringify(other)},format:'csv'}]};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>input,undefined,
        {existing:{pointer:'/objects',value}}).then(result=>window.csvColumnsResult=result);
    })()`);
    const click = label => s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.wait('[...document.querySelectorAll(".operation-dialog button")].some(button=>button.textContent==="Load source names")', 'CSV field picker');
    await click('Load source names');
    await s.wait('[...document.querySelectorAll(".operation-dialog button")].some(button=>button.textContent==="pressure;kPa")', 'reported CSV header');
    await click('pressure;kPa');
    await s.evaluate(`(() => {
      const input = [...document.querySelectorAll('.operation-dialog input')].find(field => field.value === 'samples');
      input.value = 'other';
      input.dispatchEvent(new Event('input', {bubbles: true}));
    })()`);
    assert.equal(await s.evaluate(`[...document.querySelectorAll('.operation-dialog button')]
      .some(button => button.textContent === 'sample')`), false);
    await click('Load source names');
    await s.wait('[...document.querySelectorAll(".operation-dialog button")].some(button=>button.textContent==="voltage")', 'replacement CSV header');
    await click('voltage');
    await click('Apply changes');
    await s.wait('window.csvColumnsResult', 'CSV columns applied');
    assert.deepEqual(await s.evaluate('csvColumnsResult.replace.value[0].data.columns'), ['temp','pressure;kPa','voltage']);
  } finally {
    await s.close();
    await rm(directory, {recursive:true, force:true});
  }
});

test('HDF5 compound fields and comparison paths use source metadata', {
  timeout:120000, skip: !process.env.SCHEMAXIS_HDF5,
}, async () => {
  const {mkdtemp, rm} = await import('node:fs/promises');
  const {tmpdir} = await import('node:os');
  const {join} = await import('node:path');
  const {execFile} = await import('node:child_process');
  const {promisify} = await import('node:util');
  const directory = await mkdtemp(join(tmpdir(), 'studio-hdf5-compound-'));
  const file = join(directory, 'readings.h5');
  const reference = join(directory, 'reference.h5');
  let s;
  try {
    await promisify(execFile)(process.env.SCHEMAXIS_HDF5, ['-c', `import sys, h5py
with h5py.File(sys.argv[1], 'w') as f:
    f.create_dataset('/run/readings', shape=(1,), dtype=[('sample','<i4'),('Druck, kPa','<f8')])
    f.create_dataset('/other', shape=(1,), dtype=[('other','<i4')])
    f['alias'] = h5py.SoftLink('/run/readings')
with h5py.File(sys.argv[2], 'w') as f:
    f.create_dataset('/referenceOnly', data=[1])
`, file, reference]);
    s = await launch({provider:'hdf5'});
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`studio.api.post('/api/setup', {action:'configure', provider:'hdf5', role:'admin',
      location:${JSON.stringify(process.env.SCHEMAXIS_HDF5)}})`);
    await s.evaluate(`(async () => {
      const version = 'schemaxis.hdf5/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'hdf5',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:extracts');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = [{id:'readings',dataset:'/run/readings',format:'csv',fields:['sample']}];
      const input = {version,operation:'extractData',source:${JSON.stringify(file)},extracts:value};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>input,undefined,
        {existing:{pointer:'/extracts',value}}).then(result=>window.fieldResult=result);
    })()`);
    const buttons = `[...document.querySelectorAll('.operation-dialog button')]`;
    const click = label => s.evaluate(`${buttons}.find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.wait(`${buttons}.some(button=>button.textContent==='Load source names')`, 'compound field picker');
    await click('Load source names');
    await s.wait(`${buttons}.some(button=>button.textContent==='Druck, kPa')`, 'compound names');
    assert.equal(await s.evaluate(`${buttons}.some(button=>button.textContent==='other')`), false);
    await click('Druck, kPa');
    await click('Apply changes');
    await s.wait('window.fieldResult', 'compound fields applied');
    assert.deepEqual(await s.evaluate('fieldResult.replace.value[0].fields'), ['sample','Druck, kPa']);

    await s.evaluate(`(async () => {
      const version = 'schemaxis.hdf5/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'hdf5',version});
      const item = meta.addCatalogue.items.find(row => row.id === 'document:tolerance');
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const value = {paths: ['/other']};
      const input = {version,operation:'compareFiles',source:${JSON.stringify(file)},
        reference:${JSON.stringify(reference)},tolerance:value};
      void configureOperation(studio,item,meta.addCatalogue.definitions,()=>input,undefined,
        {existing:{pointer:'/tolerance',value}}).then(result=>window.pathsResult=result);
    })()`);
    await s.wait(`${buttons}.some(button=>button.textContent==='Load source names')`, 'comparison path picker');
    await click('Load source names');
    await s.wait(`${buttons}.some(button=>button.textContent==='/referenceOnly')`, 'reference-only path');
    assert.equal(await s.evaluate(`${buttons}.some(button=>button.textContent==='/alias')`), false);
    await click('/referenceOnly');
    await click('/run/readings');
    await click('Apply changes');
    await s.wait('window.pathsResult', 'comparison paths applied');
    assert.deepEqual(await s.evaluate('pathsResult.replace.value.paths'), ['/other','/referenceOnly','/run/readings']);
  } finally {
    if (s) await s.close();
    await rm(directory, {recursive:true, force:true});
  }
});

test('ExifTool keyword removal offers the current item’s base values', {timeout:120000}, async () => {
  const s = await launch({provider:'exiftool'});
  const {fileURLToPath} = await import('node:url');
  const fixture = name => fileURLToPath(new URL(`../../../../examples/schemaxis/fixtures/exiftool/${name}`, import.meta.url));
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.exiftool/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'exiftool',version});
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const edits = {keywords:{remove:['draft']}};
      const itemEdits = [{item:'one',edits:{keywords:{remove:['draft']}}},{item:'two',edits:{keywords:{set:['replacement']}}}];
      const input = {version,operation:'editMetadata',edits,itemEdits,media:{items:[
        {id:'one',path:${JSON.stringify(fixture('edit-keywords.jpg'))}},
        {id:'two',path:${JSON.stringify(fixture('edit-keywords-conflict.jpg'))}}
      ]}};
      window.openKeywordEdit = (id, value, pointer) => void configureOperation(studio,
        meta.addCatalogue.items.find(row => row.id === id),meta.addCatalogue.definitions,()=>input,undefined,
        {existing:{pointer,value}}).then(result=>window.keywordResult=result);
      openKeywordEdit('document:itemEdits',itemEdits,'/itemEdits');
    })()`);
    const buttons = `[...document.querySelectorAll('.operation-dialog button')]`;
    const click = label => s.evaluate(`${buttons}.find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.wait(`${buttons}.some(button=>button.textContent==='Load source names')`, 'keyword picker');
    await click('Load source names');
    await s.wait(`${buttons}.some(button=>button.textContent==='alpine')`, 'item keywords');
    await click('alpine');
    await click('Apply changes');
    await s.wait('window.keywordResult', 'keyword removal applied');
    assert.deepEqual(await s.evaluate('keywordResult.replace.value[0].edits.keywords.remove'), ['draft','alpine']);
  } finally {
    await s.close();
  }
});

test('HDF5 dimension scales follow the selected axis length', {timeout:120000}, async () => {
  const s = await launch({provider:'hdf5'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const version = 'schemaxis.hdf5/1';
      const meta = await studio.api.get('/api/studio/adaptor',{id:'hdf5',version});
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      const type = {class:'int',bits:32};
      const value = [
        {path:'/data',type,shape:[4,2],dimensions:[{axis:1,scales:[]}]},
        {path:'/time',type,shape:[4],scale:'time'},
        {path:'/channels',type,shape:[2],scale:'channels'},
        {path:'/ordinary',type,shape:[2]}
      ];
      const input = {version,operation:'createFile',file:{name:'out.h5'},objects:value};
      void configureOperation(studio,meta.addCatalogue.items.find(row => row.id==='document:objects'),
        meta.addCatalogue.definitions,()=>input,undefined,
        {existing:{pointer:'/objects',value}}).then(result=>window.scalesResult=result);
    })()`);
    const buttons = `[...document.querySelectorAll('.operation-dialog button')].filter(button=>button.offsetParent)`;
    const click = label => s.evaluate(`${buttons}.find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.wait(`${buttons}.some(button=>button.textContent==='Load source names')`, 'dimension scale picker');
    await click('Load source names');
    await s.wait(`${buttons}.some(button=>button.textContent==='/channels')`, 'matching scale');
    assert.equal(await s.evaluate(`${buttons}.some(button=>['/time','/ordinary'].includes(button.textContent))`), false);
    await click('/channels');
    await click('Apply changes');
    await s.wait('window.scalesResult', 'scales applied');
    assert.deepEqual(await s.evaluate('scalesResult.replace.value[0].dimensions[0].scales'), ['/channels']);
  } finally {
    await s.close();
  }
});

test('Oracle window partition choices use report output names', {timeout:120000}, async () => {
  const {readFile} = await import('node:fs/promises');
  const {consoleTemplate: input} = JSON.parse(await readFile(
    new URL('../../adaptors/oracle/adaptor.json', import.meta.url), 'utf8'));
  input.report.windows = [{name:'rank',function:'rank',orderBy:[{column:'region'}],partitionBy:[]}];
  const s = await launch({provider:'oracle'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio');
    await s.evaluate(`(async () => {
      const input = ${JSON.stringify(input)};
      const meta = await studio.api.get('/api/studio/adaptor',{id:'oracle',version:input.version});
      const {configureOperation} = await import('/windows/workbench/operation-form.mjs');
      void configureOperation(studio,meta.addCatalogue.items.find(row => row.id==='document:report'),
        meta.addCatalogue.definitions,()=>input,undefined,
        {existing:{pointer:'/report',value:input.report}}).then(result=>window.partitionResult=result);
    })()`);
    const buttons = `[...document.querySelectorAll('.operation-dialog button')]`;
    const click = label => s.evaluate(`${buttons}.find(button => button.textContent === ${JSON.stringify(label)}).click()`);
    await s.wait(`${buttons}.some(button=>button.textContent==='Load source names')`, 'window partition picker');
    await click('Load source names');
    await s.wait(`${buttons}.some(button=>button.textContent==='revenue')`, 'projected revenue');
    await click('revenue');
    await click('Apply changes');
    await s.wait('window.partitionResult', 'partition applied');
    assert.deepEqual(await s.evaluate('partitionResult.replace.value.windows[0].partitionBy'), ['revenue']);
  } finally {
    await s.close();
  }
});
