"""Inspect an actual carried launcher after host admission and private staging."""
import hashlib
import json
import os
from pathlib import Path
import sys


def edit(directory,stage,expected_sha):
    import FreeCAD as A,FreeCADGui as G
    from Path import Preferences
    from schemaxis.adaptors.freecad.cam_reduced import FILENAME,LAUNCHER_NAME,LAUNCHER,MODULE,module_bytes
    from schemaxis.adaptors.freecad.cam_pointed_native import physical,holder_readback
    if stage!='portable-launcher':raise ValueError('Unknown finite portable inspection')
    directory=Path(directory);native=directory/'machining.FCStd'
    assert hashlib.sha256(native.read_bytes()).hexdigest()==expected_sha
    assert (directory/FILENAME).read_bytes()==module_bytes() and (directory/LAUNCHER_NAME).read_bytes()==LAUNCHER
    settings=directory/(stage+'-settings')
    assert all(Path(os.environ[k]).resolve().is_relative_to(settings.resolve()) for k in ('FREECAD_USER_HOME','FREECAD_USER_DATA','FREECAD_USER_TEMP','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','XDG_RUNTIME_DIR'))
    assert Path(A.getUserAppDataDir()).resolve().is_relative_to(settings.resolve())
    assert Path(A.ConfigGet('UserParameter')).resolve()==(directory/'preferences.cfg').resolve()
    assert Preferences.getAssetPath().resolve()==(directory/'cam-assets').resolve()
    assert abs(Preferences.defaultLibAreaCurveAccuracy()-1e-5)<1e-14
    extension=sys.modules[MODULE]
    assert Path(extension.__file__).resolve()==(directory/FILENAME).resolve()
    doc=A.ActiveDocument
    assert doc is not None and Path(doc.FileName).resolve()==native.resolve(),'Carried launcher did not open its native document'
    try:
        p=json.loads((directory/'plan.json').read_text());spec=p['tools'][0];tool=doc.getObject(spec['nativeTool'])
        assert type(tool.Proxy) is extension.SCXReducedTool
        result=physical(tool,spec);holder_readback(doc,spec)
        for op in doc.getObject('Machining').Operations.Group:op.touch()
        doc.recompute();physical(tool,spec)
        G.activeDocument().activeView().viewAxonometric();G.activeDocument().activeView().fitAll()
        G.activeDocument().activeView().saveImage(str(directory/(stage+'.png')),960,720,'Current')
        assert hashlib.sha256(native.read_bytes()).hexdigest()==expected_sha
        assert (directory/FILENAME).read_bytes()==module_bytes()
        (directory/(stage+'.json')).write_text(json.dumps({'verified':True,'nativeSha256':expected_sha,'moduleSha256':hashlib.sha256(module_bytes()).hexdigest(),'actualCarriedLauncher':True,'actualBundledModule':extension.__file__,'physical':result,'privateSettings':str(settings),'pid':os.getpid()}))
    finally:A.closeDocument(doc.Name)
