# Copyright (C) 2026 David L F Gaden
"""Read-only validation of an operation draft in its saved workflow context."""
import copy
from dataclasses import replace

from . import authoring, captured_inputs
from .adaptors import registry
from .adaptor_runtime import workflow_inputs
from .core.faults import SchemaxisError
from .errors import fail
from .storage import encoded
from .workflow import dependencies

CONTEXT_FIELDS = ('document', 'revision', 'operation')


def _draft_location(fault, index, operation):
    """Keep only coordinates known to belong to the selected operation."""
    if 'workflowOperation' in fault.observed:
        return fault.location if fault.observed['workflowOperation'] == operation else '$'
    for prefix in (f'/operations/{index}/document', f'/workflow/operations/{index}/document'):
        if fault.location == prefix or fault.location.startswith(prefix + '/'):
            return fault.location[len(prefix):] or '$'
    for prefix in (f'$.operations[{index}].document', f'$.workflow.operations[{index}].document'):
        if fault.location == prefix or fault.location.startswith((prefix + '.', prefix + '[')):
            return '$' + fault.location[len(prefix):]
    return '$'


def operation_validator(session, request, provider):
    """Return a draft validator without changing focus, revision or native state.

    The normal parent validator checks reference shape, ordering and concrete
    operations. Future artifact contents remain deferred by the workflow planner;
    no synthetic file path or blanket standalone-validation exemption is used.
    The caller holds the session lock throughout validation.
    """
    if not all(key in request for key in CONTEXT_FIELDS):
        fail('INVALID_REQUEST', 'nested validation requires document, revision and operation', 'validate')
    identity, operation = request['document'], request['operation']
    records = session._state['documents']
    if not isinstance(identity, str) or identity not in records:
        fail('UNKNOWN_DOCUMENT', 'document is not in this workspace', 'document')
    record = records[identity]
    authoring.check(record, identity, identity, request['revision'])
    parent = record['document']
    if not isinstance(parent, dict):
        fail('INVALID_DOCUMENT', 'repair the parent workflow before validating an operation', 'document')
    version = parent.get('version')
    if version == 'schemaxis.workflow/1':
        body = parent
    elif version in ('schemaxis.workflow-design/1', 'schemaxis.workflow-design/2'):
        body = parent.get('workflow', {})
    else:
        fail('UNSUPPORTED_VERSION', 'nested validation requires a workflow or workflow design', 'document')
    operations = body.get('operations', []) if isinstance(body, dict) else []
    if not isinstance(operations, list):
        fail('INVALID_DOCUMENT', 'repair the parent workflow operations before validating a draft', 'document')
    matches = [index for index, item in enumerate(operations) if isinstance(item, dict) and item.get('id') == operation]
    if not isinstance(operation, str) or not operation or len(matches) != 1:
        fail('UNKNOWN_OPERATION', 'choose an existing operation in this workflow', 'operation')
    index = matches[0]
    status = {'scope': 'workflow-operation', 'deferred': False, 'requiresWorkflow': False}

    def validate(candidate):
        owner, _ = registry.resolve(candidate)
        if owner != provider or registry.resolve(operations[index]['document'])[0] != provider:
            fail('UNSUPPORTED_VERSION', 'document must match the selected provider', '$.version')
        proposed = copy.deepcopy(parent)
        proposed_body = proposed if version == 'schemaxis.workflow/1' else proposed['workflow']
        proposed_body['operations'][index]['document'] = copy.deepcopy(candidate)
        if len(encoded(proposed)) > authoring.LIMIT:
            fail('INVALID_DOCUMENT', 'the combined workflow must be at most one MiB', '$')
        try:
            session._validate(proposed, record['provider'])
            effective = workflow_inputs(proposed_body, defer_unfilled=True)['operations'][index]['document']
        except SchemaxisError as error:
            # Parent faults can concern another operation or a connection; only
            # explicit provenance permits a field address inside this draft.
            raise SchemaxisError(replace(error.fault, location=_draft_location(error.fault, index, operation),
                message='Workflow validation: ' + error.fault.message,
                observed={**error.fault.to_dict()['observed'], 'workflowLocation': error.fault.location})) from error
        connected = any(isinstance(item, dict) and (item.get('target') == operation
                        or isinstance(item.get('to'), dict) and item['to'].get('operation') == operation)
                        for item in proposed.get('connections', []))
        # References may reach future outputs through workflow definitions. Use
        # the normal resolver rather than just looking for markers in the draft.
        status['deferred'] = bool(list(dependencies(effective))) or connected
        # Captured inputs wait for nothing: verify each pinned snapshot and the
        # adaptor reader policy now, without changing the draft. Only consumer
        # fields count, matching workflow consumption and recheck.
        captured = bool(list(captured_inputs.consumed(effective)))
        if captured:
            captured_inputs.consume(effective, '')
        # Even concrete resolved inputs must keep their authored scope when the
        # Workbench would otherwise copy the operation into a standalone preview.
        status['requiresWorkflow'] = status['deferred'] or captured or effective != candidate
        status.pop('message', None)
        if status['deferred']:
            status['message'] = 'Input files and values will be checked after their workflow steps finish.'
        elif captured:
            status['message'] = ('Captured inputs match their pinned snapshots. They are consumed only '
                                 'by the workflow, so run this operation from its workflow.')

    return validate, status
