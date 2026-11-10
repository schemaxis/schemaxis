"""Independent packed channels, shared stored UV mapping and binary coverage."""
import argparse,copy,hashlib,json,math
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from qualify_blender_render_policy import document,expected
from qualify_blender_image_preview import png,rgba
from blender_surface_evidence import identity,verify_identity


def constant(value):return {'kind':'constant','value':value}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    archive=hashlib.sha256(runtime_archive()).hexdigest();report={'status':'running','sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':archive,'checks':[]}
    target=out/'summary.json'
    report.update(identity(out,args.blender))
    def execute(label,d,points,reference):
        report['activeCase']=label;target.write_text(json.dumps(report,indent=2)+'\n')
        directory=out/label;run(d,directory,executable=args.blender,timeout=180)
        with location_context({'blender':args.blender}):assert verify(directory)['verified']
        pixels=rgba(directory,points);wanted=[expected(row,0) if len(row)==3 else row for row in reference]
        result={'label':label,'pixels':pixels,'independentExpectedRGBA':wanted,'maximumByteError':1}
        report['checks'].append(result);target.write_text(json.dumps(report,indent=2)+'\n')
        assert all(abs(a-b)<=1 for row,ref in zip(pixels,wanted) for a,b in zip(row,ref)),result
        print(label+' PASS',flush=True);return directory
    def fixture():
        d=document();d['render'].update(worldStrength=0,lightEnergy=0);d['cameras'][0].update(scale=2,focalPoint=[0,0,0])
        d['production']['materialGraphs']=[];return d
    try:
        packed=out/'packed.png';data=[32,96,160,224];png(packed,[data]*4)
        d=fixture();p=d['production'];p['images']=[{'id':'packed','file':str(packed),'colourSpace':'Non-Color','alphaMode':'channelPacked'}]
        p['surfaceMaterials']=[];p['meshData']=[];original=p['objects'][0];p['objects']=[]
        channels=['red','green','blue','alpha','luminance','inverted','colour','tinted'];linear=[v/255 for v in data];references=[]
        d['size']=[256,32];d['cameras'][0]['scale']=16
        for i,channel in enumerate(channels):
            material={'id':'surface'+str(i),'baseColour':constant([0,0,0]),'ior':constant(1),
                      'samplers':[{'id':'data','image':'packed','filter':'nearest'}]}
            emission={'colour':constant([1,1,1]),'strength':constant(1)}
            if channel in ('colour','tinted'):
                tint=[.5,.25,1] if channel=='tinted' else [1,1,1]
                emission['colour']={'kind':'sample','sampler':'data','tint':tint};reference=[v*t for v,t in zip(linear,tint)]
            else:
                emission['strength']={'kind':'sample','sampler':'data','channel':'red' if channel=='inverted' else channel}
                if channel=='inverted':emission['strength']['range']=[1,0];value=1-linear[0]
                elif channel=='luminance':value=sum(v*w for v,w in zip(linear,[.2126,.7152,.0722]))
                else:value=linear[channels.index(channel)]
                reference=[value]*3
            material['emission']=emission;p['surfaceMaterials'].append(material)
            obj=copy.deepcopy(original);obj.update(id='part'+str(i),material=material['id'],location=[-7+2*i,0,0]);p['objects'].append(obj)
            p['meshData'].append({'object':obj['id'],'uvMaps':[{'name':'UV','method':'planar','origin':[-1,-1,0],'size':[2,2]}]});references.append(reference)
        execute('packed-scalar-colour-alpha-luminance',d,[(16+32*i,16) for i in range(8)],references)
        colours=[[32,64,96,255],[64,128,192,255],[96,160,224,255],[192,96,32,255]]
        colour_image=out/'colour.png';png(colour_image,colours)
        orm_image=out/'orm.png';png(orm_image,[[0,96,0,255]]*4)
        normal_image=out/'normal.png';png(normal_image,[[128,204,230,255]]*4)
        for label,angle,scale in [('rotate90',90,[1,1]),('mirrorV',0,[1,-1]),('rotate-mirror-scale',45,[-2,3])]:
            d=fixture();d['size']=[64,64];p=d['production'];p['images']=[{'id':name,'file':str(path),'colourSpace':'Non-Color','alphaMode':'channelPacked'} for name,path in [('colour',colour_image),('orm',orm_image),('normal',normal_image)]]
            sampler=lambda name:{'id':name,'image':name,'filter':'nearest','coordinates':{'kind':'uv','set':{'kind':'named','name':'Finish'}}}
            p['surfaceMaterials']=[{'id':'surface','baseColour':{'kind':'sample','sampler':'colour'},'ior':constant(1),
               'samplers':[sampler(name) for name in ('colour','orm','normal')],
               'metallic':{'kind':'sample','sampler':'orm','channel':'blue'},'roughness':{'kind':'sample','sampler':'orm','channel':'green'},
               'normal':{'kind':'normalMap','map':{'sampler':'normal'}},
               'emission':{'colour':{'kind':'sample','sampler':'colour'},'strength':constant(1)}}]
            p['meshData']=[{'object':'patch','uvMaps':[{'name':'Base','method':'planar','origin':[-1,-1,0],'size':[2,2]},
               {'name':'Finish','method':'copy','source':'Base','transform':{'pivot':[.5,.5],'rotationDegrees':angle,'scale':scale}}]}]
            points=[(16,16),(48,16),(16,48),(48,48)];references=[]
            for x,y in points:
                u,v=(x+.5)/64,1-(y+.5)/64;a=(u-.5)*scale[0];b=(v-.5)*scale[1];r=math.radians(angle)
                u=(.5+math.cos(r)*a-math.sin(r)*b)%1;v=(.5+math.sin(r)*a+math.cos(r)*b)%1
                index=(0 if v>=.5 else 2)+(0 if u<.5 else 1);references.append([c/255 for c in colours[index][:3]])
            directory=execute('shared-base-orm-normal-'+label,d,points,references)
            observed=json.loads((directory/'reopened.json').read_text())['production'][0]['materialGraphs'][0]
            uv_nodes=[n for n in observed['nodes'] if n['kind']=='uvMap'];assert len(uv_nodes)==1 and uv_nodes[0]['properties']['name']=='Finish'
            images=[n for n in observed['nodes'] if n['kind']=='image'];assert len(images)==3
            for image in images:assert {'from':{'node':uv_nodes[0]['id'],'socket':'uv'},'to':{'node':image['id'],'socket':'vector'}} in observed['links']
            assert next(n for n in observed['nodes'] if n['kind']=='normalMap')['properties']['uvMap']=='Finish'
        alpha=out/'alpha.png';alpha_colours=[[64,32,16,0],[32,64,96,255],[96,32,64,255],[64,96,32,0]];png(alpha,alpha_colours)
        d=fixture();d['size']=[64,64];d['render']['transparent']=True;p=d['production'];p['images']=[{'id':'alpha','file':str(alpha),'colourSpace':'Non-Color','alphaMode':'channelPacked'}]
        p['surfaceMaterials']=[{'id':'surface','baseColour':constant([0,0,0]),'ior':constant(1),
          'samplers':[{'id':'image','image':'alpha','filter':'nearest'}],
          'coverage':{'kind':'sample','sampler':'image','channel':'alpha'},
          'emission':{'colour':{'kind':'sample','sampler':'image'},'strength':constant(1)}}]
        p['meshData']=[{'object':'patch','uvMaps':[{'name':'UV','method':'planar','origin':[-1,-1,0],'size':[2,2]}]}]
        references=[expected([v/255 for v in row[:3]],0) if row[3] else [0,0,0,0] for row in alpha_colours]
        execute('binary-coverage-keeps-colour-channels',d,[(16,16),(48,16),(16,48),(48,48)],references)
        assert hashlib.sha256(runtime_archive()).hexdigest()==archive
        verify_identity(report,args.blender)
        report['status']='passed';report.pop('activeCase',None)
    finally:
        if report['status']=='running':report['status']='failed'
        target.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
