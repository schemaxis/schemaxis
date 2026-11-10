"""Independent analytic oracle and edit/reopen controls for machined recesses."""
import json
import math
import os
from pathlib import Path
import FreeCAD as App
import Part


def find(doc,label):
    items=[o for o in doc.Objects if o.Label==label]
    assert len(items)==1,label
    return items[0]


def oracle(doc,thickness,depth,radius,through=3,centre=(15,10)):
    shape=find(doc,'finished').Shape
    assert shape.isValid() and len(shape.Solids)==1
    d=min(depth,thickness);a=80*50;small=math.pi*through**2;annulus=math.pi*(radius**2-through**2)
    volume=a*thickness-small*thickness-annulus*d
    horizontal=2*(a-small) if depth<thickness else 2*(a-math.pi*radius**2)
    area=horizontal+2*(80+50)*thickness+2*math.pi*through*(thickness-d)+2*math.pi*radius*d
    assert math.isclose(shape.Volume,volume,rel_tol=1e-10),(shape.Volume,volume)
    assert math.isclose(shape.Area,area,rel_tol=1e-10),(shape.Area,area)
    box=shape.BoundBox;bounds=[box.XMin,box.XMax,box.YMin,box.YMax,box.ZMin,box.ZMax]
    assert all(math.isclose(v,w,abs_tol=1e-7) for v,w in zip(bounds,[-40,40,-25,25,0,thickness]))
    removed=small*thickness+annulus*d
    expected=[-centre[0]*removed/volume,-centre[1]*removed/volume,
              (a*thickness**2/2-small*thickness**2/2-annulus*d**2/2)/volume]
    com=list(shape.Solids[0].CenterOfMass)
    assert all(math.isclose(v,w,abs_tol=1e-7) for v,w in zip(com,expected)),(com,expected)
    mid=(through+radius)/2
    assert not shape.isInside(App.Vector(centre[0]+mid,centre[1],d/2),1e-7,False)
    if depth<thickness:assert shape.isInside(App.Vector(centre[0]+mid,centre[1],(d+thickness)/2),1e-7,False)
    assert shape.isInside(App.Vector(-20,0,thickness/2),1e-7,False)
    assert shape.isInside(App.Vector(*centre,thickness/2),1e-7,False)==(through==0 and depth<thickness and thickness/2>depth)
    cylinders=[f for f in shape.Faces if isinstance(f.Surface,Part.Cylinder)]
    observed=sorted((round(f.Surface.Radius,7),round(f.BoundBox.ZMin,7),round(f.BoundBox.ZMax,7)) for f in cylinders)
    wanted=[(radius,0,d)]+([(through,d,thickness)] if through and depth<thickness else [])
    assert observed==sorted(wanted),(observed,wanted)
    for label in ('outline','counterbore'):
        s=find(doc,label);assert s.FullyConstrained and s.solve()==0
    return {'volume':shape.Volume,'area':shape.Area,'bounds':bounds,'centreOfMass':com,'cylinders':observed}


def main(directory,mode):
    directory=Path(directory);report={'pid':os.getpid(),'runtime':App.Version(),'verified':False}
    if mode=='edit':
        report['baseline']={}
        for name,values in [('counterbore',(12,4,6,3)),('variant',(20,8,8,3)),('blind',(12,4,6,0)),('length-through-stock',(12,30,6,3))]:
            doc=App.openDocument(str(directory/name/'model.FCStd'))
            report['baseline'][name]=oracle(doc,*values)
            expected_type='Length';cut=find(doc,'finished')
            assert cut.Type==expected_type and cut.Reversed and cut.SideType=='One side'
            assert math.isclose(cut.Length.Value,values[1],abs_tol=1e-8)
            App.closeDocument(doc.Name)
        doc=App.openDocument(str(directory/'rectangle/model.FCStd'));shape=find(doc,'finished').Shape
        assert shape.isValid() and len(shape.Solids)==1
        assert math.isclose(shape.Volume,47200,abs_tol=1e-7)
        assert math.isclose(shape.Area,11360,abs_tol=1e-7)
        assert math.isclose(shape.Solids[0].CenterOfMass.z,286400/47200,abs_tol=1e-7)
        assert not shape.isInside(App.Vector(0,0,2),1e-7,False)
        assert shape.isInside(App.Vector(0,0,8),1e-7,False)
        assert find(doc,'recess').FullyConstrained and find(doc,'recess').solve()==0
        report['rectangle']={'volume':shape.Volume,'area':shape.Area,'centreOfMass':list(shape.Solids[0].CenterOfMass)}
        App.closeDocument(doc.Name)
        report['perturbations']={}
        for parameter,ends in [('counterboreDepth',(2,8)),('thickness',(10,20)),('counterboreRadius',(5,8))]:
            results=[]
            for value in ends:
                doc=App.openDocument(str(directory/'counterbore/model.FCStd'))
                setattr(doc.SchemaxisParameters,'dim_'+parameter,value);doc.recompute()
                current={'thickness':12,'counterboreDepth':4,'counterboreRadius':6,parameter:value}
                results.append(oracle(doc,current['thickness'],current['counterboreDepth'],current['counterboreRadius']))
                App.closeDocument(doc.Name)
            assert results[0]!=results[1];report['perturbations'][parameter]=results
        # Direct native edits of unbound sketch dimensions, alongside persistent drivers.
        doc=App.openDocument(str(directory/'counterbore/model.FCStd'))
        doc.SchemaxisParameters.dim_thickness=20;doc.SchemaxisParameters.dim_counterboreDepth=8;doc.SchemaxisParameters.dim_counterboreRadius=8
        for label in ('bore','counterbore'):
            sketch=find(doc,label)
            for name,value in [('centreX',-12),('centreY',-7)]:
                index=next(i for i,c in enumerate(sketch.Constraints) if c.Name==name)
                sketch.setDatum(index,App.Units.Quantity(str(value)+' mm'))
        doc.recompute();report['edited']=oracle(doc,20,8,8,3,(-12,-7))
        report['expressions']={o.Name:list(o.ExpressionEngine) for o in doc.Objects}
        doc.saveAs(str(directory/'edited.FCStd'));Part.export([find(doc,'part')],str(directory/'edited.step'));App.closeDocument(doc.Name)
        # A finite cut already beyond the stock looks through, but changing stock
        # later distinguishes its machining intent from ThroughAll.
        doc=App.openDocument(str(directory/'length-through-stock/model.FCStd'))
        report['sameShapeFinite']=oracle(doc,12,30,6)
        from schemaxis.adaptors.freecad.native import check_definition
        from schemaxis.core.faults import SchemaxisError
        plan=json.loads((directory/'length-through-stock/plan.json').read_text())
        cut=find(doc,'finished');cut.Type='ThroughAll';doc.recompute()
        report['sameShapeThroughAll']=oracle(doc,12,30,6)
        try:check_definition(doc,plan,{})
        except SchemaxisError as error:
            assert error.fault.code=='VERIFICATION_FAILED';report['wrongTypeRejected']=error.fault.code
        else:raise AssertionError('same-shape ThroughAll substituted for finite-depth machining intent')
        cut.Type='Length';doc.SchemaxisParameters.dim_thickness=40;doc.recompute()
        report['thickerStockFinite']=oracle(doc,40,30,6)
        cut.Type='ThroughAll';doc.recompute();report['thickerStockThroughAll']=oracle(doc,40,40,6)
        assert report['thickerStockFinite']['volume']!=report['thickerStockThroughAll']['volume']
        App.closeDocument(doc.Name)
    else:
        doc=App.openDocument(str(directory/'edited.FCStd'))
        for item in doc.Objects:item.touch()
        doc.recompute();report['edited']=oracle(doc,20,8,8,3,(-12,-7))
        report['expressions']={o.Name:list(o.ExpressionEngine) for o in doc.Objects}
        shape=Part.Shape();shape.read(str(directory/'edited.step'))
        assert math.isclose(shape.Volume,report['edited']['volume'],rel_tol=1e-10)
        report['stepVolume']=shape.Volume;App.closeDocument(doc.Name)
    report['verified']=True
    (directory/('independent-'+mode+'.json')).write_text(json.dumps(report,indent=2)+'\n')
