"""Independent actual native/STEP geometry and native Draft parameter edits."""
import json,math,os
from pathlib import Path
import FreeCAD as App
import Part
from schemaxis.artifacts import atomic_json,file_digest


def check(shape,oracle):
    assert shape.isValid() and len(shape.Solids)==1
    def near(a,b):assert math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-6),(a,b)
    near(shape.Volume,oracle['volume'])
    for a,b in zip(shape.Solids[0].CenterOfMass,oracle['centre']):near(a,b)
    box=shape.optimalBoundingBox(False,False)
    for a,b in zip([getattr(box,k) for k in ('XMin','XMax','YMin','YMax','ZMin','ZMax')],oracle['bounds']):near(a,b)
    sections={}
    for z,spec in oracle['sections'].items():
        actual=sorted(Part.Face(wire).Area for wire in shape.slice(App.Vector(*oracle['normal']),spec['distance']))
        assert len(actual)==len(spec['areas']),(z,actual,spec['areas'])
        for a,b in zip(actual,spec['areas']):near(a,b)
        sections[z]=actual
    for sample in oracle['points']:assert shape.isInside(App.Vector(*sample['point']),1e-7,True)==sample['inside'],sample
    return {'volume':shape.Volume,'centre':list(shape.Solids[0].CenterOfMass),'sections':sections,'pointChecks':len(oracle['points'])}


def main(directory):
    directory=Path(directory);request=json.loads((directory/'independent-request.json').read_text());report={'pid':os.getpid(),'runtime':'.'.join(App.Version()[:3]),'cases':{}}
    for case in request['cases']:
        path=Path(case['native']);assert file_digest(path)==case['sha256']
        doc=App.openDocument(str(path));doc.recompute()
        node=next(n for n in case['document']['nodes'] if n['id']==case['document']['output']);objects=doc.getObjectsByLabel(node['id']);assert len(objects)==1
        native=check(objects[0].Shape,case['oracle']);neutral=Part.Shape();neutral.read(case['step']);step=check(neutral,case['oracle'])
        if case['oracle']['lidVolume'] is not None:assert math.isclose(doc.getObjectsByLabel('lidFinished')[0].Shape.Volume,case['oracle']['lidVolume'],rel_tol=1e-8,abs_tol=1e-6)
        report['cases'][case['id']]={'native':native,'step':step};App.closeDocument(doc.Name)
    report['verified']=True;atomic_json(directory/'independent.json',report)


def edit(directory):
    directory=Path(directory);request=json.loads((directory/'edit-request.json').read_text());source=Path(request['source']);assert file_digest(source)==request['sourceSha256']
    doc=App.openDocument(str(source));authored=request['document']
    if request['edit']:
        for key,value in authored['parameters'].items():setattr(doc.getObject('SchemaxisParameters'),'dim_'+key,value['value'])
        doc.getObjectsByLabel('release')[0].Angle=next(n for n in authored['nodes'] if n['id']=='release')['options']['angle']
        for obj in doc.Objects:obj.touch()
    doc.recompute()
    from schemaxis.adaptors.freecad import adaptor,history_native
    from schemaxis.adaptors.freecad.document_xml import Document
    from schemaxis.adaptors.freecad.history_saved import observation
    prepared=adaptor.plan(authored);history_native.observe(doc,prepared)
    checks=check(doc.getObjectsByLabel('finished')[0].Shape,request['oracle'])
    assert math.isclose(doc.getObjectsByLabel('lidFinished')[0].Shape.Volume,request['oracle']['lidVolume'],rel_tol=1e-8,abs_tol=1e-6)
    target=Path(request['target'])
    if request['edit']:doc.saveAs(str(target));doc.getObjectsByLabel('finished')[0].Shape.exportStep(str(target.with_suffix('.step')))
    observation(prepared,Document(target))
    atomic_json(directory/(request['id']+'.json'),{'verified':True,'pid':os.getpid(),'sha256':file_digest(target),'geometry':checks,'angle':doc.getObjectsByLabel('release')[0].Angle.Value,'lidVolume':doc.getObjectsByLabel('lidFinished')[0].Shape.Volume})
    App.closeDocument(doc.Name)
