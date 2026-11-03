# Copyright (C) 2026 David L F Gaden
"""Operation handoff through verified durable artifacts, with optional scheduling."""
import copy
import json
from dataclasses import replace
from pathlib import Path
from .core.faults import SchemaxisError
from .errors import fail, keys
from .artifacts import atomic_json
from .adaptors import registry
from .adaptors.registry import run
from .pipeline import name
from .storage import prepare_run_directory


def dependencies(value):
    if isinstance(value, dict):
        from .adaptor_runtime import output_reference
        if '$artifact' in value or output_reference(value):
            yield value
        for child in value.values():
            yield from dependencies(child)
    elif isinstance(value, list):
        for child in value:
            yield from dependencies(child)


def validate(document, *, allow_unfilled=False):
    if not allow_unfilled:
        from .unfilled import reject_unfilled
        reject_unfilled(document)
    keys(document, ('version', 'operations', 'execution', 'dimensions', 'definitions', 'settings', 'axes', 'maxStates'), '$')
    if document.get('version') != 'schemaxis.workflow/1':
        fail('UNSUPPORTED_VERSION', 'expected schemaxis.workflow/1')
    from .adaptor_runtime import workflow_inputs
    document = workflow_inputs(document, defer_unfilled=allow_unfilled)
    operations = document.get('operations')
    if not isinstance(operations, list) or not operations:
        fail('EMPTY_WORKFLOW', 'workflow needs operations')
    seen = set()
    producers = {}
    for operation in operations:
        keys(operation, ('id', 'document', 'execution'), '$.operations')
        identity = name(operation.get('id'), '$.operations.id')
        if identity in seen:
            fail('DUPLICATE_OPERATION', 'operation identity is duplicated', identity)
        if not isinstance(operation.get('document'), dict):
            fail('INVALID_DOCUMENT', 'operation needs a pipeline document', identity)
        for reference in dependencies(operation['document']):
            from .adaptor_runtime import output_reference
            is_value = output_reference(reference)
            keys(reference, ('$value', 'path', 'visit', 'artifact') if is_value else ('$artifact', 'index'), identity)
            source = reference['$value'] if is_value else reference['$artifact']
            index = reference.get('visit', 0) if is_value else reference.get('index')
            if not isinstance(source, str) or source not in seen:
                fail('UNAVAILABLE_OPERATION', 'artifact must reference an earlier operation', identity, source=source)
            hook = None if is_value else registry.route_hook(producers[source], 'validateHandoff', legacy=True)
            if hook: hook(producers[source], operation['document'], identity)
            if type(index) is not int or index < 0:
                fail('INVALID_SELECTION', 'artifact index must be nonnegative', identity)
        version = operation['document'].get('version')
        supported = tuple(v for v, (_, route) in registry.routes().items() if route.get('workflow'))
        # Preserve legacy unversioned input validation and error precedence.
        if 'version' in operation['document'] and version not in supported:
            fail('UNSUPPORTED_PROVIDER',
                 'this document version is not supported inside a workflow; run supported standalone adaptors directly',
                 identity + '.document.version', version=version, supported=list(supported))
        seen.add(identity)
        producers[identity] = operation['document']
    return copy.deepcopy(operations)


def scheduled(document, operations):
    from .adaptor_runtime import output_reference
    return ('execution' in document or any(output_reference(ref) for op in operations for ref in dependencies(op['document']))
            or any('execution' in op or registry.resolve(op['document'], legacy=True)[1].get('scheduled') for op in operations))


def execute(document, directory, *, roots=None, blender=None, freecad=None, timeout=300, resume=False, locations=None):
    from .configuration import location_context
    roots, locations = copy.deepcopy(roots), copy.deepcopy(locations)
    overrides = {'roots': roots, 'blender': blender, 'freecad': freecad,
                 **{key: value for key, value in (locations or {}).items() if value is not None}}
    with location_context(overrides):
        return _execute(document, directory, roots=roots, blender=blender, freecad=freecad,
                        timeout=timeout, resume=resume, locations=locations)


def _execute(document, directory, *, roots, blender, freecad, timeout, resume, locations):
    from .unfilled import reject_unfilled
    reject_unfilled(document)
    if study_required(document):
        from .adaptor_runtime import execute as execute_study
        def native(value, target, *, timeout):
            result = execute(value, target, roots=roots, blender=blender, freecad=freecad,
                             timeout=timeout, resume=resume and Path(target).exists(), locations=locations)
            atomic_json(Path(target)/'verification.json', publication_receipt(target))
            return result
        return execute_study(document, directory, {}, native, verify_study_child, inspect_plan,
                             timeout=timeout, workflow=True, resume=resume)
    operations = validate(document)
    if resume or scheduled(document, operations):
        from .parallel import execute as parallel_execute
        return parallel_execute(document, directory, roots=roots, blender=blender, freecad=freecad, timeout=timeout, resume=resume, locations=locations)
    directory = prepare_run_directory(directory, document)
    from .schema_snapshots import capture_run
    capture_run(directory, document)
    results, handoffs = [], []
    status = {'status': 'incomplete', 'verified': False, 'operations': results, 'handoffs': handoffs}
    atomic_json(directory / 'result.json', status)
    try:
        for operation in operations:
            def resolve(value):
                if isinstance(value, list):
                    return [resolve(v) for v in value]
                if not isinstance(value, dict):
                    return value
                if '$artifact' in value:
                    source = value['$artifact']
                    previous = directory / source
                    from .parallel import verify_native
                    from .dispatch import execution_deadline
                    with execution_deadline(timeout):
                        receipt = verify_native(previous, json.loads((previous/'authored.json').read_text()))
                    index = value['index']
                    if index >= len(receipt['artifacts']):
                        fail('INVALID_SELECTION', 'artifact index exceeds output count', source, index=index)
                    artifact = receipt['artifacts'][index]
                    if artifact.get('kind', artifact.get('identity', {}).get('kind')) not in registry.resolve(operation['document'], legacy=True)[1].get('acceptedArtifacts', []):
                        fail('TYPE_MISMATCH', 'data reader handoff requires a geometry or glTF artifact', source)
                    handoffs.append({'from': source, 'to': operation['id'], 'index': index,
                                     'file': artifact['file'], 'verification': 'source receipt rechecked'})
                    return artifact['file']
                return {k: resolve(v) for k, v in value.items()}
            effective = resolve(operation['document'])
            result = run(effective, directory / operation['id'], locations=locations, roots=roots, blender=blender, freecad=freecad, timeout=timeout)
            results.append({'id': operation['id'], **result})
            atomic_json(directory / 'result.json', status)
        from .publication_metadata import publish_artifacts
        publications = [artifact for operation in operations
                        for artifact in json.loads((directory/operation['id']/'verification.json').read_text())['artifacts']]
        publish_artifacts(directory, publications)
        status.update(status='succeeded', verified=True)
        atomic_json(directory / 'result.json', status)
        return status
    except Exception as error:
        status.update(status='failed', verified=False)
        status['fault'] = error.to_dict().get('fault') if hasattr(error, 'to_dict') else {'message': str(error)}
        atomic_json(directory / 'result.json', status)
        raise


def inspect_plan(document):
    from .unfilled import reject_unfilled
    reject_unfilled(document)
    if study_required(document):
        from .adaptor_runtime import InputProgram
        program = InputProgram(document, workflow=True)
        return {'version': 'schemaxis.study.plan/1', 'states': program.count, 'bindings': program.bindings,
                'visits': [{**visit, 'plan': inspect_plan(visit['document'])} for visit in program.visits()]}
    operations = validate(document)
    result = []
    for operation in operations:
        try:
            plan = provisional_plan(operation['document'])
        except SchemaxisError as error:
            # Keep adaptor-relative coordinates, with their operation of origin.
            # Two operations can contain nodes with exactly the same identity.
            raise SchemaxisError(replace(error.fault, observed={
                **error.fault.to_dict()['observed'], 'workflowOperation': operation['id']})) from error
        entry = {'id': operation['id'], 'provisionalPlan': plan}
        if registry.resolve(operation['document'], legacy=True)[1].get('graph'):
            entry['artifactReferences'] = list(dependencies(operation['document']))
        result.append(entry)
    if scheduled(document, operations):
        from .parallel import work_items
        _, budget, jobs = work_items(document)
        return {'version': 'schemaxis.workflow.plan/2', 'operations': result, 'budget': budget, 'jobs': jobs}
    return {'version': 'schemaxis.workflow.plan/1', 'operations': result,
            'artifactResolution': 'deferred until producer receipts are verified'}


def provisional_plan(document):
    """Plan concrete inputs only; a future publication is not a synthetic path.

    Workflow membership, reference shapes and ordering are checked by validate.
    Adaptor-specific validation needs the actual verified producer outputs and
    is repeated by the scheduler before dispatch, or by the serial adaptor run.
    """
    registry.resolve(document, legacy=True)
    references = list(dependencies(document))
    if references:
        return {'status': 'deferred', 'reason': 'verified producer artifacts or values required',
                'references': copy.deepcopy(references),
                'validation': 'adaptor input and resource validation deferred until producer receipts are verified'}
    return registry.plan(document, legacy=True)


def verify(directory):
    directory = Path(directory).resolve()
    from .schema_snapshots import verify_run
    verify_run(directory)
    from .adaptor_runtime import is_common, verify as verify_study
    if is_common(directory):
        return verify_study(directory, json.loads((directory/'authored.json').read_text()), {},
                            verify_study_child, workflow=True)
    if json.loads((directory/'result.json').read_text()).get('executionVersion') == 2:
        from .parallel import verify as parallel_verify
        return parallel_verify(directory)
    authored = json.loads((directory / 'authored.json').read_text())
    operations = validate(authored)
    result = json.loads((directory / 'result.json').read_text())
    if result.get('status') != 'succeeded' or result.get('verified') is not True:
        fail('INCOMPLETE_EXECUTION', 'workflow did not complete', str(directory))
    if [o.get('id') for o in result.get('operations', [])] != [o['id'] for o in operations]:
        fail('VERIFICATION_FAILED', 'workflow operation membership differs', str(directory))
    receipts, handoffs = {}, []
    count = 0
    for operation, outcome in zip(operations, result['operations']):
        identity = operation['id']
        target = directory / identity
        def resolve(value):
            if isinstance(value, list):
                return [resolve(v) for v in value]
            if isinstance(value, dict):
                if '$artifact' in value:
                    source, index = value['$artifact'], value['index']
                    if index >= len(receipts[source]['artifacts']):
                        fail('VERIFICATION_FAILED', 'handoff artifact is absent', identity)
                    artifact = receipts[source]['artifacts'][index]
                    if artifact.get('kind', artifact.get('identity', {}).get('kind')) not in registry.resolve(operation['document'], legacy=True)[1].get('acceptedArtifacts', []):
                        fail('VERIFICATION_FAILED', 'handoff is not geometry or glTF', identity)
                    handoffs.append({'from': source, 'to': identity, 'index': index,
                                     'file': artifact['file'], 'verification': 'source receipt rechecked'})
                    return artifact['file']
                return {k: resolve(v) for k, v in value.items()}
            return value
        effective = resolve(operation['document'])
        retained = json.loads((target / 'authored.json').read_text())
        if retained != effective:
            fail('VERIFICATION_FAILED', 'operation input differs from workflow request', identity)
        hook = registry.route_hook(effective, 'verifyLegacy', legacy=True)
        if hook:
            receipt = hook(target, effective, outcome, identity)
        else:
            from .parallel import verify_native
            receipt = verify_native(target, effective)
        receipts[identity] = receipt
        from .publication_metadata import verify as verify_metadata
        verify_metadata(target, receipt['artifacts'])
        count += len(receipt['artifacts'])
    if handoffs != result.get('handoffs'):
        fail('VERIFICATION_FAILED', 'workflow handoff evidence differs', str(directory))
    verify_metadata(directory, [artifact for receipt in receipts.values() for artifact in receipt['artifacts']])
    return {'verified': True, 'operations': len(operations), 'artifacts': count}


def study_required(document):
    from .adaptor_runtime import walk, requires_common, pending
    if not isinstance(document, dict): fail('INVALID_DOCUMENT', 'workflow must be an object')
    if not isinstance(document.get('operations', []), list): fail('INVALID_DOCUMENT', 'operations must be a list')
    if document.get('axes') or any('$analytic' in value for key in ('dimensions','definitions','settings')
                                  for _, value in walk(document.get(key))):
        return True
    for operation in document.get('operations', []):
        if not isinstance(operation, dict): fail('INVALID_DOCUMENT', 'operation must be an object')
        value = operation.get('document', {})
        if not isinstance(value, dict): fail('INVALID_DOCUMENT', 'operation document must be an object')
        if not pending(value) and any('$analytic' in item for _, item in walk(value)):
            if requires_common(value, registry.resolve(value, legacy=True)[1]): return True
    return False


def publication_receipt(directory):
    """Aggregate only publications already checked by whole-workflow verification."""
    directory = Path(directory)
    verify(directory)
    from .adaptor_runtime import is_common
    if is_common(directory):
        return {'artifacts': json.loads((directory/'verification.json').read_text())['artifacts']}
    saved = json.loads((directory/'result.json').read_text())
    from .run_paths import owned_path
    targets = ([owned_path(directory, job['directory'], kind='directory') for job in saved['jobs']] if saved.get('executionVersion') == 2
               else [directory/op['id'] for op in saved['operations']])
    return {'artifacts': [artifact for target in targets
                          for artifact in json.loads((target/'verification.json').read_text())['artifacts']]}


def verify_study_child(directory, document):
    directory = Path(directory)
    if json.loads((directory/'authored.json').read_text()) != document:
        fail('VERIFICATION_FAILED', 'workflow state input differs')
    receipt = publication_receipt(directory)
    if json.loads((directory/'verification.json').read_text()) != receipt:
        fail('VERIFICATION_FAILED', 'workflow state publications differ')
