"""Explicit human-edit revisions of a completed, verified workflow.

A completed parent workflow can expose one verified producer artifact as a
separate working copy (``checkout``). The parent is either a serial result or a
simple scheduled result (``executionVersion`` 2) in which every operation ran
as one batch with one native visit (a study of one state qualifies) and no
authored execution, composition or workflow study applies. After a person saves
an edited copy in their application, ``prepare`` adopts it as a new pinned
``schemaxis.resource/1`` snapshot and writes a ``schemaxis.revision/1``
document. The document records the parent identity, the selected artifact, the
single direct ``$artifact`` consumer field it replaces, the adopted snapshot and
the reason.

``plan``, ``run`` and ``verify`` accept the revision document. Each re-verifies
the parent workflow, its authored digest and the selected artifact's bytes, and
derives the child workflow again rather than trusting a stored copy. The child
runs in a new directory and reruns every operation; nothing is reused. The
replacement snapshot is rechecked before and after its consumer runs and during
later verification by the ordinary captured-input contract.

Ancestry is one level deep: a revision result is refused as a parent, so
verification never follows a chain. The record is provenance, not a signature,
and does not establish that the edited data is scientifically equivalent.
Locks are held only while a command runs, never while waiting for a person.
"""

import copy
import os
from pathlib import Path
import re
import shutil

from . import storage
from .core.faults import SchemaxisError
from .errors import fail, keys
from .run_paths import owned_path


VERSION = 'schemaxis.revision/1'
CHECKOUT = 'schemaxis.revision.checkout/1'
RESULT = 'schemaxis.revision.result/1'
WORKFLOW = 'workflow'
_EXECUTION = 'conservative: every operation is rerun in a new directory; nothing is reused'
_LIMITATIONS = [
    'the revision record is provenance, not a signature',
    'the edited data is not claimed to be scientifically equivalent to the producer output',
    'units, coordinate frames and native project dependencies are not inferred',
    'every operation is rerun; selective continuation is not implemented',
]
_UNSUPPORTED_TOP = ('dimensions', 'definitions', 'settings', 'axes', 'maxStates', 'execution')
_HEX = re.compile('[0-9a-f]{64}')
_SCHEDULED = 2


def _record(path, code):
    """Read retained JSON through the strict parser and require an object."""
    try:
        value = storage.load(path.read_text())
    except (OSError, UnicodeError, RecursionError) as error:
        fail(code, 'cannot read retained revision evidence: ' + str(error), str(path))
    if not isinstance(value, dict):
        fail(code, 'retained revision evidence must be a JSON object', str(path))
    return value


def _pointer(value, location):
    """Parse a canonical RFC 6901 pointer into tokens; refuse malformed escapes."""
    if not isinstance(value, str) or not value.startswith('/') or len(value) > 4096:
        fail('INVALID_REVISION', 'consumer pointer must be a JSON pointer starting with /', location)
    tokens = []
    for raw in value[1:].split('/'):
        if re.search('~(?![01])', raw):
            fail('INVALID_REVISION', 'consumer pointer has an invalid ~ escape', location, pointer=value)
        tokens.append(raw.replace('~1', '/').replace('~0', '~'))
    return tokens


def _lookup(document, tokens, location):
    value = document
    for token in tokens:
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and re.fullmatch('0|[1-9][0-9]*', token) and int(token) < len(value):
            value = value[int(token)]
        else:
            fail('INVALID_REVISION', 'consumer pointer does not select an authored field', location, token=token)
    return value


def _replace(document, tokens, replacement):
    result = copy.deepcopy(document)
    parent = result
    for token in tokens[:-1]:
        parent = parent[int(token)] if isinstance(parent, list) else parent[token]
    parent[int(tokens[-1]) if isinstance(parent, list) else tokens[-1]] = copy.deepcopy(replacement)
    return result


def _aliases(path):
    path = Path(path).expanduser()
    if '..' in path.parts:
        fail('INVALID_REVISION', 'revision paths must not contain parent traversal', str(path))
    absolute = Path(os.path.abspath(path))
    return {absolute, Path(os.path.realpath(absolute))}


def _disjoint(path, protected, location):
    """Refuse a destination equal to, inside or an ancestor of protected trees.

    Lexical and symlink-resolved spellings are both compared, before any write.
    """
    for candidate in _aliases(path):
        for name, guard in protected.items():
            for alias in _aliases(guard):
                if candidate == alias or alias in candidate.parents or candidate in alias.parents:
                    fail('REVISION_OVERLAP', location + ' must be disjoint from the ' + name
                         + ' (neither inside it nor an ancestor of it)', str(path), protected=str(guard))


def _parent(directory):
    """Verify a completed, non-study, non-revision parent: serial or simple scheduled."""
    directory = Path(os.path.abspath(Path(directory).expanduser()))
    authored_path, result_path = directory / 'authored.json', directory / 'result.json'
    if not authored_path.is_file() or not result_path.is_file():
        fail('REVISION_PARENT_INVALID', 'parent is not a retained workflow result', str(directory))
    authored = _record(authored_path, 'REVISION_PARENT_INVALID')
    enclosing = directory.parent / 'authored.json'
    if authored.get('version') == VERSION or (
            directory.name == WORKFLOW and enclosing.is_file()
            and _record(enclosing, 'REVISION_PARENT_INVALID').get('version') == VERSION):
        fail('REVISION_PARENT_UNSUPPORTED', 'a revision cannot yet be the parent of another revision; '
             'author a new workflow with an explicit captured input instead', str(directory))
    if not isinstance(authored, dict) or authored.get('version') != 'schemaxis.workflow/1':
        fail('REVISION_PARENT_INVALID', 'parent must be a schemaxis.workflow/1 result', str(directory))
    from .workflow import study_required, verify
    unsupported = sorted(key for key in _UNSUPPORTED_TOP if key in authored)
    if unsupported or study_required(authored):
        fail('REVISION_UNSUPPORTED', 'composed or study parents are not supported by this revision slice',
             str(directory), keys=unsupported)
    result = _record(result_path, 'REVISION_PARENT_INVALID')
    if result.get('executionVersion') not in (None, _SCHEDULED):
        fail('REVISION_UNSUPPORTED', 'unrecognised scheduler result version is not supported by this revision '
             'slice', str(directory))
    if result.get('executionVersion') == _SCHEDULED and any(
            isinstance(operation, dict) and 'execution' in operation for operation in authored.get('operations', [])):
        fail('REVISION_UNSUPPORTED', 'parents with authored per-operation execution are not supported by this '
             'revision slice', str(directory))
    if result.get('status') != 'succeeded' or result.get('verified') is not True:
        fail('INCOMPLETE_EXECUTION', 'parent workflow did not complete successfully', str(directory))
    verify(directory)
    if result.get('executionVersion') == _SCHEDULED:
        _single_visits(directory, authored, result)
    return directory, authored


def _job(saved, operation, role):
    """Return the one completed visit the scheduler recorded for an operation."""
    jobs = [job for job in saved.get('jobs', []) if isinstance(job, dict) and job.get('operation') == operation]
    if len(jobs) != 1 or jobs[0].get('batch') != 0 or jobs[0].get('status') != 'succeeded':
        fail('REVISION_UNSUPPORTED', role + ' must have exactly one completed visit in this slice', operation,
             visits=len(jobs))
    return jobs[0]


def _attempt_directory(directory, job):
    """Resolve a scheduled job's recorded attempt, which must be inside its own batch directory."""
    operation = job['operation']
    target = owned_path(directory, job.get('directory'), kind='directory', fault='REVISION_PARENT_INVALID')
    batch = directory / operation / 'batch-0'
    if (target.parent != batch or not re.fullmatch('attempt-[0-9]+', target.name)
            or target.resolve().parent != batch.resolve()):
        fail('REVISION_PARENT_INVALID', 'recorded attempt is not inside its job directory', operation)
    return target


def _attempt(directory, job):
    """Resolve and re-verify a scheduled job's recorded attempt like the scheduler does."""
    from .parallel import verify_native
    target = _attempt_directory(directory, job)
    return target, verify_native(target, job.get('effective'))


def _single_visits(directory, authored, saved):
    """Require every operation of a verified scheduled parent to be one batch with one native visit.

    Defaults give one job per operation, and the scheduler chunks only on authored
    execution, which is refused. A document-level study still runs as one batch of
    several native states, so each retained receipt must hold at most one state.
    """
    for operation in authored['operations']:
        job = _job(saved, operation['id'], 'every operation')
        receipt = _record(_attempt_directory(directory, job) / 'verification.json', 'REVISION_PARENT_INVALID')
        if 'states' in receipt and (not isinstance(receipt['states'], list) or len(receipt['states']) != 1):
            fail('REVISION_UNSUPPORTED', 'every operation must be one native visit; a multi-state study '
                 'cannot be a revision parent in this slice', operation['id'], operation=operation['id'],
                 states=len(receipt['states']) if isinstance(receipt['states'], list) else None)


def _consumed(saved, consumer, producer, artifact, index, tokens):
    """Require the consumer's one recorded visit to have received exactly this artifact at the field."""
    job = _job(saved, consumer, 'consumer operation')
    handoff = {'from': producer, 'index': index, 'file': artifact.get('file'), 'sha256': artifact.get('sha256')}
    try:
        field = _lookup(job.get('effective'), tokens, producer)
    except SchemaxisError:
        field = None
    if handoff not in job.get('handoffs', []) or field != artifact.get('file'):
        fail('REVISION_PARENT_INVALID', 'consumer visit did not consume the selected producer artifact at '
             'the selected field', consumer, producer=producer, index=index)


def _select(directory, authored, consumer, pointer, location='$'):
    """Return the direct ``$artifact`` at ``pointer`` and its verified artifact."""
    from .adaptors import registry
    from .artifacts import file_digest
    from .workflow import validate
    operations = validate(authored)
    by_id = {operation['id']: operation for operation in operations}
    if consumer not in by_id:
        fail('INVALID_REVISION', 'consumer operation is not in the parent workflow', location + '/consumer',
             operation=consumer, available=sorted(by_id))
    tokens = _pointer(pointer, location + '/pointer')
    from .adaptor_runtime import META
    if tokens[0] in META:
        fail('UNSUPPORTED_RESOURCE', 'revision edits must select an executable reader field, not metadata',
             location + '/pointer', pointer=pointer)
    original = _lookup(by_id[consumer]['document'], tokens, location + '/pointer')
    if not isinstance(original, dict) or set(original) != {'$artifact', 'index'}:
        fail('REVISION_UNSUPPORTED', 'consumer pointer must select a direct {"$artifact", "index"} reference; '
             'composed $document/$value inputs are not supported', location + '/pointer', pointer=pointer)
    producer, index = original['$artifact'], original['index']
    saved = _record(directory / 'result.json', 'REVISION_PARENT_INVALID')
    scheduled = saved.get('executionVersion') == _SCHEDULED
    if scheduled:
        target, receipt = _attempt(directory, _job(saved, producer, 'producer operation'))
    else:
        target = owned_path(directory, producer, kind='directory', fault='REVISION_PARENT_INVALID')
        receipt = _record(target / 'verification.json', 'REVISION_PARENT_INVALID')
    if len(receipt.get('states', [None])) > 1:
        fail('REVISION_UNSUPPORTED', 'producers with multiple visits or chunks are ambiguous in this slice',
             producer, states=len(receipt['states']))
    artifacts = receipt.get('artifacts', [])
    if index >= len(artifacts):
        fail('INVALID_SELECTION', 'artifact index exceeds the producer output count', producer, index=index)
    artifact = artifacts[index]
    members = artifact.get('files', [])
    if not isinstance(members, list):
        fail('REVISION_PARENT_INVALID', 'artifact files must be a list', producer, index=index)
    if len(members) > 1 or artifact.get('publicationMode') is not None:
        fail('REVISION_UNSUPPORTED', 'multi-file and distributed artifacts cannot be edited as one file',
             producer, index=index)
    kind = artifact.get('kind', artifact.get('identity', {}).get('kind'))
    if kind not in registry.resolve(by_id[consumer]['document'], legacy=True)[1].get('acceptedArtifacts', []):
        fail('TYPE_MISMATCH', 'selected artifact kind is not accepted by the consumer', producer, kind=kind)
    path = owned_path(target, artifact.get('file'), fault='REVISION_PARENT_INVALID')
    from .workflow_resources import _regular
    _regular(path)
    digest = file_digest(path)
    if not isinstance(artifact.get('sha256'), str) or digest != artifact['sha256']:
        fail('REVISION_PARENT_INVALID', 'selected artifact bytes differ from the producer receipt', str(path))
    if members:
        member = members[0]
        if (not isinstance(member, dict)
                or owned_path(target, member.get('file'), fault='REVISION_PARENT_INVALID') != path
                or member.get('sha256') != digest):
            fail('REVISION_UNSUPPORTED', 'artifact has a companion file instead of only its primary file',
                 producer, index=index)
    if scheduled:
        _consumed(saved, consumer, producer, artifact, index, tokens)
    selection = {'producer': producer, 'index': index, 'kind': kind,
                 'file': path.relative_to(directory / producer).as_posix(), 'sha256': digest}
    return selection, path, original, tokens


def checkout(parent, consumer, pointer, destination):
    """Copy a verified producer artifact to a new, separate editable file."""
    directory, authored = _parent(parent)
    selection, path, original, _ = _select(directory, authored, consumer, pointer)
    _disjoint(destination, {'parent result': directory}, 'working copy')
    from .workflow_resources import _path, _read_file, _regular
    target = _path(destination, 'destination')
    if target.exists():
        fail('OUTPUT_EXISTS', 'choose a working-copy path that does not exist', str(target))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        copied = _read_file(path, _regular(path), target)
    except FileExistsError:
        fail('OUTPUT_EXISTS', 'working copy was claimed; choose a fresh path', str(target))
    if copied != selection['sha256']:
        fail('REVISION_PARENT_INVALID', 'artifact changed while copying', str(path))
    return {'version': CHECKOUT, 'parent': str(directory), 'consumer': consumer, 'pointer': pointer,
            'original': original, 'selection': selection, 'workingCopy': str(target),
            'next': 'edit and save the working copy, then run schemaxis revision prepare',
            'limitations': list(_LIMITATIONS)}


def _parent_record(directory, authored):
    return {'directory': str(directory), 'authoredDigest': storage.digest(authored)}


def child_workflow(document):
    """Re-verify a revision against its parent and derive the child workflow."""
    check(document)
    directory, authored = _parent(document['parent']['directory'])
    if storage.digest(authored) != document['parent']['authoredDigest']:
        fail('REVISION_MISMATCH', 'parent authored workflow differs from the revision record',
             '$/parent/authoredDigest')
    consumer = document['consumer']
    selection, _, original, tokens = _select(directory, authored, consumer['operation'], consumer['pointer'],
                                            '$/consumer')
    if original != consumer['original']:
        fail('REVISION_MISMATCH', 'recorded original reference differs from the parent', '$/consumer/original')
    if selection != document['selection']:
        fail('REVISION_MISMATCH', 'selected producer artifact differs from the revision record', '$/selection')
    index = next(i for i, op in enumerate(authored['operations']) if op['id'] == consumer['operation'])
    child = _replace(authored, ['operations', str(index), 'document', *tokens], document['replacement'])
    if storage.digest(child) != document['child']['authoredDigest']:
        fail('REVISION_MISMATCH', 'derived child workflow differs from the revision record',
             '$/child/authoredDigest')
    _disjoint(document['replacement']['$resource'], {'parent result': directory}, 'adopted snapshot')
    from .captured_inputs import open_reference
    # Refuse a changed replacement before any output is claimed or operation runs.
    opened = open_reference(document['replacement'], '$/replacement')
    # Ordinary workflow planning defers a whole operation when any producer
    # reference remains. Check this reader explicitly even in that case.
    from .adaptors import registry
    consumer_document = child['operations'][index]['document']
    hook = registry.route_hook(consumer_document, 'acceptResource', legacy=True)
    if hook is None:
        fail('UNSUPPORTED_RESOURCE', 'the consumer adaptor declares no captured-input reader policy',
             '$/consumer/pointer')
    hook(consumer_document, consumer['pointer'], opened)
    return directory, child


def check(document):
    """Closed structural check of a revision document without filesystem access."""
    keys(document, ('version', 'parent', 'selection', 'consumer', 'replacement', 'workingCopy', 'reason',
                    'child', 'units', 'frame', 'execution', 'limitations'), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$/version')
    for name, fields in (('parent', ('directory', 'authoredDigest')),
                         ('selection', ('producer', 'index', 'kind', 'file', 'sha256')),
                         ('consumer', ('operation', 'pointer', 'original')), ('child', ('authoredDigest',))):
        value = document.get(name)
        if not isinstance(value, dict) or set(value) != set(fields):
            fail('INVALID_REVISION', name + ' must contain exactly ' + ', '.join(fields), '$/' + name)
    for location, value in (('$/parent/authoredDigest', document['parent']['authoredDigest']),
                            ('$/selection/sha256', document['selection']['sha256']),
                            ('$/child/authoredDigest', document['child']['authoredDigest'])):
        if not isinstance(value, str) or not _HEX.fullmatch(value):
            fail('INVALID_REVISION', 'expected a 64-hex SHA-256 digest', location)
    for location, value in (('$/parent/directory', document['parent']['directory']),
                            ('$/workingCopy', document.get('workingCopy'))):
        if not isinstance(value, str) or not Path(value).is_absolute():
            fail('INVALID_REVISION', 'expected an absolute path', location)
    _pointer(document['consumer']['pointer'], '$/consumer/pointer')
    if not isinstance(document['consumer']['operation'], str):
        fail('INVALID_REVISION', 'consumer operation must be a string', '$/consumer/operation')
    reason = document.get('reason')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
        fail('INVALID_REVISION', 'reason must be a nonempty explanation of at most 4096 characters', '$/reason')
    from .captured_inputs import check_reference
    replacement = document.get('replacement')
    if not isinstance(replacement, dict) or '$resource' not in replacement:
        fail('INVALID_REVISION', 'replacement must be a pinned captured-input reference', '$/replacement')
    check_reference(replacement, '$/replacement')
    if 'member' not in replacement:
        fail('INVALID_REVISION', 'replacement must pin the adopted file member', '$/replacement')
    if document.get('units') != 'unknown' or document.get('frame') != 'unknown':
        fail('INVALID_REVISION', 'units and frame are recorded as unknown; they are not inferred', '$/units')
    if document.get('execution') != _EXECUTION or document.get('limitations') != _LIMITATIONS:
        fail('INVALID_REVISION', 'execution policy and limitations must be the retained conservative text',
             '$/execution')
    return document


def prepare(parent, consumer, pointer, replacement, snapshot, reason, *, max_bytes=1073741824):
    """Adopt a saved working copy and return a checked ``schemaxis.revision/1`` document."""
    directory, authored = _parent(parent)
    selection, _, original, tokens = _select(directory, authored, consumer, pointer)
    protected = {'parent result': directory}
    _disjoint(replacement, protected, 'replacement working copy')
    _disjoint(snapshot, {**protected, 'replacement working copy': replacement}, 'adopted snapshot')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
        fail('INVALID_REVISION', 'an explicit nonempty reason of at most 4096 characters is required', 'reason')
    from .adaptors import registry
    consumer_document = next(op['document'] for op in authored['operations'] if op['id'] == consumer)
    if registry.route_hook(consumer_document, 'acceptResource', legacy=True) is None:
        fail('UNSUPPORTED_RESOURCE', 'the consumer adaptor declares no captured-input reader policy',
             'pointer', operation=consumer)
    from . import captured_inputs
    adopted = captured_inputs.adopt(replacement, snapshot, kind='file', max_bytes=max_bytes)
    reference = {**adopted['reference'], 'origin': 'human edit of ' + selection['producer'] + ' artifact '
                 + str(selection['index'])}
    index = next(i for i, op in enumerate(authored['operations']) if op['id'] == consumer)
    child = _replace(authored, ['operations', str(index), 'document', *tokens], reference)
    document = {'version': VERSION, 'parent': _parent_record(directory, authored), 'selection': selection,
                'consumer': {'operation': consumer, 'pointer': pointer, 'original': original},
                'replacement': reference, 'workingCopy': os.path.abspath(Path(replacement).expanduser()),
                'reason': reason, 'child': {'authoredDigest': storage.digest(child)},
                'units': 'unknown', 'frame': 'unknown', 'execution': _EXECUTION,
                'limitations': list(_LIMITATIONS)}
    try:
        check(document)
        # Graph, types, reader policy and native-free plan of the child.
        plan(document)
    except BaseException:
        # Adoption exclusively created this snapshot. A refused preparation has
        # not published a revision referencing it; release it for a corrected retry.
        shutil.rmtree(adopted['snapshot'])
        raise
    return document


def plan(document):
    from .workflow import inspect_plan
    directory, child = child_workflow(document)
    return {'version': 'schemaxis.revision.plan/1', 'parent': str(directory),
            'consumer': document['consumer'], 'replacement': document['replacement'],
            'execution': _EXECUTION, 'plan': inspect_plan(child)}


def _protect(document, directory, output):
    _disjoint(output, {'parent result': directory, 'adopted snapshot': document['replacement']['$resource'],
                       'replacement working copy': document['workingCopy']}, 'revision output')


def execute(document, output, *, timeout=300, locations=None, backend='native'):
    """Run the derived child into ``output/workflow`` after rechecking provenance."""
    from .artifacts import atomic_json
    from .storage import prepare_run_directory
    from .workflow import execute as run_workflow, validate
    directory, child = child_workflow(document)
    _protect(document, directory, output)
    output = prepare_run_directory(output, document)
    status = {'version': RESULT, 'status': 'incomplete', 'verified': False, 'parent': str(directory),
              'workflow': WORKFLOW, 'rerun': [op['id'] for op in validate(child)], 'reused': [],
              'execution': _EXECUTION}
    atomic_json(output / 'result.json', status)
    try:
        from .module_runtime import runtime
        with runtime(child, backend=backend):
            result = run_workflow(child, output / WORKFLOW, timeout=timeout, locations=locations)
        # The parent and selected artifact must still match after consumption.
        child_workflow(document)
        status.update(status='succeeded', verified=bool(result.get('verified')))
        atomic_json(output / 'result.json', status)
        return {**status, 'result': result}
    except BaseException as error:
        status.update(status='cancelled' if isinstance(error, KeyboardInterrupt) else 'failed')
        status['fault'] = error.to_dict().get('fault') if hasattr(error, 'to_dict') else {'message': str(error)}
        atomic_json(output / 'result.json', status)
        raise


def verify(output):
    """Verify a revision result without following ancestry beyond its parent."""
    from .workflow import validate, verify as verify_workflow
    output = Path(os.path.abspath(Path(output).expanduser()))
    document = _record(output / 'authored.json', 'VERIFICATION_FAILED')
    directory, child = child_workflow(document)
    _protect(document, directory, output)
    status = _record(output / 'result.json', 'VERIFICATION_FAILED')
    expected = {'version': RESULT, 'status': 'succeeded', 'verified': True, 'parent': str(directory),
                'workflow': WORKFLOW, 'rerun': [op['id'] for op in validate(child)], 'reused': [],
                'execution': _EXECUTION}
    if status != expected:
        fail('INCOMPLETE_EXECUTION' if status.get('status') != 'succeeded' else 'VERIFICATION_FAILED',
             'revision result is incomplete or differs from its record', str(output))
    if _record(output / WORKFLOW / 'authored.json', 'VERIFICATION_FAILED') != child:
        fail('VERIFICATION_FAILED', 'child workflow differs from the revision derived from its parent',
             str(output / WORKFLOW))
    report = verify_workflow(output / WORKFLOW)
    return {'verified': True, 'revision': VERSION, 'parent': str(directory),
            'consumer': document['consumer'], 'replacementDigest': document['replacement']['digest'],
            'operations': report['operations'], 'artifacts': report['artifacts'], 'execution': _EXECUTION}
