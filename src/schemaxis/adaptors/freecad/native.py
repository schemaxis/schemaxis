"""Native FreeCAD workers. Imported only inside FreeCAD's interpreter."""
import json
from pathlib import Path
import FreeCAD as App
import Part
import Mesh
import MeshPart
from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from .adaptor import DECLARATIONS, output_files, artifact_units, close, verify
from schemaxis.artifacts import file_digest


def bounds(box):
    return [box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax]


def snapshot(shape):
    return {'valid': bool(shape.isValid()), 'solids': len(shape.Solids), 'volume': shape.Volume,
            'area': shape.Area, 'bounds': bounds(shape.optimalBoundingBox(False, False))}


def check_runtime():
    version = App.Version()
    if version[:2] != ['1', '1']:
        fail('UNSUPPORTED_RUNTIME', 'FreeCAD adaptor is qualified for 1.1.x', version=version)
    return version


def check_definition(doc, prepared, sources):
    if len(doc.Objects) != len(prepared['nodes']):
        fail('VERIFICATION_FAILED', 'CAD object membership differs')
    for index, node in enumerate(prepared['nodes']):
        obj = doc.getObject('N'+str(index))
        if obj is None or obj.TypeId != DECLARATIONS[node['filter']]['native'] or obj.Label != node['id']:
            fail('VERIFICATION_FAILED', 'CAD feature identity differs')
        from .features import check
        check(obj,node,close,sources)
        if obj.Shape.isNull() or not obj.Shape.isValid() or 'Invalid' in obj.State:
            fail('INVALID_GEOMETRY', 'CAD feature is invalid', node['id'])


def build(directory):
    directory = Path(directory)
    check_runtime()
    prepared = json.loads((directory/'plan.json').read_text())
    sources=json.loads((directory/'sources.json').read_text())
    doc = App.newDocument('Schemaxis')
    objects = {}
    for index, node in enumerate(prepared['nodes']):
        obj = doc.addObject(DECLARATIONS[node['filter']]['native'], 'N'+str(index))
        obj.Label = node['id']
        from .features import configure
        configure(obj,node,objects,sources)
        objects[node['id']] = obj
    doc.recompute()
    check_definition(doc, prepared, sources)
    output = objects[prepared['output']]
    shape = snapshot(output.Shape)
    if shape['solids'] != 1 or shape['volume'] <= 0:
        fail('INVALID_GEOMETRY', 'CAD output must be one positive-volume solid')
    for obj in doc.Objects:
        obj.Visibility = obj == output
    doc.saveAs(str(directory/'model.FCStd'))
    Part.export([output], str(directory/'model.step'))
    mesh = MeshPart.meshFromShape(Shape=output.Shape, LinearDeflection=prepared['linearDeflection']/2, AngularDeflection=0.1, Relative=False)
    mesh.write(str(directory/'model.stl'))
    from .selections import native_evidence
    from .measurements import native_observations, evaluate
    measurements = native_observations(doc, prepared)
    if prepared.get('measurements'):
        atomic_json(directory/'measurements.json', evaluate(prepared, measurements))
    atomic_json(directory/'built.json', {'definition': prepared, 'shape': shape,
                                       'measurementObservations': measurements,
                                       'selections': native_evidence(doc, prepared)})
    App.closeDocument(doc.Name)


def reopen(directory):
    directory = Path(directory)
    runtime = check_runtime()
    prepared = json.loads((directory/'plan.json').read_text())
    sources=json.loads((directory/'sources.json').read_text()) if (directory/'sources.json').exists() else {}
    doc = App.openDocument(str(directory/'model.FCStd'))
    for obj in doc.Objects:
        obj.touch()
    doc.recompute()
    check_definition(doc, prepared, sources)
    index = next(i for i,n in enumerate(prepared['nodes']) if n['id'] == prepared['output'])
    if any(bool(obj.Visibility) != (obj.Label == prepared['output']) for obj in doc.Objects):
        fail('VERIFICATION_FAILED', 'saved CAD scene visibility differs')
    native = snapshot(doc.getObject('N'+str(index)).Shape)
    shape = Part.Shape(); shape.read(str(directory/'model.step'))
    mesh = Mesh.Mesh(str(directory/'model.stl'))
    receipt = {'status': 'succeeded', 'freshProcess': True, 'definition': prepared, 'units': 'mm',
               'runtime': runtime, 'native': native, 'step': snapshot(shape),
               'mesh': {'solid': bool(mesh.isSolid()), 'facets': mesh.CountFacets, 'volume': abs(mesh.Volume), 'boundsOrder': ['xmin','xmax','ymin','ymax','zmin','zmax'], 'axisOrder': ['x','y','z'],
                                'bounds': bounds(mesh.BoundBox)},
               'artifacts': [{'file': str(directory/filename), 'kind': kind, 'units': artifact_units(kind), 'sha256': file_digest(directory/filename),
                    **({'facets': mesh.CountFacets} if filename.endswith('.stl') else {}),
                    'spatial': {'state': 'known', 'frame': 'native-world', 'units': 'mm',
                                'boundsOrder': ['xmin','xmax','ymin','ymax','zmin','zmax'], 'axisOrder': ['x','y','z'],
                                'bounds': bounds(mesh.BoundBox) if filename.endswith('.stl') else snapshot(shape)['bounds'] if filename.endswith('.step') else native['bounds'], 'coordinateRepresentation': 'world coordinates stored in geometry'}
                    if kind in ('cadScene', 'geometry', 'cad', 'mesh') else {'state': 'notApplicable'}} for filename,kind in output_files(prepared)]}
    from .selections import native_evidence
    receipt['selections'] = native_evidence(doc, prepared)
    from .measurements import native_observations
    receipt['measurementObservations'] = native_observations(doc, prepared)
    atomic_json(directory/'verification.json', receipt)
    verify(directory, require_result=False)
    App.closeDocument(doc.Name)
