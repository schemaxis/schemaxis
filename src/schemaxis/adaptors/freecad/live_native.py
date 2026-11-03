# Copyright (C) 2026 David L F Gaden
"""Trusted GUI timer worker. Importing this module on the host is safe.

Only start() imports FreeCAD/PySide. All document and view operations run from
the main-thread QTimer callback. No authored source is compiled or evaluated.
"""
import json
import os
from pathlib import Path
import re
import time

from schemaxis.core.faults import SchemaxisError
from schemaxis.artifacts import atomic_json
from .live import MAX_BYTES, fault, owner_alive, prepare, validate

_worker = None


class Worker:
    def __init__(self, directory, app, gui, qt, owner=None):
        self.directory, self.app, self.gui, self.qt = Path(directory), app, gui, qt
        self.owner = owner
        self.owner_check = 0
        self.doc = app.newDocument('SchemaxisLive')
        self.doc.UndoMode = 1
        self.objects = {}
        self.prepared = None
        self.revision = 0
        self.counter = 0
        self.fingerprints = {}
        self.busy = False
        self.timer = qt.QTimer(gui.getMainWindow())
        self.timer.timeout.connect(self.tick)
        self.timer.start(25)

    def status(self):
        reverse = {v.Name: k for k, v in self.objects.items()}
        selection = [{'object': reverse[s.ObjectName], 'subelements': list(s.SubElementNames)}
                     for s in self.gui.Selection.getSelectionEx(self.doc.Name) if s.ObjectName in reverse]
        return {'pid': os.getpid(), 'runtime': self.app.Version(), 'revision': self.revision,
                'document': self.doc.Name, 'units': 'mm', 'output': self.prepared['output'] if self.prepared else None,
                'objects': [{'id': k, 'name': v.Name, 'type': v.TypeId} for k, v in self.objects.items()],
                'selection': selection, 'mainThread': self.qt.QThread.currentThread() == self.gui.getMainWindow().thread()}

    def apply(self, document):
        from .adaptor import DECLARATIONS, close
        from .features import configure, check
        prepared = prepare(document)
        previous = self.objects.copy()
        previous_names = {k: o.Name for k, o in previous.items()}
        previous_visibility = {k: o.ViewObject.Visibility for k, o in previous.items()}
        previous_selection = self.status()['selection']
        for node in prepared['nodes']:
            old = previous.get(node['id'])
            if old and old.TypeId != DECLARATIONS[node['filter']]['native']:
                fault('FEATURE_TYPE_CHANGED', 'Use a new ID when changing feature type', node['id'])
        objects = {}
        self.doc.openTransaction('Schemaxis declared update')
        try:
            for node in prepared['nodes']:
                obj = previous.get(node['id'])
                if obj is None:
                    self.counter += 1
                    obj = self.doc.addObject(DECLARATIONS[node['filter']]['native'], 'Live'+str(self.counter))
                elif obj.TypeId == 'Sketcher::SketchObject':
                    for property_name, expression in obj.ExpressionEngine:
                        obj.setExpression(property_name, None)
                    for index in range(obj.ConstraintCount-1, -1, -1):
                        obj.delConstraint(index)
                    for index in range(obj.GeometryCount-1, -1, -1):
                        obj.delGeometry(index)
                obj.Label = node['id']
                configure(obj, node, objects, {})
                objects[node['id']] = obj
            for identity, obj in reversed(list(previous.items())):
                if identity not in objects:
                    self.doc.removeObject(obj.Name)
            self.doc.recompute()
            for node in prepared['nodes']:
                obj = objects[node['id']]
                check(obj, node, close, {})
                if obj.Shape.isNull() or not obj.Shape.isValid() or any(s in obj.State for s in ('Invalid', 'Error')):
                    fault('INVALID_GEOMETRY', 'Native feature failed recompute', node['id'])
                if DECLARATIONS[node['filter']]['kinds'] != ['profile'] and (len(obj.Shape.Solids) != 1 or obj.Shape.Volume <= 0):
                    fault('INVALID_GEOMETRY', 'Each solid feature must contain one positive-volume solid', node['id'])
                obj.ViewObject.Visibility = node['id'] == prepared['output']
            from .measurements import native_observations, evaluate
            evaluate(prepared, native_observations(self.doc, prepared, objects))
            self.doc.commitTransaction()
            self.doc.clearUndos()
        except Exception:
            self.doc.abortTransaction()
            self.doc.recompute()
            self.objects = {k: self.doc.getObject(name) for k, name in previous_names.items()}
            for k, obj in self.objects.items():
                obj.ViewObject.Visibility = previous_visibility[k]
            self.gui.Selection.clearSelection()
            for selected in previous_selection:
                for subelement in selected['subelements'] or ['']:
                    self.gui.Selection.addSelection(self.doc.Name, previous_names[selected['object']], subelement)
            self.fingerprints = self.fingerprint()
            raise
        self.objects, self.prepared = objects, prepared
        self.fingerprints = self.fingerprint()
        self.revision += 1
        self.gui.Selection.clearSelection()
        view = self.gui.getDocument(self.doc.Name).activeView()
        view.viewAxonometric()
        view.fitAll()
        # The first-run Start page can remain foregrounded despite an active
        # document. Bring this session's model tab forward without preferences.
        from PySide import QtWidgets
        area = self.gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        if area:
            for window in area.subWindowList():
                if window.windowTitle().startswith(self.doc.Label+' :'):
                    area.setActiveSubWindow(window)
                    break
        return self.status()

    def fingerprint(self):
        return {k: (o.Shape.hashCode(), tuple(o.Placement.Base), tuple(o.Placement.Rotation.Q),
                    tuple(tuple(e) for e in o.ExpressionEngine))
                for k, o in self.objects.items()}

    def ensure_synchronised(self):
        """Fail closed for detected native GUI changes; no reverse synchronisation."""
        from .adaptor import DECLARATIONS, close
        from .features import check
        try:
            if {o.Name for o in self.doc.Objects} != {o.Name for o in self.objects.values()}:
                raise ValueError('Native object membership changed')
            if self.fingerprint() != self.fingerprints:
                raise ValueError('Native shape or placement changed')
            for node in self.prepared['nodes'] if self.prepared else []:
                obj = self.objects[node['id']]
                if obj.Label != node['id'] or obj.TypeId != DECLARATIONS[node['filter']]['native']:
                    raise ValueError('Native object identity changed')
                if any(s in obj.State for s in ('Touched', 'Invalid', 'Error')):
                    raise ValueError('Native object has pending or invalid edits')
                check(obj, node, close, {})
        except Exception as error:
            fault('NATIVE_DIVERGENCE', 'Native GUI state changed; restart from authored input. '+str(error))

    def geometry(self):
        if self.prepared is None:
            fault('NO_DOCUMENT', 'Apply a declared document first')
        obj = self.objects[self.prepared['output']]
        shape = obj.Shape
        if len(shape.Faces) > 10000 or len(shape.Edges) > 20000 or len(shape.Vertexes) > 40000:
            fault('LIVE_LIMIT', 'Topology exceeds viewer limits')
        faces, edges, count = [], [], 0
        for index, face in enumerate(shape.Faces, 1):
            vertices, triangles = face.tessellate(self.prepared['linearDeflection'])
            count += len(vertices)+len(triangles)
            if count > 200000:
                fault('LIVE_LIMIT', 'Tessellation exceeds 200000 vertices/triangles')
            faces.append({'id': 'Face'+str(index), 'vertices': [list(v) for v in vertices],
                          'triangles': [list(t) for t in triangles], 'area': face.Area,
                          'centre': list(face.CenterOfMass), 'surface': type(face.Surface).__name__})
        for index, edge in enumerate(shape.Edges, 1):
            # Fixed bounded samples; faces use declared chordal deflection.
            points = edge.discretize(Number=33)
            edges.append({'id': 'Edge'+str(index), 'points': [list(p) for p in points], 'length': edge.Length})
        box = shape.BoundBox
        result = {'revision': self.revision, 'object': self.prepared['output'], 'nativeName': obj.Name,
                'units': 'mm', 'coordinateSpace': 'world', 'topologyIds': 'revision-scoped',
                'valid': shape.isValid(), 'volume': shape.Volume, 'area': shape.Area,
                'bounds': [box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax],
                'objects': [{'id': self.prepared['output'], 'label': obj.Label, 'nativeName': obj.Name,
                    'faces': faces, 'edges': edges,
                    'vertices': [{'id': 'Vertex'+str(i), 'point': list(v.Point)} for i, v in enumerate(shape.Vertexes, 1)]}]}
        if self.prepared.get('measurements'):
            from .measurements import native_observations, evaluate
            result['measurements'] = evaluate(self.prepared, native_observations(self.doc, self.prepared, self.objects))
        return result

    def dispatch(self, command, args):
        validate(command, args)
        if command not in ('status', 'shutdown'):
            self.ensure_synchronised()
        if command == 'status':
            return self.status()
        if command == 'apply':
            return self.apply(args['document'])
        if command == 'geometry':
            return self.geometry()
        if command == 'shutdown':
            return {'closed': True}
        if self.prepared is None:
            fault('NO_DOCUMENT', 'Apply a declared document first')
        if command == 'select':
            obj = self.objects.get(args['object'])
            sub = args['subelement']
            match = re.fullmatch(r'(Face|Edge|Vertex)([1-9][0-9]*)', sub)
            if obj is None or (sub and not match):
                fault('INVALID_SELECTION', 'Choose a declared object and FaceN/EdgeN/VertexN or empty subelement')
            if match:
                elements = {'Face': obj.Shape.Faces, 'Edge': obj.Shape.Edges, 'Vertex': obj.Shape.Vertexes}[match[1]]
                if int(match[2]) > len(elements):
                    fault('INVALID_SELECTION', 'Subelement exceeds current topology')
            self.gui.Selection.clearSelection()
            self.gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
            return self.status()
        path = Path(args['path'])
        if command == 'save':
            self.doc.recompute()
            self.doc.saveAs(str(path))
        elif command == 'image':
            self.gui.getDocument(self.doc.Name).activeView().saveImage(str(path), 960, 720, 'White')
        if not path.is_file() or path.stat().st_size == 0:
            fault('PUBLICATION_FAILED', 'FreeCAD did not create the requested file', str(path))
        from schemaxis.publication_metadata import publish_artifacts
        metadata = publish_artifacts(path.parent, [{'file': str(path),
            'kind': 'cadScene' if command == 'save' else 'image', 'units': 'mm' if command == 'save' else 'unknown'}])
        return {'path': str(path), 'bytes': path.stat().st_size, 'revision': self.revision,
                'metadata': str(path)+'.metadata.json', 'metadataVersion': metadata['version']}

    def tick(self):
        if self.owner is not None and time.monotonic() >= self.owner_check:
            self.owner_check = time.monotonic()+0.5
            if not owner_alive(self.owner):
                self.timer.stop()
                atomic_json(self.directory/'owner-exited.json', {'owner': self.owner, 'workerPid': os.getpid()})
                self.app.closeDocument(self.doc.Name)
                self.qt.QTimer.singleShot(100, self.gui.getMainWindow().close)
                return
        path = self.directory/'request.json'
        if self.busy or not path.exists():
            return
        self.busy = True
        identity, shutdown = None, False
        try:
            if path.stat().st_size > MAX_BYTES:
                fault('LIVE_LIMIT', 'Request exceeds transfer limit')
            request = json.loads(path.read_text())
            path.unlink()
            identity = request['id']
            if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
                fault('IPC_ERROR', 'Invalid request ID')
            result = self.dispatch(request['command'], request['args'])
            response = {'id': identity, 'result': result}
            if len(json.dumps(response, indent=2, allow_nan=False).encode())+1 > MAX_BYTES:
                fault('LIVE_LIMIT', 'Response exceeds transfer limit')
            shutdown = request['command'] == 'shutdown'
        except Exception as error:
            detail = error.fault.to_dict() if isinstance(error, SchemaxisError) else {
                'code': 'NATIVE_ERROR', 'message': str(error), 'location': '$', 'phase': 'live',
                'recovery': 'Correct the declaration or inspect freecad.log.'}
            response = {'id': identity, 'fault': detail}
        finally:
            self.busy = False
        if isinstance(identity, str) and re.fullmatch('[a-f0-9]{32}', identity):
            atomic_json(self.directory/(identity+'.json'), response)
        if shutdown:
            self.timer.stop()
            self.app.closeDocument(self.doc.Name)
            self.qt.QTimer.singleShot(100, self.gui.getMainWindow().close)


def start(directory):
    global _worker
    import FreeCAD as App
    import FreeCADGui as Gui
    from PySide import QtCore
    Gui.activateWorkbench('PartWorkbench')
    owner = json.loads((Path(directory)/'owner.json').read_text())
    _worker = Worker(directory, App, Gui, QtCore, owner=owner)
    atomic_json(Path(directory)/'ready.json', _worker.status())
