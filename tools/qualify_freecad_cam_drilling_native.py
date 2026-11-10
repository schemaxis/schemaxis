"""Independent synthetic geometry and controlled private native CAM edit probes."""
import hashlib
import json
import math
import os
from pathlib import Path


def source(directory):
    import FreeCAD as A,Part
    directory=Path(directory);oracles={}
    for label,origin,size,holes in (
        ('counterbore',[7,-20,-4],[36,20,12],[(23,-11,3,2),(23,-11,1,8)]),
        ('ring',[-17,5,2],[40,26,10],[(3+7*math.cos(math.radians(30+90*i)),18+7*math.sin(math.radians(30+90*i)),1.5875,6.25) for i in range(4)])):
        doc=A.newDocument('IndependentDrillingSource');obj=doc.addObject('Part::Feature','Solid');top=origin[2]+size[2]
        shape=Part.makeBox(*size,A.Vector(*origin));volume=math.prod(size)
        moments=[volume*(origin[i]+size[i]/2) for i in range(3)]
        # Concentric counterbore cylinders overlap: the small cylinder's top
        # two millimetres are already removed by the larger tool.
        for index,(x,y,r,depth) in enumerate(holes):
            shape=shape.cut(Part.makeCylinder(r,depth,A.Vector(x,y,top-depth)))
            removed_depth=depth-(2 if label=='counterbore' and index==1 else 0)
            removed=math.pi*r*r*removed_depth;volume-=removed
            centre=[x,y,top-depth+removed_depth/2]
            moments=[m-removed*c for m,c in zip(moments,centre)]
        obj.Shape=shape;doc.recompute();com=[m/volume for m in moments]
        assert len(shape.Solids)==1 and abs(shape.Volume-volume)<1e-7
        centre=shape.Solids[0].CenterOfMass
        assert max(abs(v-c) for v,c in zip((centre.x,centre.y,centre.z),com))<1e-7
        doc.saveAs(str(directory/(label+'.FCStd')));shape.exportStep(str(directory/(label+'.step')))
        oracles[label]={'volume':volume,'bounds':[v for i in range(3) for v in (origin[i],origin[i]+size[i])],'centreOfMass':com}
        A.closeDocument(doc.Name)
    (directory/'source-oracles.json').write_text(json.dumps(oracles))


def edit(directory,stage,expected_sha):
    """Only programme-generated, digest-pinned files enter this test worker.

    This is a qualification helper, not an authored project-adoption API. The
    parent pins its controlled edit output before the separate reopen process.
    """
    import FreeCAD as A,FreeCADGui as G
    import Path as NativePath
    from Path import Preferences
    directory=Path(directory);native=directory/'machining.FCStd'
    assert hashlib.sha256(native.read_bytes()).hexdigest()==expected_sha
    settings=(directory/(stage+'-settings')).resolve()
    assert all(Path(os.environ[k]).resolve().is_relative_to(settings) for k in ('FREECAD_USER_HOME','FREECAD_USER_DATA','FREECAD_USER_TEMP','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','XDG_RUNTIME_DIR'))
    assert Path(A.getUserAppDataDir()).resolve().is_relative_to(settings)
    assert Path(A.ConfigGet('UserParameter')).resolve()==(directory/'preferences.cfg').resolve()
    assert Preferences.getAssetPath().resolve()==(directory/'cam-assets').resolve()
    assert abs(Preferences.defaultLibAreaCurveAccuracy()-1e-5)<1e-14
    assert abs(NativePath.Area().getParams()['Accuracy']-1e-5)<1e-14
    from schemaxis.adaptors.freecad.cam_names import operation_names
    plan=json.loads((directory/'plan.json').read_text());names=operation_names(plan)
    doc=A.openDocument(str(native));job=doc.getObject('Machining')
    assert [o.Name for o in job.Operations.Group]==list(names.values())
    op=doc.getObject(names[plan['operations'][1]['id']]);tc=op.ToolController
    if stage=='edit':
        op.setExpression('PeckDepth',None);op.PeckDepth=1.375
        tc.VertFeed='105 mm/min';tc.VertRapid='315 mm/min'
    for item in job.Operations.Group:item.touch()
    doc.recompute()
    assert abs(op.PeckDepth.Value-1.375)<1e-12 and abs(tc.VertFeed.Value*60-105)<1e-12
    assert len(job.Tools.Group)==2 and [t.ToolNumber for t in job.Tools.Group]==[1,2]
    assert op.ToolController.Name=='Cutter1' and op.ToolController.Tool.Name=='MillingTool1'
    from schemaxis.adaptors.freecad.cam_tool_native import physical_cutter
    plan=json.loads((directory/'plan.json').read_text())
    for tool in plan['tools']:physical_cutter(doc.getObject(tool['nativeTool']).Shape,{'tool':tool,'stockBounds':plan['stockBounds']})
    from Path.Main import Job
    from Path.Post.Processor import WrapperPost
    from schemaxis.adaptors.freecad.cam_native import POST_ARGS
    program=WrapperPost(job,str(Path(Job.__file__).parents[1]/'Post/scripts/linuxcnc_post.py'),'linuxcnc_post').export()
    assert len(program)==1
    if stage=='edit':doc.save()
    (directory/(stage+'.ngc')).write_text(program[0][1])
    G.activeDocument().activeView().viewAxonometric();G.activeDocument().activeView().fitAll()
    G.activeDocument().activeView().saveImage(str(directory/(stage+'.png')),960,720,'Current')
    (directory/(stage+'.json')).write_text(json.dumps({'verified':True,'pid':os.getpid(),'peck':op.PeckDepth.Value,'plunge':tc.VertFeed.Value*60,'nativeSha256':hashlib.sha256(native.read_bytes()).hexdigest(),'programSha256':hashlib.sha256(program[0][1].encode()).hexdigest(),'display':os.environ['DISPLAY'],'privateSettings':str(settings),'userParameter':A.ConfigGet('UserParameter')}))
    A.closeDocument(doc.Name)
