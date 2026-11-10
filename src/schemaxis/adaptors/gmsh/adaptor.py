# Copyright (C) 2026 David L F Gaden
"""Bounded single-solid tetrahedral meshing with isolated native execution."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time

from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import mesh, geometry, groups, cylinders

VERSION = 'schemaxis.gmsh/1'
VECTOR = {'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':3,'maxItems':3,'default':[0,0,0]}
SIZE = {'type':'number','minimum':0.001,'maximum':100000}
LABEL = {'type':'string','minLength':1,'maxLength':64}
FACE_GROUPS = {'type':'array','maxItems':12,'default':[], 'items':{
    'type':'object','properties':{
        'name':{**LABEL,'required':True},
        'axis':{'type':'enum','values':['x','y','z'],'required':True},
        'coordinate':{'type':'number','minimum':-100000,'maximum':200000,'required':True},
        'tolerance':{'type':'number','minimum':0.000001,'maximum':0.001,'default':0.000001},
        'areaTolerance':{'type':'number','minimum':1e-10,'maximum':0.02,'default':1e-10}}}}
CYLINDER_GROUPS = {'type':'array','maxItems':12,'default':[], 'items':{
    'type':'object','properties':{
        'name':{**LABEL,'required':True},
        'axis':{'type':'enum','values':['x','y','z'],'required':True},
        'centre':{'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':3,'maxItems':3,'required':True},
        'radius':{**SIZE,'required':True},
        'side':{'type':'enum','values':['inner','outer'],'required':True},
        'tolerance':{'type':'number','minimum':0.000001,'maximum':0.001,'default':0.000001},
        'areaTolerance':{'type':'number','minimum':1e-10,'maximum':0.02,'default':1e-9}}}}
NEAR_BOUNDARIES = {'type': 'array', 'maxItems': 13, 'default': [], 'items': {
    'type': 'object', 'properties': {
        'boundary': {**LABEL, 'required': True}, 'size': {**SIZE, 'required': True},
        'distance': {**SIZE, 'required': True}}}}


def declaration(native, kind, options, inputs=None):
    return {'native':native,'kinds':[kind],'inputs':inputs or {},
            'options':{k:{'value':v} for k,v in options.items()}}


DECLARATIONS = {
    'box': declaration('gmsh.model.occ.addBox', 'solid', {
        'origin':VECTOR, 'size':{**VECTOR,'items':SIZE,'default':[10,10,10]}}),
    'readSTEP': declaration('gmsh.model.occ.importShapes', 'solid', {
        'file':{'type':'string','minLength':1,'maxLength':4096,'required':True}}),
    'tetrahedral': declaration('gmsh.model.mesh.generate', 'mesh', {
        'size':{**SIZE,'default':3}, 'volumeName':{**LABEL,'default':'domain'},
        'boundaryName':{**LABEL,'default':'boundary'},
        'faceGroups':FACE_GROUPS,
        'cylinderGroups':CYLINDER_GROUPS,
        'algorithm':{'type':'enum','values':['delaunay','hxt'],'default':'delaunay'},
        'optimise':{'type':'boolean','default':True},
        'nearBoundaries':NEAR_BOUNDARIES,
        'volumeTolerance':{'type':'number','minimum':0.00000001,'maximum':0.02,'default':0.01}},
        {'input':{'kind':'solid','required':True}}),
    'cylinder': declaration('gmsh.model.occ.addCylinder', 'solid', {
        'origin':VECTOR, 'axis':{'type':'enum','values':['x','y','z'],'default':'z'},
        'radius':{**SIZE,'default':5}, 'height':{**SIZE,'default':10}}),
    'hollowCylinder': declaration('gmsh.model.occ.cut', 'solid', {
        'origin':VECTOR, 'axis':{'type':'enum','values':['x','y','z'],'default':'z'},
        'radius':{**SIZE,'default':5}, 'innerRadius':{**SIZE,'default':3},
        'height':{**SIZE,'default':10}}),
    'sphere': declaration('gmsh.model.occ.addSphere', 'solid', {
        'centre':VECTOR, 'radius':{**SIZE,'default':5}}),
}
FILES = [('result.msh','mesh'),('volume.vtu','geometry'),('boundary.vtu','geometry'),('mesh-summary.json','text')]
EVIDENCE = ('built.json','reopened.json','sources.json','worker.py')


def plan(document):
    from schemaxis.pipeline import name
    keys(document, ('version','units','nodes','output','refinement'), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION','expected '+VERSION)
    if document.get('units') != 'mm': fail('UNSUPPORTED_UNITS','declare mm explicitly; STEP is normalised to mm')
    nodes = document.get('nodes')
    if not isinstance(nodes,list) or len(nodes) != 2:
        fail('INVALID_DOCUMENT','provide one primitive/readSTEP followed by one tetrahedral node')
    prepared = []; seen = set()
    for i, node in enumerate(nodes):
        keys(node, ('id','filter','options','inputs'), '$.nodes')
        identity = name(node.get('id'),'node.id'); op = node.get('filter')
        if identity in seen: fail('DUPLICATE_NODE','node id is repeated',identity)
        if not isinstance(op,str) or op not in DECLARATIONS: fail('UNKNOWN_FILTER','unsupported meshing operation',identity)
        if (i == 0 and op not in geometry.PRIMITIVES+('readSTEP',)) or (i == 1 and op != 'tetrahedral'):
            fail('INVALID_DEPENDENCY','one solid source must precede tetrahedral',identity)
        decl = DECLARATIONS[op]
        options = validate_arguments({k:v['value'] for k,v in decl['options'].items()},node.get('options',{}),location=identity+'.options')
        inputs = node.get('inputs',{}); keys(inputs,tuple(decl['inputs']),identity+'.inputs')
        if set(inputs) != set(decl['inputs']) or any(not isinstance(v,str) or v not in seen for v in inputs.values()):
            fail('INVALID_DEPENDENCY','reference the earlier solid node',identity)
        if op == 'readSTEP' and (not Path(options['file']).is_absolute() or Path(options['file']).suffix.lower() not in ('.step','.stp')):
            fail('INVALID_RESOURCE','provide an absolute single-file STEP path',identity)
        if op == 'hollowCylinder' and options['radius']-options['innerRadius'] < 0.001:
            fail('INVALID_ARGUMENT','innerRadius must leave a wall at least 0.001 mm thick',identity+'.options.innerRadius')
        if op == 'tetrahedral':
            cylinder_groups = options['cylinderGroups']
            if len(options['faceGroups'])+len(cylinder_groups) > 12:
                fail('INVALID_ARGUMENT','faceGroups and cylinderGroups together allow at most 12 groups',identity)
            names = [options[k] for k in ('volumeName','boundaryName')]+[g['name'] for g in options['faceGroups']]+[g['name'] for g in cylinder_groups]
            if any(re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',n) is None for n in names):
                fail('INVALID_ARGUMENT','physical names use ASCII letters, digits, underscores and hyphens',identity)
            if len(set(names)) != len(names): fail('INVALID_ARGUMENT','physical names must be distinct',identity)
            for index, group in enumerate(options['faceGroups']):
                for earlier in options['faceGroups'][:index]:
                    if group['axis'] == earlier['axis'] and abs(group['coordinate']-earlier['coordinate']) <= group['tolerance']+earlier['tolerance']:
                        fail('INVALID_SELECTION','face selection planes must not overlap',identity)
            for index, group in enumerate(cylinder_groups):
                location = identity+'.options.cylinderGroups['+str(index)+']'
                for earlier in cylinder_groups[:index]:
                    if (group['axis'] == earlier['axis']
                            and abs(group['radius']-earlier['radius']) <= group['tolerance']+earlier['tolerance']
                            and all(abs(group['centre'][k]-earlier['centre'][k]) <= group['tolerance']+earlier['tolerance']
                                    for k in range(3) if k != 'xyz'.index(group['axis']))):
                        fail('INVALID_SELECTION','cylinder selectors must describe distinct cylinders; a cylinder met by material on both sides cannot be named per side',location)
                if prepared[0]['filter'] in geometry.PRIMITIVES and not any(
                        geometry.wall_match(w,group) for w in geometry.walls(prepared[0])):
                    fail('INVALID_SELECTION','cylinder selector does not describe a cylindrical wall of the solid; check axis, centre, radius and side',
                         location,walls=[{k:w[k] for k in ('axis','centre','radius','side')} for w in geometry.walls(prepared[0])])
            boundary_names = groups.declared_names(options)
            empty_remainder = geometry.remainder_empty(prepared[0],options) if prepared[0]['filter'] in geometry.PRIMITIVES else False
            if empty_remainder: boundary_names.discard(options['boundaryName'])
            selected = set()
            for index, rule in enumerate(options['nearBoundaries']):
                if rule['boundary'] not in boundary_names or rule['boundary'] in selected:
                    fail('INVALID_SELECTION', 'sizing requires distinct declared boundary names' +
                         ('; the remainder boundary is empty' if empty_remainder and rule['boundary'] == options['boundaryName'] else ''),
                         identity+'.options.nearBoundaries['+str(index)+'].boundary' if empty_remainder and rule['boundary'] == options['boundaryName'] else identity)
                if rule['size'] > options['size']:
                    fail('INVALID_ARGUMENT', 'boundary size must not exceed the global size', identity)
                selected.add(rule['boundary'])
            if not cylinder_groups: del options['cylinderGroups']
            minimum = min([options['size']]+[r['size'] for r in options['nearBoundaries']])
            if prepared[0]['filter'] in geometry.PRIMITIVES:
                _, bounds = geometry.measures(prepared[0])
                if 6*math.prod((bounds[i+3]-bounds[i])/minimum+1 for i in range(3)) > mesh.MAX_CELLS:
                    fail('RESOURCE_LIMIT','increase mesh size; estimated cell budget exceeds 200000',identity)
        prepared.append({'id':identity,'filter':op,'options':options,'inputs':inputs}); seen.add(identity)
    if document.get('output') != prepared[-1]['id']: fail('INVALID_SELECTION','output must select the tetrahedral node')
    result = {'version':'schemaxis.gmsh.plan/1','units':'mm','nodes':prepared,'output':document['output'],
            'limits':{'nodes':mesh.MAX_NODES,'cells':mesh.MAX_CELLS,'sourceBytes':16*1024*1024},
            'losses':['CAD feature history and STEP labels are not retained',
                      'linear tetrahedra approximate curved boundaries',
                      'one volume group and disjoint planar face groups with a remainder boundary; no automatic boundary conditions',
                      'VTU carries numeric physicalTag; names and mm units are in mesh-summary.json']}
    if 'cylinderGroups' in prepared[1]['options']:
        result['losses'] = result['losses']+[
            'cylinder groups select whole typed analytic cylindrical faces with a world-axis direction; linear facets approximate the wall (published as chord deviation)',
            'a flat face lying on a cylinder cannot be told from a coarse wall facet and fails verification; the remainder boundary may be empty when named groups cover the boundary']
    if 'refinement' in document:
        from .refinement import prepare
        result['refinement'] = prepare(document['refinement'], result)
    return result


def schema():
    from schemaxis.schema import DRAFT, NAME, object_schema, arguments_schema
    from .refinement import schema as refinement_schema
    variants = []
    for op, decl in DECLARATIONS.items():
        options = arguments_schema({k:v['value'] for k,v in decl['options'].items()})
        variants.append(object_schema({'id':NAME,'filter':{'const':op},'options':options,
            'inputs':object_schema({k:NAME for k in decl['inputs']},list(decl['inputs']))},
            ['id','filter']+(['options'] if options.get('required') else [])+(['inputs'] if decl['inputs'] else [])))
    return {'$schema':DRAFT,**object_schema({'version':{'const':VERSION},'units':{'const':'mm'},
        'nodes':{'type':'array','minItems':2,'maxItems':2,'items':{'oneOf':variants}},'output':NAME,
        'refinement':refinement_schema()},['version','units','nodes','output'])}


def reusableInputs(document):
    source = plan(document)['nodes'][0]
    if source['filter'] != 'readSTEP': return {}
    path = Path(source['options']['file'])
    try:
        if not path.exists(): fail('RESOURCE_NOT_FOUND','STEP input is absent',str(path))
        if not path.is_file(): fail('UNSUPPORTED_RESOURCE','STEP input must be a regular file',str(path))
        if path.stat().st_size > 16*1024*1024: fail('RESOURCE_LIMIT','STEP exceeds 16 MiB',str(path))
        return {str(path):file_digest(path)}
    except OSError as error: fail('RESOURCE_NOT_FOUND',str(error),str(path))


def resources(document, spec, identity):
    if spec.get('threads',1) != 1: fail('INVALID_EXECUTION','Gmsh slice uses one allocated thread',identity)
    return {'threads':1}


def manifest(directory):
    observed = json.loads((directory/'mesh-summary.json').read_text()) if (directory/'mesh-summary.json').is_file() else {}
    return [{'file':str(directory/name),'kind':kind,'units':'mm','sha256':file_digest(directory/name),
             'data': {key: observed[key] for key in ('points','cells','nodes','elements') if key in observed},
             'spatial': {'state': 'known' if observed.get('bounds') else 'unknown', 'frame': 'native-world', 'units': 'mm', 'bounds': observed.get('bounds'),
                         'boundsOrder':['xmin','ymin','zmin','xmax','ymax','zmax'], 'axisOrder':['x','y','z']} if kind in ('mesh','geometry') else {'state':'notApplicable'}} for name,kind in FILES]


def wall_reports(prepared, built, data, source):
    """Independently proven reports for every authored cylinder group, or None when there are none."""
    settings = prepared['nodes'][1]['options']
    walls = groups.cylinders(settings)
    if not walls: return None
    expected = {str(groups.cylinder_tag(settings,i)) for i in range(len(walls))}
    mesh.check(set(built.get('cylinderAreas',{})) == expected,'CAD cylinder areas missing')
    opposite = cylinders.adjacent(data); reports = []
    for index, group in enumerate(walls):
        tag = groups.cylinder_tag(settings,index); cad_area = built['cylinderAreas'][str(tag)]
        report = cylinders.measure(data,group,tag,opposite)
        mesh.check(math.isfinite(cad_area) and cad_area > 0,'invalid CAD cylinder area')
        if source['filter'] in geometry.PRIMITIVES:
            analytic = geometry.verify_wall(source,group,report)
            mesh.check(math.isclose(cad_area,analytic,rel_tol=1e-10,abs_tol=1e-8),'CAD wall area differs from analytic primitive')
        error = abs(report['unrolledArea']-cad_area)/cad_area
        mesh.check(error <= group['areaTolerance'] or abs(report['unrolledArea']-cad_area) <= 1e-8,
                   'unrolled wall area differs from CAD beyond areaTolerance: '+group['name'])
        reports.append({'name':group['name'],'tag':tag,'axis':group['axis'],'centre':group['centre'],'radius':group['radius'],
            'side':group['side'],'triangles':report['triangles'],'cadArea':cad_area,'unrolledArea':report['unrolledArea'],
            'areaRelativeError':error,'areaTolerance':group['areaTolerance'],
            'maximumVertexResidual':report['maximumVertexResidual'],'maximumChordDeviation':report['maximumChordDeviation'],
            'chordSegmentsEquivalent':cylinders.segments(group['radius'],report['maximumChordDeviation']),
            'maximumAngularSpan':report['maximumAngularSpan'],'axialRange':report['axialRange']})
    return reports


def summary(prepared, observed, cad, data, face_areas, walls=None, surfaces=None):
    from .quality import assess
    result = {'version':'schemaxis.gmsh.summary/1','units':'mm',**observed,
            'quality': assess(data),
            'cadBounds': cad['bounds'],
            'boundaryAreaChecks':[{'name':g['name'],'cadArea':face_areas[str(i+3)],
                'meshArea':next(b['area'] for b in observed['boundaryGroups'] if b['tag'] == i+3),
                'relativeError':abs(next(b['area'] for b in observed['boundaryGroups'] if b['tag'] == i+3)-face_areas[str(i+3)])/face_areas[str(i+3)],
                'tolerance':g['areaTolerance'],'absoluteTolerance':1e-8} for i,g in enumerate(prepared['nodes'][1]['options']['faceGroups'])],
            'cadVolume':cad['volume'],'volumeRelativeError':abs(observed['volume']-cad['volume'])/cad['volume'],
            'losses':prepared['losses']}
    if walls is not None: result['cylinderChecks'] = walls
    if surfaces is not None: result['cadSurfaces'] = {'source':'native readback for authoring; advisory, not independent proof',**surfaces}
    return result


NATIVE_FAULTS = ('NATIVE_UNAVAILABLE','UNSUPPORTED_RUNTIME','UNSUPPORTED_RESOURCE','INVALID_RESOURCE',
                 'INVALID_SELECTION','RESOURCE_LIMIT','NATIVE_EXECUTION_FAILED')


def native_fault(path):
    """Rebuild the worker's refusal, trusting only allow-listed codes and plain-text fields."""
    try:
        value = json.loads(Path(path).read_text())
        text = lambda key: value[key] if type(value.get(key)) is str and value[key].strip() else None
        if value.get('code') not in NATIVE_FAULTS or not text('message') or not isinstance(value.get('observed', {}), dict):
            raise ValueError('malformed native fault')
        if any(len(text(key) or '') > 2000 for key in ('message','location','recovery')) or len(json.dumps(value.get('observed', {}))) > 2000:
            raise ValueError('native fault record too large')
        return Fault(value['code'], text('message'), text('location') or '$', 'native',
                     observed=value.get('observed', {}), recovery=text('recovery'))
    except (OSError, ValueError, TypeError, AttributeError):
        return Fault('NATIVE_EXECUTION_FAILED', 'native Gmsh failed without a trustworthy fault record', '$', 'native',
                     recovery='inspect the retained build/reopen logs in the run directory')


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    executable = executable or os.environ.get('GMSH_PYTHON')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK):
        fail('INTERPRETER_NOT_FOUND','configure an absolute Python executable with Gmsh 4.15.x using --gmsh or GMSH_PYTHON')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT','timeout must be in (0,3600]')
    if 'refinement' in document:
        from .refinement import run as refine
        return refine(document, directory, executable=executable, timeout=timeout)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS','choose a fresh directory',str(directory))
    source_hashes = reusableInputs(document)
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json',document); atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    try:
        sources = {}
        if source_hashes:
            path, digest = next(iter(source_hashes.items()))
            with Path(path).open('rb') as stream: data = stream.read(16*1024*1024+1)
            if len(data) > 16*1024*1024: fail('RESOURCE_LIMIT','STEP exceeds 16 MiB')
            if hashlib.sha256(data).hexdigest() != digest: fail('INPUT_CHANGED','STEP changed during capture',path)
            if not data.lstrip().startswith(b'ISO-10303-21;'): fail('UNSUPPORTED_RESOURCE','expected single-file ISO-10303-21 STEP')
            (directory/'source.step').write_bytes(data)
            sources = {'file':path,'retained':'source.step','sha256':digest}
        atomic_json(directory/'sources.json',sources)
        shutil.copyfile(Path(__file__).with_name('native.py'),directory/'worker.py')
        deadline = time.monotonic()+timeout
        for stage in ('build','reopen'):
            try:
                execute([executable,str(directory/'worker.py'),str(directory),stage],directory,stage,deadline-time.monotonic())
            except SchemaxisError:
                if (directory/'native-fault.json').is_file():
                    raise SchemaxisError(native_fault(directory/'native-fault.json'))
                raise
        data = mesh.read(directory/'result.msh'); observed = mesh.inspect(data)
        for dim, name in ((3,'volume.vtu'),(2,'boundary.vtu')): mesh.write_vtu(directory/name,data,dim)
        built = json.loads((directory/'built.json').read_text())
        atomic_json(directory/'mesh-summary.json',summary(prepared,observed,built['cad'],data,built['faceAreas'],
            wall_reports(prepared,built,data,prepared['nodes'][0]),built.get('cadSurfaces')))
        atomic_json(directory/'verification.json',{'artifacts':manifest(directory),'evidence':{n:file_digest(directory/n) for n in EVIDENCE}})
        result = verify(directory,require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED','mesh publication cancelled')
        result.update(status='succeeded'); atomic_json(directory/'result.json',result)
        return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()})
        raise error


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        def read(name): return json.loads((directory/name).read_text())
        if 'refinement' in read('authored.json'):
            from .refinement import verify as verify_refinement
            return verify_refinement(directory)
        def close(a,b): return math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8)
        required = [name for name,_ in FILES]+list(EVIDENCE)+['authored.json','plan.json','result.json','verification.json']
        for name in required:
            p = directory/name; mesh.check(p.is_file() and not p.is_symlink(),'missing regular evidence: '+name)
        prepared = plan(read('authored.json'))
        mesh.check(prepared == read('plan.json'),'effective plan differs from authored input')
        if require_result: mesh.check(read('result.json').get('status') == 'succeeded' and read('result.json').get('verified') is True,'execution incomplete')
        sources = read('sources.json'); source = prepared['nodes'][0]
        if source['filter'] == 'readSTEP':
            p = directory/'source.step'
            mesh.check(p.is_file() and not p.is_symlink(),'missing retained STEP')
            mesh.check(sources == {'file':source['options']['file'],'retained':'source.step','sha256':file_digest(p)},'STEP provenance differs')
        else: mesh.check(sources == {},'unexpected STEP evidence')
        receipt = read('verification.json')
        mesh.check(receipt == {'artifacts':manifest(directory),'evidence':{n:file_digest(directory/n) for n in EVIDENCE}},'publication or native evidence digest differs')
        built, reopened = read('built.json'), read('reopened.json')
        mesh.check(built['stage'] == 'build' and reopened['stage'] == 'reopen' and built['pid'] != reopened['pid'],'missing fresh-process native readback')
        mesh.check(built['plan'] == reopened['plan'] == prepared and built['runtime'] == reopened['runtime'],'native plan/runtime differs')
        mesh.check(reopened['runtime']['version'].split('.')[:2] == ['4','15'],'unsupported observed runtime')
        data = mesh.read(directory/'result.msh'); observed = mesh.inspect(data)
        settings = prepared['nodes'][1]['options']
        from .sizing import verify as verify_sizing
        verify_sizing(built, settings)
        remainder = any(g['dimension'] == 2 and g['tag'] == groups.REMAINDER_TAG for g in observed['groups'])
        mesh.check(remainder or groups.cylinders(settings),'remainder boundary group missing')
        mesh.check(observed['groups'] == groups.expected(settings,remainder),'physical groups differ from authored names')
        mesh.verify_face_groups(data, settings['faceGroups'], groups.cylinders(settings))
        measured_counts = {str(g['tag']):g['triangles'] for g in observed['boundaryGroups']}
        for native in (built['snapshot'],reopened['snapshot']):
            mesh.check(native['boundaryCounts'] == measured_counts,'native physical face membership differs')
        mesh.check(set(built['faceAreas']) == {str(i+3) for i in range(len(settings['faceGroups']))},'CAD face areas missing')
        for index, selector in enumerate(settings['faceGroups']):
            group = next(g for g in observed['boundaryGroups'] if g['tag'] == index+3)
            area = built['faceAreas'][str(group['tag'])]
            mesh.check(math.isfinite(area) and area > 0,'invalid CAD face area')
            analytic_area = geometry.face_area(source,selector) if source['filter'] in geometry.PRIMITIVES else None
            if analytic_area is not None:
                mesh.check(close(area,analytic_area),'CAD face area differs from analytic primitive')
            mesh.check(abs(group['area']-area) <= max(1e-8,selector['areaTolerance']*area),
                       'selected planar mesh area differs from CAD beyond areaTolerance')
        mesh.check(built.get('meshing') == {'algorithm': {'delaunay':1,'hxt':10}[settings['algorithm']],
                   'optimise':int(settings['optimise']), 'elementOrder':1, 'threads':1},
                   'native meshing decision readback differs')
        for native in (built['snapshot'],reopened['snapshot']):
            for key in ('nodes','triangles','tetrahedra','groups'): mesh.check(observed[key] == native[key],'native mesh '+key+' differs')
            for key in ('volume','minimumVolume'): mesh.check(close(observed[key],native[key]),'independent/native volume differs')
            mesh.check(len(native['bounds']) == 6 and all(close(a,b) for a,b in zip(observed['bounds'],native['bounds'])),'native bounds differ')
        from .quality import assess
        quality = assess(data)
        for native in (built['snapshot'], reopened['snapshot']):
            for key, statistic in (('minimumEdgeLength', 'minimum'), ('maximumEdgeLength', 'maximum')):
                mesh.check(close(quality[key][statistic], native[key]), 'independent/native edge lengths differ')
        cad = built['cad']
        mesh.check(math.isfinite(cad['volume']) and cad['volume'] > 0,'invalid CAD volume')
        if source['filter'] in geometry.PRIMITIVES:
            geometry.verify(source,cad,data)
        if source['filter'] == 'box':
            _, expected = geometry.measures(source)
            mesh.check(all(close(a,b) for a,b in zip(observed['bounds'],expected)),'mesh bounds differ from analytic box')
        mesh.check(abs(observed['volume']-cad['volume']) <= settings['volumeTolerance']*cad['volume'],'mesh volume differs from CAD beyond declared tolerance')
        bounds = cad['bounds']
        mesh.check(len(bounds) == 6 and all(math.isfinite(v) for v in bounds),'invalid CAD bounds')
        mesh.check(all(bounds[k]-1e-6 <= xyz[k] <= bounds[k+3]+1e-6 for xyz in data['nodes'].values() for k in range(3)), 'mesh exceeds CAD bounds')
        for dim, name in ((3,'volume.vtu'),(2,'boundary.vtu')): mesh.verify_vtu(directory/name,data,dim)
        mesh.check(read('mesh-summary.json') == summary(prepared,observed,cad,data,built['faceAreas'],
            wall_reports(prepared,built,data,source),built.get('cadSurfaces')),'summary differs from measured mesh')
        return {'verified':True,'artifacts':len(FILES),'runtime':reopened['runtime'],
                'nodes':observed['nodes'],'tetrahedra':observed['tetrahedra'],'volume':observed['volume']}
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError,OverflowError,mesh.ET.ParseError) as error:
        fail('VERIFICATION_FAILED','missing or invalid mesh evidence: '+str(error))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
