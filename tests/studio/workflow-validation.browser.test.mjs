import assert from 'node:assert/strict';
import {test} from 'node:test';
import {launch} from '../../src/schemaxis/studio_ui/tests/harness.mjs';

const workflow = {version: 'schemaxis.workflow/1', operations: [
  {id: 'samples', document: {version: 'schemaxis.octave/1', nodes: [
    {id: 'data', filter: 'sequence', options: {start: 0, stop: 4, count: 5}}], outputs: ['data']}},
  {id: 'scaled', document: {version: 'schemaxis.octave/1', nodes: [
    {id: 'data', filter: 'readCSV', options: {file: {$artifact: 'samples', index: 0}}},
    {id: 'result', filter: 'scale', inputs: {input: 'data'}, options: {factor: 2}}], outputs: ['result']}},
]};

test('nested validation checks workflow references without saving drafts or previewing unproduced files', {timeout: 120000}, async () => {
  const s = await launch({provider: 'workflow'});
  try {
    await s.wait('window.studio?.store.get().server', 'Studio ready');
    const record = await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
      {action:'new',provider:'workflow',name:'Measurement workflow',document:${JSON.stringify(workflow)}});
      await c.refresh();c.windows.open('workbench',{document:r.id,operation:'scaled'});return r;})()`);
    await s.wait('window.studio.windows.active()?.window?.editor?.getValue().includes("$artifact")', 'nested operation loaded');
    await s.evaluate(`(() => {window.__contextChecks=[];window.__contextWrites=[];
      const post=window.studio.api.post.bind(window.studio.api);
      window.studio.api.post=async(path,request)=>{const result=await post(path,request);
        if(path==='/api/validate')window.__contextChecks.push({request,result});
        if(path==='/api/documents'||path==='/api/authoring')window.__contextWrites.push({path,request});return result;};})()`);
    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    await s.key('End', {modifiers: 2});
    await s.type('\n');
    await s.wait('window.__contextChecks.length>0', 'background validation completed');
    const background = await s.evaluate('window.__contextChecks.at(-1)');
    assert.equal(background.result.valid, true, JSON.stringify(background.result));
    assert.equal(background.result.validation.deferred, true);
    assert.deepEqual({document: background.request.document, revision: background.request.revision,
      operation: background.request.operation}, {document: record.id, revision: record.revision, operation: 'scaled'});
    await s.wait(`document.querySelector('.wb-diagnostic-state')?.textContent==='0 diagnostics'`, 'no false file-path diagnostic');

    const count = await s.evaluate('window.__contextChecks.length');
    await s.clickSelector('[data-action="validate"]');
    await s.wait(`window.__contextChecks.length>${count}`, 'explicit validation completed');
    await s.wait(`document.body.textContent.includes('Workflow references checked')`, 'deferred validation explained');
    assert.equal(await s.evaluate('window.__contextChecks.at(-1).request.operation'), 'scaled');
    await s.wait(`!document.querySelector('[data-action="preview"]').disabled`, 'validation action finished');
    await s.clickSelector('[data-action="preview"]');
    await s.wait(`document.body.textContent.includes('Run from the workflow')`, 'preview explains producer dependency');
    assert.deepEqual(await s.evaluate('window.__contextWrites'), [], 'no save or standalone preview instance');

    const bad = structuredClone(workflow.operations[1].document);
    bad.nodes[0].options.file.$artifact = 'missing';
    await s.evaluate('window.studio.windows.active().window.editor.focus()');
    await s.key('a', {modifiers: 2});
    await s.type(JSON.stringify(bad, null, 2));
    await s.wait(`window.__contextChecks.at(-1)?.result.diagnostics?.[0]?.code==='UNAVAILABLE_OPERATION'`,
      'missing producer refused in parent context');
    const after = await s.evaluate(`window.studio.api.get('/api/document',{id:${JSON.stringify(record.id)}})`);
    assert.equal(after.revision, record.revision);
    assert.deepEqual(after.document, workflow);
    assert.deepEqual(s.exceptions, []);
  } finally {await s.close();}
});

for (const indirectArtifact of [true, false]) {
  test(`nested preview preserves ${indirectArtifact ? 'indirect artifact' : 'concrete definition'} context`, {timeout: 120000}, async () => {
    const document = structuredClone(workflow);
    const operation = indirectArtifact ? 'scaled' : 'samples';
    document.definitions = {input: indirectArtifact ? {$artifact: 'samples', index: 0} : 5};
    document.operations[indirectArtifact ? 1 : 0].document.nodes[0].options[indirectArtifact ? 'file' : 'count'] =
      {$document: '/definitions/input', scope: 'workflow'};
    const s = await launch({provider: 'workflow'});
    try {
      await s.wait('window.studio?.store.get().server', 'Studio ready');
      const record = await s.evaluate(`(async()=>{const c=window.studio;const r=await c.api.post('/api/documents',
        {action:'new',provider:'workflow',name:'Referenced workflow',document:${JSON.stringify(document)}});
        await c.refresh();c.windows.open('workbench',{document:r.id,operation:${JSON.stringify(operation)}});return r;})()`);
      await s.wait('window.studio.windows.active()?.window?.editor?.getValue().includes("$document")', 'referenced operation loaded');
      await s.evaluate(`(() => {window.__contextWrites=[];window.__lastValidation=null;
        const post=window.studio.api.post.bind(window.studio.api);
        window.studio.api.post=async(path,request)=>{const result=await post(path,request);
          if(path==='/api/validate')window.__lastValidation=result;
          if(path==='/api/documents'||path==='/api/authoring')window.__contextWrites.push({path,request});return result;};})()`);
      await s.clickSelector('[data-action="preview"]');
      await s.wait(`document.body.textContent.includes('Run from the workflow')`, 'preview preserves context');
      const validation = await s.evaluate('window.__lastValidation');
      assert.equal(validation.valid, true, JSON.stringify(validation));
      assert.equal(validation.validation.deferred, indirectArtifact);
      assert.equal(validation.validation.requiresWorkflow, true);
      assert.deepEqual(await s.evaluate('window.__contextWrites'), []);
      const after = await s.evaluate(`window.studio.api.get('/api/document',{id:${JSON.stringify(record.id)}})`);
      assert.equal(after.revision, record.revision);
      assert.deepEqual(after.document, document);
      assert.deepEqual(s.exceptions, []);
    } finally {await s.close();}
  });
}
