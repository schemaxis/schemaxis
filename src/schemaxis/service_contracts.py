"""Shared declarative service tool catalogue; no native application imports."""
import copy
import inspect
from functools import partial
from dataclasses import dataclass
from .observations import fail

METHODS = {
    'schedule_create': 'Register caller-authorised pinned Schemaxis work for an independent schedule worker; no worker is launched.',
    'schedule_preview': 'Validate a schedule and preview its bounded upcoming occurrences without executing applications.',
    'schedule_list': 'List durable future-work declarations and their current lifecycle state.',
    'schedule_get': 'Read one schedule, revision and occurrence history.',
    'schedule_update': 'Revise a schedule at its expected revision with validation.',
    'schedule_pause': 'Pause future dispatch at the expected schedule revision.',
    'schedule_resume': 'Resume future dispatch at the expected schedule revision.',
    'schedule_cancel': 'Cancel a schedule at the expected revision.',
    'schedule_delete': 'Delete a schedule declaration at the expected revision without erasing execution artifacts.',
    'prepare_template': 'Bind an exact workflow-template case and optionally plan it; returns ordinary workflow and binding provenance without native execution.',
    'adaptor_context': 'Read bounded route guidance, editable examples, data/inspection contracts and scoped qualification.',
    'inspection_workspace': 'Read trusted view contracts or change presentation without editing a draft.',
    'inspection_resources': 'List immutable text/table snapshot resources with bounded pagination.',
    'capture_inspection': 'Capture at most one MiB of local UTF-8 text or CSV for historical inspection.',
    'snapshot_resource': 'Capture a digest-checked verified job publication with its provenance.',
    'inspect_snapshot': 'Read bounded text, CSV rows or explicitly mapped finite numeric series.',
    'reference_snapshot': 'Retain a typed text span, table range or series interval in the current snapshot.',
    'inspect_selection': 'Inspect retained evidence for a historical selection, with explicit staleness.',
    'selections': 'List typed evidence selections with current staleness and bounded pagination.',
    'workflow_graph': 'Inspect real workflow operations and artifact edges with bounded paging; no native execution.',
    'rewire_workflow': 'Replace one existing artifact handoff with full host validation and shared undo.',
    'create_workflow_design': 'Create a separate saved diagram design from a workflow, preserving the original draft.',
    'connect_workflow': 'Add a data arrow and identify closed feedback groups in one undoable revision.',
    'disconnect_workflow': 'Remove a design arrow and discard controller settings for changed feedback groups.',
    'configure_workflow_feedback': 'Save bounded feedback settings for an existing closed group; does not execute native coupling.',
    'compile_workflow_design': 'Create an ordinary host-planned workflow from an acyclic design; closed loops cannot execute yet.',
    'reference_workflow': 'Retain a typed historical authored-operation reference, not native result evidence.',
    'create_draft': 'Create a document in the shared console authoring workspace.',
    'list_drafts': 'List recoverable draft identities and revisions with bounded pagination.',
    'draft': 'Read an exact source slice and diagnostics at the expected document revision.',
    'locate_draft': 'Map a JSON pointer to a source range, or a source caret to a property value.',
    'edit_draft': 'Retain valid or invalid JSON/YAML source as one undo group; requires current revision; optional format selects syntax.',
    'patch_draft': 'Apply an atomic group of add/replace/remove/test JSON pointer edits.',
    'undo_draft': 'Undo one authored group, advancing the revision and invalidating native state.',
    'redo_draft': 'Redo one authored group at the current revision.',
    'draft_command': 'Apply a declared authoring command; native execution still uses task budgets.',
    'open_draft': 'Open a UTF-8 source file, retaining invalid drafts and its conflict baseline.',
    'write_draft': 'Save exact source with conflict detection, including recoverable invalid text.',
    'plan_draft': 'Capture the current valid draft; later draft edits block execution of this plan.',
    'create_task': 'Record caller-authorised providers, objective and fixed attempt/time budgets.',
    'list_tasks': 'Recover task identities and revisions with bounded pagination.',
    'task': 'Read current task revision, authorisation and budget usage.',
    'plan': 'Capture an ordinary authored document and host plan against an expected revision.',
    'execute': 'Start the current captured plan within authorisation and budgets; return a job ID.',
    'job': 'Read small job status without waiting for the native process.',
    'observe': 'Read bounded captured document, plan, result, verification, resources or fault evidence.',
    'cancel': 'Request cooperative process-tree cancellation, retaining authored input and partial evidence.',
    'verify': 'Recheck current artifacts and their receipts; invalidate success if verification fails.',
    'resource': 'Read a digest-checked bounded byte range from a verified publication.',
    'inspect_resource': 'Inspect a small JSON or CSV publication as bounded structured data.',
    'inspect_resource_metadata': 'Read verified output size and spatial placement metadata with bounded paging.',
    'capabilities.browse': 'Browse bounded application/category/operation summaries.',
    'capabilities.search': 'Search declarations with keywords and kind facets.',
    'capabilities.describe': 'Retrieve complete selected operation contract sections.',
    'capabilities.schema': 'Navigate exact document schema fragments.'}

METHODS['run_tool'] = 'Bind a local digest-pinned declared tool package into an ordinary task plan; optionally execute within the same authorisation and budgets.'

PAGE = {'pointer': '', 'offset': 0, 'limit': 12, 'max_bytes': 8192, 'revision': None}
CONTROL = frozenset({'cancel', 'job', 'execute', 'create_task', 'plan', 'plan_draft',
                     'schedule_pause', 'schedule_resume', 'schedule_cancel', 'schedule_delete'})
READS = frozenset({'methods', 'job', 'task', 'observe', 'resource', 'inspect_resource',
    'inspect_resource_metadata', 'list_tasks', 'list_drafts', 'draft', 'locate_draft',
    'adaptor_context', 'inspection_resources', 'inspect_snapshot', 'inspect_selection',
    'selections', 'workflow_graph', 'schedule_get', 'schedule_list', 'schedule_preview'})


def target_for(service, method):
    """Resolve only entries from the trusted explicit allow-list."""
    if method not in METHODS:
        fail('UNKNOWN_METHOD', 'choose a declared method or request methods')
    if method == 'run_tool':
        from .tool_packages import run_tool
        return partial(run_tool, service)
    if method.startswith('capabilities.'):
        return getattr(service.catalogue, method.split('.')[1])
    return getattr(service, method)


def _field(method, name, default=inspect.Parameter.empty):
    integers = {'offset', 'length', 'limit', 'max_bytes', 'count', 'artifact_index',
                'draft_revision', 'expected_revision'}
    objects = {'document', 'budget', 'bindings', 'values', 'spec', 'changes',
               'selection', 'connection', 'config'}
    arrays = {'allowed_providers', 'sections', 'columns', 'edits'}
    kind = ('integer' if name in integers else 'object' if name in objects else
            'array' if name in arrays else 'boolean' if name in {'planning', 'execute'} else 'string')
    if method == 'capture_inspection' and name == 'expected_revision':
        kind = 'string'
    value = {'type': [kind, 'null'] if default is None else kind}
    if kind == 'integer':
        value['minimum'] = 0
    if name == 'max_bytes':
        value.update(minimum=2048, maximum=65536)
    if name == 'limit':
        value.update(minimum=1, maximum=16384 if method == 'inspect_snapshot' else 100)
    if name == 'length':
        value.update(minimum=1, maximum=16384)
    if name == 'allowed_providers':
        value.update(items={'type': 'string'}, minItems=1)
    if name in {'sections', 'columns'}:
        value['items'] = {'type': 'string'}
    if name == 'section':
        value['enum'] = ['document', 'plan', 'result', 'verification', 'resources', 'fault']
    if default is not inspect.Parameter.empty:
        value['default'] = default
    return value


@dataclass(frozen=True)
class ToolSpec:
    method: str
    summary: str
    input_schema: dict
    effect: str

    @property
    def mcp_name(self):
        return self.method.replace('.', '_')

    def definition(self, profile):
        return {'name': self.mcp_name, 'description': self.summary,
                'inputSchema': copy.deepcopy(self.input_schema),
                'outputSchema': {'type': 'object', 'required': ['ok'],
                    'properties': {'ok': {'type': 'boolean'}, 'result': {},
                        'fault': {'type': 'object'}, 'resultResource': {'type': 'object'}},
                    'additionalProperties': False},
                '_meta': {'io.schemaxis/method': self.method,
                          'io.schemaxis/profile': profile,
                          'io.schemaxis/contracts': ['schemaxis.agent/1', 'schemaxis.capabilities/1']}}


class ToolCatalogue:
    """Generate both frontends from shared summaries and callable contracts.

    Nested domain values remain validated by their original service validators;
    schemas never turn a precise service fault into a generic protocol error.
    """
    def __init__(self, service):
        self.service = service
        self.specs = {}
        for method, summary in {'methods': 'Read the shared service method and parameter catalogue.', **METHODS}.items():
            properties, required = {}, []
            if method != 'methods':
                for parameter in inspect.signature(target_for(service, method)).parameters.values():
                    if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                        properties.update({name: _field(method, name, default) for name, default in PAGE.items()})
                    else:
                        properties[parameter.name] = _field(method, parameter.name, parameter.default)
                        if parameter.default is inspect.Parameter.empty:
                            required.append(parameter.name)
            schema = {'type': 'object', 'properties': properties, 'additionalProperties': False}
            if required:
                schema['required'] = required
            self.specs[method] = ToolSpec(method, summary, schema,
                'read' if method in READS or method.startswith('capabilities.') else 'mutate')
        names = [spec.mcp_name for spec in self.specs.values()]
        if len(names) != len(set(names)):
            raise ValueError('service tool names collide')
        self.by_name = {spec.mcp_name: spec for spec in self.specs.values()}
