# Copyright (C) 2026 David L F Gaden
"""Independent geometric/edit oracle for the bounded mechanical-part workflow."""
import json
import math
import os
from pathlib import Path
import FreeCAD as App
import Part


def find(doc,label):
    objects=[o for o in doc.Objects if o.Label==label]
    assert len(objects)==1,label
    return objects[0]


def oracle(doc,width,thickness,radius,centre):
    shape=find(doc,'finished').Shape
    assert shape.isValid() and len(shape.Solids)==1
    expected=(width*50-math.pi*radius**2)*thickness
    area=2*(width*50-math.pi*radius**2)+2*(width+50)*thickness+2*math.pi*radius*thickness
    assert math.isclose(shape.Volume,expected,rel_tol=1e-10)
    assert math.isclose(shape.Area,area,rel_tol=1e-10)
    bb=shape.BoundBox;actual=[bb.XMin,bb.XMax,bb.YMin,bb.YMax,bb.ZMin,bb.ZMax]
    bounds=[-width/2,width/2,-25,25,0,thickness]
    assert all(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-7) for a,b in zip(actual,bounds))
    centre_of_mass=shape.Solids[0].CenterOfMass
    fraction=math.pi*radius**2/(width*50-math.pi*radius**2)
    expected_centre=[-fraction*centre[0],-fraction*centre[1],thickness/2]
    assert all(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-7) for a,b in zip(list(centre_of_mass),expected_centre))
    assert not shape.isInside(App.Vector(*centre,thickness/2),1e-7,False)
    assert shape.isInside(App.Vector(-width/4,0,thickness/2),1e-7,False)
    cylinders=[f for f in shape.Faces if isinstance(f.Surface,Part.Cylinder)]
    assert cylinders
    assert all(math.isclose(f.Surface.Radius,radius,rel_tol=1e-10) for f in cylinders)
    assert all(math.isclose(f.BoundBox.ZMin,0,abs_tol=1e-7) and math.isclose(f.BoundBox.ZMax,thickness,abs_tol=1e-7) for f in cylinders)
    for label in ('outline','bore'):
        sketch=find(doc,label);assert sketch.FullyConstrained and sketch.solve()==0
    return {'volume':shape.Volume,'area':shape.Area,'bounds':actual,'centreOfMass':list(centre_of_mass),'holeCentre':centre}


def main(directory,mode):
    directory=Path(directory);plan=json.loads((directory/'plan.json').read_text())
    report={'pid':os.getpid(),'verified':False}
    values={k:p['value'] for k,p in plan['parameters'].items()}
    if mode=='edit':
        report['perturbations']={}
        from schemaxis.adaptors.freecad.native import check_definition
        from schemaxis.core.faults import SchemaxisError
        import Sketcher
        report['nativeConstraintNegatives']={}
        for label in ('name','type','endpoint','body-placement'):
            doc=App.openDocument(str(directory/'model.FCStd'));hole=find(doc,'bore')
            index=next(i for i,c in enumerate(hole.Constraints) if c.Name=='centreX')
            if label=='body-placement':doc.N0.Placement.Base=App.Vector(10,20,30)
            elif label=='name':hole.renameConstraint(index,'wrongCentre')
            else:
                hole.delConstraint(index)
                constraint=Sketcher.Constraint('DistanceY',0,3,15) if label=='type' else Sketcher.Constraint('DistanceX',0,1,15)
                added=hole.addConstraint(constraint);hole.renameConstraint(added,'centreX')
            doc.recompute()
            try:check_definition(doc,plan,{})
            except SchemaxisError as error:
                assert error.fault.code in ('VERIFICATION_FAILED','INVALID_GEOMETRY')
                report['nativeConstraintNegatives'][label]=error.fault.code
            else:raise AssertionError('native constraint tampering accepted: '+label)
            App.closeDocument(doc.Name)
        for key,p in plan['parameters'].items():
            results=[]
            for end in ('minimum','maximum'):
                doc=App.openDocument(str(directory/'model.FCStd'))
                setattr(doc.SchemaxisParameters,'dim_'+key,p[end]);doc.recompute()
                current={**values,key:p[end]}
                results.append(oracle(doc,current['width'],current['thickness'],current['boreRadius'],[15,10]))
                App.closeDocument(doc.Name)
            assert results[0]!=results[1]
            report['perturbations'][key]=results
        doc=App.openDocument(str(directory/'model.FCStd'))
        for key,p in plan['parameters'].items():setattr(doc.SchemaxisParameters,'dim_'+key,p['maximum'])
        doc.recompute()
        hole=find(doc,'bore')
        for name,value in [('centreX',18),('centreY',-7)]:
            index=next(i for i,c in enumerate(hole.Constraints) if c.Name==name)
            hole.setDatum(index,App.Units.Quantity(str(value)+' mm'))
        doc.recompute()
        report['edited']=oracle(doc,100,50,5,[18,-7])
        report['expressions']={o.Name:list(o.ExpressionEngine) for o in doc.Objects}
        doc.saveAs(str(directory/'independently-edited.FCStd'))
        Part.export([find(doc,'part')],str(directory/'independently-edited.step'))
        App.closeDocument(doc.Name)
        doc=App.openDocument(str(directory/'model.FCStd'))
        pocket=find(doc,'finished');pocket.Type='Length';pocket.Length=values['thickness'];doc.recompute()
        oracle(doc,values['width'],values['thickness'],values['boreRadius'],[15,10])
        from schemaxis.adaptors.freecad.native import check_definition
        from schemaxis.core.faults import SchemaxisError
        try:check_definition(doc,plan,{})
        except SchemaxisError as error:report['wrongTypeSameShapeRejected']=error.fault.code
        else:raise AssertionError('fixed-length Pocket accepted as ThroughAll')
        doc.SchemaxisParameters.dim_thickness=40;doc.recompute()
        assert find(doc,'finished').Shape.isInside(App.Vector(15,10,20),1e-7,False)
        try:oracle(doc,values['width'],40,values['boreRadius'],[15,10])
        except AssertionError:report['blindHoleDiscriminated']=True
        else:raise AssertionError('independent oracle failed to distinguish blind hole')
        report['blindHoleVolume']=find(doc,'finished').Shape.Volume
        doc.saveAs(str(directory/'wrong-fixed-depth.FCStd'));App.closeDocument(doc.Name)
    else:
        doc=App.openDocument(str(directory/'independently-edited.FCStd'))
        for obj in doc.Objects:obj.touch()
        doc.recompute();report['edited']=oracle(doc,100,50,5,[18,-7])
        report['expressions']={o.Name:list(o.ExpressionEngine) for o in doc.Objects}
        shape=Part.Shape();shape.read(str(directory/'independently-edited.step'))
        assert math.isclose(shape.Volume,report['edited']['volume'],rel_tol=1e-10)
        report['stepVolume']=shape.Volume
        App.closeDocument(doc.Name)
    report['verified']=True
    (directory/('independent-'+mode+'.json')).write_text(json.dumps(report,indent=2)+'\n')
