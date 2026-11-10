"""Independent sweep integrals, interior samples and editable native histories."""
import copy,json,math,os
from pathlib import Path
import FreeCAD as App
import Part
from schemaxis.artifacts import atomic_json,file_digest
from freecad_sweep_cases import elbow_integrals,guide_frame


def controls(shape,e):
    assert shape.isValid() and len(shape.Solids)==1
    assert math.isclose(shape.Volume,e['volume'],rel_tol=1e-8,abs_tol=1e-6),(shape.Volume,e['volume'])
    centre=list(shape.Solids[0].CenterOfMass)
    assert all(math.isclose(a,b,abs_tol=2e-6) for a,b in zip(centre,e['centre'])),(centre,e['centre'])
    def pose(p):return [20+p[2],30+p[0],40+p[1]] if e.get('pose')=='cycled' else p
    def inside(p,wanted):assert shape.isInside(App.Vector(*pose(p)),1e-7,True)==wanted,(p,wanted)
    def bounds(wanted):
        actual=[getattr(shape.optimalBoundingBox(False,False),k) for k in ['XMin','XMax','YMin','YMax','ZMin','ZMax']]
        assert all(math.isclose(a,b,abs_tol=2e-6) for a,b in zip(actual,wanted)),(actual,wanted)
    kind=e['shape']
    if kind=='elbow':
        b,outer,inner=e['bend'],e['outer'],e['inner'];theta=math.radians(e['angle'])
        for fraction in [.25,.5,.75]:
            a=fraction*theta;p=[b*(1-math.cos(a)),0,b*math.sin(a)];radial=[-math.cos(a),0,math.sin(a)]
            inside(p,inner==0)
            for distance,wanted in [((inner+outer)/2,True),(outer+.1,False)]:inside([x+distance*y for x,y in zip(p,radial)],wanted)
            inside([p[0],(inner+outer)/2,p[2]],True);inside([p[0],outer+.1,p[2]],False)
        if e['length']:
            length,flange=e['length'],e['flange'];bounds([-flange,b+length,-flange,flange,-length,b+flange])
            for p in [[b+length/2,0,b],[0,0,-length/2]]:inside(p,False)
            for p in [[b+length/2,(inner+flange)/2,b],[0,(inner+flange)/2,-length/2]]:inside(p,True)
            cylinders=[f.Surface for f in shape.Faces if type(f.Surface).__name__=='Cylinder']
            for radius in [inner,flange]:assert sum(math.isclose(s.Radius,radius,abs_tol=1e-6) for s in cylinders)>=2
        # Auxiliary orientation exports an exact-looking toroidal control as
        # B-spline patches. Check the independent implicit surface equation,
        # rather than assuming its STEP analytic representation is Toroid.
        radii=[]
        for face in shape.Faces:
            if type(face.Surface).__name__ in ('Plane','Cylinder'):continue
            u0,u1,v0,v1=face.ParameterRange;samples=[]
            for fu in [.2,.5,.8]:
                for fv in [.2,.5,.8]:
                    p=list(face.valueAt(u0+(u1-u0)*fu,v0+(v1-v0)*fv))
                    if e.get('pose')=='cycled':p=[p[1]-30,p[2]-40,p[0]-20]
                    samples.append(math.hypot(math.hypot(p[0]-b,p[2])-b,p[1]))
            radius=min([outer]+([inner] if inner else []),key=lambda r:abs(samples[0]-r))
            assert max(abs(s-radius) for s in samples)<1e-6,(samples,radius)
            radii.append(radius)
        assert all(any(math.isclose(r,radius,abs_tol=1e-6) for r in radii) for radius in [outer]+([inner] if inner else []))
    elif kind=='rectangular-elbow':
        a=math.pi/4;p=[10*(1-math.cos(a)),0,10*math.sin(a)];inside(p,True)
        inside([p[0],.9,p[2]],True);inside([p[0],1.1,p[2]],False)
    elif kind=='oblique':
        bounds([-2,12,-2,2,0,20]);inside([5,0,10],True);inside([7.1,0,10],False)
    elif kind=='cone':
        end=e.get('endRadius',3);extent=5 if e['outer'] else max(2,end);bounds([-extent,extent,-extent,extent,0,20])
        for z in [2,10,18]:
            r=2+(end-2)*z/20;inside([0,0,z],not e['outer']);inside([r-.1,0,z],not e['outer']);inside([r+.1,0,z],e['outer'])
            if e['outer']:inside([4.9,0,z],True)
        assert any(type(f.Surface).__name__=='Cone' for f in shape.Faces)
    elif kind=='ring':
        b,r=e['bend'],e['outer'];bounds([-r,2*b+r,-r,r,-b-r,b+r]);inside([b,0,0],False);inside([0,0,0],True);inside([0,r+.1,0],False)
    elif kind=='miter':
        bounds([-2,20,-2,2,0,22]);inside([0,0,10],True);inside([10,0,20],True);inside([0,2.1,10],False);inside([10,0,22.1],False)
        inside([-1,0,20.5],True);inside([-1.5,1.5,21.5],False)
    elif kind=='guided':
        for t in [.25,.5,.75]:
            x,y,z,dx,dy=guide_frame(t,e['equivalence'])
            for u,v,wanted in [(0,0,True),(1.9,.45,True),(-1.9,-.45,True),(0,.6,False),(2.1,0,False)]:
                inside([(20*t if k==2 else 0)+u*x[k]+v*y[k] for k in range(3)],wanted)
    else:raise AssertionError(kind)
    return {'volume':shape.Volume,'centre':centre,'interiorExteriorChecked':True,'analyticShapeChecked':True}


def main(directory,stage='neutral'):
    root=Path(directory)
    if stage!='neutral':return edit(root,stage)
    q=json.loads((root/'qualification.json').read_text());results={}
    for name,record in q['checks'].items():
        shape=Part.Shape();shape.read(str(root/name/'model.step'));results[name]=controls(shape,record['expected'])
    atomic_json(root/'independent-neutral.json',{'verified':True,'pid':os.getpid(),'cases':results})


def edit(root,stage):
    from schemaxis.adaptors.freecad import adaptor,history_native
    from schemaxis.adaptors.freecad.document_xml import Document
    from schemaxis.adaptors.freecad.history_saved import observation
    from schemaxis.adaptors.freecad.parameters import verify_saved
    def datum(obj,name,value,unit):
        indices=[i for i,c in enumerate(obj.Constraints) if c.Name==name];assert len(indices)==1
        obj.setDatum(indices[0],App.Units.Quantity(str(value)+' '+unit))
    values={'bendRadius':12,'outerRadius':3.2,'wall':.8,'flangeRadius':5.5,'flangeLength':4} if stage=='edit1' else {'bendRadius':9,'outerRadius':2.8,'wall':1.2,'flangeRadius':4.8,'flangeLength':6}
    results={}
    for name in ['flanged-elbow','hollow-normal','multisection']:
        source=root/name/'model.FCStd' if stage=='edit1' else root/(name+'-edit1.FCStd' if stage=='edit2' else name+'-edit2.FCStd')
        wanted=json.loads((root/name/'verification.json').read_text())['artifacts'][2]['sha256'] if stage=='edit1' else json.loads((root/('edit1.json' if stage=='edit2' else 'edit2.json')).read_text())['cases'][name]['sha256']
        assert file_digest(source)==wanted
        authored=json.loads((root/name/'authored.json').read_text());d=App.openDocument(str(source))
        if name=='flanged-elbow':
            for key,value in values.items():
                authored['parameters'][key]['value']=value
                if stage!='reopen':setattr(d.getObject('SchemaxisParameters'),'dim_'+key,value)
            expected=elbow_integrals(values['bendRadius'],values['outerRadius'],values['outerRadius']-values['wall'],flange=values['flangeRadius'],length=values['flangeLength'])
        elif name=='hollow-normal':
            radius,angle=(12,60) if stage=='edit1' else (8,210)
            node=next(n for n in authored['nodes'] if n['id']=='bend');node['options'].update(bendRadius=radius,sweepAngle=angle)
            if stage!='reopen':
                path=d.getObjectsByLabel('bend')[0];datum(path,'bendRadius',radius,'mm');datum(path,'sweep',angle,'deg')
            expected=elbow_integrals(bend=radius,angle=angle)
        else:
            radius=2.5 if stage=='edit1' else 3.5;next(n for n in authored['nodes'] if n['id']=='end')['options']['radius']=radius
            if stage!='reopen':
                end=d.getObjectsByLabel('end')[0];datum(end,'radius',radius,'mm')
            den=4+2*radius+radius*radius;expected={'volume':20*math.pi*den/3,'centre':[0,0,20*(4+4*radius+3*radius*radius)/(4*den)],'shape':'cone','outer':False,'endRadius':radius}
        for obj in d.Objects:obj.touch()
        d.recompute();prepared=adaptor.plan(authored);history_native.observe(d,prepared)
        shape=d.getObjectsByLabel(authored['output'])[0].Shape;checks=controls(shape,expected)
        if stage!='reopen':
            saved=root/(name+'-'+stage+'.FCStd');d.saveAs(str(saved));shape.exportStep(str(root/(name+'-'+stage+'.step')))
            neutral=Part.Shape();neutral.read(str(root/(name+'-'+stage+'.step')));controls(neutral,expected)
        else:saved=source
        observation(prepared,Document(saved))
        if 'parameters' in prepared:verify_saved(prepared,saved)
        results[name]={'sha256':file_digest(saved),'geometry':checks,'expected':expected}
        App.closeDocument(d.Name)
    atomic_json(root/(stage+'.json'),{'verified':True,'pid':os.getpid(),'cases':results})
