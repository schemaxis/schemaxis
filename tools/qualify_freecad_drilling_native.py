"""Independent geometric drilling checks through neutral STEP and public APIs."""
import copy
import json
import math
import os
from pathlib import Path
import FreeCAD as App
import Part
from schemaxis.artifacts import atomic_json


def geometric_checks(shape,expected):
    assert shape.isValid() and len(shape.Solids)==1
    assert math.isclose(shape.Volume,expected['volume'],rel_tol=1e-8,abs_tol=1e-6)
    if expected['axis']=='oblique':
        cylinders=[]
        for face in shape.Faces:
            surface=face.Surface
            if type(surface).__name__!='Cylinder':continue
            assert math.isclose(surface.Radius,expected['diameter']/2,rel_tol=1e-7,abs_tol=1e-7)
            direction=list(surface.Axis);wanted=expected['direction'];assert abs(abs(sum(a*b for a,b in zip(direction,wanted)))-1)<1e-7
            delta=[a-b for a,b in zip(list(surface.Center),expected['lineOrigin'])];along=sum(a*b for a,b in zip(delta,wanted));assert math.sqrt(sum((a-along*b)**2 for a,b in zip(delta,wanted)))<1e-6
            cylinders.append(surface.Radius)
        assert cylinders
        for point in expected['voidPoints']:assert not shape.isInside(App.Vector(*point),1e-7,True)
        assert shape.isInside(App.Vector(14,14,5),1e-7,True)
        return {'volume':shape.Volume,'axis':wanted,'radius':expected['diameter']/2,'voidChecks':len(expected['voidPoints']),'stockPointInside':True}
    axis=2 if expected['axis']=='Z' else 0;other=[i for i in range(3) if i!=axis];positions=[]
    for face in shape.Faces:
        surface=face.Surface
        if type(surface).__name__!='Cylinder' or not math.isclose(surface.Radius,expected['diameter']/2,rel_tol=1e-7,abs_tol=1e-7):continue
        direction=list(surface.Axis)
        assert abs(abs(direction[axis])-1)<1e-7 and all(abs(direction[i])<1e-7 for i in other)
        point=[list(surface.Center)[i] for i in other]
        if not any(math.dist(point,p)<1e-6 for p in positions):positions.append(point)
    assert len(positions)==len(expected['positions']),(positions,expected['positions'])
    for p in expected['positions']:
        assert sum(math.dist(p,actual)<1e-6 for actual in positions)==1,(p,positions)
        point=[0,0,0];point[axis]=expected['voidSample']
        for i,value in zip(other,p):point[i]=value
        assert not shape.isInside(App.Vector(*point),1e-7,True),point
    assert shape.isInside(App.Vector(14,14,5),1e-7,True)
    advanced=0;o=expected.get('holeOptions',{})
    if expected['axis']=='Z' and o:
        x,y=expected['positions'][0];radius=expected['diameter']/2
        def check(dx,z,wanted):
            nonlocal advanced
            assert shape.isInside(App.Vector(x+dx,y,z),1e-7,True)==wanted,(x+dx,y,z,wanted)
            advanced+=1
        if o.get('extent')=='length':
            tip=radius/math.tan(math.radians(o.get('tipAngle',118)/2)) if o.get('tip')=='conical' else 0
            apex=10-o['depth']-(tip if o.get('depthMeasure','cylindrical')=='cylindrical' else 0)
            check(0,apex-.5,True)
            if tip:
                check(radius*.125,apex+tip*.25,False);check(radius*.75,apex+tip*.25,True)
        if o.get('recess','none')!='none':
            outer=o['recessDiameter']/2;radial=(radius+outer)/2;depth=o.get('recessDepth',0)
            transition=(outer-radius)/math.tan(math.radians(o.get('recessAngle',90)/2))
            if o['recess']=='counterbore':check(radial,10-depth*.5,False);check(radial,10-depth-.5,True)
            elif o['recess']=='countersink':check(radial,10-transition*.25,False);check(radial,10-transition*.75,True)
            else:check(radial,10-depth-transition*.25,False);check(radial,10-depth-transition*1.25,True)
    return {'volume':shape.Volume,'drillCentres':positions,'drillRadius':expected['diameter']/2,'axis':expected['axis'],'voidChecks':len(positions),'stockPointInside':True,'additionalDepthRecessChecks':advanced}


def main(directory,stage='neutral'):
    root=Path(directory)
    if stage!='neutral':return edit_stage(root,stage)
    if stage=='neutral':
        q=json.loads((root/'qualification.json').read_text());results={}
        for name,record in q['checks'].items():
            expected=record['expected']
            if 'positions' not in expected and expected.get('axis')!='oblique':continue
            shape=Part.Shape();shape.read(str(root/name/'model.step'));results[name]=geometric_checks(shape,expected)
        atomic_json(root/'independent-neutral.json',{'verified':True,'pid':os.getpid(),'cases':results})


def edit_stage(root,stage):
    from schemaxis.adaptors.freecad import adaptor
    from schemaxis.adaptors.freecad.document_xml import Document
    from schemaxis.adaptors.freecad.history_saved import observation
    from schemaxis.adaptors.freecad.parameters import verify_saved as verify_parameters
    from schemaxis.artifacts import file_digest
    target=root/('native-'+stage)
    if stage!='reopen':target.mkdir()
    results={}
    for kind,baseline in [('grid','driven-grid'),('circle','bolt-circle-6'),('enclosure','enclosure')]:
        source=root/baseline/'model.FCStd' if stage=='edit1' else root/('native-edit1' if stage=='edit2' else 'native-edit2')/(kind+'.FCStd')
        authored=json.loads((root/baseline/'authored.json').read_text())
        if kind=='grid':
            values={'pitch':18,'drill':3.5,'headDepth':3} if stage=='edit1' else {'pitch':14,'drill':2.5,'headDepth':1.5}
            for key,value in values.items():authored['parameters'][key]['value']=value
            radius=values['drill']/2;positions=[[x,y] for y in [-7,7] for x in [-values['pitch']/2,values['pitch']/2]]
            volume=9000-4*math.pi*(radius*radius*10+(9-radius*radius)*values['headDepth'])
            expected={'volume':volume,'positions':positions,'axis':'Z','diameter':values['drill'],'voidSample':5}
        elif kind=='circle':
            values={'radius':11,'phase':-15,'diameter':2.8} if stage=='edit1' else {'radius':8,'phase':45,'diameter':3.2}
            authored['nodes'][-2]['options'].update(radius=values['radius'],phase=values['phase']);authored['nodes'][-1]['options']['diameter']=values['diameter']
            positions=[[values['radius']*math.cos(math.radians(values['phase']+60*n)),values['radius']*math.sin(math.radians(values['phase']+60*n))] for n in range(6)]
            expected={'volume':9000-6*math.pi*(values['diameter']/2)**2*10,'positions':positions,'axis':'Z','diameter':values['diameter'],'voidSample':5}
        else:
            values={'mountDiameter':2.4,'wall':2.5,'floor':3.5,'height':21,'bossHeight':5} if stage=='edit1' else {'mountDiameter':1.8,'wall':3,'floor':2.5,'height':19,'bossHeight':7}
            for key,value in values.items():authored['parameters'][key]['value']=value
            w,f,h,b=values['wall'],values['floor'],values['height'],values['bossHeight'];diameter=values['mountDiameter'];radius=diameter/2
            volume=1200*h-(40-2*w)*(30-2*w)*(h-f)+16*math.pi*b-4*math.pi*radius*radius*(f+b)
            expected={'volume':volume,'positions':[[-14,-9],[14,-9],[-14,9],[14,9]],'axis':'Z','diameter':diameter,'voidSample':5}
        # Own generated histories use exact closed native type/constraint/engine
        # membership. Baseline verification precedes edits; later files bind the
        # successful previous stage's digest before native restoration.
        if stage!='edit1':
            prior=json.loads((source.parent/'edited.json').read_text());assert file_digest(source)==prior['documents'][kind]['sha256']
        doc=App.openDocument(str(source))
        if stage!='reopen':
            if kind in ('grid','enclosure'):
                parameters=doc.getObject('SchemaxisParameters')
                for key,value in values.items():setattr(parameters,'dim_'+key,value)
            else:
                sketch=doc.getObjectsByLabel('locations')[0]
                for constraint,value,unit in [('pitchRadius',values['radius'],'mm'),('phase',values['phase'],'deg')]:
                    indices=[n for n,c in enumerate(sketch.Constraints) if c.Name==constraint];assert len(indices)==1
                    sketch.setDatum(indices[0],App.Units.Quantity(str(value)+' '+unit))
                doc.getObjectsByLabel('holes')[0].Diameter=values['diameter']
        for obj in doc.Objects:obj.touch()
        doc.recompute();hole=doc.getObjectsByLabel('finished' if kind=='enclosure' else 'holes')[0];checks=geometric_checks(hole.Shape,expected)
        if stage!='reopen':
            saved=target/(kind+'.FCStd');doc.saveAs(str(saved));hole.Shape.exportStep(str(target/(kind+'.step')))
            prepared=adaptor.plan(authored);observation(prepared,Document(saved))
            if 'parameters' in authored:verify_parameters(prepared,saved)
            # Neutral export must preserve the edited geometry as well.
            neutral=Part.Shape();neutral.read(str(target/(kind+'.step')));geometric_checks(neutral,expected)
        else:
            saved=source;prepared=adaptor.plan(authored);observation(prepared,Document(saved))
            if 'parameters' in authored:verify_parameters(prepared,saved)
        results[kind]={'sha256':file_digest(saved),'expected':expected,'geometry':checks};App.closeDocument(doc.Name)
    atomic_json(root/('native-reopened.json' if stage=='reopen' else 'native-'+stage+'/edited.json'),{'verified':True,'pid':os.getpid(),'documents':results})
