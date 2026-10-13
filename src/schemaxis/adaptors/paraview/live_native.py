"""Trusted serial builtin ParaView worker. Native imports remain process-local."""
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from schemaxis.live_runtime import GraphWorker, MAX_FACES, MAX_VERTICES
from schemaxis.live_transport import fault, serve


def leaves(data):
    if data.IsA('vtkCompositeDataSet'):
        iterator = data.NewIterator()
        iterator.SkipEmptyNodesOn()
        if hasattr(iterator, 'VisitOnlyLeavesOn'):
            iterator.VisitOnlyLeavesOn()
        iterator.InitTraversal()
        while not iterator.IsDoneWithTraversal():
            leaf = iterator.GetCurrentDataObject()
            if leaf is not None:
                yield str(iterator.GetCurrentFlatIndex()), leaf
            iterator.GoToNextItem()
    else:
        yield '0', data


class Worker(GraphWorker):

    provider = 'paraview'

    def dispatch(self, command, args):
        if command not in ('inspect', 'prepare-input'):
            return super().dispatch(command, args)
        if self.active is not None:
            fault('SESSION_BUSY', 'Inspect in a separate worker to preserve the displayed preview')
        if command == 'prepare-input':
            from .studio_native import prepare_input
            return prepare_input(args['document'], args['node'])
        from schemaxis.pipeline import DefinitionGraph, RuntimeClosure
        from .filters import catalogue
        from .studio import inspection_document
        from vtkmodules.vtkCommonCore import vtkIndent
        master = DefinitionGraph(inspection_document(args['document'], args['node']), catalogue())
        active = RuntimeClosure(master, self.backend())
        try:
            active.activate([args['node']])
            active.apply(next(active.selection.visits()))
            proxy = active.handles[args['node']]
            proxy = active.backend.output_port(proxy, args['port'])
            info = proxy.GetDataInformation()
            assemblies = {}
            for name, assembly in (('Hierarchy', info.GetHierarchy()), ('Assembly', info.GetDataAssembly())):
                blocks = []
                if assembly is not None:
                    root = ET.fromstring(assembly.SerializeToXML(vtkIndent()))

                    def visit(element, depth=0, parent=None):
                        identity = int(element.attrib['id'])
                        path = assembly.GetNodePath(identity)
                        blocks.append({'selector': path, 'label': element.get('label', element.tag),
                                       'depth': depth, 'parent': parent})
                        if len(blocks) > 10000:
                            fault('INSPECTION_LIMIT', 'Block hierarchy exceeds 10,000 entries')
                        for child in element:
                            if child.tag != 'dataset':
                                visit(child, depth + 1, path)
                    visit(root)
                assemblies[name] = blocks
            return {'node': args['node'], 'port': args['port'],
                    'observation': {'bounds': list(info.GetBounds()), 'points': info.GetNumberOfPoints(), 'cells': info.GetNumberOfCells()},
                    'assemblies': assemblies, 'scope': 'Current draft input and its upstream dependencies; no publications'}
        finally:
            active.close()

    def backend(self):
        from .native import ParaViewBackend
        return ParaViewBackend()

    def reset_native(self):
        from paraview import simple
        simple.ResetSession()

    def present(self, prepared):
        pass  # Companion renders geometry; native rendering is requested explicitly.

    def object_ids(self):
        return [{'id': identity, 'label': self.active.backend.sm.ProxyManager().GetProxyName('sources', obj.SMProxy) or identity,
                 'nativeId': str(obj.SMProxy.GetGlobalIDAsString())}
                for identity, obj in self.active.handles.items()]

    def geometry(self):
        from vtkmodules.vtkFiltersGeometry import vtkDataSetSurfaceFilter
        from vtkmodules.vtkFiltersCore import vtkTriangleFilter
        from vtkmodules.vtkCommonCore import vtkIdTypeArray
        objects, face_count, vertex_count = [], 0, 0
        for identity in self.prepared[3]:
            proxy = self.active.handles[identity]
            data = self.active.backend.fetch(proxy)
            label = self.active.backend.sm.ProxyManager().GetProxyName('sources', proxy.SMProxy) or identity
            for block, leaf in leaves(data):
                if not leaf.IsA('vtkDataSet'):
                    fault('UNSUPPORTED_GEOMETRY', 'Live tessellation requires dataset leaves', node=identity,
                          nativeType=leaf.GetClassName())
                surface_filter = vtkDataSetSurfaceFilter()
                surface_filter.SetInputData(leaf)
                surface_filter.Update()
                surface = surface_filter.GetOutput()
                face_count += surface.GetNumberOfCells()
                if face_count > MAX_FACES or surface.GetNumberOfPoints() > MAX_VERTICES:
                    fault('LIVE_LIMIT', 'Native surface exceeds live tessellation budget')
                ids = vtkIdTypeArray()
                ids.SetName('__schemaxis_live_face')
                ids.SetNumberOfTuples(surface.GetNumberOfCells())
                for index in range(surface.GetNumberOfCells()):
                    ids.SetValue(index, index)
                surface.GetCellData().AddArray(ids)
                triangulate = vtkTriangleFilter()
                triangulate.SetInputData(surface)
                triangulate.PassVertsOff()
                triangulate.PassLinesOff()
                triangulate.Update()
                triangles = triangulate.GetOutput()
                original = triangles.GetCellData().GetArray('__schemaxis_live_face')
                faces, maps = {}, {}
                for index in range(triangles.GetNumberOfCells()):
                    cell = triangles.GetCell(index)
                    if cell.GetNumberOfPoints() != 3:
                        fault('UNSUPPORTED_GEOMETRY', 'Native surface did not triangulate')
                    face_id = int(original.GetValue(index))
                    face = faces.setdefault(face_id, {'id': 'Face' + str(face_id), 'vertices': [], 'triangles': []})
                    mapping = maps.setdefault(face_id, {})
                    triangle = []
                    for corner in range(3):
                        point = cell.GetPointId(corner)
                        if point not in mapping:
                            mapping[point] = len(face['vertices'])
                            face['vertices'].append(list(triangles.GetPoint(point)))
                            vertex_count += 1
                        triangle.append(mapping[point])
                    face['triangles'].append(triangle)
                    if vertex_count > MAX_VERTICES:
                        fault('LIVE_LIMIT', 'Tessellation exceeds live vertex budget')
                edges = []
                for index in range(surface.GetNumberOfCells()):
                    cell = surface.GetCell(index)
                    if cell.GetCellDimension() == 1:
                        points = [list(surface.GetPoint(cell.GetPointId(i))) for i in range(cell.GetNumberOfPoints())]
                        vertex_count += len(points)
                        if vertex_count > MAX_VERTICES:
                            fault('LIVE_LIMIT', 'Edges exceed live vertex budget')
                        edges.append({'id': 'Edge' + str(index), 'points': points})
                objects.append({'id': identity if not data.IsA('vtkCompositeDataSet') else identity + '/block/' + block,
                                'node': identity, 'label': label, 'block': block,
                                'faces': list(faces.values()), 'edges': edges})
        return objects

    def image(self, path):
        from .publication import Renderer, style
        from schemaxis.camera import camera_values
        boxes = [self.active.observations[n]['bounds'] for n in self.prepared[3]
                 if self.active.observations[n].get('points')]
        if not boxes:
            fault('EMPTY_SCENE', 'Cannot frame an empty live scene')
        bounds = [min(b[i] for b in boxes) if i % 2 == 0 else max(b[i] for b in boxes) for i in range(6)]
        renderer = Renderer(self.active.backend)
        try:
            renderer.prepare(self.active.handles, {n: style({}, n) for n in self.prepared[3]},
                             time=self.active.last_time)
            return {**renderer.write(path, {'size': [640, 480]},
                                     camera_values({'direction': [1, -1, 1]}, 'live.camera'), bounds),
                    'scope': 'live geometry preview with fixed camera and neutral surface style'}
        finally:
            renderer.close()

    def save(self, path):
        from paraview import simple
        metadata = self.save_metadata()
        metadata['runtime'] = str(simple.GetParaViewVersion())
        dependencies = []
        for identity, values in self.active.values.items():
            for option in ('file', 'files'):
                if option not in values:
                    continue
                native = values[option] if isinstance(values[option], list) else [values[option]]
                dependencies.append({'node': identity, 'option': option, 'nativeValues': native,
                                     'files': [str(Path(p).absolute()) for p in native], 'copied': False})
        simple.SaveState(str(path))
        root = ET.parse(path).getroot()
        state = root if root.tag == 'ServerManagerState' else root.find('ServerManagerState')
        if state is None:
            fault('VERIFICATION_FAILED', 'Saved ParaView state has no server-manager state')
        ids = {node.get('id') for node in state.findall('Proxy')}
        expected = {str(obj.SMProxy.GetGlobalIDAsString()) for obj in self.active.handles.values()}
        if not expected.issubset(ids):
            fault('VERIFICATION_FAILED', 'Saved ParaView state is missing live pipeline proxies')
        return self.save_receipt(path, {'kind': 'state', 'format': 'pvsm', 'verified': True,
            'verificationScope': 'state XML structure and live proxy identity membership; dataset reload is not independently verified',
            'externalDependencies': dependencies, 'datasetsCopied': False, 'workingDirectory': os.getcwd(),
            'dependencyScope': 'declared file/files references only; sidecars, case directories and transitive dataset dependencies are not copied or exhaustively enumerated',
            'portable': False}, metadata)


def start(directory, parent_pid=None, parent_start=None):
    from paraview import simple, servermanager
    from vtkmodules.vtkParallelCore import vtkMultiProcessController
    controller = vtkMultiProcessController.GetGlobalController()
    if servermanager.ActiveConnection.IsRemote() or (controller and controller.GetNumberOfProcesses() != 1):
        fault('UNSUPPORTED_EXECUTION', 'Live ParaView requires a serial builtin connection')
    serve(directory, Worker(), parent_pid=parent_pid, parent_start=parent_start)
