"""Independent millable solid and persistent native CAM edit acceptance."""
import json
import math
import os
from pathlib import Path


def source(directory):
    import FreeCAD as A,Part
    directory=Path(directory);oracles={}
    for name,l,w,h,wall,floor,radius in [('enclosure',40,30,20,3,3,2),('variant',48,36,24,4,4,3),('sharp',40,30,20,3,3,0)]:
        doc=A.newDocument('IndependentMillingSolid');obj=doc.addObject('Part::Feature','Solid');obj.Label=name
        cutter=Part.makeBox(l-2*wall,w-2*wall,h-floor,A.Vector(wall,wall,floor))
        if radius:cutter=cutter.makeFillet(radius,[e for e in cutter.Edges if e.BoundBox.ZLength>h-floor-1e-6])
        obj.Shape=Part.makeBox(l,w,h).cut(cutter);doc.recompute();doc.saveAs(str(directory/(name+'.FCStd')));obj.Shape.exportStep(str(directory/(name+'.step')))
        area=(l-2*wall)*(w-2*wall)-(4-math.pi)*radius**2;volume=l*w*h-area*(h-floor);cz=(l*w*h*h/2-area*(h-floor)*(h+floor)/2)/volume
        assert abs(obj.Shape.Volume-volume)<1e-6 and abs(obj.Shape.Solids[0].CenterOfMass.z-cz)<1e-6
        oracles[name]={'volume':volume,'bounds':[0,l,0,w,0,h],'centreOfMass':[l/2,w/2,cz],'floor':[l/2,w/2,floor]};A.closeDocument(doc.Name)
    (directory/'source-oracles.json').write_text(json.dumps(oracles))


def edit(directory,stage):
    import FreeCAD as A
    import Path as NativePath
    from Path import Preferences
    assert abs(Preferences.defaultLibAreaCurveAccuracy()-1e-5)<1e-14
    assert abs(NativePath.Area().getParams()['Accuracy']-1e-5)<1e-14
    directory=Path(directory);assert Preferences.getAssetPath().resolve()==(directory/'cam-assets').resolve() and (directory/'cam-assets').is_dir()
    settings=(directory/(stage+'-settings')).resolve();assert Path(A.getUserAppDataDir()).resolve().is_relative_to(settings)
    user_parameter=A.ConfigGet('UserParameter');assert Path(user_parameter).resolve()==(directory/'preferences.cfg').resolve()
    system_parameter=A.ConfigGet('SystemParameter');assert Path(system_parameter).resolve()==(settings/'system.cfg').resolve()
    assert all(Path(os.environ[key]).resolve().is_relative_to(settings) for key in ('FREECAD_USER_HOME','FREECAD_USER_DATA','FREECAD_USER_TEMP','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','XDG_RUNTIME_DIR'))
    phase=directory/(stage+'-phase.txt');phase.write_text('effective profile and private paths checked')
    doc=A.openDocument(str(directory/'machining.FCStd'));op=doc.getObject('Op_cavity');phase.write_text('native document opened')
    if stage=='edit':op.StepDown=1.25
    for item in doc.getObject('Machining').Operations.Group:item.touch()
    phase.write_text('recomputing native edited paths');doc.recompute();phase.write_text('native edited paths recomputed');doc.save()
    assert abs(op.StepDown.Value-1.25)<1e-12 and len(op.Path.Commands)>10
    assert doc.getObject('Cutter').Tool.Name=='Endmill' and doc.getObject('Machining').Model.Group[0].Shape.isValid()
    import Path.Main.Job as Job
    from Path.Post.Processor import WrapperPost
    from schemaxis.adaptors.freecad.cam_native import POST_ARGS
    program=WrapperPost(doc.getObject('Machining'),str(Path(Job.__file__).parents[1]/'Post/scripts/linuxcnc_post.py'),'linuxcnc_post').export()
    phase.write_text('native edited program posted')
    assert len(program)==1
    (directory/'program.ngc').write_text(program[0][1])
    (directory/(stage+'.json')).write_text(json.dumps({'verified':True,'pid':os.getpid(),'stepDown':op.StepDown.Value,'areaAccuracy':NativePath.Area().getParams()['Accuracy'],'commands':len(op.Path.Commands),'display':os.environ['DISPLAY'],'userData':A.getUserAppDataDir(),'userParameter':user_parameter,'systemParameter':system_parameter,'assetPath':str(Preferences.getAssetPath().resolve()),'programSha256':__import__('hashlib').sha256((directory/'program.ngc').read_bytes()).hexdigest()}));A.closeDocument(doc.Name)
