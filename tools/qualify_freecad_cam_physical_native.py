"""Finite controlled reduced-tool GUI edits of admitted synthetic native packets.

The host first verifies the complete original source/Job/bundle, then pins a
private native copy. Later saves are owned qualification outputs, not a general
edited-CAM adoption API. Only the installed extension is imported here.
"""
import hashlib
import json
import math
import os
from pathlib import Path


def edit(directory,stage,expected_sha):
    import FreeCAD as A,FreeCADGui as G
    from Path import Preferences
    import Path as NativePath
    from schemaxis.adaptors.freecad.cam_reduced import native_module,MODULE
    from schemaxis.adaptors.freecad.cam_pointed_native import physical,holder_readback
    from schemaxis.adaptors.freecad.cam_names import operation_names
    from schemaxis.adaptors.freecad.cam_native import POST_ARGS
    from Path.Main import Job
    from Path.Post.Processor import WrapperPost
    values={'reduced-initial':(3,None),'reduced-edit':(3,4),'reduced-reopen':(4,None),
            'reduced-return':(4,3),'reduced-final':(3,None)}
    if stage not in values:raise ValueError('Unknown finite reduced-profile GUI stage')
    before,changed=values[stage]
    directory=Path(directory);native=directory/'machining.FCStd'
    assert hashlib.sha256(native.read_bytes()).hexdigest()==expected_sha
    settings=(directory/(stage+'-settings')).resolve()
    assert all(Path(os.environ[k]).resolve().is_relative_to(settings) for k in ('FREECAD_USER_HOME','FREECAD_USER_DATA','FREECAD_USER_TEMP','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','XDG_RUNTIME_DIR'))
    assert Path(A.getUserAppDataDir()).resolve().is_relative_to(settings)
    assert Path(A.ConfigGet('UserParameter')).resolve()==(directory/'preferences.cfg').resolve()
    assert Preferences.getAssetPath().resolve()==(directory/'cam-assets').resolve()
    assert abs(Preferences.defaultLibAreaCurveAccuracy()-1e-5)<1e-14
    assert abs(NativePath.Area().getParams()['Accuracy']-1e-5)<1e-14
    extension=native_module();plan=json.loads((directory/'plan.json').read_text())
    assert len(plan['tools'])==1 and plan['tools'][0]['shankDiameter']==1
    spec=dict(plan['tools'][0]);spec['cuttingReach']=before
    assert hashlib.sha256(native.read_bytes()).hexdigest()==expected_sha
    doc=A.openDocument(str(native))
    try:
        tool=doc.getObject(spec['nativeTool']);job=doc.getObject('Machining')
        assert type(tool.Proxy) is extension.SCXReducedTool and type(tool.Proxy).__module__==MODULE
        assert tool.CuttingEdgeHeight.Value==before and tool.SchemaxisCuttingReach.Value==before
        assert [o.Name for o in job.Operations.Group]==list(operation_names(plan).values())
        assert len(job.Tools.Group)==1 and job.Tools.Group[0].Tool is tool
        initial=physical(tool,spec)
        if changed is not None:
            tool.CuttingEdgeHeight=changed;tool.SchemaxisCuttingReach=changed
            spec['cuttingReach']=changed
        for item in job.Operations.Group:item.touch()
        doc.recompute();observed=physical(tool,spec);holder_readback(doc,spec)
        c=spec['cuttingReach'];r=1.;rs=.5;h=1.;length=16.
        volume=math.pi*(r*r*(c-2*h/3)+rs*rs*(length-c))
        moment=math.pi*(r*r*(c*c/2-h*h/4)+rs*rs*(length*length-c*c)/2)
        assert abs(tool.Shape.Volume-volume)<1e-7
        assert abs(tool.Shape.Solids[0].CenterOfMass.z-moment/volume)<1e-7
        for z,radius in ((.5,.5),(2,1),(c+.5,.5),(15,.5)):
            assert tool.Shape.isInside(A.Vector(radius-1e-4,0,z),1e-9,True)
            assert not tool.Shape.isInside(A.Vector(radius+1e-4,0,z),1e-9,True)
        assert job.PostProcessorArgs==POST_ARGS
        program=WrapperPost(job,str(Path(Job.__file__).parents[1]/'Post/scripts/linuxcnc_post.py'),'linuxcnc_post').export()
        assert len(program)==1 and 'G81' in program[0][1]
        if changed is not None:doc.save()
        G.activeDocument().activeView().viewAxonometric();G.activeDocument().activeView().fitAll()
        G.activeDocument().activeView().saveImage(str(directory/(stage+'.png')),960,720,'Current')
        (directory/(stage+'.ngc')).write_text(program[0][1])
        (directory/(stage+'.json')).write_text(json.dumps({'verified':True,'pid':os.getpid(),'before':before,'cuttingReach':c,'initial':initial,'physical':observed,'nativeSha256':hashlib.sha256(native.read_bytes()).hexdigest(),'programSha256':hashlib.sha256(program[0][1].encode()).hexdigest(),'privateSettings':str(settings),'display':os.environ['DISPLAY'],'userParameter':A.ConfigGet('UserParameter')}))
    finally:A.closeDocument(doc.Name)
