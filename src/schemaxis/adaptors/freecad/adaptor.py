# Copyright (C) 2026 David L F Gaden
"""Host-safe FreeCAD solid declarations, planning, dispatch and verification."""
import copy
import hashlib
import json
import math
import os
import time
from pathlib import Path
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.runners import Interpreter
from schemaxis.core.faults import SchemaxisError, Fault
from schemaxis.artifacts import atomic_json, runtime_archive
from schemaxis.dispatch import cancellation_requested
from .process import SubprocessRunner
from schemaxis.errors import fail, keys
from schemaxis.pipeline import name
from schemaxis.artifacts import file_digest

VECTOR = {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3, 'default': [0, 0, 0]}
LENGTH = {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True, 'maximum': 100000}

def declaration(native, options, inputs=()):
    return {'native': native, 'kinds': ['solid'],
            'options': {k: {'value': v} for k, v in options.items()},
            'inputs': {k: {'required': True, 'kind': 'solid'} for k in inputs}}

DECLARATIONS = {
    'box': declaration('Part::Box', {'length': {**LENGTH, 'default': 10}, 'width': {**LENGTH, 'default': 10},
                                    'height': {**LENGTH, 'default': 10}, 'origin': VECTOR}),
    'cylinder': declaration('Part::Cylinder', {'radius': {**LENGTH, 'default': 5}, 'height': {**LENGTH, 'default': 10},
                                             'origin': VECTOR, 'axis': {**VECTOR, 'default': [0, 0, 1]}}),
    'cut': declaration('Part::Cut', {}, ('base', 'tool')),
    'fuse': declaration('Part::Fuse', {}, ('base', 'tool')),
}
from .operations import extend, validate as validate_geometry
DECLARATIONS.update(extend(declaration, LENGTH, VECTOR))

FILES = [('model.step', 'cad'), ('model.stl', 'geometry'), ('model.FCStd', 'cadScene')]


def output_files(prepared):
    return FILES + ([('measurements.json', 'text')] if prepared.get('measurements') else [])


def artifact_units(kind):
    return 'per-measurement' if kind == 'text' else 'mm'


def plan(document, *, allow_profile=False, source=None):
    """`source` supplies importSTEP bytes: the authored path by default, retained copies in saved verification."""
    from schemaxis.documents import resolve_document
    document, _ = resolve_document(copy.deepcopy(document))
    keys(document, ('version', 'units', 'nodes', 'output', 'linearDeflection', 'dimensions', 'definitions', 'settings', 'measurements', 'designStudy', 'parameters', 'spreadsheet'), '$')
    if document.get('version') != 'schemaxis.freecad/1':
        fail('UNSUPPORTED_VERSION', 'expected schemaxis.freecad/1')
    if document.get('units', 'mm') != 'mm':
        fail('UNSUPPORTED_UNITS', 'this CAD contract uses millimetres')
    nodes = document.get('nodes')
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 200:
        fail('INVALID_DOCUMENT', 'provide 1 to 200 CAD nodes')
    from . import parameters as parameter_policy
    spreadsheet = None
    if 'spreadsheet' in document and 'parameters' in document:
        fail('CONFLICTING_PARAMETERS', 'Choose a native spreadsheet or VarSet parameters for this document', '$.spreadsheet')
    if 'spreadsheet' in document:
        from .spreadsheet import prepare as prepare_spreadsheet
        spreadsheet, parameters = prepare_spreadsheet(document['spreadsheet'])
    else:
        parameters = parameter_policy.prepare(document['parameters']) if 'parameters' in document else None
    if parameters is not None and 'designStudy' in document:
        fail('UNSUPPORTED_PARAMETER_STUDY', 'Native parameters support batch variants; designStudy is not supported', '$.designStudy')
    used_parameters, binding_count = set(), 0
    prepared, seen, kinds = [], set(), {}
    for node in nodes:
        keys(node, ('id', 'filter', 'options', 'inputs', 'drive'), '$.nodes')
        identity = name(node.get('id'), '$.nodes.id')
        if identity in seen:
            fail('DUPLICATE_NODE', 'CAD node is duplicated', identity)
        operation = node.get('filter')
        if not isinstance(operation, str) or operation not in DECLARATIONS:
            fail('UNKNOWN_FILTER', 'unsupported CAD operation', identity)
        declaration = DECLARATIONS[operation]
        raw_options = copy.deepcopy(node.get('options', {}))
        drives = parameter_policy.drive(node, parameters, used_parameters, spreadsheet=spreadsheet) if 'drive' in node else None
        if drives is not None:
            binding_count += len(drives)
            if binding_count > 128:
                fail('INVALID_BINDING', 'Use at most 128 native length bindings', '$.nodes')
            values = {k:v['value'] for k,v in parameters.items()}
            for option,binding in drives.items():
                raw_options[option] = parameter_policy.evaluate(binding, values, identity+'.drive.'+option)
        options = validate_arguments({k: v['value'] for k, v in declaration['options'].items()}, raw_options,
                                     **({'location': identity+'.options'} if operation in ('importSTEP','importMesh') else {}))
        validate_geometry(operation, options, identity)
        imported = None
        if operation == 'importSTEP':
            from .step_import import prepare as prepare_import
            imported = prepare_import(identity, options, source)
        elif operation == 'importMesh':
            from .mesh_import import prepare as prepare_mesh
            imported = prepare_mesh(identity, options, source)
        inputs = node.get('inputs', {})
        keys(inputs, tuple(declaration['inputs']), identity)
        if not {k for k,v in declaration['inputs'].items() if v.get('required')} <= set(inputs):
            fail('INVALID_DEPENDENCY', 'CAD inputs require every declared port', identity)
        for port, value in inputs.items():
            spec = declaration['inputs'][port]
            sources = value if spec.get('multiple') else [value]
            if (not isinstance(sources, list) or not spec.get('minItems', 1) <= len(sources) <= spec.get('maxItems', 1)
                    or any(not isinstance(source, str) or source not in seen for source in sources)):
                fail('INVALID_DEPENDENCY', 'CAD inputs must reference earlier nodes within the declared port limits', identity, port=port)
            if len(set(sources)) != len(sources):
                fail('INVALID_DEPENDENCY', 'CAD list inputs must be distinct', identity, port=port)
            for source in sources:
                if kinds[source] != spec['kind']:
                    fail('TYPE_MISMATCH', 'CAD input kind differs', identity, port=port, actual=kinds[source])
        kinds[identity] = declaration['kinds'][0]
        prepared.append({'id': identity, 'filter': operation, 'options': options, 'inputs': inputs})
        if operation=='draftProfile':
            from .drafting import prepare as prepare_drafting
            prepare_drafting(prepared[-1])
        if imported is not None:
            prepared[-1].update(imported)
        if drives is not None:
            prepared[-1]['drive'] = drives
        seen.add(identity)
    if spreadsheet is not None:
        from .spreadsheet import check_used
        check_used(spreadsheet, [binding for node in prepared for binding in node.get('drive', {}).values()], parameters)
    elif parameters is not None and used_parameters != set(parameters):
        fail('INVALID_PARAMETER', 'Every native parameter must drive at least one supported option', '$.parameters')
    output = document.get('output')
    if not isinstance(output, str) or output not in seen:
        fail('INVALID_SELECTION', 'output must name a CAD node')
    if kinds[output] != 'solid' and not (allow_profile and kinds[output] == 'profile'):
        fail('TYPE_MISMATCH', 'CAD output must select a solid, not a sketch', output)
    deflection = validate_arguments({'value': {'type': 'number', 'minimum': 0.001, 'maximum': 1, 'default': 0.1}},
                                    {'value': document.get('linearDeflection', 0.1)})['value']
    result = {'version': 'schemaxis.freecad.plan/1', 'units': 'mm', 'nodes': prepared,
            'output': output, 'linearDeflection': deflection, 'expectedPublications': 3 if kinds[output] == 'solid' else 1}
    if parameters is not None:
        result['parameters'] = parameters
    if spreadsheet is not None:
        result['spreadsheet'] = spreadsheet
    if 'measurements' in document:
        from .measurements import prepare
        result['measurements'] = prepare(document['measurements'], kinds)
        result['expectedPublications'] += 1
    if 'designStudy' in document and any(n['filter'] in ('body','pad','pocket') for n in prepared):
        fail('UNSUPPORTED_BODY_STUDY','PartDesign supports batch variants, not scalar designStudy')
    if 'designStudy' in document:
        from .design_study import prepare
        result['designStudy'] = prepare(document['designStudy'], document, result)
        result['expectedPublications'] += 2
    from .part_design import prepare as prepare_body
    if any(n['filter']=='body' for n in prepared) and any(n['filter']=='draftProfile' for n in prepared):
        fail('UNSUPPORTED_BODY_PROFILE','Draft profiles currently feed Part features; the Body bridge requires a native Sketcher profile','$.nodes')
    from .mesh_source import MAX_FACETS
    if sum(n.get('source',{}).get('facets',0) for n in prepared if n['filter']=='importMesh')>MAX_FACETS:
        fail('RESOURCE_LIMIT','Use at most 20000 STL facets across one document','$.nodes',limit=MAX_FACETS)
    prepare_body(result)
    if any(n['filter'] == 'body' for n in prepared) and any(n['filter'] in ('importSTEP','importMesh') for n in prepared) and not result.get('partDesign',{}).get('seeds'):
        fail('UNSUPPORTED_SOURCE', 'Checked external imports cannot share a document with a PartDesign Body; Body geometry only feeds its '
             'own feature chain', next(n['id'] for n in prepared if n['filter'] in ('importSTEP','importMesh')))
    return result


def input_schema(ports):
    from schemaxis.schema import object_schema, NAME
    return object_schema({key: ({'type': 'array', 'items': NAME,
                                'minItems': spec['minItems'], 'maxItems': spec['maxItems'],
                                'uniqueItems': True} if spec.get('multiple') else NAME)
                          for key, spec in ports.items()}, [k for k,v in ports.items() if v.get('required')])


def schema():
    from schemaxis.schema import object_schema, argument_schema, DRAFT, NAME, arguments_schema, json_value_schema
    from .measurements import DECLARATION as measurements
    from .design_study import ARGUMENTS as study
    from . import spreadsheet as spreadsheet_policy
    from . import parameters as parameter_policy
    alternatives = []
    for operation, definition in DECLARATIONS.items():
        options = arguments_schema({k: v['value'] for k, v in definition['options'].items()})
        alternatives.append(object_schema({'id': NAME, 'filter': {'const': operation},
            'options': options,
            'inputs': input_schema(definition['inputs']),
            **({'drive':parameter_policy.drive_schema(operation)} if operation in parameter_policy.TARGETS else {})},
            ['id', 'filter'] + (['inputs'] if any(v.get('required') for v in definition['inputs'].values()) else []) + (['options'] if options.get('required') else [])))
    return {'$schema': DRAFT, '$defs': {'json': json_value_schema()},
        'not':{'required':['parameters','spreadsheet']}, **object_schema({'version': {'const': 'schemaxis.freecad/1'}, 'units': {'const': 'mm'},
        'nodes': {'type': 'array', 'items': {'oneOf': alternatives}, 'minItems': 1, 'maxItems': 200},
        'output': NAME, 'linearDeflection': {'type': 'number', 'minimum': 0.001, 'maximum': 1},
        'measurements': argument_schema(measurements),
        'designStudy': arguments_schema(study),
        'parameters': parameter_policy.schema(),
        'spreadsheet': spreadsheet_policy.schema(),
        **{key: {'$ref': '#/$defs/json'} for key in ('definitions', 'dimensions', 'settings')}},
        ['version', 'nodes', 'output'])}


def run(document, directory, *, executable=None, timeout=300):
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout <= 0:
        fail('INVALID_TIMEOUT', 'CAD timeout must be finite and positive')
    # One whole-run deadline covers planning (the STEP source scan), capture, native stages and verification.
    from schemaxis.dispatch import execution_deadline
    with execution_deadline(timeout):
        return _run(document, directory, executable=executable, timeout=timeout, deadline=time.monotonic()+timeout)


def _run(document, directory, *, executable, timeout, deadline):
    prepared = plan(document)
    executable = executable or os.environ.get('FREECAD_CMD')
    if not executable or not Path(executable).is_absolute() or not Path(executable).is_file():
        fail('INTERPRETER_NOT_FOUND', 'provide an absolute FreeCAD command-line executable with --freecad')
    if 'designStudy' in document:
        from .design_study import run as study
        return study(document, directory, executable=executable, timeout=timeout)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'choose a fresh output directory', str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json', document)
    atomic_json(directory/'plan.json', prepared)
    atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
    try:
        # Capture failures leave a failed result like every later stage.
        sources = capture(prepared, directory)
        atomic_json(directory/'sources.json', sources)
        snapshot = runtime_archive()
        (directory/'runtime.zip').write_bytes(snapshot)
        runtime = Interpreter('freecad', str(Path(executable).resolve()))
        runner = SubprocessRunner(runtime, directory, timeout=timeout, environment={'QT_QPA_PLATFORM': 'offscreen'})
        from contextlib import ExitStack
        from .helix import active as helical
        with ExitStack() as stack:
            from schemaxis.configuration import location_context
            stack.enter_context(location_context({'freecad':runtime.executable}))
            admission=None
            for stage in ('build', 'reopen'):
                stage_directory=directory
                if stage=='reopen' and helical(prepared):
                    from .helix_authority import admit
                    admission=stack.enter_context(admit(directory,prepared,sources))
                    stage_directory=admission.private
                if cancellation_requested(): fail('RUNNER_CANCELLED', 'CAD execution cancelled before a native stage')
                runner.timeout = deadline-time.monotonic()
                if runner.timeout <= 0: fail('RUNNER_TIMED_OUT', 'CAD execution exhausted its total timeout')
                source = (f'import sys\nsys.path.insert(0, {str(directory/"runtime.zip")!r})\n'
                          f'from schemaxis.adaptors.freecad.native import {stage}\n'
                          'from schemaxis.native_boundary import execute_guarded\n'
                          f'execute_guarded({stage}, {str(stage_directory)!r})\n')
                try:report = runner(source)
                except Exception as error:
                    if isinstance(error,SchemaxisError) and error.fault.code in ('RUNNER_CANCELLED','RUNNER_TIMED_OUT'):raise
                    if stage_directory!=directory and (stage_directory/'native-fault.json').exists():
                        from .saved_checks import read_json
                        atomic_json(directory/'native-fault.json',read_json(stage_directory,'native-fault.json',limit=128*1024))
                    raise
                atomic_json(directory/(stage+'-submission.json'), report.to_dict())
                if (stage_directory/'native-fault.json').exists():
                    raise SchemaxisError(Fault(**json.loads((stage_directory/'native-fault.json').read_text())))
                if stage=='reopen' and admission is not None:admission.publish_reopen()
            result = verify(directory, require_result=False)
            if cancellation_requested(): fail('RUNNER_CANCELLED', 'CAD publication cancelled')
            if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'CAD verification exhausted its total timeout')
            result.update(status='succeeded', runtimeSha256=hashlib.sha256(snapshot).hexdigest())
            if admission is not None:admission.check_current(prepared,sources)
            atomic_json(directory/'result.json', result)
            return result
    except Exception as error:
        if (directory/'native-fault.json').exists():
            error=SchemaxisError(Fault(**json.loads((directory/'native-fault.json').read_text())))
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict() if isinstance(error,SchemaxisError) else {'message':str(error)}})
        raise error


def capture(prepared, directory):
    """Retain run-owned copies; importSTEP bytes must be exactly the planned bytes."""
    import shutil
    from .step_source import read_bounded, admit
    sources, legacy, imports, meshes = {}, 0, 0, 0
    for node in prepared['nodes']:
        if node['filter'] == 'readSTEP':
            source = Path(node['options']['file']).absolute()
            if not source.is_file():
                fail('RESOURCE_NOT_FOUND', 'STEP input is absent', str(source))
            local = directory/('source-'+str(legacy)+'.step')
            legacy += 1
            shutil.copyfile(source, local)
            digest = file_digest(local)
            if file_digest(source) != digest:
                fail('INPUT_CHANGED', 'STEP input changed during capture', str(source))
            sources[node['id']] = {'file':str(source),'retained':str(local),'sha256':digest}
        elif node['filter'] == 'importSTEP':
            planned, location = node['source'], node['id']+'.options.file'
            data = read_bounded(planned['path'], location)
            if hashlib.sha256(data).hexdigest() != planned['sha256']:
                fail('INPUT_CHANGED', 'STEP input changed after planning; plan and run again', location)
            local = directory/('import-'+str(imports)+'.step')
            imports += 1
            local.write_bytes(data)
            # Rescan the retained bytes immediately before any native process can read them.
            facts = admit(read_bounded(local, location, code='VERIFICATION_FAILED'), location)
            if any(facts[k] != planned[k] for k in planned if k != 'path'):
                fail('INPUT_CHANGED', 'Retained STEP copy differs from the planned source', location)
            sources[node['id']] = {'file': planned['path'], 'retained': str(local), 'sha256': planned['sha256'],
                                   'bytes': planned['bytes'], 'route': 'importSTEP'}
        elif node['filter']=='importMesh':
            from .mesh_import import geometry
            planned,location=node['source'],node['id']+'.options.file'
            data=read_bounded(planned['path'],location)
            if hashlib.sha256(data).hexdigest()!=planned['sha256']:
                fail('INPUT_CHANGED','STL input changed after planning; plan and run again',location)
            local=directory/('mesh-import-'+str(meshes)+'.stl');meshes+=1;local.write_bytes(data)
            facts,_,_=geometry(read_bounded(local,location,code='VERIFICATION_FAILED'),node['options'],location)
            if any(facts[k]!=planned[k] for k in facts):
                fail('INPUT_CHANGED','Retained STL differs from its planned geometry',location)
            sources[node['id']]={'file':planned['path'],'retained':str(local),'sha256':planned['sha256'],
                                 'bytes':planned['bytes'],'route':'importMesh'}
    return sources


def close(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return type(a) in (int, float) and type(b) in (int, float) and math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-6)


def _verify(directory, require_result=True):
    directory = Path(directory).absolute()
    from .saved_checks import read_json
    document = read_json(directory, 'authored.json')
    if 'designStudy' in document:
        from .design_study import verify as verify_study
        return verify_study(directory)
    from .saved_checks import records, verify_sources, verify_saved_document, verify_imports, verify_exports
    from .step_source import CapturedSources
    from schemaxis.run_paths import owned_path
    captured = records(directory)
    # Replay planning from retained bytes bound to the capture record; never reopen originals.
    prepared = plan(document, source=CapturedSources(directory, captured))
    if read_json(directory, 'plan.json') != prepared:
        fail('VERIFICATION_FAILED', 'CAD plan differs from input')
    if require_result and read_json(directory, 'result.json').get('verified') is not True:
        fail('INCOMPLETE_EXECUTION', 'CAD job did not complete')
    verify_sources(directory, prepared, captured)
    receipt = read_json(directory, 'verification.json')
    built = read_json(directory, 'built.json')
    from .saved_checks import require_hardened
    require_hardened(built, receipt, directory, prepared=prepared)
    from .helix import active as helical
    authority=None
    if helical(prepared):
        from .helix_authority import current,admit
        authority=current(directory,prepared,captured)
        if authority is None:
            with admit(directory,prepared,captured):return _verify(directory,require_result=require_result)
        built=read_json(authority.private,'built.json')
        receipt=read_json(authority.private,'verification.json')
        from .helix_authority import verify_observations
        verify_observations(prepared,built,receipt,authority.trusted)
    checked=authority.private if authority is not None else directory
    if receipt.get('status') != 'succeeded' or receipt.get('units') != 'mm' or not receipt.get('freshProcess'):
        fail('VERIFICATION_FAILED', 'CAD reopening evidence is incomplete')
    if receipt.get('definition') != prepared or built.get('definition') != prepared:
        fail('VERIFICATION_FAILED', 'native CAD definition differs')
    if 'parameters' in prepared:
        from .parameters import verify_observation, verify_saved, saved_length
        first, second = built.get('parameterObservations'), receipt.get('parameterObservations')
        verify_observation(prepared, first)
        verify_observation(prepared, second)
        saved = verify_saved(prepared, checked/'model.FCStd')
        for identity, parameter in prepared['parameters'].items():
            if 'spreadsheet' in prepared:
                from .parameters import quantity_agrees
                valid=all(quantity_agrees(record['parameters'][identity]['value'],parameter['value']) for record in (first,second,saved))
            else:
                valid=(first['parameters'][identity]['value']==parameter['value']
                       and second['parameters'][identity]['value']==saved_length(parameter['value'])
                       and saved['parameters'][identity]['value']==saved_length(parameter['value']))
            if not valid:
                fail('VERIFICATION_FAILED','Native parameter values differ from authored intent',identity)
        if any(first[key] != second[key] or saved[key] != second[key] for key in ('object','expressions')):
            fail('VERIFICATION_FAILED', 'Native parameter relationships differ between build, saved file and reopening')
    if 'partDesign' in prepared:
        from .part_design import verify_observation as verify_body
        from .part_design_saved import verify as verify_saved_body
        first,second=built.get('partDesignObservations'),receipt.get('partDesignObservations')
        verify_body(prepared,first);verify_body(prepared,second)
        def structural(record):
            value=copy.deepcopy(record)
            for feature in value['features'].values():
                feature.pop('length',None)
                feature.pop('edgeInventory',None)
                feature.pop('faceInventory',None)
            for profile in value['profiles'].values():
                profile.pop('faceInventory',None)
                for constraint in profile['constraints']:constraint.pop('value')
            return value
        from .history import equivalent
        if not equivalent(structural(first),structural(second)):fail('VERIFICATION_FAILED','Body history changed after native reopening')
        saved=verify_saved_body(prepared,checked/'model.FCStd')
        comparable=copy.deepcopy(second)
        for profile in comparable['profiles'].values():profile.pop('solver')
        if not equivalent(structural(saved),structural(comparable)):fail('VERIFICATION_FAILED','Saved Body history differs from native observations')
    from .selections import verify as verify_selections
    verify_selections(prepared, built.get('selections', {}), receipt.get('selections', {}))
    from .measurements import verify as verify_measurements, evaluate
    publication = (read_json(checked, 'measurements.json') if prepared.get('measurements')
                   else evaluate(prepared, {}))
    verify_measurements(prepared, built.get('measurementObservations', {}),
                        receipt.get('measurementObservations', {}), publication)
    for key in ('native', 'step'):
        observed = receipt.get(key, {})
        if observed.get('valid') is not True or observed.get('solids') != 1 or observed.get('volume', 0) <= 0:
            fail('VERIFICATION_FAILED', 'CAD output must be one valid positive-volume solid')
        for measure in ('volume', 'area', 'bounds'):
            if key=='step' and helical(prepared) and measure!='bounds':continue
            if not close(observed.get(measure), built['shape'].get(measure)):
                fail('VERIFICATION_FAILED', 'CAD export or reopening changed geometry', key, measure=measure)
    mesh = receipt.get('mesh', {})
    if mesh.get('solid') is not True or mesh.get('facets', 0) <= 0:
        fail('VERIFICATION_FAILED', 'STL is not watertight')
    if not close(mesh.get('bounds'), built['shape']['bounds']):
        # Chordal meshes may miss extrema by at most the requested linear deflection.
        if not isinstance(mesh.get('bounds'), list) or len(mesh['bounds']) != 6 or any(not math.isfinite(a) or abs(a-b) > prepared['linearDeflection']*1.1+1e-5 for a,b in zip(mesh['bounds'],built['shape']['bounds'])):
            fail('VERIFICATION_FAILED', 'STL bounds exceed tessellation tolerance')
    verify_imports(prepared, built, receipt)
    # The host volume, not native Mesh.Volume, now carries the established 0.5 % ceiling.
    export_checks = verify_exports(checked, prepared, built, receipt,
                                   authority=authority.trusted if authority is not None else None)
    artifacts = receipt.get('artifacts', [])
    files = output_files(prepared)
    if len(artifacts) != len(files):
        fail('VERIFICATION_FAILED', 'CAD artifact membership differs')
    for artifact, (filename, kind) in zip(artifacts, files):
        path = directory/filename
        if (not isinstance(artifact.get('file'), str) or owned_path(directory, artifact['file']) != path or artifact.get('kind') != kind
                or artifact.get('units') != artifact_units(kind) or path.is_symlink() or path.resolve().parent != directory.resolve()
                or (authority.snapshots[filename].sha256 if authority is not None
                    else file_digest(path)) != artifact.get('sha256')):
            fail('VERIFICATION_FAILED', 'CAD artifact path, units or digest differs', filename)
    verify_saved_document(checked/'model.FCStd', prepared,
                          authority.private_captured if authority is not None else captured)
    if any(n['filter'] in ('importMesh','draftProfile','bodySeed') for n in prepared['nodes']):
        from .part_reconstruction import verify as verify_part
        local=(authority.trusted['bodyLocalExportEvidence'] if authority is not None
               else verify_part(directory/'model.FCStd',prepared,captured))
        if prepared.get('partDesign',{}).get('seeds'):
            from .history import equivalent
            if not isinstance(local,dict) or any(not equivalent(record.get('bodyLocalExportEvidence'),local) for record in (built,receipt)):
                fail('VERIFICATION_FAILED','Body-local source facts differ from fresh trusted reconstruction')
    if any(n['filter']=='bodyDraft' for n in prepared['nodes']):
        from .draft_verify import verify as verify_draft_selection
        verify_draft_selection(checked/'model.FCStd',prepared,first,second,saved)
    if authority is not None:authority.check_current(prepared,captured)
    return {'verified': True, 'artifacts': len(artifacts), 'volumeMM3': (receipt['exportEvidence']['precision']['native']['fine']['signedVolume']
            if authority is not None else receipt['native']['volume']), 'runtime': receipt['runtime'],
            'exportChecks': export_checks}


def verify(directory, require_result=True):
    """Retained evidence failures use the public structured fault boundary."""
    try:
        return _verify(directory, require_result=require_result)
    except SchemaxisError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError) as error:
        fail('VERIFICATION_FAILED', 'Missing or malformed CAD evidence: ' + str(error), str(directory))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
