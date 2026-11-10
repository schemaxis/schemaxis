"""Native geometry and real input-cell edits for typed engineering tables."""
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
    for a,b in zip([getattr(box,key) for key in ('XMin','XMax','YMin','YMax','ZMin','ZMax')],oracle['bounds']):near(a,b)
    sections=[];n=oracle['normal'];origin=oracle['sectionOrigin']
    for height,areas in oracle['sections']:
        distance=sum(x*y for x,y in zip(n,origin))+height
        actual=sorted(Part.Face(wire).Area for wire in shape.slice(App.Vector(*n),distance))
        assert len(actual)==len(areas),(actual,areas)
        for a,b in zip(actual,sorted(areas)):near(a,b)
        sections.append(actual)
    for point,inside in oracle['points']:assert shape.isInside(App.Vector(*point),1e-7,True)==inside,(point,inside)
    return {'volume':shape.Volume,'centre':list(shape.Solids[0].CenterOfMass),'sections':sections,'pointChecks':len(oracle['points'])}


def inspect(directory):
    directory=Path(directory);request=json.loads((directory/'independent-request.json').read_text());report={'pid':os.getpid(),'cases':{}}
    for case in request['cases']:
        source=Path(case['native']);assert file_digest(source)==case['sha256']
        doc=App.openDocument(str(source));doc.recompute()
        output=doc.getObjectsByLabel(case['document']['output']);assert len(output)==1
        neutral=Part.Shape();neutral.read(case['step'])
        report['cases'][case['id']]={'native':check(output[0].Shape,case['oracle']),'step':check(neutral,case['oracle'])}
        App.closeDocument(doc.Name)
    report['verified']=True;atomic_json(directory/'independent.json',report)


def edit(directory):
    directory=Path(directory);request=json.loads((directory/'edit-request.json').read_text());source=Path(request['source'])
    assert file_digest(source)==request['sha256']
    doc=App.openDocument(str(source));authored=request['document'];sheet=doc.getObject('SchemaxisParameters')
    from schemaxis.adaptors.freecad import adaptor,parameters_native,parameters,history_native
    prepared=adaptor.plan(authored)
    if request['edit']:
        for alias,item in authored['spreadsheet']['inputs'].items():
            sheet.set(prepared['spreadsheet']['cells'][alias],format(item['value'],'.17g')+' '+item['unit'])
        for obj in doc.Objects:obj.touch()
    doc.recompute();quantities=parameters_native.observe(doc,prepared);history_native.observe(doc,prepared)
    output=doc.getObjectsByLabel(authored['output']);assert len(output)==1
    geometry=check(output[0].Shape,request['oracle']);target=Path(request['target'])
    if request['edit']:
        doc.saveAs(str(target));Part.export([output[0]],str(target.with_suffix('.step')))
    parameters.verify_saved(prepared,target)
    neutral=Part.Shape();neutral.read(str(target.with_suffix('.step')));check(neutral,request['oracle'])
    atomic_json(directory/(request['id']+'.json'),{'verified':True,'pid':os.getpid(),'geometry':geometry,
                'sha256':file_digest(target),'quantities':quantities['parameters']})
    App.closeDocument(doc.Name)
