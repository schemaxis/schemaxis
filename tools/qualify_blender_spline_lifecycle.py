"""Physical gasket handoff and manual rational/profile control adoption."""
import argparse,json,math
from pathlib import Path
from qualify_blender_mesh_data import close,native,production
from qualify_blender_splines import geometry
from qualify_blender_geometry_resources import base
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.adaptors.blender.production_outputs import file_geometry
from schemaxis.errors import SchemaxisError
from blender_tamper import qualify


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=False);root=Path(__file__).resolve().parents[1];cases=[]
    example=json.loads((root/'examples/schemaxis/blender-splines.json').read_text());directory=out/'gasket-and-hose';result=run(example,directory,executable=a.blender,timeout=180);assert verify(directory)['verified'];obs=production(directory)['samples'][0]['objects'];close(obs['gasket']['bounds'],[-20,20,-10,10,-1,1]);geo=geometry(a.blender,directory,'gasket');assert math.isclose(geo['volume'],1200,rel_tol=1e-6);metric=file_geometry(directory/'0000-export-gasket.glb','glb');close(metric['bounds'],[-.02,.02,-.01,.01,-.001,.001]);assert metric['triangles']==32 and math.isclose(metric['signedVolume'],1.2e-6,rel_tol=2e-6),metric;cases.append({'case':'runnable-starter-physical-gasket-GLB','result':result,'literalVolumeMM3':1200,'literalPhysicalVolumeM3':1.2e-6,'literalTriangles':32,'parsedGeometry':metric})
    from qualify_blender_splines import curve,point
    prototype=curve('prototype',[point(-1,-1),point(1,-1),point(1,1),point(-1,1)],dimensions='2D',extrude=1,collection='sections');prototype['splines'][0]['closed']=True
    instanced={'version':'schemaxis.blender.production/1','prepareOnly':True,'visible':['first','second'],'production':{'units':'millimetres','collections':[{'id':'sections'}],'objects':[prototype,{'id':'first','kind':'collectionInstance','source':'sections','location':[5,0,0]},{'id':'second','kind':'collectionInstance','source':'sections','location':[10,0,0]}],'exports':[{'id':f,'format':f,'objects':['first','second']} for f in ('stl','obj','ply','glb','usd')]}}
    directory=out/'curve-collection-instances';result=run(instanced,directory,executable=a.blender,timeout=180);assert verify(directory)['verified'];formats=[]
    for fmt,extension in [('stl','stl'),('obj','obj'),('ply','ply'),('glb','glb'),('usd','usda')]:
        metric=file_geometry(directory/('0000-export-'+fmt+'.'+extension),fmt);scale=.001 if fmt in ('glb','usd') else 1;close(metric['bounds'],[4*scale,11*scale,-scale,scale,-scale,scale]);assert metric['triangles']==24 and math.isclose(metric['signedVolume'],16*scale**3,rel_tol=2e-6),metric;formats.append({'format':fmt,'metrics':metric})
    cases.append({'case':'two-curve-collection-instances-five-formats','result':result,'literalTriangles':24,'literalVolumeMM3':16,'formats':formats})
    source=out/'hand-edited-rational.blend';native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(a.suite/"rational-quarter/0000.blend")!r},use_scripts=False)\n'+"bpy.data.objects['quarter'].data.splines[0].points[1].weight=.5\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(source)!r})\n')
    d=base();s=d['production'];s['objects']=s['objects'][1:];s['objects'][0]['location']=[0,0,0];s['assets']=[{'id':'adopted','file':str(source),'format':'blend'}];s['geometryResources']=[{'id':'selected','kind':'object','object':'adopted','sourceObject':'quarter'}]
    graph=s['geometryGraphs'][0];graph['nodes'].insert(1,{'id':'wire','kind':'curveToMesh'});graph['links']=[{'from':{'node':'source','socket':'geometry'},'to':{'node':'wire','socket':'curve'}},{'from':{'node':'wire','socket':'mesh'},'to':{'node':'realise','socket':'geometry'}},graph['links'][-1]]
    directory=out/'adopted-rational';result=run(d,directory,executable=a.blender,timeout=180);assert verify(directory)['verified'];geo=geometry(a.blender,directory,'target');assert len(geo['points'])==13;close(geo['points'][6],[2/3,2/3,0]);cases.append({'case':'manual-weight-edit-adopted-as-new-source','result':result,'literalInteriorPoint':[2/3,2/3,0]})
    held=source.with_suffix('.held');source.rename(held)
    try:
        native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(directory/"0000.blend")!r},use_scripts=False)\n'+"assert bpy.data.objects['adopted--quarter'].data.splines[0].points[1].weight==.5\n")
        try:verify(directory)
        except SchemaxisError as error:assert error.fault.code in ('VERIFICATION_FAILED','RESOURCE_NOT_FOUND');fault=error.fault.to_dict()
        else:raise AssertionError('receipt accepted a missing original source')
    finally:held.rename(source)
    assert verify(directory)['verified'];cases.append({'case':'packed-native-reopen-original-absence-receipt-refusal-restoration','fault':fault})
    # Quarter-profile point edits remain native editable controls in a new source;
    # source fidelity must compare them independently from declaration witnesses.
    profile=out/'hand-edited-profile.blend';native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(a.suite/"profile-chamfer/0000.blend")!r},use_scripts=False)\n'+"p=bpy.data.objects['profile'].data.bevel_profile;p.points[1].location=(1,.25);p.update()\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(profile)!r})\n')
    d={'version':'schemaxis.blender.production/1','prepareOnly':True,'production':{'assets':[{'id':'edited','file':str(profile),'format':'blend'}]}};directory=out/'adopted-profile';result=run(d,directory,executable=a.blender,timeout=180);assert verify(directory)['verified'];geo=geometry(a.blender,directory,'edited--profile');assert math.isclose(geo['volume'],.26,rel_tol=2e-6),geo['volume'];cases.append({'case':'custom-quarter-profile-edit-adopted','result':result,'literalSectionArea':.13,'literalVolume':.26})
    attacks=qualify(a.blender,[('capturedProfile',directory)],{'capturedControl':"p=bpy.data.objects['edited--profile'].data.bevel_profile;p.points[1].location=(.8,.25);p.update()"})
    free=out/'unmapped-free-profile.blend';native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(profile)!r},use_scripts=False)\n'+"p=bpy.data.objects['profile'].data.bevel_profile\nfor n in p.points:n.select=False\np.points[1].select=True;p.points[1].handle_type_1='FREE'\nassert p.points[1].handle_type_1=='FREE'\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(free)!r})\n')
    d['production']['assets'][0]['file']=str(free)
    try:run(d,out/'free-profile-refusal',executable=a.blender,timeout=180)
    except SchemaxisError as error:assert error.fault.code=='UNSUPPORTED_ASSET_DEPENDENCY';cases.append({'case':'unmapped-free-profile-refusal','fault':error.fault.to_dict()})
    else:raise AssertionError('unmapped free quarter-profile handles were accepted')
    report={'status':'passed','cases':cases,'nativeTamper':attacks};(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(cases),'mutations':len(attacks['cases']),'controls':len(attacks['controls'])}))

if __name__=='__main__':main()
