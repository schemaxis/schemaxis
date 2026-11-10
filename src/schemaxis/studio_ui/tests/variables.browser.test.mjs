import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from './harness.mjs';

const active = 'studio.windows.active().window';
async function button(session, label) {
  await session.evaluate(`(() => {const dialog=[...document.querySelectorAll('.dialog')].at(-1);
    const button=[...dialog.querySelectorAll('button')].find(b=>b.textContent===${JSON.stringify(label)});
    if (!button) throw Error('Missing button: '+${JSON.stringify(label)});button.click();})()`);
}
async function field(session, label, value) {
  await session.evaluate(`(() => {const dialog=[...document.querySelectorAll('.dialog')].at(-1);
    const input=dialog.querySelector('[aria-label='+${JSON.stringify(JSON.stringify(label))}+']');
    if (!input) throw Error('Missing field: '+${JSON.stringify(label)});
    input.value=${JSON.stringify(value)};input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}

test('create a shared Case Runner parameter before operations, then undo its saved edit', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async()=>{const record=await studio.api.post('/api/documents',{action:'new',provider:'workflow-design',name:'Dimensions first'});
      window.variableDoc=record.id;await studio.refresh();studio.openDocument(record.id);})()`);
    await session.wait('studio.designers.get(window.variableDoc)?.model.store.get().projection', 'empty design');
    await session.evaluate('void studio.openVariables()');
    await session.wait(`document.querySelector('[aria-label="Variables & expressions"]')`, 'variables');
    await button(session, 'Create new value…');
    await session.wait(`document.querySelector('[aria-label="Variable name"]')`, 'create value');
    await field(session, 'Variable name', 'distance');
    await field(session, 'Value', '10');
    await session.evaluate(`document.querySelector('[aria-label="Expose in Case Runner"]').click()`);
    await field(session, 'Units', 'mm');
    await button(session, 'Create value');
    await session.wait('document.querySelector(".variable-row")', 'staged value');
    await button(session, 'Save changes to workflow');
    await session.wait('!document.querySelector(".dialog")', 'saved values');
    const record = await session.evaluate('studio.api.get("/api/document",{id:window.variableDoc})');
    assert.deepEqual(record.diagnostics, []);
    assert.equal(record.document.workflow.dimensions.distance, 10);
    assert.equal(record.document.parameters.distance.units, 'mm');
    assert.deepEqual(record.document.workflow.operations, []);
    assert.equal(await session.evaluate('studio.designers.get(window.variableDoc).model.store.get().projection.compilationAvailable'), false);
    await session.evaluate('studio.designers.get(window.variableDoc).model.history("undo")');
    const undone = await session.evaluate('studio.api.get("/api/document",{id:window.variableDoc})');
    assert.equal(undone.document.workflow.dimensions, undefined);
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('creating and binding a value is cancellable, schema checked, and one local undo', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async()=>{const record=await studio.api.post('/api/documents',{action:'new',provider:'freecad',name:'Variables',document:{
      version:'schemaxis.freecad/1',nodes:[{id:'body',filter:'box',options:{length:10,width:2,height:3}}],output:'body'}});
      await studio.refresh();studio.openDocument(record.id);})()`);
    await session.wait(`${active}.store?.get().schema`, 'Workbench');
    const original = await session.evaluate(`${active}.editor.getValue()`);
    for (const cancel of [true, false]) {
      await session.evaluate(`void ${active}.editor.getOption('chooseValue')({pointer:'/nodes/0/options/length'})`);
      await session.wait(`document.querySelector('[aria-label="Choose a value or expression"]')`, 'picker');
      await button(session, 'Create new value…');
      await session.wait(`document.querySelector('[aria-label="Variable name"]')`, 'creator');
      await field(session, 'Variable name', 'distance');
    await field(session, 'Value', '12');
      await button(session, 'Create value');
      await session.wait(`!document.querySelector('[aria-label="Variable name"]')`, 'created');
      await session.wait(`document.querySelector('[aria-label="Choose a value or expression"] .variables-preview')?.textContent === 'Preview: 12'`, 'new value ready');
      await button(session, cancel ? 'Cancel' : 'Use value');
      await session.wait('!document.querySelector(".dialog")', 'picker closed');
      if (cancel) assert.equal(await session.evaluate(`${active}.editor.getValue()`), original);
    }
    const value = await session.evaluate(`${active}.editor.getDocument()`);
    assert.equal(value.dimensions.distance, 12);
    assert.deepEqual(value.nodes[0].options.length, {$document:'/dimensions/distance'});
    await session.evaluate(`${active}.editor.focus()`);
    await session.key('z', {modifiers: 2});
    assert.equal(await session.evaluate(`${active}.editor.getValue()`), original);
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('Blender Add forms stage variables with the operation, and embedded Help omits its repeated introduction', {timeout: 120000}, async () => {
  const session = await launch({provider: 'blender'});
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async()=>{const record=await studio.api.post('/api/documents',{action:'new',provider:'blender',name:'Ring',source:JSON.stringify({
      version:'schemaxis.blender/1',nodes:[{id:'blue',filter:'material'}],scenes:[]})});
      await studio.refresh();studio.openDocument(record.id);})()`);
    await session.wait(`${active}.store?.get().schema`, 'Blender Workbench');
    const before = await session.evaluate(`${active}.editor.getValue()`);
    await session.clickSelector('[data-add=all]');
    await session.evaluate(`(()=>{const e=document.querySelector('[aria-label="Search Add anything…"]');e.value='torus';e.dispatchEvent(new Event('input'));})()`);
    await session.clickSelector('[data-library="operation:torus"]');
    await session.wait('document.querySelector(".operation-form")', 'torus form');
    await session.evaluate(`(() => {const e=document.querySelector('[aria-label="Include torus.options"]');e.click();
      document.querySelector('[aria-label="Include torus.options.majorRadius"]').click();})()`);
    await session.evaluate(`document.querySelector('[aria-label="Value or expression for torus.options.majorRadius"]').click()`);
    await session.wait(`document.querySelector('[aria-label="Choose a value or expression"]')`, 'radius picker');
    await button(session, 'Create new value…');
    await session.wait(`document.querySelector('[aria-label="Variable name"]')`, 'new radius');
    await field(session, 'Variable name', 'ringRadius');
    await field(session, 'Value', '3');
    await button(session, 'Create value');
    await session.wait(`document.querySelector('[aria-label="Choose a value or expression"] .variables-preview')?.textContent === 'Preview: 3'`, 'radius ready');
    await button(session, 'Use value');
    await session.wait(`document.querySelector('.operation-form .variables-preview:not([hidden])')`, 'bound form field');
    assert.equal(await session.evaluate(`${active}.editor.getValue()`), before, 'form edits are still staged');
    await button(session, 'Add operation');
    await session.wait(`!document.querySelector('.operation-form')`, 'added torus');
    const value = await session.evaluate(`${active}.editor.getDocument()`);
    assert.equal(value.dimensions.ringRadius, 3);
    assert.deepEqual(value.nodes.find(n=>n.filter==='torus').options.majorRadius, {$document:'/dimensions/ringRadius'});
    await session.evaluate(`${active}.editor.focus()`); await session.key('z', {modifiers: 2});
    assert.equal(await session.evaluate(`${active}.editor.getValue()`), before);
    await session.clickSelector('[data-add=all]');
    await session.evaluate(`(()=>{const e=document.querySelector('[aria-label="Search Add anything…"]');e.value='material';e.dispatchEvent(new Event('input'));})()`);
    await session.clickSelector('[data-library="operation:material"]');
    await session.wait('document.querySelector(".operation-form")', 'material form');
    await session.evaluate(`(()=>{for(const d of document.querySelectorAll('.operation-form > details')) d.open=true;})()`);
    await session.wait(`document.querySelector('.operation-reference .help-article')`, 'reference loaded');
    const help = await session.evaluate(`(()=>{const form=document.querySelector('.operation-form');const intro=form.querySelector(':scope > p').textContent;
      return {copies:[...form.querySelectorAll('p')].filter(p=>p.textContent===intro).length,reference:form.querySelector('.operation-reference').textContent,
        direct:[...form.children].some(e=>e.tagName==='DETAILS' && e.querySelector('summary')?.textContent==='? Operation reference')};})()`);
    assert.equal(help.copies, 1); assert.equal(help.direct, true); assert.match(help.reference, /Roughness|roughness/);
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('an operation Workbench creates and binds a shared parameter without losing its local draft', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async()=>{const record=await studio.api.post('/api/documents',{action:'new',provider:'workflow-design',name:'Shared',document:{
      version:'schemaxis.workflow-design/2',workflow:{version:'schemaxis.workflow/1',operations:[{id:'part',document:{
      version:'schemaxis.freecad/1',nodes:[{id:'body',filter:'box',options:{length:10,width:2,height:3}}],output:'body'}}]},
      ports:{},connections:[],controllers:{},parameters:{},outputs:{},naming:{},layout:{nodes:{}}}});
      window.variableDoc=record.id;await studio.refresh();studio.windows.open('workbench',{document:record.id,operation:'part'});})()`);
    await session.wait(`${active}.store?.get().schema`, 'operation Workbench');
    await session.evaluate(`${active}.editor.insertAtPointer('/nodes/0/options/width',7)`);
    await session.evaluate(`void ${active}.editor.getOption('chooseValue')({pointer:'/nodes/0/options/length'})`);
    await session.wait(`document.querySelector('[aria-label="Choose a value or expression"]')`, 'picker');
    await button(session, 'Create new value…');
    await session.wait(`document.querySelector('[aria-label="Variable name"]')`, 'creator');
    await field(session, 'Value scope', '/workflow');
    await session.wait(`!document.querySelector('[aria-label="Expose in Case Runner"]').closest('.variables-fields').hidden && document.querySelector('[aria-label="Create a named value"] [aria-label="Value"]')`, 'shared value form');
    await field(session, 'Variable name', 'distance');
    await field(session, 'Value', '14');
    await session.evaluate(`document.querySelector('[aria-label="Expose in Case Runner"]').click()`);
    await button(session, 'Create value');
    await session.wait(`document.querySelector('[aria-label="Choose a value or expression"] .variables-preview')?.textContent === 'Preview: 14'`, 'shared value ready');
    await button(session, 'Use value');
    await session.wait(`!document.querySelector('.dialog') && ${active}.editor.getDocument().nodes[0].options.length.scope==='workflow'`, 'shared binding saved');
    const record = await session.evaluate('studio.api.get("/api/document",{id:window.variableDoc})');
    assert.deepEqual(record.diagnostics, []);
    assert.equal(record.document.workflow.dimensions.distance, 14);
    assert.equal(record.document.workflow.operations[0].document.nodes[0].options.width, 7);
    assert.deepEqual(record.document.workflow.operations[0].document.nodes[0].options.length,
      {$document:'/dimensions/distance',scope:'workflow'});
    assert.equal(record.document.parameters.distance.default, 14);
    await session.evaluate(`(async()=>{const r=await studio.api.get('/api/document',{id:window.variableDoc});
      await studio.api.post('/api/authoring',{action:'undo',document:r.id,revision:r.revision});})()`);
    const undone = await session.evaluate('studio.api.get("/api/document",{id:window.variableDoc})');
    assert.equal(undone.document.workflow.dimensions, undefined);
    assert.equal(undone.document.workflow.operations[0].document.nodes[0].options.width, 2);
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('Add forms inside workflows stage shared variables and the new node in one saved edit', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async()=>{const record=await studio.api.post('/api/documents',{action:'new',provider:'workflow-design',name:'Shared Add',document:{
      version:'schemaxis.workflow-design/2',workflow:{version:'schemaxis.workflow/1',operations:[{id:'part',document:{
      version:'schemaxis.freecad/1',nodes:[{id:'body',filter:'box',options:{length:10,width:2,height:3}}],output:'body'}}]},
      ports:{},connections:[],controllers:{},parameters:{},outputs:{},naming:{},layout:{nodes:{}}}});
      window.variableDoc=record.id;await studio.refresh();studio.windows.open('workbench',{document:record.id,operation:'part'});})()`);
    await session.wait(`${active}.store?.get().schema`, 'operation Workbench');
    await session.evaluate(`${active}.editor.insertAtPointer('/nodes/0/options/width',7)`);
    await session.clickSelector('[data-add=all]');
    await session.evaluate(`(()=>{const e=document.querySelector('[aria-label="Search Add anything…"]');e.value='box';e.dispatchEvent(new Event('input'));})()`);
    await session.clickSelector('[data-library="operation:box"]');
    await session.wait('document.querySelector(".operation-form")', 'box form');
    await session.evaluate(`(()=>{document.querySelector('[aria-label="Include box.options"]').click();
      document.querySelector('[aria-label="Include box.options.length"]').click();
      document.querySelector('[aria-label="Value or expression for box.options.length"]').click();})()`);
    await session.wait(`document.querySelector('[aria-label="Choose a value or expression"]')`, 'length picker');
    await button(session, 'Create new value…');
    await session.wait(`document.querySelector('[aria-label="Variable name"]')`, 'new shared length');
    await field(session, 'Value scope', '/workflow');
    await session.wait(`!document.querySelector('[aria-label="Expose in Case Runner"]').closest('.variables-fields').hidden && document.querySelector('[aria-label="Create a named value"] [aria-label="Value"]')`, 'shared controls');
    await field(session, 'Variable name', 'distance');
    await field(session, 'Value', '18');
    await session.evaluate(`document.querySelector('[aria-label="Expose in Case Runner"]').click()`);
    await button(session, 'Create value');
    await session.wait(`document.querySelector('[aria-label="Choose a value or expression"] .variables-preview')?.textContent === 'Preview: 18'`, 'shared length ready');
    await button(session, 'Use value');
    await session.wait(`document.querySelector('.operation-form .variables-preview:not([hidden])')`, 'bound field');
    const staged = await session.evaluate('studio.api.get("/api/document",{id:window.variableDoc})');
    assert.equal(staged.document.workflow.dimensions, undefined);
    await button(session, 'Add operation');
    await session.wait(`!document.querySelector('.dialog') && ${active}.editor.getDocument().nodes.length===2`, 'shared add saved').catch(async error => {
      throw Error(error.message + ' / ' + JSON.stringify(await session.evaluate(`({log:studio.notify.store.get().log,error:document.querySelector('.operation-error')?.textContent})`)));
    });
    const record = await session.evaluate('studio.api.get("/api/document",{id:window.variableDoc})');
    assert.deepEqual(record.diagnostics, []);
    assert.equal(record.document.workflow.dimensions.distance, 18);
    assert.equal(record.document.parameters.distance.default, 18);
    assert.equal(record.document.workflow.operations[0].document.nodes[0].options.width, 7);
    assert.deepEqual(record.document.workflow.operations[0].document.nodes[1].options.length,
      {$document:'/dimensions/distance',scope:'workflow'});
    await session.evaluate(`studio.api.post('/api/authoring',{action:'undo',document:window.variableDoc,revision:${JSON.stringify(record.revision)}})`);
    const undone = await session.evaluate('studio.api.get("/api/document",{id:window.variableDoc})');
    assert.equal(undone.document.workflow.dimensions, undefined);
    assert.equal(undone.document.workflow.operations[0].document.nodes.length, 1);
    assert.equal(undone.document.workflow.operations[0].document.nodes[0].options.width, 2);
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally { await session.close(); }
});

test('the common picker rejects incompatible named values and authors calculations and sweeps', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`(async()=>{const r=await studio.api.post('/api/documents',{action:'new',provider:'freecad',name:'Computed dimensions',document:{
      version:'schemaxis.freecad/1',dimensions:{distance:5,material:'steel'},nodes:[{id:'body',filter:'box',options:{length:10,width:2,height:3}}],output:'body'}});
      await studio.refresh();studio.openDocument(r.id);})()`);
    await session.wait(`${active}.store?.get().schema`, 'Workbench');
    await session.evaluate(`void ${active}.editor.getOption('chooseValue')({pointer:'/nodes/0/options/length'})`);
    await session.wait(`document.querySelector('[aria-label="Choose a value or expression"]')`, 'picker');
    assert.equal(await session.evaluate(`document.querySelector('.variables-list [data-pointer="/dimensions/material"]').disabled`), true);
    await session.evaluate(`document.querySelector('[aria-label="Choose a value or expression"] details').open=true`);
    await field(session, 'Value source', '$expr');
    await field(session, 'Calculation', 'multiply');
    await field(session, 'Left argument source', '0');
    await field(session, 'Right argument', '2');
    await button(session, 'Use value');
    await session.wait('!document.querySelector(".dialog")', 'calculation applied');
    assert.deepEqual(await session.evaluate(`${active}.editor.getDocument().nodes[0].options.length`),
      {$expr:{op:'multiply',args:[{$document:'/dimensions/distance'},2]}});
    await session.evaluate(`void ${active}.editor.getOption('chooseValue')({pointer:'/nodes/0/options/height'})`);
    await session.wait(`document.querySelector('[aria-label="Choose a value or expression"]')`, 'height picker');
    await button(session, 'Create new value…');
    await session.wait(`document.querySelector('[aria-label="Variable name"]')`, 'sweep creator');
    await field(session, 'Variable name', 'heights'); await field(session, 'Value group', 'axes');
    await field(session, 'Sweep values (JSON)', '[1,2,3]');
    await button(session, 'Create value');
    await session.wait(`!document.querySelector('[aria-label="Variable name"]')`, 'sweep created');
    await button(session, 'Use value');
    await session.wait('!document.querySelector(".dialog")', 'sweep bound');
    const document = await session.evaluate(`${active}.editor.getDocument()`);
    assert.deepEqual(document.axes, [{name:'heights',values:[1,2,3]}]);
    assert.deepEqual(document.nodes[0].options.height, {$axis:'heights'});
    await session.evaluate(`void ${active}.editor.getOption('chooseValue')({pointer:'/nodes/0/options/width'})`);
    await session.wait(`document.querySelector('[aria-label="Choose a value or expression"]')`, 'width picker');
    await session.evaluate(`document.querySelector('[aria-label="Choose a value or expression"] details').open=true`);
    await field(session, 'Value source', '$axis');
    await field(session, 'Named sweep', 'heights');
    await button(session, 'Use value');
    await session.wait('!document.querySelector(".dialog")', 'existing sweep applied');
    assert.deepEqual(await session.evaluate(`${active}.editor.getDocument().nodes[0].options.width`), {$axis:'heights'});
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally {await session.close();}
});

test('binding repeated fields across operation scopes keeps the selected variable owner', {timeout: 120000}, async () => {
  const session = await launch();
  try {
    await session.wait('window.studio?.store.get().server', 'Studio');
    await session.evaluate(`void (async()=>{const {chooseValue}=await import('/windows/variables/panel.mjs');
      const root={version:'schemaxis.workflow/1',operations:['a','b'].map((id,i)=>({id,document:{
        version:'schemaxis.freecad/1',dimensions:{length:i?99:12},nodes:[{id:'body',filter:'box',options:{length:{$fill:'length'},width:2,height:3}}],output:'body'}}))};
      window.repeatedValue=await chooseValue(studio,{root,pointer:'/operations/0/document/nodes/0/options/length',
        pointers:[0,1].map(i=>'/operations/'+i+'/document/nodes/0/options/length')});})()`);
    await session.wait(`document.querySelector('[aria-label="Choose a value or expression"]')`, 'repeated picker');
    await session.evaluate(`document.querySelector('.variables-list [data-pointer="/operations/0/document/dimensions/length"]').click()`);
    await button(session, 'Use value');
    await session.wait('window.repeatedValue', 'repeated bindings');
    const root = await session.evaluate('window.repeatedValue.document');
    assert.deepEqual(root.operations[0].document.nodes[0].options.length, {$document:'/dimensions/length'});
    assert.deepEqual(root.operations[1].document.nodes[0].options.length, {$document:'/dimensions/length',operation:'a'});
    assert.deepEqual(session.exceptions, []); assert.deepEqual(session.consoleErrors, []);
  } finally {await session.close();}
});
