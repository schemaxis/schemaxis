"""Independent literal geometry, sharing and source-replay mesh edit acceptance."""
import argparse
import copy
import json
import io
import zipfile
from pathlib import Path
from qualify_blender_mesh_data import close,native,production
from qualify_blender_geometry_resources import base as resource_base
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.errors import SchemaxisError


def stage(kind,selection=None,**options):return {'id':kind,'kind':kind,'selection':selection or {'kind':'all'},**options}

def panel():return {'id':'part','kind':'mesh','vertices':[[0,0,0],[2,0,0],[2,2,0],[0,2,0]],'faces':[[0,1,2,3]]}

def document(obj,steps,**target):return {'version':'schemaxis.blender.production/1','prepareOnly':True,'production':{'objects':[obj],'meshEdits':[{'object':obj['id'],'steps':steps,**target}]}}


def signed_volume(g):
    result=0
    for face in g['faces']:
        a=g['vertices'][face[0]]
        for i in range(1,len(face)-1):
            b=g['vertices'][face[i]];c=g['vertices'][face[i+1]]
            result+=(a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cad',type=Path);p.add_argument('--resume',action='store_true');a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=a.resume);results=[];refusals=[]
    from schemaxis.artifacts import runtime_archive
    with zipfile.ZipFile(io.BytesIO(runtime_archive())) as archive:trusted={name:archive.read(name) for name in archive.namelist()}
    def execute(label,d,bounds,vertices,faces,volume=None,object_='part'):
        directory=out/label;reused=False
        if a.resume and (directory/'result.json').is_file() and json.loads((directory/'result.json').read_text()).get('status')=='succeeded':
            assert json.loads((directory/'authored.json').read_text())==d
            with zipfile.ZipFile(directory/'runtime.zip') as archive:assert set(archive.namelist())==set(trusted) and all(archive.read(name)==trusted[name] for name in trusted),'runtime source changed'
            result=json.loads((directory/'result.json').read_text());reused=True
        else:result=run(d,directory,executable=a.blender,timeout=180)
        assert result['verified'] and verify(directory)['verified'];obs=production(directory);sample=obs['samples'][0]['objects'][object_];close(sample['bounds'],bounds);assert (sample.get('vertices',sample.get('points')),sample.get('faces',sample.get('cells')))==(vertices,faces),(label,sample)
        if volume is not None:close([signed_volume(obs['meshEdits'][0]['geometry'])],[volume])
        results.append({'case':label,'literalBounds':bounds,'vertices':vertices,'faces':faces,'signedVolume':volume,'freshlyVerifiedRetainedRun':reused,'result':result});print(label+' PASS',flush=True);return obs
    def refuse(label,d,code):
        directory=out/label
        if directory.exists() and a.resume:
            n=1
            while (out/(label+'-retry-'+str(n))).exists():n+=1
            directory=out/(label+'-retry-'+str(n))
        try:run(d,directory,executable=a.blender,timeout=180)
        except SchemaxisError as error:assert error.fault.code==code,error.fault.to_dict();refusals.append({'case':label,'fault':error.fault.to_dict()});print(label+' REFUSED',flush=True)
        else:raise AssertionError(label+' unexpectedly succeeded')
    steps=[stage('extrudeFaces',offset=[0,0,2],keepBase=True),stage('insetFaces',{'kind':'normal','direction':[0,0,1]},distance=.25),{**stage('extrudeFaces',{'kind':'box','minimum':[.5,.5,2],'maximum':[1.5,1.5,2]},offset=[0,0,1]),'id':'cap'}]
    d=document(panel(),steps);d['production']['meshData']=[{'object':'part','attributes':[{'name':'temperature','kind':'float','mode':'constant','value':315}],'uvMaps':[{'name':'Paint','method':'planar','axis':'Z','size':[2,2]}]}]
    execute('enclosure-fields-uv',d,[0,2,0,2,0,3],16,14,10.25)
    obj=panel();obj['vertices']=[[0,0,0],[2,0,0],[2,2,0],[1,1,0],[0,2,0]];obj['faces']=[[0,1,2,3,4]]
    obs=execute('concave-triangulate',document(obj,[stage('triangulate')]),[0,2,0,2,0,0],5,3)
    areas=[]
    for face in obs['meshEdits'][0]['geometry']['faces']:
        x,y,z=[obj['vertices'][i] for i in face];areas.append(abs((y[0]-x[0])*(z[1]-x[1])-(y[1]-x[1])*(z[0]-x[0]))/2)
    close([sum(areas)],[3])
    obj=panel();obj['vertices']=[[0,0,0],[1,0,0],[1,1,0],[0,1,0],[1,0,0],[2,0,0],[2,1,0],[1,1,0]];obj['faces']=[[0,1,2,3],[4,5,6,7]]
    execute('weld-shared-boundary',document(obj,[stage('mergeVertices',{'kind':'all'},distance=.001)]),[0,2,0,1,0,0],6,2)
    execute('split-face',document(obj,[stage('splitFaces',{'kind':'indices','indices':[1]})]),[0,2,0,1,0,0],12,2)
    execute('delete-face-orphans',document(obj,[stage('delete',{'kind':'indices','indices':[1]})]),[0,1,0,1,0,0],4,1)
    obj=panel();obj['vertices']=[[0,0,0],[2,0,0],[2,2,0],[0,2,0],[0,0,2],[2,0,2],[2,2,2],[0,2,2]];obj['faces']=[[0,1,2,3],[4,7,6,5],[0,4,5,1],[1,5,6,2],[2,6,7,3],[3,7,4,0]]
    execute('outward-and-shading',document(obj,[stage('normals',mode='outward'),stage('shade',{'kind':'normal','direction':[0,0,1]},smooth=True)]),[0,2,0,2,0,2],8,6,8)
    cube=panel();cube['vertices']=[[0,0,0],[2,0,0],[2,2,0],[0,2,0],[0,0,2],[2,0,2],[2,2,2],[0,2,2]];cube['faces']=[[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
    caps=copy.deepcopy(cube);caps['faces']=caps['faces'][:2]
    execute('bridge-oriented-loops',document(caps,[stage('bridgeLoops',{'kind':'boundary'})]),[0,2,0,2,0,2],8,6,8)
    frustum=copy.deepcopy(caps);frustum['vertices'][4:]=[[.5,.5,3],[1.5,.5,3],[1.5,1.5,3],[.5,1.5,3]]
    obs=execute('bridge-tapered-frustum',document(frustum,[stage('bridgeLoops',{'kind':'boundary'},smooth=True)]),[0,2,0,2,0,3],8,6,7);assert sum(obs['meshEdits'][0]['geometry']['smooth'])==4
    for side,bounds in [('positive',[0,2,0,2,1,2]),('negative',[0,2,0,2,0,1])]:execute('plane-cut-'+side,document(cube,[stage('bisect',point=[0,0,1],side=side)]),bounds,8,6,4)
    execute('plane-cut-uncapped',document(cube,[stage('bisect',point=[0,0,1],cap=False)]),[0,2,0,2,1,2],8,5)
    for sharing in ('copy','shared'):
        d=document(panel(),[stage('transform',translation=[0,0,1])],sharing=sharing);d['production']['objects'].append({'id':'replica','kind':'instance','source':'part','location':[3,0,0]});d['production']['meshEdits'][0]['object']='replica'
        obs=execute('instance-'+sharing,d,[3,5,0,2,1,1],4,1,object_='replica');close(obs['samples'][0]['objects']['part']['bounds'],[0,2,0,2,0 if sharing=='copy' else 1,0 if sharing=='copy' else 1])
    d=resource_base();d['production']['meshEdits']=[{'object':'source','steps':[stage('extrudeFaces',offset=[0,0,1],keepBase=True)]}]
    execute('resource-after-topology',d,[4,6,1,2,0,1],6,5,1,object_='target')
    d={'version':'schemaxis.blender/1','nodes':[{'id':'paint','filter':'material'},{'id':'box','filter':'cube','inputs':{'material':'paint'},'options':{'size':2}}],'scenes':[{'id':'edit','visible':['box'],'prepareOnly':True,'render':{'samples':1,'threads':1},'images':[{'id':'preview','size':[32,32],'cameras':[{}]}],'production':{'meshEdits':[{'object':'box','steps':[stage('extrudeFaces',{'kind':'box','minimum':[-1,-1,1],'maximum':[1,1,1]},offset=[0,0,1])]}]}}]}
    execute('dag-constructor-source',d,[-1,1,-1,1,-1,2],12,10,12,object_='box')
    source=out/'source.blend'
    if not source.is_file():native(a.blender,"import bpy\nbpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)\nm=bpy.data.meshes.new('plate');m.from_pydata([(0,0,0),(2,0,0),(2,2,0),(0,2,0)],[],[(0,1,2,3)]);o=bpy.data.objects.new('plate',m);bpy.context.scene.collection.objects.link(o)\nm.materials.append(bpy.data.materials.new('A'));m.materials.append(bpy.data.materials.new('B'));m.polygons[0].material_index=1\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(source)!r})\n')
    asset={'version':'schemaxis.blender.production/1','prepareOnly':True,'production':{'assets':[{'id':'adopted','file':str(source),'format':'blend','location':[5,0,0],'rotation':[0,0,1.5707963267948966]}],'meshEdits':[{'object':'adopted','sourceObject':'plate','steps':[stage('extrudeFaces',{'kind':'material','slots':[1]},offset=[0,0,2],keepBase=True)]}]}}
    execute('native-source-material-selection',asset,[3,5,0,2,0,2],8,6,8,object_='adopted')
    diagonal=copy.deepcopy(asset);diagonal['production']['meshEdits'][0]['steps'].append(stage('bisect',point=[0,0,2],normal=[1,1,1],side='negative',capMaterial=0))
    obs=execute('native-diagonal-tetrahedral-cut',diagonal,[3,5,0,2,0,2],4,4,4/3,object_='adopted');assert sorted(obs['meshEdits'][0]['geometry']['materials'])==[0,1,1,1]
    rebound=copy.deepcopy(asset);rebound['production']['materialGraphs']=[{'id':'newFinish','nodes':[{'id':'surface','kind':'principled'},{'id':'out','kind':'output'}],'links':[{'from':{'node':'surface','socket':'shader'},'to':{'node':'out','socket':'surface'}}]}];rebound['production']['materialBindings']=[{'object':'adopted','material':'newFinish'}]
    obs=execute('edited-part-material-rebind',rebound,[3,5,0,2,0,2],8,6,8,object_='adopted');assert set(obs['meshEdits'][0]['geometry']['materials'])=={0};assert obs['meshEditBaselines'][0]['materialOverride'] is True
    grouped=copy.deepcopy(rebound);grouped['production']['objects']=[{'id':'carrier','kind':'empty'}];grouped['production']['hierarchy']=[{'object':'adopted','parent':'carrier'}];grouped['production']['materialBindings'][0]['object']='carrier'
    obs=execute('edited-hierarchy-material-rebind',grouped,[3,5,0,2,0,2],8,6,8,object_='adopted');assert obs['meshEditBaselines'][0]['materialOverride'] is True
    # Data-loss choice is explicit; unchanged native source remains available for
    # fresh replay rather than an editable saved pre-edit witness.
    uvsource=out/'uv-source.blend'
    if not uvsource.is_file():native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(source)!r},use_scripts=False)\n'+"bpy.data.objects['plate'].data.uv_layers.new(name='OriginalUV')\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(uvsource)!r})\n')
    d=copy.deepcopy(asset);d['production']['assets'][0]['file']=str(uvsource);refuse('source-uv-needs-loss-choice',d,'UNSUPPORTED_MESH_EDIT_DATA');d['production']['meshEdits'][0]['dataPolicy']='discard';execute('source-uv-explicit-discard',d,[3,5,0,2,0,2],8,6,8,object_='adopted')
    d=copy.deepcopy(asset);d['production']['meshEdits'].append({**copy.deepcopy(d['production']['meshEdits'][0]),'sourceObject':'','sharing':'copy'});refuse('source-alias-collision',d,'AMBIGUOUS_MESH_TARGET')
    d=document(panel(),[stage('extrudeFaces',offset=[0,0,1])]);d['production']['objects'].append({'id':'replica','kind':'instance','source':'part'});refuse('shared-needs-choice',d,'SHARED_MESH_DATA')
    refuse('collapsed-inset',document(panel(),[stage('insetFaces',distance=2)]),'INVALID_MESH_EDIT')
    refuse('outside-selection',document(panel(),[stage('shade',{'kind':'indices','indices':[4]})]),'INVALID_MESH_SELECTION')
    crossing=panel();crossing['vertices']=[[0,0,0],[2,2,0],[0,2,0],[2,0,0],[3,1,0]];crossing['faces']=[[0,1,2,3,4]]
    refuse('crossing-polygon-boundary',document(crossing,[stage('triangulate')]),'INVALID_MESH_EDIT')
    far=panel();far['vertices']=[[1000000,0,0],[1000000,2,0],[1000000,2,2],[1000000,0,2]]
    thin=[stage('extrudeFaces',offset=[.001,0,0],keepBase=True)]
    refuse('native-coordinate-precision-collapse',document(far,thin),'NATIVE_VALUE_MISMATCH')
    far['vertices']=[[0,y,z] for _,y,z in far['vertices']]
    obs=execute('recentered-thin-feature',document(far,thin),[0,.001,0,2,0,2],8,6,.004)
    xs=[p[0] for p in obs['meshEdits'][0]['geometry']['vertices']]
    assert abs(max(xs)-min(xs)-.001)<=2e-9
    assert abs(signed_volume(obs['meshEdits'][0]['geometry'])-.004)<=8e-9
    if a.cad:
        d={'version':'schemaxis.blender.production/1','prepareOnly':True,'production':{'units':'millimetres','assets':[{'id':'cad','file':str(a.cad.absolute()),'format':'glb'}],'meshEdits':[{'object':'cad','sourceObject':'housingView-exchange','dataPolicy':'discard','steps':[stage('transform',translation=[0,0,.001])]}],'meshData':[{'object':'cad','sourceObject':'housingView-exchange','attributes':[{'name':'temperature','kind':'float','mode':'constant','value':315}]}]}}
        # Historical accepted GLB is INPUT only. Counts are independently parsed
        # source accessors/indices by the resource qualifier, not native-derived.
        execute('cad-field-topology-handoff',d,[-15,15,-20,20,1,30],7370,4604,object_='cad')
    (out/'summary.json').write_text(json.dumps({'status':'passed','cases':results,'refusals':refusals},indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(results),'refusals':len(refusals)}))

if __name__=='__main__':main()
