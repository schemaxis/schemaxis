"""Independent manufacturing geometry and native drawing edit/reopen probes."""
import json
import math
import os
from pathlib import Path


def source(directory):
    import FreeCAD as A,Part
    directory=Path(directory);doc=A.newDocument('IndependentEnclosure');obj=doc.addObject('Part::Feature','Enclosure');obj.Label='enclosure'
    shape=Part.makeBox(80,60,30).cut(Part.makeBox(76,56,28,A.Vector(2,2,2)))
    for x in (10,70):
        for y in (10,50):shape=shape.cut(Part.makeCylinder(2,2,A.Vector(x,y,0)))
    obj.Shape=shape;doc.recompute();doc.saveAs(str(directory/'enclosure.FCStd'));shape.exportStep(str(directory/'enclosure.step'))
    # Independent formula: outer stock - open cavity -4floor mounting bores.
    volume=80*60*30-76*56*28-4*math.pi*2**2*2
    cz=(80*60*30*15-76*56*28*16-4*math.pi*2**2*2*1)/volume
    assert abs(shape.Volume-volume)<1e-6 and abs(shape.Solids[0].CenterOfMass.z-cz)<1e-6
    (directory/'source-oracle.json').write_text(json.dumps({'verified':True,'volume':volume,'bounds':[0,80,0,60,0,30],'centreOfMass':[40,30,cz],'wall':2,'mountingCentres':[[10,10,0],[70,10,0],[10,50,0],[70,50,0]],'pid':os.getpid()}))
    A.closeDocument(doc.Name)
    for name,solid in (('cylinder',Part.makeCylinder(5,12)),('triangle',Part.Face(Part.makePolygon([A.Vector(0,0,0),A.Vector(30,0,0),A.Vector(0,20,0),A.Vector(0,0,0)])).extrude(A.Vector(0,0,7)))):
        doc=A.newDocument('Independent'+name);obj=doc.addObject('Part::Feature','Solid');obj.Label=name;obj.Shape=solid;doc.recompute();doc.saveAs(str(directory/(name+'.FCStd')));A.closeDocument(doc.Name)


def edit(directory,stage):
    import FreeCAD as A
    directory=Path(directory);doc=A.openDocument(str(directory/'drawing.FCStd'));v=doc.getObject('View_top')
    if stage=='edit':
        v.Scale=.25;doc.getObject('Title').Text=['Enclosure revision B','Changed natively'];doc.recompute();doc.save()
    assert abs(v.Scale-.25)<1e-12 and list(doc.getObject('Title').Text)==['Enclosure revision B','Changed natively']
    assert len(doc.getObject('Source').Shape.Solids)==1
    assert doc.getObject('Dimension_wall').getText().startswith('2.00')
    (directory/(stage+'.json')).write_text(json.dumps({'verified':True,'pid':os.getpid(),'scale':v.Scale,'dimension':doc.getObject('Dimension_wall').getText(),'objects':{o.Name:o.TypeId for o in doc.Objects}}));A.closeDocument(doc.Name)
