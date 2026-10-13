"""Trusted built-in Assembly workers; native imports remain process-local."""
import hashlib
import json
import math
import os
from pathlib import Path

from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from .adaptor import close
from .assembly import face_centre, plan


def runtime():
    import FreeCAD as App
    import Part
    import AssemblyApp
    import JointObject
    if App.Version()[:2] != ['1', '1']:
        fail('UNSUPPORTED_RUNTIME', 'Native assemblies are qualified for FreeCAD 1.1.x')
    return App, JointObject


def require(condition, message):
    if not condition:
        fail('ASSEMBLY_VERIFICATION_FAILED', message)


def load(directory):
    directory = Path(directory)
    prepared = plan(json.loads((directory/'authored.json').read_text()))
    require(json.loads((directory/'plan.json').read_text()) == prepared, 'Saved plan differs from authored input')
    return directory, prepared


def members(doc, prepared):
    assembly = doc.getObject('Assembly')
    require(assembly is not None and assembly.TypeId == 'Assembly::AssemblyObject' and assembly.Type == 'Assembly',
            'Missing native assembly')
    group = doc.getObject('Joints')
    require(group is not None and group.TypeId == 'Assembly::JointGroup' and group in assembly.Group,
            'Missing native joint group')
    parts = {p['id']: doc.getObject('Part'+str(i)) for i, p in enumerate(prepared['parts'])}
    components = {c['id']: doc.getObject('Component'+str(i)) for i, c in enumerate(prepared['components'])}
    joints = {j['id']: doc.getObject('Joint'+str(i)) for i, j in enumerate(prepared['joints'])}
    require(all(o is not None for objects in (parts, components, joints) for o in objects.values()), 'Missing native member')
    require(set(group.Group) == {doc.getObject('Ground'), *joints.values()}, 'Native joint group membership differs')
    # Assembly's group extension also exposes the JointGroup's children.
    require(set(assembly.Group) == {group, *components.values(), *group.Group}, 'Native assembly component membership differs')
    return assembly, group, parts, components, joints


def named_face(source, part, face_name):
    """Match primitive caps analytically rather than assuming FaceN ordering."""
    import Part
    target = face_centre(part, face_name)
    matches = [(index, face) for index, face in enumerate(source.Shape.Faces, 1)
               if isinstance(face.Surface, Part.Plane) and close(list(face.CenterOfMass), target)]
    require(len(matches) == 1, 'Named planar cap is absent or ambiguous')
    return 'Face'+str(matches[0][0])


def placement(obj):
    App, _ = runtime()
    p = obj.Placement
    return {'position': list(p.Base), 'xAxis': list(p.Rotation.multVec(App.Vector(1, 0, 0))),
            'zAxis': list(p.Rotation.multVec(App.Vector(0, 0, 1)))}


def expected_placements(components, prepared):
    for identity, obj in components.items():
        observed = placement(obj)
        for field in ('position', 'xAxis', 'zAxis'):
            require(close(observed[field], prepared['expected'][identity][field]), 'Analytic '+field+' differs for '+identity)


def solve_probe(doc, assembly, components, prepared):
    """Perturb every ungrounded body; only the compiled solver restores poses."""
    App, _ = runtime()
    before = {identity: placement(obj) for identity, obj in components.items()}
    displaced = []
    for index, (identity, obj) in enumerate(components.items(), 1):
        if identity == prepared['grounded']:
            continue
        p = obj.Placement
        p.Base = p.Base+App.Vector(2+index, -3-index, 1+index)
        p.Rotation = App.Rotation(App.Vector(0, 0, 1), 7).multiply(p.Rotation)
        obj.Placement = p
        displaced.append(identity)
    perturbed = {identity: placement(obj) for identity, obj in components.items()}
    require(all(not close(perturbed[c]['position'], before[c]['position']) for c in displaced), 'Perturbation was not applied')
    # Do not recompute or call connector presolve between perturbation and solve.
    result = assembly.solve()
    require(type(result) is int and result == 0, 'Native assembly.solve failed with code '+str(result))
    expected_placements(components, prepared)
    solved = {identity: placement(obj) for identity, obj in components.items()}
    doc.recompute()
    return {'returnCode': result, 'displaced': True, 'restored': True, 'displacedComponents': displaced,
            'before': before, 'perturbed': perturbed, 'after': solved}


def snapshot(doc, prepared, stage, solver):
    App, JointObject = runtime()
    assembly, group, parts, components, joints = members(doc, prepared)
    require(close(list(assembly.Placement.Base), [0, 0, 0]) and close(list(assembly.Placement.Rotation.Q), [0, 0, 0, 1]),
            'Assembly root placement must remain identity')
    ground = doc.getObject('Ground')
    require(isinstance(ground.Proxy, JointObject.GroundedJoint) and ground.ObjectToGround == components[prepared['grounded']],
            'Grounded joint does not point at declared root')
    observed_parts = []
    for declared in prepared['parts']:
        obj = parts[declared['id']]
        require(obj.TypeId == {'box': 'Part::Box', 'cylinder': 'Part::Cylinder'}[declared['type']]
                and obj.Label == declared['id'], 'Part constructor or identity changed')
        require(close(list(obj.Placement.Base), [0, 0, 0]) and close(list(obj.Placement.Rotation.Q), [0, 0, 0, 1]),
                'Shared part definitions must stay at identity')
        options = {key: float(getattr(obj, key.title()).Value) for key in declared['options']}
        require(all(close(options[k], v) for k, v in declared['options'].items()), 'Native dimensions differ')
        observed_parts.append({'id': declared['id'], 'type': declared['type'], 'options': options})
    observed_components = []
    for declared in prepared['components']:
        obj = components[declared['id']]
        require(obj.TypeId == 'App::Link' and obj.LinkedObject == parts[declared['part']] and obj.Label == declared['id'],
                'Component is not a link to its declared source')
        require(obj.LinkTransform is False, 'Component link transform mode changed')
        shape = obj.Shape
        box = shape.optimalBoundingBox(False, False)
        observed_components.append({'id': declared['id'], 'part': declared['part'], 'type': obj.TypeId,
            **placement(obj), 'bounds': [box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax],
            'volume': shape.Volume, 'valid': bool(shape.isValid()), 'solids': len(shape.Solids),
            'nativeName': obj.Name, 'linkedNativeName': obj.LinkedObject.Name})
    component_definitions = {c['id']: c for c in prepared['components']}
    part_definitions = {p['id']: p for p in prepared['parts']}
    observed_joints = []
    for declared in prepared['joints']:
        obj = joints[declared['id']]
        require(isinstance(obj.Proxy, JointObject.Joint) and obj.Label == declared['id'], 'Missing installed native Joint proxy')
        for index, endpoint in enumerate(('parent', 'child'), 1):
            identity = declared[endpoint]['component']
            part = component_definitions[identity]['part']
            face = named_face(parts[part], part_definitions[part], declared[endpoint]['face'])
            reference = getattr(obj, 'Reference'+str(index))
            require(reference[0] == components[identity] and list(reference[1]) == [face, face], 'Native face reference differs')
            # Native cap connector convention must match independent analytics.
            connector = getattr(obj, 'Placement'+str(index))
            centre = face_centre(part_definitions[part], declared[endpoint]['face'])
            if index == 1:
                centre = [a+b for a, b in zip(centre, declared['offset'])]
            require(close(list(connector.Base), centre) and close(list(connector.Rotation.Q), [0, 0, 0, 1]),
                    'Native connector frame differs from planar contract')
        require(close(list(obj.Offset1.Base), declared['offset']) and close(list(obj.Offset1.Rotation.Q), [0, 0, 0, 1])
                and close(list(obj.Offset2.Base), [0, 0, 0]) and close(list(obj.Offset2.Rotation.Q), [0, 0, 0, 1]),
                'Native attachment offsets differ')
        a = components[declared['parent']['component']].Placement.multiply(obj.Placement1)
        b = components[declared['child']['component']].Placement.multiply(obj.Placement2)
        difference = a.inverse().multiply(b)
        observed_joints.append({**declared, 'nativeType': str(obj.JointType), 'suppressed': bool(obj.Suppressed),
            'detached': [bool(obj.Detach1), bool(obj.Detach2)], 'translationResidual': difference.Base.Length,
            'rotationResidual': abs(difference.Rotation.Angle),
            'nativeReferences': [list(obj.Reference1[1]), list(obj.Reference2[1])]})
    require(all(not any(s in obj.State for s in ('Invalid', 'Error')) for obj in doc.Objects), 'Invalid native object state')
    return {'stage': stage, 'pid': os.getpid(), 'runtime': App.Version(), 'definition': prepared,
        'assemblyType': assembly.TypeId, 'jointGroupType': group.TypeId, 'grounded': prepared['grounded'],
        'groundCount': sum(isinstance(o.Proxy, JointObject.GroundedJoint) for o in group.Group),
        'jointCount': len(joints), 'parts': observed_parts, 'components': observed_components,
        'joints': observed_joints, 'solver': solver}


def build(directory):
    App, JointObject = runtime()
    directory, prepared = load(directory)
    doc = App.newDocument('SchemaxisAssembly')
    try:
        assembly = doc.addObject('Assembly::AssemblyObject', 'Assembly')
        assembly.Type = 'Assembly'
        group = assembly.newObject('Assembly::JointGroup', 'Joints')
        parts, components = {}, {}
        for index, part in enumerate(prepared['parts']):
            obj = doc.addObject({'box': 'Part::Box', 'cylinder': 'Part::Cylinder'}[part['type']], 'Part'+str(index))
            obj.Label = part['id']
            for option, value in part['options'].items():
                setattr(obj, option.title(), value)
            parts[part['id']] = obj
        for index, component in enumerate(prepared['components']):
            obj = assembly.newObject('App::Link', 'Component'+str(index))
            obj.setLink(parts[component['part']])
            obj.Label = component['id']
            obj.LinkTransform = False
            obj.Placement = App.Placement(App.Vector(*component['position']), App.Rotation(App.Vector(0, 0, 1), component['rotation']))
            components[component['id']] = obj
        doc.recompute()
        ground = group.newObject('App::FeaturePython', 'Ground')
        JointObject.GroundedJoint(ground, components[prepared['grounded']])
        component_definitions = {c['id']: c for c in prepared['components']}
        part_definitions = {p['id']: p for p in prepared['parts']}
        for index, joint in enumerate(prepared['joints']):
            obj = group.newObject('App::FeaturePython', 'Joint'+str(index))
            JointObject.Joint(obj, JointObject.JointTypes.index('Fixed'))
            obj.Label = joint['id']
            obj.Offset1 = App.Placement(App.Vector(*joint['offset']), App.Rotation())
            refs = []
            for end in ('parent', 'child'):
                identity = joint[end]['component']
                part = component_definitions[identity]['part']
                face = named_face(parts[part], part_definitions[part], joint[end]['face'])
                refs.append([components[identity], [face, face]])
            obj.Proxy.setJointConnectors(obj, refs)
        doc.recompute()
        require(assembly.solve() == 0, 'Initial native assembly solve failed')
        expected_placements(components, prepared)
        solver = solve_probe(doc, assembly, components, prepared)
        receipt = snapshot(doc, prepared, 'build', solver)
        doc.saveAs(str(directory/'model.FCStd'))
        atomic_json(directory/'built.json', receipt)
    finally:
        App.closeDocument(doc.Name)


def reopen(directory):
    App, _ = runtime()
    directory, prepared = load(directory)
    doc = App.openDocument(str(directory/'model.FCStd'))
    try:
        assembly, group, parts, components, joints = members(doc, prepared)
        # Validate the persisted state BEFORE recompute/solve could repair it.
        expected_placements(components, prepared)
        snapshot(doc, prepared, 'reopen', {})
        solver = solve_probe(doc, assembly, components, prepared)
        receipt = snapshot(doc, prepared, 'reopen', solver)
        receipt['artifact'] = {'file': str(directory/'model.FCStd'), 'kind': 'cadScene', 'units': 'mm',
            'sha256': hashlib.sha256((directory/'model.FCStd').read_bytes()).hexdigest(),
            'spatial': {'state': 'known', 'frame': 'native-world', 'units': 'mm',
                        'components': receipt['components'],
                        'componentBoundsOrder': ['xmin','xmax','ymin','ymax','zmin','zmax'],
                        'placementConvention': {'axisVectorsFrame': 'native-world',
                            'translationField': 'position', 'translationUnits': 'mm',
                            'composition': 'world = position + local.x*xAxis + local.y*(zAxis cross xAxis) + local.z*zAxis'},
                        'coordinateRepresentation': 'native assembly placements retained in FCStd'}}
        receipt['artifacts'] = [receipt['artifact']]
        atomic_json(directory/'verification.json', receipt)
    finally:
        App.closeDocument(doc.Name)


def gui_finish(directory):
    """Attach the installed native joint editors and capture the assembly GUI."""
    App, JointObject = runtime()
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    directory, prepared = load(directory)
    Gui.activateWorkbench('AssemblyWorkbench')
    doc = App.openDocument(str(directory/'model.FCStd'))
    assembly, group, parts, components, joints = members(doc, prepared)
    assembly.ViewObject.Visibility = True
    for obj in parts.values():
        obj.ViewObject.Visibility = False
    for obj in components.values():
        obj.ViewObject.Visibility = True
    ground_view = doc.getObject('Ground').ViewObject
    ground_provider = JointObject.ViewProviderGroundedJoint(ground_view)
    if not hasattr(ground_provider, 'app_obj'):
        ground_provider.attach(ground_view)
    for obj in joints.values():
        # Headless-created view providers emit property callbacks immediately
        # upon Proxy assignment, before attach(). Initialise the installed
        # provider's scene graph via its public attach hook before binding it.
        provider = JointObject.ViewProviderJoint.__new__(JointObject.ViewProviderJoint)
        provider.attach(obj.ViewObject)
        JointObject.ViewProviderJoint.__init__(provider, obj.ViewObject)
        obj.ViewObject.Visibility = False
    doc.recompute()
    require(assembly.solve() == 0, 'GUI native solve failed')
    expected_placements(components, prepared)
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.activeDocument().activeView().fitAll()
    area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    if area:
        for window in area.subWindowList():
            if window.windowTitle().startswith(doc.Label+' :'):
                area.setActiveSubWindow(window)
                break
    def finish():
        try:
            assembly.ViewObject.Visibility = True
            for obj in components.values():
                obj.ViewObject.Visibility = True
            if area:
                for window in area.subWindowList():
                    if window.windowTitle().startswith(doc.Label+' :'):
                        area.setActiveSubWindow(window)
                        break
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
            Gui.updateGui()
            doc.save()
            # App::Link scenes can render blank via offscreen saveImage on the
            # qualified build. Capture the actual native model viewport.
            require(area is not None and area.activeSubWindow() is not None, 'Native model viewport is unavailable')
            viewport = area.activeSubWindow().widget().grab()
            pixels = viewport.toImage()
            colours = {pixels.pixelColor(x, y).rgba() for x in range(0, pixels.width(), max(1, pixels.width()//30))
                       for y in range(0, pixels.height(), max(1, pixels.height()//30))}
            require(len(colours) > 3, 'Native viewport capture appears blank')
            require(viewport.save(str(directory/'assembly.png')), 'Could not save native viewport capture')
            Gui.getMainWindow().grab().save(str(directory/'native-window.png'))
            atomic_json(directory/'gui.json', {'nativeJointEditors': True, 'components': len(components), 'pid': os.getpid(),
                'nativeViewportCaptured': True, 'sampledViewportColours': len(colours)})
        except Exception as error:
            atomic_json(directory/'native-fault.json', {'code': 'GUI_PUBLICATION_FAILED', 'message': str(error), 'location': '$', 'phase': 'native'})
        finally:
            App.closeDocument(doc.Name)
            Gui.getMainWindow().close()
    QtCore.QTimer.singleShot(1000, finish)


def gui_reopen(directory):
    """Independently reopen and check the persisted installed native editors."""
    App, JointObject = runtime()
    import FreeCADGui as Gui
    from PySide import QtCore
    directory, prepared = load(directory)
    Gui.activateWorkbench('AssemblyWorkbench')
    doc = App.openDocument(str(directory/'model.FCStd'))
    try:
        assembly, group, parts, components, joints = members(doc, prepared)
        require(isinstance(doc.getObject('Ground').ViewObject.Proxy, JointObject.ViewProviderGroundedJoint),
                'Ground native view provider did not survive GUI reopening')
        for obj in joints.values():
            require(isinstance(obj.ViewObject.Proxy, JointObject.ViewProviderJoint)
                    and hasattr(obj.ViewObject.Proxy, 'app_obj'), 'Native joint editor did not survive GUI reopening')
        require(assembly.ViewObject.Visibility and all(o.ViewObject.Visibility for o in components.values()),
                'Assembly component visibility did not survive reopening')
        require(assembly.solve() == 0, 'Reopened GUI assembly did not solve')
        expected_placements(components, prepared)
        atomic_json(directory/'gui-reopened.json', {'pid': os.getpid(), 'nativeJointEditors': True,
            'visibleComponents': len(components), 'solverReturnCode': 0})
    finally:
        App.closeDocument(doc.Name)
        QtCore.QTimer.singleShot(100, Gui.getMainWindow().close)


def edit_probe(directory):
    """Qualification-only shared-part edit, saved for an independent reopen."""
    App, _ = runtime()
    directory, prepared = load(directory)
    authored = {k: prepared[k] for k in ('units', 'parts', 'components', 'grounded', 'joints')}
    authored['version'] = 'schemaxis.freecad.assembly/1'
    authored['parts'][0]['options']['height'] += 2
    edited = plan(authored)
    doc = App.openDocument(str(directory/'model.FCStd'))
    try:
        assembly, group, parts, components, joints = members(doc, edited)
        parts[edited['parts'][0]['id']].Height = edited['parts'][0]['options']['height']
        doc.recompute()
        require(assembly.solve() == 0, 'Assembly solve failed after a shared source edit')
        expected_placements(components, edited)
        solver = solve_probe(doc, assembly, components, edited)
        receipt = snapshot(doc, edited, 'edit', solver)
        doc.saveAs(str(directory/'edited.FCStd'))
        atomic_json(directory/'edited-authored.json', authored)
        atomic_json(directory/'edit.json', receipt)
    finally:
        App.closeDocument(doc.Name)


def edit_reopen(directory):
    App, _ = runtime()
    directory = Path(directory)
    edited = plan(json.loads((directory/'edited-authored.json').read_text()))
    doc = App.openDocument(str(directory/'edited.FCStd'))
    try:
        assembly, group, parts, components, joints = members(doc, edited)
        expected_placements(components, edited)
        solver = solve_probe(doc, assembly, components, edited)
        atomic_json(directory/'edit-reopened.json', snapshot(doc, edited, 'edit-reopen', solver))
    finally:
        App.closeDocument(doc.Name)
