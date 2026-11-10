# Copyright (C) 2026 David L F Gaden
"""Native workers for sourced assemblies; imported only inside FreeCAD's interpreter.

The workers only observe and record. The host judges every receipt against the
analytic plan, the producer receipts and the captured copies.
"""
import json
import os
from pathlib import Path

from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from .assembly_sources import labels, mount_expressions, visibility, proxies
from .source_bridge import requires_copy_regeneration


def runtime():
    import FreeCAD as App
    import Part  # noqa: F401
    import PartDesign  # noqa: F401
    import AssemblyApp  # noqa: F401
    import JointObject
    if App.Version()[:2] != ['1', '1']:
        fail('UNSUPPORTED_RUNTIME', 'Native assemblies are qualified for FreeCAD 1.1.x')
    return App, JointObject


def require(condition, message, **detail):
    if not condition:
        fail('ASSEMBLY_VERIFICATION_FAILED', message, **detail)


def load(directory):
    from .assembly import plan
    directory = Path(directory)
    authored=json.loads((directory/'authored.json').read_text());saved=json.loads((directory/'plan.json').read_text())
    from .source_bridge import replay_plan
    prepared = replay_plan(directory,authored,saved)
    require(json.loads((directory/'plan.json').read_text()) == prepared, 'Saved plan differs from authored input')
    require(prepared.get('sourced') is True, 'Not a sourced assembly plan')
    return directory, prepared


def matrix(placement):
    return [float(v) for v in placement.toMatrix().A]


def shape_record(shape):
    box = shape.optimalBoundingBox(False, False)
    solids = shape.Solids
    return {'valid': bool(shape.isValid()), 'solids': len(solids), 'volume': shape.Volume, 'area': shape.Area,
            'bounds': [box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax],
            'centreOfMass': [float(v) for v in solids[0].CenterOfMass] if len(solids) == 1 else None}


HISTORY_SHAPES = ('Shape', 'AddSubShape', 'SuppressedShape', 'InternalShape')


HISTORY_ELEMENTS = 20000


def history_record(shape):
    """Topology counts, measures and full vertex/face/edge descriptors of one history shape."""
    if shape.isNull():
        return None
    box = shape.BoundBox
    require(len(shape.Vertexes) + len(shape.Faces) + len(shape.Edges) <= HISTORY_ELEMENTS,
            'History shape exceeds the bounded capture description')
    return {'type': shape.ShapeType, 'valid': bool(shape.isValid()),
            'vertices': sorted([float(c) for c in v.Point] for v in shape.Vertexes),
            'faces': sorted([f.Surface.__class__.__name__, f.Area] for f in shape.Faces),
            'edges': sorted([e.Curve.__class__.__name__, e.Length] for e in shape.Edges),
            'counts': [len(shape.Solids), len(shape.Shells), len(shape.Faces), len(shape.Wires),
                       len(shape.Edges), len(shape.Vertexes)],
            'volume': shape.Volume, 'area': shape.Area, 'length': shape.Length,
            'bounds': [box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax],
            'centreOfMass': [float(v) for v in shape.Solids[0].CenterOfMass] if len(shape.Solids) == 1 else None}


def history(doc):
    return {o.Name+'.'+prop: history_record(getattr(o, prop)) for o in doc.Objects
            for prop in HISTORY_SHAPES if prop in o.PropertiesList}


def ordered_history(doc,mapping):
    """Capture every indexed history element and each actual subelement consumer.

    Persistent names may regenerate; an EdgeN/FaceN selection must still resolve
    to the same indexed geometry. Keep ordering here, unlike the shape-level
    recompute oracle's unordered vertex and face/edge inventories.
    """
    back={new:old for old,new in mapping.items()};shapes={};references={}
    for old,new in mapping.items():
        obj=doc.getObject(new)
        for prop in HISTORY_SHAPES:
            if prop not in obj.PropertiesList:continue
            shape=getattr(obj,prop)
            shapes[old+'.'+prop]=None if shape.isNull() else {
                kind:[ordered_record(element) for element in getattr(shape,native)]
                for kind,native in [('faces','Faces'),('edges','Edges'),('vertices','Vertexes')]}
        for prop in obj.PropertiesList:
            kind=obj.getTypeIdOfProperty(prop)
            if kind not in ('App::PropertyLinkSub','App::PropertyLinkSubList'):continue
            value=getattr(obj,prop)
            links=([value] if value and value[0] else []) if kind=='App::PropertyLinkSub' else value
            entries=[]
            for target,subs in links:
                require(target is not None and target.Document==doc and target.Name in back,
                        'History subelement reference escapes its copied source',object=old,property=prop)
                for sub in subs:
                    if not sub:continue
                    element=target.getSubObject(sub)
                    require(element is not None and not element.isNull(),'History subelement is unresolved',object=old,property=prop)
                    entries.append({'target':back[target.Name],'sub':sub,'shape':ordered_record(element)})
            references[old+'.'+prop]=entries
    return {'shapes':shapes,'references':references}


def ordered_record(shape):
    """Current source/copy geometry: enclosed material and finite orientation.

    OCCT's default VolumeProperties also integrates open faces, where a result
    is not enclosed material and can carry cancellation noise. Keep the old
    shape-level receipt format unchanged; this record is freshly measured on
    both sides of every current regeneration, never supplied by a receipt.
    """
    result=history_record(shape)
    if result is None:return None
    result['volume']=sum(solid.Volume for solid in shape.Solids)
    result['orientation']=str(shape.Orientation)
    require(result['orientation'] in ('Forward','Reversed','Internal','External'),'Unknown native history orientation')
    return result


def capture(directory):
    """Measure each retained source copy alone, then prove its stored history by recompute."""
    App, _ = runtime()
    directory, prepared = load(directory)
    parts = {}
    for part in prepared['parts']:
        doc = App.openDocument(str(directory/prepared['native']['retained'][part['id']]))
        try:
            body = doc.getObject(part['source']['body'])
            require(body is not None and body.TypeId == 'PartDesign::Body', 'Captured source Body is absent', part=part['id'])
            # Measure the saved producer state as found; no recompute.
            require(not [o.Name for o in doc.Objects if any(s in o.State for s in ('Invalid', 'Error', 'Touched'))],
                    'Captured source opens invalid or out of date', part=part['id'])
            stored = history(doc)
            ordered=ordered_history(doc,{o.Name:o.Name for o in doc.Objects}) if requires_copy_regeneration(part['source']) else None
            from .body_seed_native import local_shape
            record = {'objects': dict(sorted((o.Name, o.TypeId) for o in doc.Objects)),
                      'tip': body.Tip.Name if body.Tip else None, 'shape': shape_record(local_shape(body))}
            # Every stored history payload must be what the feature history reproduces.
            for obj in doc.Objects:
                obj.touch()
            doc.recompute()
            record['recomputeStates'] = {o.Name: list(o.State) for o in doc.Objects
                                         if any(s in o.State for s in ('Invalid', 'Error', 'Touched'))}
            record['history'] = {'stored': stored, 'recomputed': history(doc)}
            if ordered is not None:record['orderedHistory']=ordered
            parts[part['id']] = record
        finally:
            App.closeDocument(doc.Name)
    atomic_json(directory/'capture.json', {'stage': 'capture', 'pid': os.getpid(), 'runtime': App.Version(),
                                           'definition': prepared, 'parts': parts})


def snapshot(doc, prepared, renames):
    """Record native state as found; never recomputes or solves."""
    App, _ = runtime()
    native = prepared['native']
    parts = {p['id']: p for p in prepared['parts']}
    out = {'documents': sorted(App.listDocuments()),
           'badStates': {o.Name: list(o.State) for o in doc.Objects if any(s in o.State for s in ('Invalid', 'Error'))},
           'externalLinks': sorted({o.Name+'->'+x.Document.Name+'#'+x.Name for o in doc.Objects for x in o.OutList if x.Document != doc}),
           'proxies': {o.Name: type(o.Proxy).__name__ for o in doc.Objects
                       if o.TypeId == 'App::FeaturePython' or getattr(o, 'Proxy', None) is not None},
           'components': {}, 'mounts': {}, 'joints': {}, 'sources': {}}
    for identity, name in native['components'].items():
        link = doc.getObject(name)
        out['components'][identity] = {'name': link.Name, 'label': link.Label, 'linked': link.LinkedObject.Name,
            'linkTransform': bool(link.LinkTransform), 'matrix': matrix(link.Placement), 'shape': shape_record(link.Shape)}
    for key, name in native['mounts'].items():
        datum = doc.getObject(name)
        bodies = [x.Name for x in datum.InList if x.TypeId == 'PartDesign::Body']
        out['mounts'][key] = {'name': datum.Name, 'label': datum.Label, 'body': bodies[0] if len(bodies) == 1 else bodies,
            'mapMode': str(datum.MapMode), 'support': [[s[0].Name, list(s[1])] for s in datum.AttachmentSupport],
            'matrix': matrix(datum.Placement), 'expressions': [[str(k), str(v)] for k, v in datum.ExpressionEngine]}
    for identity, name in native['joints'].items():
        joint = doc.getObject(name)
        out['joints'][identity] = {'name': joint.Name, 'label': joint.Label, 'jointType': str(joint.JointType),
            'suppressed': bool(joint.Suppressed), 'detach': [bool(joint.Detach1), bool(joint.Detach2)],
            'reference1': [joint.Reference1[0].Name, list(joint.Reference1[1])],
            'reference2': [joint.Reference2[0].Name, list(joint.Reference2[1])],
            'offset1': matrix(joint.Offset1), 'offset2': matrix(joint.Offset2),
            'placement1': matrix(joint.Placement1), 'placement2': matrix(joint.Placement2)}
    out['ground'] = {'object': doc.getObject('Ground').ObjectToGround.Name}
    for part_id, mapped in renames.items():
        facts = parts[part_id]['source']
        body = doc.getObject(mapped[facts['body']])
        varset = doc.getObject(mapped[facts['varset']]) if facts['varset'] else None
        out['sources'][part_id] = {'tip': body.Tip.Name if body.Tip else None, 'tipVolume': body.Shape.Volume,
            'parameters': ({'dim_'+p:float(getattr(varset,'dim_'+p).Value) for p in facts['parameters']}
                           if 'spreadsheet' in facts else {p: float(getattr(varset, p).Value) for p in varset.PropertiesList if p.startswith('dim_')}) if varset else {}}
    return out


def solve_probe(doc, prepared):
    """Displace and turn every ungrounded component; only the compiled solver restores it."""
    App, _ = runtime()
    native = prepared['native']
    before = {c: matrix(doc.getObject(n).Placement) for c, n in native['components'].items()}
    displaced = []
    for index, (identity, name) in enumerate(native['components'].items(), 1):
        if identity == prepared['grounded']:
            continue
        obj = doc.getObject(name)
        p = obj.Placement
        p.Base = p.Base+App.Vector(3+index, -4-index, 2+index)
        p.Rotation = App.Rotation(App.Vector(1, 1, 0), 11).multiply(App.Rotation(App.Vector(0, 0, 1), 7)).multiply(p.Rotation)
        obj.Placement = p
        displaced.append(identity)
    perturbed = {c: matrix(doc.getObject(n).Placement) for c, n in native['components'].items()}
    # No recompute or connector presolve between the perturbation and the solve.
    code = doc.getObject('Assembly').solve()
    after = {c: matrix(doc.getObject(n).Placement) for c, n in native['components'].items()}
    return {'returnCode': code, 'displaced': displaced, 'before': before, 'perturbed': perturbed, 'after': after}


def build(directory):
    App, JointObject = runtime()
    directory, prepared = load(directory)
    native = prepared['native']
    doc = App.newDocument('SchemaxisAssembly')
    try:
        renames = {}
        for index,part in enumerate(prepared['parts']):
            path=directory/native['retained'][part['id']]
            from .source_assets_native import stage_copies
            stage_copies(directory,path,part,index)
            source = App.openDocument(str(path))
            try:
                objects = list(source.Objects)
                require({o.Name: o.TypeId for o in objects} == part['source']['objects'], 'Captured source membership differs', part=part['id'])
                # One public embedding path: copy the complete source, inputs in order.
                copies = doc.copyObject(objects, False, False)
                require(len(copies) == len(objects), 'Source copy is incomplete', part=part['id'])
                renames[part['id']] = {s.Name: c.Name for s, c in zip(objects, copies)}
            finally:
                App.closeDocument(source.Name)
            from .source_assets_native import attach_copies
            attach_copies(directory,doc,part,index,renames[part['id']])
            own = set(renames[part['id']].values())
            for name in own:
                require(all(x.Document == doc and x.Name in own for x in doc.getObject(name).OutList),
                        'Embedded source refers outside itself', part=part['id'], object=name)
        names = labels(prepared, renames)
        copied = {n for mapped in renames.values() for n in mapped.values()}
        for name, label in names.items():
            if name in copied:
                doc.getObject(name).Label = label
        doc.recompute()
        copied_history={p['id']:ordered_history(doc,renames[p['id']]) for p in prepared['parts']
                        if requires_copy_regeneration(p['source'])}
        bodies = {}
        for part in prepared['parts']:
            facts, mapped = part['source'], renames[part['id']]
            body = doc.getObject(mapped[facts['body']])
            require(body.Tip is not None and body.Tip.Name == mapped[facts['tip']], 'Embedded Body tip differs', part=part['id'])
            bodies[part['id']] = body
            xy = doc.getObject(mapped[facts['xyPlane']])
            varset = mapped[facts['varset']] if facts['varset'] else None
            for mount in part['mounts']:
                key = part['id']+'.'+mount['id']
                datum = body.newObject('PartDesign::CoordinateSystem', native['mounts'][key])
                require(datum.Name == native['mounts'][key], 'Mount native name is unavailable', mount=key)
                datum.Label = key
                datum.AttachmentSupport = [(xy, '')]
                datum.MapMode = 'ObjectXY'
                r = mount['rotation']
                rotation = App.Placement(App.Matrix(r[0][0], r[0][1], r[0][2], 0, r[1][0], r[1][1], r[1][2], 0,
                                                    r[2][0], r[2][1], r[2][2], 0, 0, 0, 0, 1)).Rotation
                datum.AttachmentOffset = App.Placement(App.Vector(*mount['value']), rotation)
                for path, text in mount_expressions(part, mount, varset).items():
                    datum.setExpression(path, text)
            require(body.Tip.Name == renames[part['id']][facts['tip']], 'Mounts changed the Body tip', part=part['id'])
        doc.recompute()
        assembly = doc.addObject('Assembly::AssemblyObject', 'Assembly')
        require(assembly.Name == 'Assembly', 'Assembly native name is unavailable')
        assembly.Type = 'Assembly'
        group = assembly.newObject('Assembly::JointGroup', 'Joints')
        components = {}
        for component in prepared['components']:
            link = assembly.newObject('App::Link', native['components'][component['id']])
            require(link.Name == native['components'][component['id']], 'Component native name is unavailable')
            link.setLink(bodies[component['part']])
            link.Label = component['id']
            link.LinkTransform = False
            link.Placement = App.Placement(App.Vector(*component['position']), App.Rotation(App.Vector(0, 0, 1), component['rotation']))
            components[component['id']] = link
        for part in prepared['parts']:
            bodies[part['id']].Visibility = False
        doc.recompute()
        ground = group.newObject('App::FeaturePython', 'Ground')
        JointObject.GroundedJoint(ground, components[prepared['grounded']])
        part_of = {c['id']: c['part'] for c in prepared['components']}
        for joint in prepared['joints']:
            obj = group.newObject('App::FeaturePython', native['joints'][joint['id']])
            require(obj.Name == native['joints'][joint['id']], 'Joint native name is unavailable')
            JointObject.Joint(obj, JointObject.JointTypes.index('Fixed'))
            obj.Label = joint['id']
            # Authored translation and clocking belong to the parent connector.
            obj.Offset1 = App.Placement(App.Vector(*joint['offset']), App.Rotation(App.Vector(0, 0, 1), joint['clocking']))
            refs = []
            for end in ('parent', 'child'):
                datum = native['mounts'][part_of[joint[end]['component']]+'.'+joint[end]['mount']]
                refs.append([components[joint[end]['component']], [datum+'.', datum+'.']])
            # Choose the coincident-frame branch before the interactive
            # presolver chooses the nearest parallel/antiparallel solution.
            # This uses actual native datums; the host's independent oracle
            # still checks every pose, and solve_probe subsequently perturbs
            # all movable links without another presolve or analytic reset.
            parent,child=joint['parent'],joint['child']
            parent_datum=doc.getObject(native['mounts'][part_of[parent['component']]+'.'+parent['mount']])
            child_datum=doc.getObject(native['mounts'][part_of[child['component']]+'.'+child['mount']])
            components[child['component']].Placement=(components[parent['component']].Placement
                .multiply(parent_datum.Placement).multiply(obj.Offset1).multiply(child_datum.Placement.inverse()))
            obj.Proxy.setJointConnectors(obj, refs)
        doc.recompute()
        require(assembly.solve() == 0, 'Initial native assembly solve failed')
        initial = snapshot(doc, prepared, renames)
        solver = solve_probe(doc, prepared)
        doc.recompute()
        solved = snapshot(doc, prepared, renames)
        doc.saveAs(str(directory/'model.FCStd'))
        objects = [o.Name for o in doc.Objects]
    finally:
        App.closeDocument(doc.Name)
    from .gui_state import persist
    persist(directory/'model.FCStd', visibility(prepared, objects, renames), proxies(prepared))
    atomic_json(directory/'built.json', {'stage': 'build', 'pid': os.getpid(), 'runtime': App.Version(), 'definition': prepared,
        'renames': renames, 'snapshots': {'initial': initial, 'solved': solved}, 'solver': solver,
        'copiedHistory':copied_history})


def _reopen(path, prepared, renames):
    """Inspect saved state before any recompute or solve, then prove the solver."""
    App, _ = runtime()
    doc = App.openDocument(str(path))
    try:
        persisted = snapshot(doc, prepared, renames)
        solver = solve_probe(doc, prepared)
        doc.recompute()
        solved = snapshot(doc, prepared, renames)
    finally:
        App.closeDocument(doc.Name)
    return {'persisted': persisted, 'solved': solved}, solver


def reopen(directory):
    import hashlib
    App, _ = runtime()
    directory, prepared = load(directory)
    renames = json.loads((directory/'built.json').read_text())['renames']
    path = directory/'model.FCStd'
    snapshots, solver = _reopen(path, prepared, renames)
    solved = snapshots['solved']['components']
    artifact = {'file': str(path), 'kind': 'cadScene', 'units': 'mm', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'spatial': {'state': 'known', 'frame': 'native-world', 'units': 'mm',
            'components': [{'id': c['id'], 'part': c['part'], 'position': [solved[c['id']]['matrix'][i] for i in (3, 7, 11)],
                            'xAxis': [solved[c['id']]['matrix'][i] for i in (0, 4, 8)],
                            'zAxis': [solved[c['id']]['matrix'][i] for i in (2, 6, 10)],
                            'bounds': solved[c['id']]['shape']['bounds'], 'volume': solved[c['id']]['shape']['volume'],
                            'nativeName': solved[c['id']]['name'], 'linkedNativeName': solved[c['id']]['linked']}
                           for c in prepared['components']],
            'componentBoundsOrder': ['xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'],
            'placementConvention': {'axisVectorsFrame': 'native-world', 'translationField': 'position', 'translationUnits': 'mm',
                'composition': 'world = position + local.x*xAxis + local.y*(zAxis cross xAxis) + local.z*zAxis'},
            'coordinateRepresentation': 'native assembly placements retained in FCStd'}}
    atomic_json(directory/'verification.json', {'stage': 'reopen', 'pid': os.getpid(), 'runtime': App.Version(),
        'definition': prepared, 'renames': renames, 'snapshots': snapshots, 'solver': solver,
        'artifact': artifact, 'artifacts': [artifact]})


# ---- Qualification-only stages. They are not reachable from authored input.

def load_saved(directory):
    """Qualification stages use the verified saved plan, so producers may be absent."""
    directory = Path(directory)
    prepared = json.loads((directory/'plan.json').read_text())
    require(prepared.get('sourced') is True, 'Not a sourced assembly plan')
    return directory, prepared


def edit_probe(directory):
    """Edit one embedded source parameter in a copy; recompute must re-solve the assembly."""
    App, _ = runtime()
    directory, prepared = load_saved(directory)
    request = json.loads((directory/'edit-request.json').read_text())
    renames = json.loads((directory/'built.json').read_text())['renames']
    doc = App.openDocument(str(directory/'model.FCStd'))
    try:
        part = next(p for p in prepared['parts'] if p['id'] == request['part'])
        varset = doc.getObject(renames[part['id']][part['source']['varset']])
        before = snapshot(doc, prepared, renames)
        if 'spreadsheet' in part['source']:
            table=part['source']['spreadsheet']
            require(request['parameter'] in table['inputs'],'Only independent spreadsheet cells can be edited')
            varset.set(table['cells'][request['parameter']],format(request['value'],'.17g')+' mm')
        else:
            setattr(varset, 'dim_'+request['parameter'], request['value'])
        doc.recompute()
        recomputed = snapshot(doc, prepared, renames)
        code = doc.getObject('Assembly').solve()
        solved = snapshot(doc, prepared, renames)
        solver = solve_probe(doc, prepared)
        doc.recompute()
        probed = snapshot(doc, prepared, renames)
        doc.saveAs(str(directory/request['output']))
        objects = [o.Name for o in doc.Objects]
    finally:
        App.closeDocument(doc.Name)
    from .gui_state import persist
    persist(directory/request['output'], visibility(prepared, objects, renames), proxies(prepared))
    atomic_json(directory/'edit.json', {'stage': 'edit', 'pid': os.getpid(), 'request': request, 'renames': renames,
        'snapshots': {'before': before, 'recomputed': recomputed, 'solved': solved, 'probed': probed},
        'solveReturnCode': code, 'solver': solver})


def inspect_copy(directory):
    """Open a named FCStd (an edited or relocated copy) in a fresh process."""
    App, _ = runtime()
    directory, prepared = load_saved(directory)
    request = json.loads((directory/'inspect-request.json').read_text())
    renames = json.loads((directory/'built.json').read_text())['renames']
    snapshots, solver = _reopen(Path(request['file']), prepared, renames)
    atomic_json(directory/request['receipt'], {'stage': 'inspect', 'pid': os.getpid(), 'request': request,
        'snapshots': snapshots, 'solver': solver})
