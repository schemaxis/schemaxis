"""Fresh render context and explicitly consumed numeric shader inputs."""
import argparse,hashlib,json
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError
from schemaxis.publication_metadata import finalise,MANIFEST
from qualify_blender_imported_materials import native
from qualify_blender_render_policy import document,pixel
from blender_surface_evidence import identity,verify_identity


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--snell-packet',type=Path,required=True)
    parser.add_argument('--plain-only',action='store_true')
    args=parser.parse_args();out=args.output.absolute();out.mkdir(parents=True)
    report={'status':'running',**identity(out,args.blender),'checks':[]};target=out/'summary.json'
    trusted=out/'trusted-runtime.zip';trusted.write_bytes(runtime_archive())
    def record(case,**values):
        report['checks'].append({'case':case,**values});target.write_text(json.dumps(report,indent=2)+'\n');print(case+' PASS',flush=True)
    def public(packet):
        with location_context({'blender':args.blender}):return verify(packet)
    def attacks(packet,cases):
        assert public(packet)['verified'];record(packet.name+'-original')
        blend=packet/'0000.blend';receipt=packet/'verification.json';reopened=packet/'reopened.json'
        saved={p:p.read_bytes() for p in [blend,receipt,reopened,packet/MANIFEST,*packet.glob('*.metadata.json')]}
        try:
            for label,mutation,positive,rerender in cases:
                for p,value in saved.items():p.write_bytes(value)
                case=out/label;case.mkdir();witness=case/'observed.json';image=case/'rerender.png'
                code='import bpy,json,sys\n'+f'sys.path.insert(0,{str(packet/"runtime.zip")!r})\n'+\
                    f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+\
                    'bpy.context.preferences.filepaths.save_version=0\nscene=bpy.context.scene\n'+mutation+'\n'+\
                    f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+\
                    'from schemaxis.adaptors.blender.adaptor import plan\nfrom schemaxis.adaptors.blender.native import snapshot\nfrom schemaxis.adaptors.blender.production_native import observe\n'+\
                    f'master,selection,_=plan(json.loads(open({str(packet/"input.json")!r}).read()))\n'+\
                    f'open({str(witness)!r},"w").write(json.dumps({{"state":snapshot(selection.order),"production":observe(master.document["scenes"][0]["production"]) if "production" in master.document["scenes"][0] else None}}))\n'
                if rerender:code+=f'scene.render.filepath={str(image)!r}\nbpy.ops.render.render(write_still=True)\n'
                (case/'native-recipe.py').write_text(code);native(args.blender,code)
                observed=json.loads(witness.read_text())
                if observed['production'] is not None:
                    observed['production']['meshEditBaselines']=json.loads(saved[receipt])['states'][0]['production']['meshEditBaselines']
                value=json.loads(saved[receipt]);value['states'][0]['snapshot']=observed['state']
                if observed['production'] is not None:value['states'][0]['production']=observed['production']
                next(a for a in value['artifacts'] if a['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();receipt.write_text(json.dumps(value))
                value=json.loads(saved[reopened]);value['states'][0]=observed['state']
                if observed['production'] is not None:value['production'][0]=observed['production']
                reopened.write_text(json.dumps(value));finalise(packet)
                fault=None
                try:public(packet)
                except SchemaxisError as error:fault=error.fault.to_dict()
                direct=case/'direct-fault.json'
                code='import sys,json\n'+f'sys.path.insert(0,{str(trusted)!r})\n'+\
                    'from schemaxis.adaptors.blender.native import reopen\nfrom schemaxis.errors import SchemaxisError\nfault=None\n'+\
                    f'try:reopen({str(packet)!r},{str(case/"direct-reopened.json")!r})\n'+\
                    'except SchemaxisError as error:fault=error.fault.to_dict()\n'+\
                    f'open({str(direct)!r},"w").write(json.dumps(fault))\n'
                (case/'direct-recipe.py').write_text(code);native(args.blender,code);fresh=json.loads(direct.read_text())
                extra={}
                if rerender:
                    from schemaxis.png import read
                    w,h,values=read(image);rgba=list(values[4*((h//2)*w+w//2):4*((h//2)*w+w//2)+4])
                    extra={'originalRGBA':pixel(packet),'sameProjectRerenderRGBA':rgba}
                    assert max(rgba[:3])<=2 and max(extra['originalRGBA'][:3])>=150,extra
                assert (fault is None)==positive and (fresh is None)==positive,(label,fault,fresh)
                if not positive:
                    assert fresh['code']=='VERIFICATION_FAILED' and any(s in fresh['message'] for s in ('render context differs','shader state differs','depth of field')),fresh
                    for p in saved:(case/p.name).write_bytes(p.read_bytes())
                record(label,positive=positive,publicFault=fault,directFault=fresh,bothSnapshotsNativeHashPublicationRefreshed=True,**extra)
        finally:
            for p,value in saved.items():p.write_bytes(value)
        assert public(packet)['verified'] and all(p.read_bytes()==v for p,v in saved.items());record(packet.name+'-restored')
    def plain():
        source=out/'plain.ply'
        source.write_text('ply\nformat ascii 1.0\nelement vertex 4\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n-1 -1 0\n1 -1 0\n1 1 0\n-1 1 0\n4 0 1 2 3\n')
        d={'version':'schemaxis.blender/1','nodes':[{'id':'box','filter':'readPLY','options':{'file':str(source)}}],
           'scenes':[{'id':'plain','visible':['box'],'prepareOnly':True,
             'render':{'samples':1,'threads':2},
             'images':[{'id':'view','size':[32,32],'cameras':[{'direction':[1,-2,1]}]}]}]}
        packet=out/'plain';run(d,packet,executable=args.blender,timeout=180)
        attacks(packet,[('plain-unchanged','',True,False),('plain-max-bounces','scene.cycles.max_bounces=0',False,False)])
    try:
        if args.plain_only:
            plain();verify_identity(report,args.blender);report['status']='passed';return
        attacks(args.snell_packet.absolute(),[
            ('unchanged-save','',True,False),
            ('unqueried-preview','scene.cycles.preview_samples=17',True,False),
            ('max-bounces','scene.cycles.max_bounces=0',False,True),
            ('transmission-bounces','scene.cycles.transmission_bounces=0',False,False),
            ('world-bounces','scene.world.cycles.max_bounces=1',False,False),
            ('light-bounces',"bpy.data.lights['__schemaxis_light'].cycles.max_bounces=1",False,False),
            ('camera-shift','scene.camera.data.shift_x=.2',False,False),
            ('camera-dof','scene.camera.data.dof.use_dof=True',False,False)])
        source=out/'attribute-source.blend'
        code='import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\n'+\
            "mesh=bpy.data.meshes.new('patch');mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)],[],[(0,1,2,3)])\nobj=bpy.data.objects.new('patch',mesh);bpy.context.scene.collection.objects.link(obj)\n"+\
            "mat=bpy.data.materials.new('attribute');mat.use_nodes=True;tree=mat.node_tree;tree.nodes.clear()\na=tree.nodes.new('ShaderNodeAttribute');a.attribute_name='cycles.preview_samples';a.attribute_type='VIEW_LAYER'\nm=tree.nodes.new('ShaderNodeMath');m.operation='DIVIDE';m.inputs[1].default_value=1024\ne=tree.nodes.new('ShaderNodeEmission');o=tree.nodes.new('ShaderNodeOutputMaterial');tree.links.new(a.outputs['Fac'],m.inputs[0]);tree.links.new(m.outputs[0],e.inputs[0]);tree.links.new(e.outputs[0],o.inputs[0]);mesh.materials.append(mat)\n"+\
            f'bpy.ops.wm.save_as_mainfile(filepath={str(source)!r})\n'
        (out/'attribute-source-recipe.py').write_text(code);native(args.blender,code)
        d=document();d['render'].update(lightEnergy=0,worldStrength=0);d['production']={'assets':[{'id':'model','file':str(source),'format':'blend'}]}
        packet=out/'attribute';run(d,packet,executable=args.blender,timeout=180)
        assert pixel(packet)==[255,255,255,255],pixel(packet)
        attacks(packet,[('queried-preview-unchanged','',True,False),
                        ('queried-preview','scene.cycles.preview_samples=0',False,True)])
        plain()
        verify_identity(report,args.blender);report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
