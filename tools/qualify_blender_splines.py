"""Analytic spline controls, rational shapes, filled sections and swept resources."""
import argparse,copy,json,math
from pathlib import Path
from qualify_blender_mesh_data import close,native,production
from schemaxis.adaptors.blender.adaptor import run,verify
from schemaxis.errors import SchemaxisError


def point(x,y,z=0,**kw):return {'position':[x,y,z],**kw}
def curve(identity,points,kind='POLY',**kw):return {'id':identity,'kind':'spline','splines':[{'id':'contour','kind':kind,'points':points}],**kw}
def document(objects,**kw):return {'version':'schemaxis.blender.production/1','prepareOnly':True,'visible':[objects[-1]['id']],'production':{'objects':objects,**kw}}
def geometry(blender,directory,identity,frame=1):
    output=directory/(identity+'-geometry.json')
    code='import bpy,json\nfrom pathlib import Path\n'+f'bpy.ops.wm.open_mainfile(filepath={str(directory/"0000.blend")!r},use_scripts=False)\nbpy.context.scene.frame_set({frame})\n'+f'o=bpy.data.objects[{identity!r}];e=o.evaluated_get(bpy.context.evaluated_depsgraph_get());m=e.to_mesh()\n'+'''points=[list(v.co) for v in m.vertices];m.calc_loop_triangles();volume=sum(m.vertices[t.vertices[0]].co.dot(m.vertices[t.vertices[1]].co.cross(m.vertices[t.vertices[2]].co))/6 for t in m.loop_triangles)
r={'points':points,'volume':volume,'faces':len(m.polygons),'area':sum(t.area for t in m.loop_triangles),'matrix':[list(row) for row in e.matrix_world]};e.to_mesh_clear()
'''+f'Path({str(output)!r}).write_text(json.dumps(r))\n'
    native(blender,code);return json.loads(output.read_text())


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--only',nargs='+');a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=False);cases=[];refusals=[]
    def execute(label,d,identity=None,bounds=None,volume=None,area=None,oracle=None):
        if a.only and label not in a.only:return None,None
        directory=out/label;result=run(d,directory,executable=a.blender,timeout=180);assert verify(directory)['verified'];identity=identity or d['production']['objects'][-1]['id'];obs=production(directory)['samples'][0]['objects'][identity];geo=geometry(a.blender,directory,identity)
        if bounds is not None:close(obs['bounds'],bounds)
        if volume is not None:assert math.isclose(geo['volume'],volume,rel_tol=2e-6,abs_tol=1e-8),(label,geo['volume'],volume)
        if area is not None:assert math.isclose(geo['area'],area,rel_tol=2e-6,abs_tol=1e-8),(label,geo['area'],area)
        if oracle:oracle(geo)
        cases.append({'case':label,'directory':str(directory),'result':result,'literalBounds':bounds,'literalVolume':volume,'geometry':{'vertices':len(geo['points']),'faces':geo['faces'],'volume':geo['volume']}});print(label+' PASS',flush=True);write();return directory,geo
    def write():(out/'summary.json').write_text(json.dumps({'status':'implementing','cases':cases,'refusals':refusals},indent=2)+'\n')
    arch=curve('arch',[point(0,0,left={'kind':'FREE','position':[-1,0,0]},right={'kind':'FREE','position':[0,2,0]}),point(2,0,left={'kind':'FREE','position':[2,2,0]},right={'kind':'FREE','position':[3,0,0]})],'BEZIER')
    def cubic(geo):
        points=geo['points'];assert len(points)==13
        for i,p in enumerate(points):
            t=i/12;close(p,[6*t*t-4*t*t*t,6*t*(1-t),0])
        close(points[6],[1,1.5,0])
    execute('cubic-analytic',document([arch]),bounds=[0,2,0,1.5,0,0],oracle=cubic)
    quarter=curve('quarter',[point(1,0),point(1,1,weight=math.sqrt(.5)),point(0,1)],'NURBS')
    def rational(weight):
        def check(geo):
            assert len(geo['points'])==13
            for i,p in enumerate(geo['points']):
                t=i/12;den=(1-t)**2+2*weight*t*(1-t)+t*t;close(p,[((1-t)**2+2*weight*t*(1-t))/den,(2*weight*t*(1-t)+t*t)/den,0])
                if weight==math.sqrt(.5):assert math.isclose(math.hypot(p[0],p[1]),1,rel_tol=2e-6)
            close(geo['points'][6],[1/math.sqrt(2),1/math.sqrt(2),0] if weight==math.sqrt(.5) else [2/3,2/3,0])
        return check
    execute('rational-quarter',document([quarter]),bounds=[0,1,0,1,0,0],oracle=rational(math.sqrt(.5)))
    half=copy.deepcopy(quarter);half['splines'][0]['points'][1]['weight']=.5;execute('rational-weight-variant',document([half]),oracle=rational(.5))
    periodic=curve('periodic',[point(1,0),point(-.5,math.sqrt(3)/2),point(-.5,-math.sqrt(3)/2)],'NURBS');periodic['splines'][0].update(closed=True,endpoint=False)
    def cyclic_quadratic(g):
        controls=[p['position'] for p in periodic['splines'][0]['points']];expected=[]
        for i in range(3):
            for j in range(12):
                t=j/12;expected.append([.5*(1-t)**2*controls[(i-1)%3][k]+(.5+t-t*t)*controls[i][k]+.5*t*t*controls[(i+1)%3][k] for k in range(3)])
        assert len(g['points'])==36
        for p in g['points']:assert any(all(math.isclose(a,b,rel_tol=1e-6,abs_tol=8*2**-23) for a,b in zip(p,q)) for q in expected),p
    execute('periodic-nurbs',document([periodic]),oracle=cyclic_quadratic)
    spans=curve('spans',[point(0,0),point(1,2),point(2,0),point(3,-2),point(4,0)],'NURBS');spans['splines'][0]['bezierKnots']=True
    def quadratic_spans(g):
        assert len(g['points'])==25
        for i,p in enumerate(g['points']):
            t=i/24;u=2*t if t<=.5 else 2*t-1;close(p,[2*u+(0 if t<=.5 else 2),(1 if t<=.5 else -1)*4*u*(1-u),0])
        close(g['points'][12],[2,0,0])
    execute('bezier-knot-nurbs-spans',document([spans]),bounds=[0,4,-1,1,0,0],oracle=quadratic_spans)
    # Equal-winding contours distinguish EVEN_ODD from NONZERO in CDT; opposite
    # contours also exercise the sweep-line baseline without invented parity.
    outer=[point(-2,-1),point(2,-1),point(2,1),point(-2,1)];inner=[point(-1,-.5),point(-1,.5),point(1,.5),point(1,-.5)]
    gasket=curve('gasket',outer,dimensions='2D',extrude=1);gasket['splines'][0]['closed']=True;gasket['splines'].append({'id':'hole','kind':'POLY','closed':True,'points':inner})
    for solver in ('SWEEP_LINE','CDT'):execute('gasket-'+solver.lower(),document([{**gasket,'fillSolver':solver}]),bounds=[-2,2,-1,1,-1,1],volume=12)
    same=copy.deepcopy(gasket);same['splines'][1]['reverse']=True;same['fillSolver']='CDT';same['extrude']=0
    execute('gasket-even-odd-same-winding',document([same]),area=6)
    execute('gasket-nonzero-same-winding',document([{**same,'fillRule':'NONZERO'}]),area=8)
    section=curve('section',[point(-.2,-.1),point(.2,-.1),point(.2,.1),point(-.2,.1)],dimensions='2D');section['splines'][0].update(closed=True,reverse=True)
    sweep=curve('sweep',[point(0,0),point(0,0,4)],bevel={'kind':'object','object':'sectionAlias'},caps=True)
    refs=[{'id':'sectionAlias','kind':'object','object':'section'}]
    execute('rectangle-profile',document([section,sweep],geometryResources=refs),bounds=[-.2,.2,-.1,.1,0,4],volume=.32)
    execute('transformed-profile',document([{**section,'location':[20,30,40],'rotation':[0,0,.7],'scale':[2,3,4]},sweep],geometryResources=refs),bounds=[-.4,.4,-.3,.3,0,4],volume=1.92)
    # A native reference frame ignores source translation/rotation but consumes
    # section X/Y scale. Taper mapping uses local X and Y, not its object origin.
    taper=curve('taper',[point(0,1),point(1,2)],dimensions='2D',fill='NONE')
    cable=curve('cable',[point(0,0),point(0,0,4)],bevel={'kind':'round','depth':.2,'resolution':0},taper={'object':'taper'},caps=True)
    def taper_ends(geo):
        for z,radius in ((0,.2),(4,.4)):
            ring=[p for p in geo['points'] if abs(p[2]-z)<1e-6];assert len(ring)>=4
            for p in ring:assert math.isclose(math.hypot(p[0],p[1]),radius,rel_tol=2e-6)
    execute('linear-taper-frustum',document([taper,cable]),bounds=[-.4,.4,-.4,.4,0,4],volume=56/75,oracle=taper_ends)
    radii=copy.deepcopy(cable);radii['taper']={'object':''};radii['splines'][0]['points'][1]['radius']=2
    execute('control-radius-frustum',document([radii]),bounds=[-.4,.4,-.4,.4,0,4],volume=56/75,oracle=taper_ends)
    tilted=copy.deepcopy(radii)
    for p in tilted['splines'][0]['points']:p.update(radius=1,tilt=math.pi/4)
    extent=.2/math.sqrt(2);execute('control-tilt-section',document([tilted]),bounds=[-extent,extent,-extent,extent,0,4],volume=.32)
    for mode,r0,r1,volume in [('MULTIPLY',.4,.8,224/75),('ADD',.6,.8,296/75)]:
        combined=copy.deepcopy(cable);combined['taper']['mode']=mode
        for p in combined['splines'][0]['points']:p['radius']=2
        def end_radii(g,start=r0,end=r1):
            for z,r in ((0,start),(4,end)):
                ring=[p for p in g['points'] if abs(p[2]-z)<1e-6];assert len(ring)>=4
                for p in ring:assert math.isclose(math.hypot(p[0],p[1]),r,rel_tol=2e-6)
        execute('taper-'+mode.lower(),document([taper,combined]),bounds=[-r1,r1,-r1,r1,0,4],volume=volume,oracle=end_radii)
    for mapping in ('RESOLUTION','SEGMENTS','SPLINE'):
        trimmed=copy.deepcopy(tilted);trimmed['trim']={'start':.25,'end':.75,'startMapping':mapping,'endMapping':mapping}
        execute('trim-'+mapping.lower(),document([trimmed]),bounds=[-extent,extent,-extent,extent,1,3],volume=.16)
    auto=curve('auto',[point(0,0),point(1,1),point(2,0)],'BEZIER',bevel={'kind':'round','depth':.1,'resolution':0});execute('automatic-handles',document([auto]),bounds=[-.1/math.sqrt(2),2+.1/math.sqrt(2),-.1/math.sqrt(2),1.1,-.1,.1])
    vector=copy.deepcopy(auto)
    for p in vector['splines'][0]['points']:p.update(left={'kind':'VECTOR'},right={'kind':'VECTOR'})
    execute('vector-handles',document([vector]))
    aligned=copy.deepcopy(arch)
    for p in aligned['splines'][0]['points']:
        p['left']={'kind':'ALIGNED','position':[p['position'][0],-2,0]};p['right']={'kind':'ALIGNED','position':[p['position'][0],2,0]}
    execute('aligned-handles',document([aligned]))
    for label,positions,expected in [('diamond',[[1,0],[0,1]],.16),('square',[[1,0],[1,1],[0,1]],.32),('chamfer',[[1,0],[1,.5],[.5,1],[0,1]],.28)]:
        profile=curve('profile',[point(0,0),point(0,0,2)],bevel={'kind':'profile','points':[{'position':p,'handle':'VECTOR'} for p in positions],'depth':.2,'resolution':8,'evenLengths':False,'straightEdges':True},caps=True)
        execute('profile-'+label,document([profile]),bounds=[-.2,.2,-.2,.2,0,2],volume=expected)
    rounded=curve('profile',[point(0,0),point(0,0,2)],bevel={'kind':'profile','points':[{'position':p,'handle':'AUTO'} for p in [[1,0],[.9,.9],[0,1]]],'depth':.2,'resolution':8,'evenLengths':True},caps=True)
    def rounded_section(g):assert .16<g['volume']<.32,g['volume']
    execute('profile-rounded-custom',document([rounded]),oracle=rounded_section)
    mixed=curve('mixed',[point(0,0),point(1000,0)]);mixed['splines'].append({'id':'fine','kind':'POLY','points':[point(0,1),point(.001,1)]})
    def fine_controls(g):assert any(math.isclose(p[0],.001,rel_tol=1e-6,abs_tol=0) and math.isclose(p[1],1,rel_tol=1e-6) for p in g['points'])
    execute('mixed-scale-splines',document([mixed]),bounds=[0,1000,0,1,0,0],oracle=fine_controls)
    edge_scales=curve('edgeScales',[point(1e9,0),point(1e9+128,0),point(2e9,0)])
    def exact_controls(g):assert [p[0] for p in g['points']]==[1e9,1e9+128,2e9],g['points']
    execute('mixed-edge-scales',document([edge_scales]),oracle=exact_controls)
    handle_scales=curve('handleScales',[point(1e9,0,left={'kind':'FREE','position':[-1e9,0,0]},right={'kind':'FREE','position':[1e9+128,0,0]}),point(2e9,0,left={'kind':'FREE','position':[2e9-128,0,0]},right={'kind':'FREE','position':[2e9+128,0,0]})],'BEZIER')
    execute('mixed-handle-scales',document([handle_scales]))
    offset_curve=curve('offset',[point(-1,-1),point(1,-1),point(1,1),point(-1,1)],dimensions='2D',offset=.25)
    offset_curve['splines'][0]['closed']=True
    execute('planar-offset',document([offset_curve]),bounds=[-1.25,1.25,-1.25,1.25,0,0],area=6.25)
    for order in (4,5,6):
        controls=[point(i,(-1)**i,i*.1,weight=1+i*.1) for i in range(order)]
        higher=curve('higher',controls,'NURBS');higher['splines'][0].update(order=order,sampling=4)
        def rational_degree(g):
            assert len(g['points'])==5,g['points']
            for j,p in enumerate(g['points']):
                t=j/4;weights=[math.comb(order-1,i)*t**i*(1-t)**(order-1-i)*c['weight'] for i,c in enumerate(controls)]
                expected=[sum(w*c['position'][axis] for w,c in zip(weights,controls))/sum(weights) for axis in range(3)]
                assert all(math.isclose(a,b,rel_tol=2e-6,abs_tol=2e-6) for a,b in zip(p,expected)),(p,expected)
        execute('rational-order-'+str(order),document([higher]),oracle=rational_degree)
    for mapped in (False,True):
        taper_line=curve('remapping',[point(0,1),point(1,2)],dimensions='2D',fill='NONE')
        cut=curve('trimmed',[point(0,0,z) for z in range(5)],bevel={'kind':'round','depth':.1,'resolution':0},twist='Z_UP',twistSmooth=2,trim={'start':.25,'end':.75},taper={'object':'remapping','mode':'MULTIPLY','mapTrim':mapped},path={'duration':17,'follow':False,'radius':False,'stretch':True,'bounds':True})
        def mapped_endpoints(g):
            for z,r in ((1,.1 if mapped else .125),(3,.2 if mapped else .175)):
                ring=[p for p in g['points'] if abs(p[2]-z)<1e-5];assert ring
                assert all(math.isclose(math.hypot(p[0],p[1]),r,rel_tol=2e-6) for p in ring),(mapped,z,r,ring)
        execute('trim-taper-map-'+str(mapped).lower(),document([taper_line,cut]),oracle=mapped_endpoints)
    # Native path consumers sample an independent exact straight path endpoint.
    line=curve('path',[point(0,0),point(4,0)],path={'enabled':True,'follow':True});follower={'id':'follower','kind':'empty'}
    for factor in (0,.5,1):
        directory,_=execute('path-follower-'+str(factor).replace('.','_'),{**document([line,follower],constraints=[{'id':'travel','kind':'followPath','object':'follower','target':'path','factor':factor,'follow':False}]),'visible':['path']},identity='path')
        if directory is None:continue
        obs=production(directory)['samples'][0]['objects']['follower']['matrix'];close([obs[i][3] for i in range(3)],[4*factor,0,0])
    def refuse(label,d,code):
        if a.only and label not in a.only:return
        try:run(d,out/label,executable=a.blender,timeout=180)
        except SchemaxisError as error:
            assert error.fault.code==code,(label,error.fault.to_dict());refusals.append({'case':label,'fault':error.fault.to_dict()});print(label+' REFUSED',flush=True);write()
        else:raise AssertionError(label+' unexpectedly accepted')
    bad=copy.deepcopy(section);bad['dimensions']='3D';refuse('spatial-profile-refusal',document([bad,sweep],geometryResources=refs),'INVALID_SPLINE')
    bad=copy.deepcopy(taper);bad['splines'][0]['closed']=True;bad['splines'][0]['points'].append(point(2,1));refuse('cyclic-taper-refusal',document([bad,cable]),'INVALID_SPLINE')
    huge=copy.deepcopy(arch);huge['sampling']={'preview':1024,'render':1024};huge['bevel']={'kind':'round','depth':.1,'resolution':32};huge['splines'][0]['points']*=8
    # Make distinct adjacent controls while retaining a large declared control set.
    huge['splines'][0]['points']=[{**p,'position':[i,0,0]} for i,p in enumerate(huge['splines'][0]['points'])]
    refuse('authored-sampling-budget',document([huge]),'RESOURCE_BUDGET_EXCEEDED')
    tiny=copy.deepcopy(quarter);tiny['splines'][0]['points'][1]['weight']=1e-300;refuse('native-weight-underflow',document([tiny]),'NATIVE_VALUE_MISMATCH')
    chain=[curve('section'+str(i),[point(0,0),point(1,0)],dimensions='2D',bevel={'kind':'object','object':'section'+str(i+1)} if i<69 else {'kind':'none'}) for i in range(70)]
    refuse('dependency-depth-budget',document(chain),'RESOURCE_BUDGET_EXCEEDED')
    lost=copy.deepcopy(mixed);lost['splines'][1]['points']=[point(1000000,1),point(1000000.001,1)];refuse('per-spline-local-precision',document([lost]),'NATIVE_VALUE_MISMATCH')
    lost_edge=copy.deepcopy(edge_scales);lost_edge['splines'][0]['points'][1]['position'][0]=1e9+1
    refuse('intraspline-local-precision',document([lost_edge]),'NATIVE_VALUE_MISMATCH')
    closed_edge=copy.deepcopy(lost_edge);closed_edge['splines'][0].update(closed=True,points=[point(1e9,0),point(2e9,0),point(1e9+1,0)])
    refuse('closed-join-local-precision',document([closed_edge]),'NATIVE_VALUE_MISMATCH')
    lost_handle=copy.deepcopy(handle_scales);lost_handle['splines'][0]['points'][0]['right']['position'][0]=1e9+1
    refuse('short-handle-local-precision',document([lost_handle]),'NATIVE_VALUE_MISMATCH')
    unsafe_radius=copy.deepcopy(radii);unsafe_radius['trim']={'start':.25,'end':.75};refuse('partial-trim-varying-radius',document([unsafe_radius]),'INVALID_SPLINE')
    from qualify_blender_geometry_resources import base
    unconverted=base();unconverted['production']['objects']=[arch,*unconverted['production']['objects'][1:]];unconverted['production']['geometryResources'][0]['object']='arch';refuse('unconverted-curve-component',unconverted,'INVALID_SCENE')
    report={'status':'passed','scope':'selected cases' if a.only else 'full bounded constructor family','cases':cases,'refusals':refusals};(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':'passed','cases':len(cases),'refusals':len(refusals)}))

if __name__=='__main__':main()
