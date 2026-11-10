"""Connected reusable surface projects with literal geometry and palette checks."""
import argparse,copy,hashlib,json
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.configuration import location_context
from schemaxis.artifacts import runtime_archive
from qualify_blender_imported_materials import native
from schemaxis.png import read
from schemaxis.studio_library import load_library,instantiate_item
from blender_surface_evidence import identity,verify_identity


def image(directory):
    receipt=json.loads((directory/'verification.json').read_text())
    return read(next(Path(a['file']) for a in receipt['artifacts'] if a.get('kind')=='image'))


def close(found,reference):
    assert len(found)==len(reference) and all(abs(a-b)<2e-6 for a,b in zip(found,reference)),(found,reference)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False);repo=Path(__file__).resolve().parents[1]
    report={'status':'running',**identity(out,args.blender),'checks':[]};target=out/'summary.json'
    library=load_library('blender')
    def starter(identity):
        return instantiate_item(library,next(item for item in library['templates'] if item['id']==identity))
    def record(value):report['checks'].append(value);target.write_text(json.dumps(report,indent=2)+'\n');print(value['case']+' PASS',flush=True)
    def execute(label,d):
        directory=out/label;run(d,directory,executable=args.blender,timeout=300)
        with location_context({'blender':args.blender}):assert verify(directory)['verified']
        return directory,json.loads((directory/'reopened.json').read_text())['production'][0]
    try:
        for label,template in [('layered','layered-surfaces'),('textured','textured-pbr-enclosure')]:
            d=starter(template)
            for value in d['production'].get('images',[]):value['file']=str(repo/value['file'])
            directory,observed=execute(label,d);objects=observed['samples'][0]['objects']
            close(objects['housing']['bounds'],[-2.3,-.3,-.6,.6,-.25,.25]);close(objects['edition']['bounds'],[.3,2.3,-.6,.6,-.25,.25])
            for name in ('housing','edition'):
                assert objects[name]['vertices']==8 and objects[name]['faces']==6,objects[name]
            assignments=observed['materialAssignments'];assert len(assignments)==2
            assert all(a['indices']==[0,1,0,0,0,0] for a in assignments),assignments
            assert assignments[0]['owners']==['edition','housing'],assignments
            width,height,pixels=image(directory);assert len(set(bytes(pixels[4*i:4*i+3]) for i in range(width*height)))>100
            record({'case':label,'independentBounds':[[-2.3,-.3,-.6,.6,-.25,.25],[.3,2.3,-.6,.6,-.25,.25]],
                    'literalTopology':{'vertices':8,'faces':6},'literalFaceSlots':[0,1,0,0,0,0],
                    'sharedOwners':['edition','housing'],'size':[width,height],
                    'imageScope':'Nonempty connected PBR composition; exact optical references are separate qualifiers.'})
        d=starter('surface-gallery')
        directory,observed=execute('resin-fabric-glass',d);objects=observed['samples'][0]['objects']
        for name,x in [('resin',-1.8),('fabric',0),('glass',1.8)]:close(objects[name]['bounds'],[x-.7,x+.7,-.7,.7,-.7,.7])
        trusted=out/'trusted-runtime.zip';trusted.write_bytes(runtime_archive());geometry=out/'sphere-native-geometry.json'
        code=f"""import sys,bpy,json,hashlib
sys.path.insert(0,{str(trusted)!r})
bpy.ops.wm.open_mainfile(filepath={str(directory/"0000.blend")!r},use_scripts=False)
for name in ("resin","fabric","glass"):
    mesh=bpy.data.objects[name].data
    assert (len(mesh.vertices),len(mesh.edges),len(mesh.polygons))==(482,992,512)
    assert all(abs(v.co.length-.7)<1e-6 for v in mesh.vertices)
    assert all(p.center.dot(p.normal)>0 for p in mesh.polygons)
from schemaxis.adaptors.blender.meshes import populate
rows=[]
for i in range(8):
    mesh=bpy.data.meshes.new("repeat")
    populate(mesh,"uvSphere",{{"segments":32,"rings":16,"radius":.7,"smoothShading":True}})
    payload={{"vertices":[list(v.co) for v in mesh.vertices],"edges":[list(e.vertices) for e in mesh.edges],"faces":[list(p.vertices) for p in mesh.polygons]}}
    rows.append(hashlib.sha256(json.dumps(payload).encode()).hexdigest())
    bpy.data.meshes.remove(mesh)
assert len(set(rows))==1
open({str(geometry)!r},"w").write(json.dumps({{"repeatedConstructionHashes":rows,"literalCounts":[482,992,512],"radius":.7,"maximumRadiusError":1e-6,"outwardFaces":True}}))
"""
        native(args.blender,code)
        record({'case':'sphere-native-topology-and-repeatability',**json.loads(geometry.read_text())})
        width,height,pixels=image(directory)
        def patch(data):
            # Projection of the fabric sphere centre is near(240,131), with
            # margins far from the silhouette and other material regions.
            rows=[data[4*(y*width+x):4*(y*width+x)+3] for y in range(128,135) for x in range(237,244)]
            return [sum(row[k] for row in rows)/len(rows) for k in range(3)]
        before=patch(pixels);assert before[2]-before[0]>=5,before
        record({'case':'resin-fabric-glass','literalSphereBounds':[[x-.7,x+.7,-.7,.7,-.7,.7] for x in [-1.8,0,1.8]],
                'fabricPatchMeanRGB':before,'independentColourOrdering':'Blue fabric patch blue exceeds red by at least5 encoded bytes.'})
        changed=copy.deepcopy(d);p=changed['scenes'][0]['production']
        fabric=next(m for m in p['surfaceMaterials'] if m['id']=='fabricMaterial')
        fabric['baseColour']={'kind':'constant','value':[.3,.03,.015]};fabric['sheen']['weight']={'kind':'constant','value':0}
        directory,_=execute('warm-fabric-variant',changed);w,h,after_pixels=image(directory);assert (w,h)==(width,height)
        after=patch(after_pixels);assert after[0]-after[2]>=5,after
        assert hashlib.sha256(pixels).hexdigest()!=hashlib.sha256(after_pixels).hexdigest()
        record({'case':'warm-fabric-variant','fabricPatchMeanRGB':after,
                'independentColourOrdering':'Warm fabric patch red exceeds blue by at least5 encoded bytes.',
                'scope':'Meaningful colour/sheen parameter response; no arbitrary image-equivalence or independent skin-scattering convergence claim.'})
        verify_identity(report,args.blender);report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
