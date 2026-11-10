"""Independent geometry and finite Points/Placement edits of owned Draft fixtures."""
import json,math,os
from pathlib import Path
import FreeCAD as App
import Part
from schemaxis.artifacts import atomic_json,file_digest
from qualify_freecad_mesh_native import check as material_check


def check(shape,expected):
    result=material_check(shape,{k:v for k,v in expected.items() if k!='sections'})
    assert math.isclose(shape.Area,expected['area'],rel_tol=1e-7,abs_tol=1e-6),(shape.Area,expected['area'])
    result['area']=shape.Area;result['sections']=[]
    for section in expected['sections']:
        actual=sorted(Part.Face(w).Area for w in shape.slice(App.Vector(*section['normal']),section['offset']))
        assert len(actual)==len(section['areas']),(actual,section)
        for a,b in zip(actual,sorted(section['areas'])):assert math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-6),(a,b)
        result['sections'].append(actual)
    return result


def inspect(directory):
    directory=Path(directory);r=json.loads((directory/'inspect-request.json').read_text());report={'pid':os.getpid(),'cases':{}}
    for case in r['cases']:
        assert file_digest(case['file'])==case['sha256']
        d=App.openDocument(case['file']);outputs=d.getObjectsByLabel(case['output']);assert len(outputs)==1
        persisted=check(outputs[0].Shape,case['oracle'])
        for obj in d.Objects:obj.touch()
        d.recompute();fresh=check(outputs[0].Shape,case['oracle'])
        step=Part.Shape();step.read(case['step'])
        report['cases'][case['id']]={'persisted':persisted,'recomputed':fresh,'step':check(step,case['oracle'])}
        App.closeDocument(d.Name)
    report['verified']=True;atomic_json(directory/'independent.json',report)


def edit(directory):
    directory=Path(directory);r=json.loads((directory/'edit-request.json').read_text())
    assert file_digest(r['source'])==r['sha256'];d=App.openDocument(r['source'])
    outputs=d.getObjectsByLabel(r['output']);assert len(outputs)==1
    before=check(outputs[0].Shape,r['before']);profile=d.getObject('N0')
    assert type(profile.Proxy).__module__=='draftobjects.wire' and type(profile.Proxy).__name__=='Wire'
    if r['mode']=='points':profile.Points=[App.Vector(x,y,0) for x,y in r['value']]
    elif r['mode']=='placement':
        placement=profile.Placement;placement.Base=App.Vector(*r['value']);profile.Placement=placement
    else:assert r['mode'] in ('reopen','save')
    for obj in d.Objects:obj.touch()
    d.recompute();after=check(outputs[0].Shape,r['after']);target=Path(r['target'])
    if r['mode']!='reopen':
        d.saveAs(str(target));Part.export([outputs[0]],str(target.with_suffix('.step')))
        from schemaxis.adaptors.freecad.gui_state import persist
        persist(target,{obj.Name:bool(obj.Visibility) for obj in d.Objects})
    step=Part.Shape();step.read(str(target.with_suffix('.step')))
    report={'verified':True,'pid':os.getpid(),'before':before,'after':after,'step':check(step,r['after']),'sha256':file_digest(target)}
    atomic_json(directory/(r['id']+'.json'),report);App.closeDocument(d.Name)
