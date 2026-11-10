"""Fresh renderer participation, transforms and cold-frame camera acceptance."""
import argparse,copy,hashlib,json,math
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError
from schemaxis.publication_metadata import finalise,MANIFEST
from qualify_blender_imported_materials import native
from qualify_blender_render_policy import document,settings,pixel,expected
from blender_surface_evidence import identity,verify_identity


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--start-at',choices=['fixed','production','workbench','physics'],default='fixed');args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True);report={'status':'running',**identity(out,args.blender),'startAt':args.start_at,'checks':[]}
    trusted=out/'trusted-runtime.zip';trusted.write_bytes(runtime_archive());target=out/'summary.json'
    def record(case,**values):
        report['checks'].append({'case':case,**values});target.write_text(json.dumps(report,indent=2)+'\n');print(case+' PASS',flush=True)
    def public(packet):
        with location_context({'blender':args.blender}):return verify(packet)
    def attacks(packet,cases):
        assert public(packet)['verified']
        images=[a for a in json.loads((packet/'verification.json').read_text())['artifacts'] if a.get('kind')=='image']
        if not images:assert json.loads((packet/'input.json').read_text())['scenes'][0].get('prepareOnly') is True
        record(packet.name+'-original',centreRGBA=pixel(packet) if images else None,prepareOnly=not images)
        blend=packet/'0000.blend';receipt=packet/'verification.json';reopened=packet/'reopened.json'
        saved={p:p.read_bytes() for p in [blend,receipt,reopened,packet/MANIFEST,*packet.glob('*.metadata.json')]}
        try:
            for label,mutation,positive,dark in cases:
                for p,raw in saved.items():p.write_bytes(raw)
                case=out/label;case.mkdir();witness=case/'observed.json';image=case/'rerender.png'
                code=f'import bpy,json,sys\nsys.path.insert(0,{str(packet/"runtime.zip")!r})\nbpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+\
                    'bpy.context.preferences.filepaths.save_version=0\nscene=bpy.context.scene\n'+mutation+'\n'+\
                    f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n'+\
                    'from schemaxis.adaptors.blender.adaptor import plan\nfrom schemaxis.adaptors.blender.native import snapshot\nfrom schemaxis.adaptors.blender.production_native import observe\n'+\
                    f'master,selection,_=plan(json.loads(open({str(packet/"input.json")!r}).read()))\np=master.document["scenes"][0].get("production")\n'+\
                    f'production=observe(p) if p is not None else None\nstate=snapshot(selection.order)\nopen({str(witness)!r},"w").write(json.dumps(dict(state=state,production=production)))\n'
                if dark:code+=f'scene.render.filepath={str(image)!r}\nbpy.ops.render.render(write_still=True)\n'
                (case/'native-recipe.py').write_text(code);native(args.blender,code)
                observed=json.loads(witness.read_text());value=json.loads(saved[receipt]);value['states'][0]['snapshot']=observed['state']
                if observed['production'] is not None:
                    observed['production']['meshEditBaselines']=value['states'][0]['production']['meshEditBaselines'];value['states'][0]['production']=observed['production']
                next(a for a in value['artifacts'] if a['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest();receipt.write_text(json.dumps(value))
                value=json.loads(saved[reopened]);value['states'][0]=observed['state']
                if observed['production'] is not None:value['production'][0]=observed['production']
                reopened.write_text(json.dumps(value));finalise(packet)
                fault=None
                try:public(packet)
                except SchemaxisError as error:fault=error.fault.to_dict()
                direct=case/'direct-fault.json'
                code=f'import sys,json\nsys.path.insert(0,{str(trusted)!r})\nfrom schemaxis.adaptors.blender.native import reopen\nfrom schemaxis.errors import SchemaxisError\nfault=None\ntry:reopen({str(packet)!r},{str(case/"direct-reopened.json")!r})\nexcept SchemaxisError as e:fault=e.fault.to_dict()\nopen({str(direct)!r},"w").write(json.dumps(fault))\n'
                (case/'direct-recipe.py').write_text(code);native(args.blender,code);fresh=json.loads(direct.read_text())
                assert (fault is None)==positive and (fresh is None)==positive,(label,fault,fresh)
                if not positive:
                    assert fault['code']==fresh['code']=='VERIFICATION_FAILED',(fault,fresh)
                    message='background scenes and scene animation need a typed render contract' if label=='background-scene' else 'render context differs'
                    assert message in fault['message'] and message in fresh['message'],(fault,fresh)
                    for p in saved:(case/p.name).write_bytes(p.read_bytes())
                extra={}
                if dark:
                    from schemaxis.png import read
                    w,h,rgba=read(image);actual=list(rgba[4*((h//2)*w+w//2):4*((h//2)*w+w//2)+4])
                    assert max(actual[:3])<=2 and max(pixel(packet)[:3])>=50,(label,actual,pixel(packet))
                    extra={'originalRGBA':pixel(packet),'sameProjectRerenderRGBA':actual,'independentDarkReference':[0,0,0,255]}
                record(label,positive=positive,publicFault=fault,directFault=fresh,bothReadbacksNativeHashPublicationRefreshed=True,**extra)
        finally:
            for p,raw in saved.items():p.write_bytes(raw)
        assert public(packet)['verified'] and all(p.read_bytes()==raw for p,raw in saved.items());record(packet.name+'-restored')
    try:
        d=document();d['render'].update(samples=16,worldStrength=0,lightEnergy=1000,lightPosition=[0,0,5],lightSize=1)
        d['production']['collections']=[{'id':'layout'}];d['production']['objects'][0]['collection']='layout'
        d['production']['materialGraphs']=[];d['production']['surfaceMaterials']=[{'id':'surface','baseColour':{'kind':'constant','value':[1,1,1]},'roughness':{'kind':'constant','value':1},'ior':{'kind':'constant','value':1}}]
        if args.start_at=='fixed':
            packet=out/'fixed';run(d,packet,executable=args.blender,timeout=180)
            attacks(packet,[('unchanged-save','',True,False),
                ('camera-translation','scene.camera.location.x+=100',False,True),
                ('camera-quaternion',"scene.camera.rotation_mode='QUATERNION';scene.camera.rotation_quaternion=(0,1,0,0)",False,False),
                ('lamp-ray-visibility',"bpy.data.objects['__schemaxis_light'].visible_diffuse=False",False,True),
                ('lamp-delta',"bpy.data.objects['__schemaxis_light'].delta_location=(100,0,0)",False,False),
                ('lamp-quaternion',"o=bpy.data.objects['__schemaxis_light'];o.rotation_mode='QUATERNION';o.rotation_quaternion=(0,1,0,0)",False,True),
                ('lamp-outside-scene',"o=bpy.data.objects['__schemaxis_light'];c=bpy.data.collections.new('Parked');c.use_fake_user=True\nfor old in list(o.users_collection):old.objects.unlink(o)\nc.objects.link(o)",False,True),
                ('extra-light',"l=bpy.data.lights.new('extra','POINT');l.energy=1000;o=bpy.data.objects.new('extra',l);scene.collection.objects.link(o)",False,False),
                ('extra-layer',"scene.view_layers.new('Extra')",False,False),
                ('layer-mask',"bpy.context.view_layer.use_solid=False",False,False),
                ('material-override',"bpy.context.view_layer.material_override=bpy.data.materials['surface']",False,False),
                ('layer-holdout',"bpy.context.view_layer.layer_collection.children['layout'].holdout=True",False,False),
                ('light-linking',"o=bpy.data.objects['__schemaxis_light'];c=bpy.data.collections.new('OnlyNone');o.light_linking.receiver_collection=c",False,False),
                ('unclaimed-compositor',"scene.compositing_node_group=bpy.data.node_groups.new('Unexpected','CompositorNodeTree')",False,False),
                ('background-scene',"scene.background_set=bpy.data.scenes.new('Unexpected')",False,False)])
        if args.start_at in ('fixed','production'):
            sun=copy.deepcopy(d);sun['render']['lightEnergy']=0
            sun['production']['objects'].append({'id':'sun','kind':'light','type':'SUN','energy':1,'angle':.000001})
            sun['production']['objects'].append({'id':'shot','kind':'camera','projection':'orthographic','location':[0,0,5]})
            packet=out/'production';run(sun,packet,executable=args.blender,timeout=180)
            wanted=expected([1/math.pi]*3,0);assert all(abs(a-b)<=2 for a,b in zip(pixel(packet),wanted)),(pixel(packet),wanted)
            record('unit-sun-reference',expectedRGBA=wanted,actualRGBA=pixel(packet),linearRadiance=1/math.pi)
            attacks(packet,[('sun-ray-visibility',"bpy.data.objects['sun'].visible_diffuse=False",False,True),
                ('sun-cycles',"bpy.data.objects['sun'].data.cycles.max_bounces=1",False,False),
                ('production-camera-shift',"bpy.data.objects['shot'].data.shift_x=.4",False,False),
                ('production-camera-panorama',"bpy.data.objects['shot'].data.type='PANO'",False,False)])
        if args.start_at in ('fixed','production','workbench'):
            wb=settings(document(),'workbench');wb['render']['renderer']['cavity']={'kind':'world','ridge':1,'valley':1}
            packet=out/'workbench';run(wb,packet,executable=args.blender,timeout=180)
            attacks(packet,[('workbench-unchanged','',True,False),
                ('workbench-distance','scene.display.matcap_ssao_distance=20',False,False),
                ('workbench-attenuation','scene.display.matcap_ssao_attenuation=.25',False,False),
                ('workbench-samples','scene.display.matcap_ssao_samples=128',False,False)])
        root=Path(__file__).resolve().parents[1];physics=json.loads((root/'examples/schemaxis/blender-production.json').read_text())
        p=physics['scenes'][0]['production'];p.update(objects=[],collections=[],hierarchy=[],tracks=[],renderFrames=[],exports=[],rigidBodies=[{'object':'box','mass':2,'shape':'BOX'}],simulationFrames=[1,20],currentFrame=20,frameEnd=24)
        physics['nodes'][1]['options']['centre']=[0,0,5]
        physics['nodes'].append({'id':'anchor','filter':'cube','inputs':{'material':'paint'},'options':{'centre':[5,0,0]}})
        physics['scenes'][0]['visible']=['box','anchor'];packet=out/'cold-framing';run(physics,packet,executable=args.blender,timeout=300)
        assert public(packet)['verified'];receipt=json.loads((packet/'verification.json').read_text());samples=receipt['states'][0]['production']['samples'];last=next(s for s in samples if s['frame']==20);z=last['objects']['box']['matrix'][2][3];wanted=5-.5*9.81*(19/24)**2
        assert abs(z-wanted)<.08,(z,wanted)
        record('frame20-cold-framing',actualBallisticZ=z,independentBallisticZ=wanted,maximumError=.08,autoCameraBoundFromColdGeometry=True)
        attacks(packet,[('physics-unchanged','',True,False),
            ('latent-rigid-margin',"o=bpy.data.objects['box'];o.rigid_body.use_margin=not o.rigid_body.use_margin",False,False),
            ('latent-world-solver','scene.rigidbody_world.solver_iterations+=1',False,False),
            ('latent-field-default',"o=bpy.data.objects['anchor'];bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o;bpy.ops.object.forcefield_toggle();o.field.type='NONE';o.field.strength=1000",False,False)])
        cloth=copy.deepcopy(physics);p=cloth['scenes'][0]['production'];p['rigidBodies']=[]
        p['objects']=[{'id':'fabric','kind':'mesh','vertices':[[x,y,3] for y in range(3) for x in range(3)],'faces':[[y*3+x,y*3+x+1,(y+1)*3+x+1,(y+1)*3+x] for y in range(2) for x in range(2)],'material':'paint'}]
        p['cloth']=[{'object':'fabric','pinVertices':[0,2]}]
        packet=out/'cloth';run(cloth,packet,executable=args.blender,timeout=300)
        receipt=json.loads((packet/'verification.json').read_text());samples=receipt['states'][0]['production']['samples'];last=next(s for s in samples if s['frame']==20)['objects']['fabric']['bounds']
        assert last[4]<2.9 and abs(last[5]-3)<1e-6,last
        record('cloth-pinned-gravity-reference',frame20Bounds=last,pinnedHeight=3,gravityMovesUnpinnedVertices=True)
        attacks(packet,[('cloth-unchanged','',True,False),
            ('cloth-hidden-damping',"bpy.data.objects['fabric'].modifiers['schemaxis-cloth'].settings.air_damping+=1",False,False)])
        verify_identity(report,args.blender);report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
