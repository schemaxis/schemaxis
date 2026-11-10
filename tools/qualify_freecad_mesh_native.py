"""Independent native geometry queries and finite edits of owned Mesh fixtures."""
import json,math,os
from pathlib import Path
import FreeCAD as App
import Part
from schemaxis.artifacts import atomic_json,file_digest


def check(shape, expected):
    assert shape.isValid() and shape.isClosed() and len(shape.Solids)==1
    def near(a,b):assert math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-6),(a,b)
    near(shape.Volume,expected['volume']);centre=list(shape.Solids[0].CenterOfMass)
    for a,b in zip(centre,expected['centreOfMass']):near(a,b)
    box=shape.optimalBoundingBox(False,False);bounds=[getattr(box,k) for k in ('XMin','XMax','YMin','YMax','ZMin','ZMax')]
    for a,b in zip(bounds,expected['bounds']):near(a,b)
    sections=[]
    for height,areas in expected.get('sections',[]):
        measured=sorted(Part.Face(wire).Area for wire in shape.slice(App.Vector(0,0,1),height))
        assert len(measured)==len(areas),(measured,areas)
        for a,b in zip(measured,sorted(areas)):near(a,b)
        sections.append(measured)
    for kind,inside in [('inside',True),('outside',False)]:
        for point in expected[kind]:assert shape.isInside(App.Vector(*point),1e-7,True)==inside,(kind,point)
    return {'volume':shape.Volume,'centreOfMass':centre,'bounds':bounds,'sections':sections,
            'pointChecks':len(expected['inside'])+len(expected['outside'])}


def inspect(directory):
    directory=Path(directory);request=json.loads((directory/'inspect-request.json').read_text());report={'pid':os.getpid(),'cases':{}}
    for case in request['cases']:
        source=Path(case['file']);assert file_digest(source)==case['sha256']
        # The host has just constructed and independently verified this owned
        # positive control. Submitted altered packets never enter this reader.
        doc=App.openDocument(str(source));outputs=doc.getObjectsByLabel(case['output']);assert len(outputs)==1
        before=check(outputs[0].Shape,case['oracle'])
        for obj in doc.Objects:obj.touch()
        doc.recompute();solved=check(outputs[0].Shape,case['oracle'])
        step=Part.Shape();step.read(case['step'])
        report['cases'][case['id']]={'persisted':before,'recomputed':solved,'step':check(step,case['oracle'])}
        App.closeDocument(doc.Name)
    report['verified']=True;atomic_json(directory/'independent.json',report)


def edit(directory):
    directory=Path(directory);r=json.loads((directory/'edit-request.json').read_text());source=Path(r['source'])
    assert file_digest(source)==r['sha256']
    doc=App.openDocument(str(source));outputs=doc.getObjectsByLabel(r['output']);assert len(outputs)==1
    persisted=check(outputs[0].Shape,r['before'])
    if r['mode'] in ('drill','casting'):
        obj=doc.getObject('N1' if r['mode']=='drill' else 'N0');placement=obj.Placement;point=placement.Base
        placement.Base=App.Vector(r['value'],point.y,point.z) if r['mode']=='drill' else App.Vector(point.x,r['value'],point.z)
        obj.Placement=placement
    elif r['mode']=='placement':doc.getObject('N0').Placement.Base=App.Vector(*r['value'])
    else:assert r['mode'] in ('reopen','save')
    for obj in doc.Objects:obj.touch()
    doc.recompute();observed=check(outputs[0].Shape,r['after']);target=Path(r['target'])
    if r['mode']!='reopen':
        doc.saveAs(str(target));Part.export([outputs[0]],str(target.with_suffix('.step')))
        from schemaxis.adaptors.freecad.gui_state import persist
        persist(target,{obj.Name:bool(obj.Visibility) for obj in doc.Objects})
    step=Part.Shape();step.read(str(target.with_suffix('.step')));neutral=check(step,r['after'])
    atomic_json(directory/(r['id']+'.json'),{'verified':True,'pid':os.getpid(),'persisted':persisted,'solved':observed,'step':neutral,'sha256':file_digest(target)})
    App.closeDocument(doc.Name)


def shifted_source(directory):
    directory=Path(directory);r=json.loads((directory/'shift-request.json').read_text())
    from schemaxis.adaptors.freecad.mesh_import import geometry
    from schemaxis.adaptors.freecad.mesh_native import construct
    assert file_digest(r['source'])==r['sha256']
    _,points,faces=geometry(Path(r['source']).read_bytes(),r['options'],'fixture')
    shifted=[(x+.25,y,z) for x,y,z in points];shape,_=construct(shifted,faces,'fixture')
    assert shape.Placement.isIdentity();shape.exportBrep(str(directory/'shifted-source.brp'))
    atomic_json(directory/'shifted-source.json',{'pid':os.getpid(),'volume':shape.Volume,'facets':len(shape.Faces),'sha256':file_digest(directory/'shifted-source.brp')})
