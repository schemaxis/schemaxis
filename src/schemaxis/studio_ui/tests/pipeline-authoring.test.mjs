import assert from 'node:assert/strict';
import {test} from 'node:test';
import {initialOperation, pipelineChoices} from '../windows/workbench/authoring-defaults.mjs';
import {duplicateNode, removeNode, dependentNodes} from '../windows/workbench/pipeline-edit.mjs';
import {libraryRequest, uniquifyInserts} from '../editor/insert-fields.mjs';

test('automatic identities and primary inputs respect selection, kinds, collisions and multiple ports', () => {
  const doc = {nodes:[{id:'cut1',filter:'solid'}, {id:'profile1',filter:'sketch'}, {id:'cut2',filter:'solid'}]};
  const item = {operation:'cut', at:'/nodes/-', schema:{properties:{id:{type:'string'}}},
    ports:{base:{kind:'solid',required:true},tool:{kind:'solid',required:true}}};
  const kinds = {solid:['solid'],sketch:['profile']};
  assert.deepEqual(initialOperation(item,doc,'cut1',kinds), {id:'cut3',inputs:{base:'cut1'}});
  assert.deepEqual(initialOperation(item,doc,'profile1',kinds), {id:'cut3',inputs:{base:'cut2'}});
  item.ports.base.multiple=true;
  assert.deepEqual(initialOperation(item,doc,null,kinds).inputs, {base:['cut2']});
  assert.equal(pipelineChoices(doc,'profile',kinds).length,1);
  assert.deepEqual(initialOperation({id:'document:axes',at:'/axes/-',schema:{properties:{name:{type:'string'}}}},
    {axes:[{name:'axis1'}]}),{name:'axis2'});
});

test('duplicate and dependent deletion preserve unrelated text and source document', () => {
  const doc = {nodes:[{id:'source',filter:'sphere'}, {id:'cut',filter:'slice',inputs:{input:{node:'source',port:0}}},
    {id:'observed',filter:'sphere',options:{radius:{$observe:'cut',path:['volume']}}}, {id:'safe',filter:'sphere',options:{label:'source'}}],
    scenes:[{id:'view',geometry:['cut','safe'],visible:{cut:{},safe:{}},measurements:[{node:'source',id:'m'}],
      images:[{id:'pic',file:'source.png'}]}], output:'cut'};
  const before=structuredClone(doc);
  const copy=duplicateNode(doc,'/nodes/1');
  assert.equal(copy.value.nodes[2].id,'cutCopy1');
  assert.deepEqual(copy.value.nodes[2].inputs,{input:{node:'source',port:0}});
  const removed=removeNode(doc,'/nodes/0');
  assert.deepEqual(removed.names,['source','cut','observed']);
  assert.deepEqual(removed.value.nodes,[doc.nodes[3]]);
  assert.deepEqual(removed.value.scenes[0].geometry,['safe']);
  assert.deepEqual(removed.value.scenes[0].visible,{safe:{}});
  assert.equal(removed.value.scenes[0].images[0].file,'source.png');
  assert.equal(removed.value.output,undefined);
  assert.equal(removed.publicationsChanged,true);
  assert.deepEqual(doc,before);
  assert.deepEqual([...dependentNodes(doc,'source')],['source','cut','observed']);
});

test('unnamed draft objects can be deleted and duplicated without affecting other unfinished objects', () => {
  const doc={nodes:[{id:{$fill:'id'},filter:'sphere'},{filter:'cone'}]};
  assert.deepEqual(removeNode(doc,'/nodes/0').value.nodes,[{filter:'cone'}]);
  assert.equal(duplicateNode(doc,'/nodes/0').value.nodes[1].id,'sphereCopy1');
  const incomplete={nodes:[{id:'source'}, {id:{$fill:'id'},inputs:{input:'source'}}, {id:'unrelated'}]};
  const result=removeNode(incomplete,'/nodes/0');
  assert.deepEqual(result.value.nodes,[{id:'unrelated'}]);
  assert.deepEqual(result.names,['source','unnamed object at node 1']);
});

test('pipeline edits stay inside their nested document scope', () => {
  const doc={operations:[{document:{nodes:[{id:'a'}]}},{document:{nodes:[{id:'a'},{id:'b',inputs:{input:'a'}}]}}]};
  const result=removeNode(doc,'/operations/1/document/nodes/0');
  assert.equal(result.base,'/operations/1/document'); assert.deepEqual(result.value.nodes,[]);
  assert.equal(doc.operations[0].document.nodes.length,1);
});

test('snippet names are supplied and collision rewrites cover native ports and observations', () => {
  const item={id:'sphere',fields:{id:{type:'id',default:'ball'}},inserts:[{at:'/nodes/-',values:[{id:{$fill:'id'},filter:'sphere'}]}]};
  assert.equal(libraryRequest(item,{nodes:[{id:'ball'}]}).inserts[0].values[0].id,'ball2');
  const result=uniquifyInserts({nodes:[{id:'ball'}]},[{at:'/nodes/-',values:[{id:'ball'},
    {id:'dependent',inputs:{input:{node:'ball',port:1}}, options:{radius:{$observe:'ball',path:['volume']},label:'ball'}}]},
    {at:'/scenes/0/exports/-',values:[{node:'ball',writer:'writer'}]}]);
  assert.deepEqual(result[0].values[1].inputs.input,{node:'ball2',port:1});
  assert.equal(result[0].values[1].options.radius.$observe,'ball2');
  assert.equal(result[0].values[1].options.label,'ball');
  assert.equal(result[1].values[0].node,'ball2');
  const mixed=libraryRequest({fields:{id:{type:'id',default:'shape'},kind:{type:'string'}},
    inserts:[{at:'/nodes/-',values:[{id:'${id}',options:{file:'${id}-${kind}.vtk'}}]}]},{});
  assert.deepEqual(mixed.inserts[0].values[0].options.file,{type:'string',$fill:'kind',template:'shape-${kind}.vtk'});
});
