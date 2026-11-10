"""Independent neutral geometry checks for uniform-wall offset controls."""
import json,math,os
from pathlib import Path
import FreeCAD as App
import Part
from schemaxis.artifacts import atomic_json


def controls(shape,expected):
    assert shape.isValid() and len(shape.Solids)==1
    assert math.isclose(shape.Volume,expected['volume'],rel_tol=1e-8,abs_tol=1e-6),(shape.Volume,expected['volume'])
    centre=list(shape.Solids[0].CenterOfMass)
    assert all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(centre,expected['centre'])),(centre,expected['centre'])
    def inside(point,wanted):assert shape.isInside(App.Vector(*point),1e-7,True)==wanted,(point,wanted)
    def bounds(wanted):
        actual=[getattr(shape.BoundBox,k) for k in ['XMin','XMax','YMin','YMax','ZMin','ZMax']]
        assert all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(actual,wanted)),(actual,wanted)
    inside([0,0,10],False)
    if expected.get('cylindrical'):
        bounds([-10,10,-10,10,0,20]);inside([0,0,1],True);inside([9,0,10],True)
        radii=sorted(f.Surface.Radius for f in shape.Faces if type(f.Surface).__name__=='Cylinder');assert len(radii)==2 and all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(radii,[7,10]))
    elif expected['side']=='inward':
        bounds([-20,20,-15,15,0,20]);inside([19,0,10],expected['axis']!='X');inside([0,0,1],expected['openings']==1);inside([-19,0,10],True)
    else:
        bounds([-23,23,-18,18,-3,20]);inside([21,0,10],True);inside([0,0,-1],True)
        inside([-22.5,-17.5,10],expected['corners']=='sharp')
        if expected['corners']=='rounded':
            cylinders=[f.Surface for f in shape.Faces if type(f.Surface).__name__=='Cylinder'];spheres=[f.Surface for f in shape.Faces if type(f.Surface).__name__=='Sphere']
            assert len(cylinders)==8 and len(spheres)==4
            assert all(math.isclose(s.Radius,3,abs_tol=1e-6) for s in cylinders+spheres)
    return {'volume':shape.Volume,'centre':centre,'voidAndWallChecks':True,'boundsChecked':True}


def main(directory,stage='neutral'):
    if stage!='neutral':return edit(Path(directory),stage)
    root=Path(directory);report={};q=json.loads((root/'qualification.json').read_text())
    for name,record in q['checks'].items():
        if name=='enclosure':
            from qualify_freecad_drilling_native import geometric_checks
            shape=Part.Shape();shape.read(str(root/name/'model.step'));report[name]=geometric_checks(shape,record['expected']);continue
        shape=Part.Shape();shape.read(str(root/name/'model.step'));report[name]=controls(shape,record['expected'])
    atomic_json(root/'independent-neutral.json',{'verified':True,'pid':os.getpid(),'cases':report})


def edit(root,stage):
    from schemaxis.adaptors.freecad import adaptor,history_native
    from schemaxis.adaptors.freecad.document_xml import Document
    from schemaxis.adaptors.freecad.history_saved import observation
    from schemaxis.adaptors.freecad.parameters import verify_saved
    from schemaxis.artifacts import file_digest
    from qualify_freecad_drilling_native import geometric_checks
    source=root/'enclosure/model.FCStd' if stage=='edit1' else root/('edit1.FCStd' if stage=='edit2' else 'edit2.FCStd')
    authored=json.loads((root/'enclosure/authored.json').read_text())
    if stage=='edit1':assert file_digest(source)==json.loads((root/'enclosure/verification.json').read_text())['artifacts'][2]['sha256']
    else:assert file_digest(source)==json.loads((root/('edit1.json' if stage=='edit2' else 'edit2.json')).read_text())['sha256']
    d=App.openDocument(str(source));values={'wall':2.5,'height':22,'bossHeight':5.5,'mountDiameter':2.4} if stage=='edit1' else {'wall':3.5,'height':19,'bossHeight':7,'mountDiameter':1.8}
    for key,value in values.items():
        authored['parameters'][key]['value']=value
        if stage!='reopen':setattr(d.getObject('SchemaxisParameters'),'dim_'+key,value)
    for obj in d.Objects:obj.touch()
    d.recompute();prepared=adaptor.plan(authored);history_native.observe(d,prepared)
    w,h,b,r=values['wall'],values['height'],values['bossHeight'],values['mountDiameter']/2
    volume=1200*h-(40-2*w)*(30-2*w)*(h-w)+16*math.pi*b-4*math.pi*r*r*(w+b)
    expected={'volume':volume,'positions':[[-14,-9],[14,-9],[-14,9],[14,9]],'axis':'Z','voidSample':5,'diameter':2*r}
    shape=d.getObjectsByLabel('finished')[0].Shape;checks=geometric_checks(shape,expected)
    assert shape.isInside(App.Vector(0,0,w-.2),1e-7,True) and not shape.isInside(App.Vector(0,0,w+.2),1e-7,True)
    lid=d.getObjectsByLabel('lidFinished')[0].Shape;assert math.isclose(lid.Volume,(1176-math.pi)*w,rel_tol=1e-8,abs_tol=1e-6)
    if stage!='reopen':
        saved=root/(stage+'.FCStd');d.saveAs(str(saved));shape.exportStep(str(root/(stage+'.step')))
        neutral=Part.Shape();neutral.read(str(root/(stage+'.step')));geometric_checks(neutral,expected)
    else:saved=source
    observation(prepared,Document(saved));verify_saved(prepared,saved)
    atomic_json(root/(stage+'.json'),{'verified':True,'sha256':file_digest(saved),'pid':os.getpid(),'dimensions':values,'enclosure':checks,'floorTracksWall':True,'lidVolume':lid.Volume})
    App.closeDocument(d.Name)
