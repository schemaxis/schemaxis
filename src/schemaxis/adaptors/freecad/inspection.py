# Copyright (C) 2026 David L F Gaden
"""Native CAD topology inspection for explicit edge selection and diagnostics."""
import copy
import json
from pathlib import Path
from schemaxis.core.runners import Interpreter
from schemaxis.artifacts import atomic_json
from .process import SubprocessRunner
from schemaxis.errors import fail
from .adaptor import plan, run


def inspect(document,node,directory,*,executable=None,timeout=300,visit=0):
    prepared=plan(document)
    visits = prepared.get('visits') if prepared.get('version') == 'schemaxis.study.plan/1' else None
    if type(visit) is not int or not 0 <= visit < (len(visits) if visits else 1):
        fail('INVALID_SELECTION', 'choose an existing CAD analytic visit', visit=visit)
    if visits: prepared = visits[visit]['plan']
    nodes={n['id']:n for n in prepared['nodes']}
    if node not in nodes:fail('UNKNOWN_REFERENCE','CAD inspection node is absent',node)
    from .adaptor import DECLARATIONS
    if DECLARATIONS[nodes[node]['filter']]['kinds']!=['solid']:
        fail('TYPE_MISMATCH','CAD inspection currently requires a solid node',node)
    needed=set()
    def collect(identity):
        if identity in needed:return
        needed.add(identity)
        for source in nodes[identity]['inputs'].values():
            for dependency in source if isinstance(source,list) else [source]:collect(dependency)
    collect(node)
    # Planned import facts are recomputed from the authored options when the pruned document is planned.
    reduced={'version':'schemaxis.freecad/1','units':'mm','nodes':[{k:v for k,v in n.items() if k not in ('source','frame')}
                                                                   for n in prepared['nodes'] if n['id'] in needed],
             'output':node,'linearDeflection':prepared['linearDeflection']}
    # Resolved options contain driven current values. Restore the authored
    # binding boundary when planning the pruned document, retaining only drivers
    # used by this dependency closure.
    if 'parameters' in prepared:
        reduced['nodes']=copy.deepcopy(reduced['nodes']);used=set()
        for item in reduced['nodes']:
            for option,binding in item.get('drive',{}).items():
                item['options'].pop(option,None);used.update(binding['terms'])
        if used:reduced['parameters']={key:copy.deepcopy(prepared['parameters'][key]) for key in sorted(used)}
    run(reduced,directory,executable=executable,timeout=timeout)
    directory=Path(directory).absolute()
    atomic_json(directory/'inspection-request.json',{'node':node,'authored':document,'visit':visit})
    import os
    runtime=Interpreter('freecad',str(Path(executable or os.environ['FREECAD_CMD']).resolve()))
    runner=SubprocessRunner(runtime,directory,timeout=timeout,environment={'QT_QPA_PLATFORM':'offscreen'})
    report=runner(f'import sys\nsys.path.insert(0,{str(directory/"runtime.zip")!r})\n'
                  'from schemaxis.adaptors.freecad.inspection import inspect_native\n'
                  'from schemaxis.native_boundary import execute_guarded\n'
                  f'execute_guarded(inspect_native,{str(directory)!r})\n')
    atomic_json(directory/'inspection-submission.json',report.to_dict())
    if (directory/'native-fault.json').exists():fail('NATIVE_EXECUTION_FAILED','native CAD inspection failed',str(directory))
    return json.loads((directory/'inspection.json').read_text())


def inspect_native(directory):
    import FreeCAD as App
    from .native import bounds, snapshot
    directory=Path(directory)
    prepared=json.loads((directory/'plan.json').read_text())
    doc=App.openDocument(str(directory/'model.FCStd'))
    from .operations import output_names
    obj=doc.getObject(output_names(prepared)[prepared['output']])
    shape=obj.Shape
    if len(shape.Edges)>10000 or len(shape.Faces)>10000:fail('RESOURCE_BUDGET_EXCEEDED','CAD topology inspection exceeds 10000 edges/faces')
    from .selections import native_edges
    edges=native_edges(shape)
    faces=[{'index':i+1,'areaMM2':f.Area,'centreMM':list(f.CenterOfMass),'boundsMM':bounds(f.optimalBoundingBox(False,False)),
            'surface':type(f.Surface).__name__} for i,f in enumerate(shape.Faces)]
    request=json.loads((directory/'inspection-request.json').read_text())
    atomic_json(directory/'inspection.json',{'verified':True,'node':obj.Label,'visit':request.get('visit',0),'units':'mm','shape':snapshot(shape),'edges':edges,'faces':faces,
        'selectionScope':'one-based edge indices belong to this exact topology; regenerate inspection after upstream edits'})
    App.closeDocument(doc.Name)
