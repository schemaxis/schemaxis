# Copyright (C) 2026 David L F Gaden
"""Qualify dimensional Sketcher profiles via full CAD build and fresh reopening."""
import argparse
import math
from pathlib import Path
from schemaxis.adaptors.freecad.adaptor import run
from schemaxis.artifacts import atomic_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--freecad',required=True)
    parser.add_argument('--output-directory',required=True,type=Path)
    args=parser.parse_args()
    root=args.output_directory.absolute()
    root.mkdir(parents=True,exist_ok=False)
    results={}
    for operation,options,expected in (
        ('rectangle',{'width':80,'height':50},80*50*6),
        ('circle',{'radius':5},math.pi*25*6)):
        document={'version':'schemaxis.freecad/1','nodes':[
            {'id':'profile','filter':operation,'options':options},
            {'id':'solid','filter':'extrude','inputs':{'profile':'profile'},'options':{'length':6}}],
            'output':'solid'}
        result=run(document,root/operation,executable=args.freecad)
        import json
        receipt=json.loads((root/operation/'verification.json').read_text())
        actual=receipt['native']['volume']
        if not math.isclose(actual,expected,rel_tol=1e-8):
            raise AssertionError((operation,actual,expected))
        results[operation]={'verified':result['verified'],'volume':actual,'expectedVolume':expected,
                            'fullyConstrainedReadback':True,'directory':str(root/operation)}
    from schemaxis.core.runners import Interpreter
    from schemaxis.dispatch import SubprocessRunner
    runner=SubprocessRunner(Interpreter('freecad',args.freecad),root,
                            environment={'QT_QPA_PLATFORM':'offscreen'})
    source=("import FreeCAD as App\nimport json\n"
            "doc=App.openDocument("+repr(str(root/'rectangle'/'model.FCStd'))+")\n"
            "sketch=doc.getObject('N0')\n"
            "index=next(i for i,c in enumerate(sketch.Constraints) if c.Name=='width')\n"
            "sketch.setDatum(index,App.Units.Quantity('90 mm'))\n"
            "doc.recompute()\n"
            "assert sketch.FullyConstrained\n"
            "assert abs(sketch.Geometry[0].StartPoint.x+45)<1e-7\n"
            "assert abs(doc.getObject('N1').Shape.Volume-27000)<1e-6\n"
            "with open("+repr(str(root/'native-edit.json'))+",'w') as stream:\n"
            "    json.dump({'width':90,'centred':True,'volume':doc.getObject('N1').Shape.Volume},stream)\n"
            "App.closeDocument(doc.Name)\n")
    runner(source)
    # FreeCADCmd may exit zero after exceptions: require the independent result.
    results['nativeDimensionEdit']=json.loads((root/'native-edit.json').read_text())
    atomic_json(root/'qualification.json',results)
    print(results)


if __name__=='__main__':
    main()
