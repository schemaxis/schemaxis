# Copyright (C) 2026 David L F Gaden
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
from .operations import extra_objects
from schemaxis.artifacts import file_digest


def bounds(box):
    return [box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax]


def snapshot(shape):
    return {'valid': bool(shape.isValid()), 'solids': len(shape.Solids), 'volume': shape.Volume,
            'area': shape.Area, 'bounds': bounds(shape.optimalBoundingBox(False, False))}


EXPORT_EVIDENCE = 'schemaxis.freecad.export/2'


def export_snapshot(shape):
    """Exact native facts the host compares with its own STL integrals and the STEP readback."""
    record = snapshot(shape)
    solids = shape.Solids
    volume = sum(s.Volume for s in solids)
    record.update(centreOfMass=[sum(s.Volume*getattr(s.CenterOfMass, a) for s in solids)/volume for a in 'xyz'] if volume > 0 else None,
                  curvedArea=sum(f.Area for f in shape.Faces if type(f.Surface).__name__ != 'Plane'), faces=len(shape.Faces))
    return record


def output_object(doc, prepared, identity=None):
    from .operations import output_names
    return doc.getObject(output_names(prepared)[identity or prepared['output']])


def import_observations(doc, prepared, sources):
    from .step_import_native import observe
    return {node['id']: observe(doc, node, index, sources[node['id']]['sha256'])
            for index, node in enumerate(prepared['nodes']) if node['filter'] == 'importSTEP'}


def check_runtime():
    version = App.Version()
    if version[:2] != ['1', '1']:
        fail('UNSUPPORTED_RUNTIME', 'FreeCAD adaptor is qualified for 1.1.x', version=version)
    return version


def check_definition(doc, prepared, sources):
    if 'partDesign' in prepared:
        from .part_design_native import observe as observe_body
        observe_body(doc,prepared,visibility=False)
    elif len(doc.Objects) != len(prepared['nodes']) + int('parameters' in prepared) + len(extra_objects(prepared)):
        fail('VERIFICATION_FAILED', 'CAD object membership differs')
    if 'parameters' in prepared:
        from .parameters_native import observe
        observe(doc, prepared)
    for index, node in enumerate(prepared['nodes']):
        obj = doc.getObject('N'+str(index))
        if obj is None or obj.TypeId != DECLARATIONS[node['filter']]['native'] or obj.Label != node['id']:
            fail('VERIFICATION_FAILED', 'CAD feature identity differs')
        if node['filter']=='body':continue
        from .features import check
        from .operations import output_names
        check(obj,node,close,sources,output_names(prepared))
        if obj.Shape.isNull() or not obj.Shape.isValid() or 'Invalid' in obj.State:
            fail('INVALID_GEOMETRY', 'CAD feature is invalid', node['id'])


def build(directory):
    directory = Path(directory)
    check_runtime()
    prepared = json.loads((directory/'plan.json').read_text())
    sources=json.loads((directory/'sources.json').read_text())
    doc = App.newDocument('Schemaxis')
    objects = {}
    if 'parameters' in prepared:
        from .parameters_native import create
        create(doc, prepared)
    for index, node in enumerate(prepared['nodes']):
        if 'partDesign' in prepared:
            from .part_design_native import create as create_body_member
            obj=create_body_member(doc,prepared,node,index)
        else:
            obj = doc.addObject(DECLARATIONS[node['filter']]['native'], 'N'+str(index))
        obj.Label = node['id']
        from .features import configure
        configure(obj,node,objects,sources)
        if node.get('drive'):
            from .parameters_native import bind
            bind(obj, node)
        if node['filter'] == 'importSTEP':
            from .step_import_native import attach_refine
            obj = attach_refine(doc, obj, node, index)
        objects[node['id']] = obj
    if 'partDesign' in prepared:
        from .part_design_native import finish
        finish(doc,prepared)
    doc.recompute()
    check_definition(doc, prepared, sources)
    imports = import_observations(doc, prepared, sources)
    output = objects[prepared['output']]
    shape = snapshot(output.Shape)
    if shape['solids'] != 1 or shape['volume'] <= 0:
        fail('INVALID_GEOMETRY', 'CAD output must be one positive-volume solid')
    if 'partDesign' in prepared:
        from .part_design_native import set_visibility
        set_visibility(doc,prepared)
    else:
        for obj in doc.Objects:
            obj.Visibility = obj == output
    doc.saveAs(str(directory/'model.FCStd'))
    if 'partDesign' in prepared or any(n['filter'] == 'importSTEP' for n in prepared['nodes']):
        # Without a view record the FreeCAD GUI opens every object hidden; record visibility only.
        from .gui_state import persist
        persist(directory/'model.FCStd',{obj.Name:bool(obj.Visibility) for obj in doc.Objects})
    Part.export([output], str(directory/'model.step'))
    mesh = MeshPart.meshFromShape(Shape=output.Shape, LinearDeflection=prepared['linearDeflection']/2, AngularDeflection=0.1, Relative=False)
    mesh.write(str(directory/'model.stl'))
    from .selections import native_evidence
    from .measurements import native_observations, evaluate
    measurements = native_observations(doc, prepared)
    if prepared.get('measurements'):
        atomic_json(directory/'measurements.json', evaluate(prepared, measurements))
    parameters = {}
    if 'parameters' in prepared:
        from .parameters_native import observe
        parameters['parameterObservations'] = observe(doc, prepared)
    if 'partDesign' in prepared:
        from .part_design_native import observe as observe_body
        parameters['partDesignObservations']=observe_body(doc,prepared)
    atomic_json(directory/'built.json', {'definition': prepared, 'shape': shape, **parameters,
                                       'measurementObservations': measurements,
                                       'selections': native_evidence(doc, prepared),
                                       'importObservations': imports,
                                       'exportEvidence': {'version': EXPORT_EVIDENCE, 'shape': export_snapshot(output.Shape),
                                                          'meshing': {'linearDeflection': prepared['linearDeflection']/2,
                                                                      'angularDeflection': 0.1, 'relative': False}}})
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
    output = output_object(doc, prepared)
    if 'partDesign' not in prepared and any(bool(obj.Visibility) != (obj.Name == output.Name) for obj in doc.Objects):
        fail('VERIFICATION_FAILED', 'saved CAD scene visibility differs')
    native = snapshot(output.Shape)
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
    if 'parameters' in prepared:
        from .parameters_native import observe
        receipt['parameterObservations'] = observe(doc, prepared)
    if 'partDesign' in prepared:
        from .part_design_native import observe as observe_body
        receipt['partDesignObservations']=observe_body(doc,prepared)
    from .selections import native_evidence
    receipt['selections'] = native_evidence(doc, prepared)
    from .measurements import native_observations
    receipt['measurementObservations'] = native_observations(doc, prepared)
    receipt['importObservations'] = import_observations(doc, prepared, sources)
    receipt['exportEvidence'] = {'version': EXPORT_EVIDENCE, 'native': export_snapshot(output.Shape), 'step': export_snapshot(shape)}
    atomic_json(directory/'verification.json', receipt)
    verify(directory, require_result=False)
    App.closeDocument(doc.Name)
