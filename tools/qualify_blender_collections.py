"""Actual collection ownership, selected native reuse and geometry qualification."""
import argparse
import copy
import json
import math
from pathlib import Path
import subprocess
from schemaxis.adaptors.blender.adaptor import run
from schemaxis.core.faults import SchemaxisError


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',required=True);a=p.parse_args();out=Path(a.output).absolute();out.mkdir(parents=True,exist_ok=False)
    fixture=out/'fixture';script=Path(__file__).with_name('blender_collection_fixture.py')
    native=subprocess.run([a.blender,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(script),'--','--output',str(fixture)],timeout=90,capture_output=True,text=True);(out/'fixture.log').write_text(native.stdout+'\n'+native.stderr);assert native.returncode==0,native.stderr
    doc={'version':'schemaxis.blender.production/1','id':'ownership','prepareOnly':True,'size':[32,32],'render':{'samples':1,'threads':1},'production':{'frameStart':1,'frameEnd':11,'currentFrame':6,'units':'millimetres','assets':[{'id':'model','file':str(fixture/'source.blend'),'format':'blend','sourceUnits':'millimetres','scene':'Assembly','viewLayer':'Main'}],'renderFrames':[6],'exports':[{'id':'frame'+str(f),'objects':['model'],'format':'glb','frame':f} for f in (1,6,11)]}}
    cases=[]
    def accept(name,value,expected,volume):
        result=run(value,out/name,executable=a.blender,timeout=180);r=json.loads((out/name/'verification.json').read_text());prod=r['states'][0]['production'];bounds=next(s for s in prod['samples'] if s['frame']==6)['objects']['model']['bounds']
        assert all(math.isclose(x,y,abs_tol=2e-5) for x,y in zip(bounds,expected)),(name,bounds,expected)
        exports=[x for x in r['artifacts'] if x.get('productionOutput') and x['format']=='glb']
        assert exports
        for e in exports:assert math.isclose(abs(e['after']['signedVolume']),volume*1e-9,rel_tol=2e-5),(name,e['after'])
        cases.append({'case':name,'result':result,'literalFrame6Bounds':expected,'literalVolumeMillimetresCubed':volume,'selection':prod['assets'][0]['selection']})
        return prod
    prod=accept('main',doc,[-4,11,0,12,-1,1],40)
    assert prod['assets'][0]['selection']['excluded']==[['Container','Excluded']]
    collision=copy.deepcopy(doc);collision['production']['assets'][0]['file']=str(fixture/'dependency-name-collision.blend');accept('dependency-name-collision',collision,[-4,11,0,12,-1,1],40)
    units=copy.deepcopy(doc);units['production']['units']='centimetres';accept('coordinate-units',units,[-.4,1.1,0,1.2,-.1,.1],40)
    selected=copy.deepcopy(doc);selected['production']['assets'][0]['viewLayer']='All';accept('all',selected,[-4,1001,0,1001,-1,1],48)
    transformed=copy.deepcopy(doc);transformed['production']['assets'][0].update(location=[20,30,0],rotation=[0,0,math.pi/2]);accept('transformed',transformed,[8,20,26,41,-1,1],40)
    variants=copy.deepcopy(doc);variants['production']['assets'][0]['file']=str(fixture/'variants.blend');accept('distinct-instance-geometry',variants,[-4,11,0,12,-2,2],56)
    offset=copy.deepcopy(doc);offset['production']['assets'][0]['file']=str(fixture/'offset.blend');accept('offset',offset,[-4,10,0,11,-1,1],40)
    reused=copy.deepcopy(doc);reused['production']['assets'][0].update(file=str(out/'main'/'0000.blend'),scene='',viewLayer='');accept('reused',reused,[-4,11,0,12,-1,1],40)
    edit=out/'edit.py';edit.write_text('import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(out/"main"/"0000.blend")!r},use_scripts=False)\n'+"next(o for o in bpy.data.objects if o.name.endswith('--FirstInstance')).location.x=12\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(out/"edited.blend")!r})\n')
    native=subprocess.run([a.blender,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(edit)],timeout=90,capture_output=True,text=True);assert native.returncode==0,(native.stdout,native.stderr)
    edited=copy.deepcopy(reused);edited['production']['assets'][0]['file']=str(out/'edited.blend');accept('native-edited',edited,[-4,13,0,12,-1,1],40)
    library=copy.deepcopy(doc);library['production']['assets'][0].update(file=str(fixture/'objects.blend'),scene='',viewLayer='');accept('object-library',library,[-1,1,-1,1,-1,1],8)
    # Observe actual packed ID sharing, source scenes removed, hierarchy and
    # instance offsets; these are independent of adaptor-authored evidence tags.
    inspect=out/'inspect.py';inspect.write_text('''import bpy,json,sys
from pathlib import Path
p=Path(sys.argv[sys.argv.index('--')+1]);bpy.ops.wm.open_mainfile(filepath=str(p/'main'/'0000.blend'),use_scripts=False)
root=bpy.data.objects['model'];a=bpy.data.objects['model--FirstInstance'];b=bpy.data.objects['model--SecondInstance'];loose=bpy.data.objects['model--LooseShared'];proto=bpy.data.objects['model--PrototypeCube'];nested=bpy.data.objects['model--NestedCube']
assert root.instance_type=='COLLECTION' and a.instance_collection==b.instance_collection
assert proto.data==nested.data==loose.data and len(loose.users_collection)==2
assert a.parent==b.parent==loose.parent==bpy.data.objects['model--AssemblyRoot']
assert len(bpy.data.scenes)==1 and not any('ExcludedCube' in o.name or 'OtherCube' in o.name for o in bpy.data.objects)
assert not any(c.name=='Excluded' for c in bpy.data.collections)
assert proto.data.materials[0].name=='Blue'
c=next(c for c in bpy.data.collections if c.name.endswith('--view--Container'));assert next(edge for child,edge in zip(c.children,c.collection_children) if child.name=='Visible').light_linking.link_state=='EXCLUDE'
assert a.parent.animation_data.action is not None
target=a.parent.constraints[0].target;assert target and not target.users_collection and list(target.location)==[0,40,50]
counts=[]
for frame in (1,6,11):
 bpy.context.scene.frame_set(frame);bpy.context.view_layer.update();occ=[i for i in bpy.context.evaluated_depsgraph_get().object_instances if i.object.type=='MESH'];assert len(occ)==5;counts.append(len(occ))
(p/'ownership.json').write_text(json.dumps({'status':'passed','physicalOccurrences':counts,'sharedMesh':True,'sharedObjectMembership':True,'sharedCollectionInstances':True,'sourceScenesRemoved':True,'excludedObjectsPruned':True},indent=2)+'\\n')
''')
    result=subprocess.run([a.blender,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(inspect),'--',str(out)],timeout=90,capture_output=True,text=True);(out/'ownership.log').write_text(result.stdout+'\n'+result.stderr);assert result.returncode==0,(result.stdout,result.stderr)
    refusals=[]
    for name,updates,code in [('ambiguous-scene',{'scene':''},'AMBIGUOUS_ASSET_SELECTION'),('ambiguous-layer',{'viewLayer':''},'AMBIGUOUS_ASSET_SELECTION'),('unknown-scene',{'scene':'Absent'},'UNKNOWN_ASSET_SELECTION'),('unknown-layer',{'viewLayer':'Absent'},'UNKNOWN_ASSET_SELECTION'),('override',{'file':str(fixture/'override.blend')},'UNSUPPORTED_ASSET_DEPENDENCY'),('holdout',{'file':str(fixture/'holdout.blend')},'UNSUPPORTED_ASSET_DEPENDENCY'),('local-hidden',{'file':str(fixture/'local-hidden.blend')},'UNSUPPORTED_ASSET_DEPENDENCY'),('collection-library',{'file':str(fixture/'collection-library.blend'),'scene':'','viewLayer':''},'UNSUPPORTED_ASSET_DEPENDENCY')]:
        value=copy.deepcopy(doc);value['production']['assets'][0].update(updates);fault=None
        try:run(value,out/name,executable=a.blender,timeout=90)
        except SchemaxisError as e:fault=e.fault.code
        assert fault==code,(name,fault,code);refusals.append({'case':name,'fault':fault})
    (out/'report.json').write_text(json.dumps({'status':'passed','cases':cases,'refusals':refusals},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(cases),'refusals':len(refusals)}))

if __name__=='__main__':main()
