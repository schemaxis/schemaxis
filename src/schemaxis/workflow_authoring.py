"""Host workflow drafts and diagrams derived from the existing workflow planner."""
import copy
import json
from .errors import fail
from .storage import digest, encoded
from .observations import bounded
from .workflow import inspect_plan, scheduled, validate as validate_workflow
from .adaptors import registry

TEMPLATE = {'version': 'schemaxis.workflow/1', 'operations': []}
DESIGN_VERSIONS = ('schemaxis.workflow-design/1', 'schemaxis.workflow-design/2')


def plan(document):
    return inspect_plan(document)


def validate(document, *, draft=True):
    if draft and document == TEMPLATE:
        return {'status': 'empty'}
    return inspect_plan(document)


def example():
    """A real, unexecuted two-stage numerical workflow using existing contracts."""
    return {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'samples', 'document': {'version': 'schemaxis.octave/1', 'nodes': [
            {'id': 'data', 'filter': 'sequence', 'options': {'start': 0, 'stop': 4, 'count': 5}}], 'outputs': ['data']}},
        {'id': 'scaled', 'document': {'version': 'schemaxis.octave/1', 'nodes': [
            {'id': 'data', 'filter': 'readCSV', 'options': {'file': {'$artifact': 'samples', 'index': 0}}},
            {'id': 'result', 'filter': 'scale', 'inputs': {'input': 'data'}, 'options': {'factor': 2}}], 'outputs': ['result']}}]}


def references(value, pointer):
    if isinstance(value, dict):
        from .adaptor_runtime import output_reference
        if '$artifact' in value or output_reference(value) or ('$document' in value and 'operation' in value):
            yield pointer, value
        for key, child in value.items():
            yield from references(child, pointer+'/'+key.replace('~','~0').replace('/','~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from references(child, pointer+'/'+str(index))


def graph(session, document_id, expected_revision):
    session._check_revision(document_id, expected_revision)
    document = session.document  # Invalid drafts never reuse an earlier graph.
    if document.get('version') in DESIGN_VERSIONS:
        from .workflow_design import project
        return {**project(document), 'document': document_id, 'revision': expected_revision,
                'sourceDigest': session.draft()['sourceDigest']}
    if document.get('version') != TEMPLATE['version']:
        fail('UNSUPPORTED_VIEW', 'choose a workflow draft for this diagram')
    if document == TEMPLATE:
        operations, concurrent = [], False
    else:
        inspect_plan(document)  # Same host validation as execution, no new graph language.
        operations = validate_workflow(document)
        concurrent = scheduled(document, operations)
    nodes, edges = [], []
    for index, operation in enumerate(operations):
        pointer = '/operations/'+str(index)
        owner, _ = registry.resolve(operation['document'], legacy=True)
        nodes.append({'id': operation['id'], 'provider': owner, 'pointer': pointer,
                      'order': index, 'documentVersion': operation['document'].get('version', 'legacy'),
                      'nodeCount': len(operation['document'].get('nodes', []))})
        for path, ref in references(document['operations'][index]['document'], pointer+'/document'):
            if '$artifact' in ref:
                edges.append({'source': ref['$artifact'], 'target': operation['id'],
                              'artifactIndex': ref['index'], 'pointer': path, 'kind': 'artifact-handoff'})
            else:
                edges.append({'source': ref.get('operation', ref.get('$value')), 'target': operation['id'],
                              'valuePath': ref.get('path', ref.get('$document')), 'pointer': path,
                              'kind': 'document-reference' if '$document' in ref else 'value-handoff'})
    return {'version': 'schemaxis.workflow.graph/1', 'document': document_id, 'revision': expected_revision,
            'sourceDigest': session.draft()['sourceDigest'], 'nodes': nodes, 'edges': edges,
            'executionMode': 'scheduled' if concurrent else 'serial',
            'orderMeaning': 'Artifact dependencies constrain scheduling; declared order breaks ties.' if concurrent else 'Operations execute in declared order, including those without a handoff edge.',
            'verification': 'host plan only; artifact index, kind and contents are rechecked against producer receipts at execution',
            'layout': 'presentation only; no execution implied'}


def observe(session, document_id, expected_revision, **page):
    return bounded(graph(session, document_id, expected_revision), document_id, **page)


def rewire(session, document_id, expected_revision, pointer, source, artifact_index):
    current = graph(session, document_id, expected_revision)
    if session.document.get('version') != TEMPLATE['version']:
        fail('UNSUPPORTED_VIEW', 'use design connections to edit a workflow design')
    if not isinstance(pointer, str) or not any(e['pointer'] == pointer for e in current['edges']):
        fail('INVALID_HANDOFF', 'choose an existing artifact handoff pointer from the current graph')
    # Session patch validates the complete replacement before publishing one undo group.
    return session.patch([{'op': 'replace', 'path': pointer,
                           'value': {'$artifact': source, 'index': artifact_index}}], document_id, expected_revision)


def reference(session, store, document_id, expected_revision, operation_id):
    current = graph(session, document_id, expected_revision)
    node = next((node for node in current['nodes'] if node['id'] == operation_id), None)
    if node is None: fail('UNKNOWN_REFERENCE', 'choose an operation in the current workflow')
    document = session.document
    body = document.get('workflow', document)
    operation = copy.deepcopy(body['operations'][node['order']])
    ref = {'version': 'schemaxis.reference/1', 'kind': 'workflow-operation',
           'document': document_id, 'revision': expected_revision,
           'target': {'document': document_id, 'revision': expected_revision},
           'payload': {'pointer': node['pointer'], 'operation': operation},
           'provenance': {'kind': 'authored-declaration', 'sourceDigest': current['sourceDigest'],
                          'documentDigest': digest(document),
                          'verification': 'host design only; no native execution' if current.get('design') else 'host plan only'},
           'replayable': False, 'label': operation_id+' · workflow operation',
           'selectionScope': 'historical authored operation; not a native result or reusable selector'}
    if len(encoded(ref)) > 16384: fail('OBSERVATION_TOO_LARGE', 'operation reference exceeds 16384 bytes; inspect source slices instead')
    return store._append(ref)


def create_design(session, document_id, expected_revision):
    """Capture an ordinary workflow in a separate persistent design draft."""
    from .workflow_design import create
    session._check_revision(document_id, expected_revision)
    document = session.document
    if document.get('version') in DESIGN_VERSIONS:
        fail('INVALID_WORKFLOW_DESIGN', 'this document is already an editable design')
    body = document if document.get('version') == TEMPLATE['version'] else example()
    design = create(body)
    session.new('Workflow design', 'workflow-design')
    session._edit(design)
    return session.draft()


def edit_design(session, document_id, expected_revision, action, **fields):
    """One revision and undo group for each shared design mutation."""
    from . import workflow_design
    session._check_revision(document_id, expected_revision)
    actions = {'connect': workflow_design.connect, 'disconnect': workflow_design.disconnect,
               'configure': workflow_design.configure}
    if action not in actions:
        fail('INVALID_REQUEST', 'choose connect, disconnect or configure')
    document = actions[action](session.document, **fields)
    session._edit(document)
    return session.draft()


def compile_design(session, document_id, expected_revision):
    """Publish a host-validated acyclic workflow without executing it."""
    from .workflow_design import compile
    session._check_revision(document_id, expected_revision)
    document = compile(session.document)
    session.new('Compiled workflow', 'workflow')
    session._edit(document)
    return session.draft()


# One session-level entry point for Workflow Designer actions. Parameters use
# the JSON API spelling; every mutation is one revisioned, undoable edit.
_DESIGN_ACTIONS = {
    'project': (), 'compile': (), 'upgrade': (),
    'add_operation': ('id', 'document', 'position'),
    'remove_operation': ('operation', 'cascade'),
    'rename_operation': ('operation', 'newId'),
    'duplicate_operation': ('operation', 'newId'),
    'set_ports': ('operation', 'ports'),
    'suggest_ports': ('operation',),
    'connect': ('connection',),
    'disconnect': ('connectionId',),
    'move': ('positions', 'viewport'),
    'configure_loop': ('loopId', 'config'),
    'expose_parameter': ('operation', 'pointer', 'parameterId', 'spec'),
    'expose_unfilled': (),
    'set_parameters': ('parameters',),
    'set_outputs': ('outputs',),
    'set_naming': ('naming',),
    'export_template': ('directory', 'templateId', 'title', 'revision'),
}


def _design_edit(module, action, document, params):
    if action == 'expose_unfilled':
        from .workflow_fills import expose_unfilled
        return expose_unfilled(document)
    edits = {
        'add_operation': lambda: module.add_operation(document, params.get('id'), params.get('document'),
                                                      position=params.get('position')),
        'remove_operation': lambda: module.remove_operation(document, params.get('operation'),
                                                            cascade=params.get('cascade', False)),
        'rename_operation': lambda: module.rename_operation(document, params.get('operation'), params.get('newId')),
        'duplicate_operation': lambda: module.duplicate_operation(document, params.get('operation'),
                                                                  params.get('newId')),
        'set_ports': lambda: module.set_ports(document, params.get('operation'), params.get('ports')),
        'connect': lambda: module.connect(document, params.get('connection')),
        'disconnect': lambda: module.disconnect(document, params.get('connectionId')),
        'move': lambda: module.move(document, params.get('positions'), params.get('viewport')),
        'configure_loop': lambda: module.configure(document, params.get('loopId'), params.get('config')),
        'expose_parameter': lambda: module.expose_parameter(document, params.get('operation'), params.get('pointer'),
                                                            params.get('parameterId'), params.get('spec')),
        'set_parameters': lambda: module.set_parameters(document, params.get('parameters')),
        'set_outputs': lambda: module.set_outputs(document, params.get('outputs')),
        'set_naming': lambda: module.set_naming(document, params.get('naming')),
        'upgrade': lambda: module.upgrade(document),
    }
    return edits[action]()


def design_action(session, document_id, expected_revision, action, params=None):
    """Run one Workflow Designer action against the active design document.

    Returns the fresh projection and revision. ``compile`` creates a separate
    ordinary workflow draft; ``export_template`` writes a bundle and leaves the
    design unchanged; ``suggest_ports`` adds ``suggestions``.
    """
    from . import workflow_design
    from .errors import keys
    params = {} if params is None else params
    if action not in _DESIGN_ACTIONS:
        fail('INVALID_REQUEST', 'unknown design action', '$.action', actions=sorted(_DESIGN_ACTIONS))
    keys(params, _DESIGN_ACTIONS[action], '$.params')
    session._check_revision(document_id, expected_revision)
    from .unfilled import find_unfilled
    diagnostics = session._record.get('diagnostics', [])
    retained = diagnostics and all(item.get('code') == 'UNFILLED_VALUES' for item in diagnostics)
    document = copy.deepcopy(session._record['document']) if retained else session.document
    if not isinstance(document, dict) or document.get('version') not in DESIGN_VERSIONS:
        fail('UNSUPPORTED_VIEW', 'choose a workflow design document for this action', '$.document')
    extra = {}
    if action == 'compile':
        compiled = workflow_design.compile(document)
        session.new('Compiled workflow', 'workflow')
        session._edit(compiled)
        draft = session.draft()
        return {'action': action, 'document': draft['document'], 'revision': draft['revision'],
                'design': document_id, 'workflow': compiled}
    if action == 'suggest_ports':
        extra['suggestions'] = workflow_design.suggest_ports(document, params.get('operation'))
    elif action == 'export_template':
        extra['export'] = workflow_design.export_template(
            document, params.get('directory'), template_id=params.get('templateId'),
            title=params.get('title'), revision=params.get('revision', 1))
    elif action != 'project':
        changed = _design_edit(workflow_design, action, document, params)
        if changed != document:
            keep = action not in ('remove_operation', 'rename_operation')
            if find_unfilled(changed):
                from . import authoring
                session.edit_source(authoring.render(session._record, changed), document_id, expected_revision)
            else:
                session._edit(changed, session.selected if keep else None)
    draft = session.draft(length=1)
    projection = workflow_design.project(copy.deepcopy(session._record['document']))
    return {'action': action, 'document': draft['document'], 'revision': draft['revision'],
            'undoCount': draft['undoCount'], 'redoCount': draft['redoCount'],
            'projection': projection, **extra}
