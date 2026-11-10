"""Copied UV and hidden shader state refuse coforged observed companions."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify,plan
from schemaxis.adaptors.blender.production import verify_snapshot
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError
from schemaxis.publication_metadata import finalise,MANIFEST
from qualify_blender_imported_materials import native
from qualify_blender_render_policy import document
from qualify_blender_image_preview import png
from blender_surface_evidence import identity,verify_identity


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    archive=hashlib.sha256(runtime_archive()).hexdigest();report={'status':'running',
        'providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':archive,
        'qualifierSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'checks':[]}
    target=out/'summary.json'
    report.update(identity(out,args.blender));trusted=out/'trusted-runtime.zip';trusted.write_bytes(runtime_archive())
    def record(value):
        report['checks'].append(value);target.write_text(json.dumps(report,indent=2)+'\n');print(value['case']+' PASS',flush=True)
    packet=out/'project';image=out/'image.png';png(image,[[32,64,96,255],[96,160,224,255],[64,128,192,255],[192,96,32,255]])
    d=document();p=d['production'];p['materialGraphs']=[]
    p['surfaceMaterials']=[{'id':'surface','samplers':[{'id':'image','image':'image','filter':'nearest',
        'coordinates':{'kind':'uv','set':{'kind':'named','name':'Finish'}}}],
        'baseColour':{'kind':'constant','value':[0,0,0]},'ior':{'kind':'constant','value':1},
        'emission':{'colour':{'kind':'sample','sampler':'image'},'strength':{'kind':'constant','value':1}}}]
    p['images']=[{'id':'image','file':str(image),'colourSpace':'Non-Color'}]
    p['meshData']=[{'object':'patch','uvMaps':[{'name':'Base','method':'planar','origin':[-1,-1,0],'size':[2,2]},
        {'name':'Finish','method':'copy','source':'Base','transform':{'rotationDegrees':45,'scale':[-2,3]}}]}]
    try:
        run(d,packet,executable=args.blender,timeout=180)
        with location_context({'blender':args.blender}):assert verify(packet)['verified']
        record({'case':'original-public-positive'})
        blend=packet/'0000.blend';receipt=packet/'verification.json';reopened=packet/'reopened.json'
        saved={path:path.read_bytes() for path in [blend,receipt,reopened,packet/MANIFEST,*packet.glob('*.metadata.json')]}
        cases=[('unchanged-save','',True),
            ('copied-stored-uv',"obj.data.uv_layers['Finish'].data[0].uv.x+=.2",False),
            ('copied-uv-all-corners',"\nfor corner in obj.data.uv_layers['Finish'].data:corner.uv.y+=.125",False),
            ('hidden-subsurface-scale',"shader.inputs['Subsurface Scale'].default_value=.37",False),
            ('cycles-material-setting',"mat.cycles.emission_sampling='NONE'",False)]
        try:
            for label,mutation,positive in cases:
                for path,value in saved.items():path.write_bytes(value)
                witness=out/(label+'-observed.json')
                code='import bpy,json,sys\n'+f'sys.path.insert(0,{str(packet/"runtime.zip")!r})\n'+\
                    f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+\
                    'bpy.context.preferences.filepaths.save_version=0\n'+\
                    'from schemaxis.adaptors.blender.adaptor import plan\nfrom schemaxis.adaptors.blender.native import snapshot\nfrom schemaxis.adaptors.blender.production_native import observe\n'+\
                    f'master,selection,_=plan(json.loads(open({str(packet/"input.json")!r}).read()))\n'+\
                    "spec=master.document['scenes'][0]['production'];obj=bpy.data.objects['patch'];mat=bpy.data.materials['surface'];shader=next(n for n in mat.node_tree.nodes if n.bl_idname=='ShaderNodeBsdfPrincipled')\n"+mutation+'\n'+\
                    f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+\
                    f'open({str(witness)!r},"w").write(json.dumps({{"state":snapshot(selection.order),"production":observe(spec)}}))\n'
                native(args.blender,code);observed=json.loads(witness.read_text())
                observed['production']['meshEditBaselines']=json.loads(saved[receipt])['states'][0]['production']['meshEditBaselines']
                current=json.loads(saved[receipt]);current['states'][0].update(snapshot=observed['state'],production=observed['production'])
                next(a for a in current['artifacts'] if a['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest()
                receipt.write_text(json.dumps(current));current=json.loads(saved[reopened]);current['states'][0]=observed['state'];current['production'][0]=observed['production'];reopened.write_text(json.dumps(current));finalise(packet)
                master,_,_=plan(d)
                verify_snapshot(master.document['scenes'][0]['production'],observed['production'],packet)
                fault=None
                with location_context({'blender':args.blender}):
                    try:verify(packet)
                    except SchemaxisError as exc:fault=exc.fault.to_dict()
                direct=out/(label+'-direct-fault.json')
                native(args.blender,'import sys,json\n'+f'sys.path.insert(0,{str(trusted)!r})\n'+
                    'from schemaxis.adaptors.blender.native import reopen\nfrom schemaxis.errors import SchemaxisError\n'+
                    f'fault=None\ntry:reopen({str(packet)!r},{str(out/(label+"-direct-readback.json"))!r})\nexcept SchemaxisError as exc:fault=exc.fault.to_dict()\n'+
                    f'open({str(direct)!r},"w").write(json.dumps(fault))\n')
                fresh=json.loads(direct.read_text())
                record({'case':label,'positive':positive,'hostProductionReplayAccepted':True,
                    'bothOrdinaryAndProductionSnapshotsRefreshed':True,'nativeHashAndPublicationRefreshed':True,
                    'publicFault':fault,'directFault':fresh})
                if positive:assert fault is None and fresh is None,(fault,fresh)
                else:
                    mutant=out/'mutants'/label;mutant.mkdir(parents=True)
                    for path in saved:(mutant/path.name).write_bytes(path.read_bytes())
                    assert fault and fault['code']=='VERIFICATION_FAILED',fault
                    assert fresh and fresh['code']=='VERIFICATION_FAILED' and 'shader state differs' in fresh['message'],fresh
        finally:
            for path,value in saved.items():path.write_bytes(value)
        with location_context({'blender':args.blender}):assert verify(packet)['verified']
        record({'case':'restored-original-public-positive'})
        assert all(path.read_bytes()==value for path,value in saved.items())
        assert hashlib.sha256(runtime_archive()).hexdigest()==archive
        verify_identity(report,args.blender)
        report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
