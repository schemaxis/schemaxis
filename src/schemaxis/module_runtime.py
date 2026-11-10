"""Dispatch ordinary adaptor visits through independently pinned OCI workers.

Outer runs retain logical inputs and publications; inner run/ evidence retains
the worker's exact captured inputs. The existing workflow scheduler owns ordering.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import copy
import hashlib
from pathlib import Path
import time
import uuid

from .app_modules import ModuleManager, private_path, regular
from .container_executor import ContainerExecutor, ImageResolver, IsolationLimits, IsolationProfile
from .errors import fail
from .execution_backends import ExecutionRequest, VerificationRequest
from .execution_inputs import CapturePolicy, InputBindings, bindings_record, bindings_from_record, bind_document
from .jobs import Cancellation
from .storage import atomic, encoded, digest, load
from .capabilities import digest as document_digest

RECORD = 'module-run.json'
_current = ContextVar('schemaxis_module_session', default=None)


def current():
    return _current.get()


def read_evidence(path):
    if regular(path).st_size > 64*1024*1024:
        fail('VERIFICATION_FAILED', 'module evidence exceeds its bounded record size', str(path))
    return load(Path(path).read_text(encoding='utf-8'))


def module_run(directory):
    return (Path(directory)/RECORD).exists()


def bind_paths(document, inputs):
    from .execution_inputs import _slot
    opaque = copy.deepcopy(document)
    for pointer, identity in inputs.slots:
        parent, leaf, _ = _slot(opaque, pointer)
        parent[leaf] = identity
    return bind_document(opaque, inputs)


def retained_inputs(directory, document):
    """Verified module captures, translated back to the user's source identities."""
    from .observations import at_pointer
    envelope = read_evidence(Path(directory)/RECORD)
    record = envelope.get('record', {})
    if envelope.get('sha256') != digest(record) or record.get('documentDigest') != digest(document):
        fail('VERIFICATION_FAILED', 'module input provenance differs from its logical document')
    inputs = bindings_from_record(record['inputs']) if record['inputs'] else None
    if inputs is None:
        return {}
    captures = {c.identity: c for c in inputs.captures}
    return {str(private_path(at_pointer(document, pointer))): captures[identity].sha256.removeprefix('sha256:')
            for pointer, identity in inputs.slots}


def documents(document):
    if document.get('version') == 'schemaxis.workflow/1':
        from .workflow import validate
        for item in validate(document):
            yield from documents(item['document'])
    else:
        yield document


class ModuleAdmission:
    """Only manifest-declared individual files are mounted into local workers."""
    def __init__(self, item):
        self.item = item

    def input_slots(self, document):
        from .mcp_admission import FileAdmission
        version = document.get('version')
        if version not in self.item['routes']:
            fail('MODULE_ROUTE_UNAVAILABLE', 'module does not supply this document route', str(version))
        result = []
        for pattern in self.item['inputFiles'][version]:
            for pointer, value in FileAdmission._matches(document, pattern):
                if not isinstance(value, str) or not value:
                    fail('MODULE_INPUT_UNSUPPORTED', 'module file slots require saved individual files', pointer)
                if pointer in result:
                    fail('INVALID_MODULE', 'module input patterns overlap', pointer)
                result.append(pointer)
        return result

    def check(self, document, context=None, *, bound=False):
        from .execution_inputs import validate_bindings, check_bound_document
        slots = self.input_slots(document)
        if context is None:
            if slots:
                fail('INVALID_INPUT_BINDINGS', 'module file slots require captured inputs')
        else:
            validate_bindings(context)
            if set(slots) != {pointer for pointer, _ in context.slots}:
                fail('INVALID_INPUT_BINDINGS', 'module inputs differ from the declared file closure')
            if bound:
                check_bound_document(document, context)
        return True


class ModuleSession:
    def __init__(self, manager, items):
        self.manager = manager
        self.items = {route: item for item in items for route in item['routes']}

    def _item(self, document):
        from .adaptors import registry
        from .__main__ import project_version
        provider, _ = registry.resolve(document, legacy=True)
        item = self.items.get(document.get('version'))
        if item is None or item['provider'] != provider:
            fail('MODULE_ROUTE_UNAVAILABLE', 'register a qualified application module for this route', document.get('version'))
        if item['coreVersion'] != project_version():
            fail('MODULE_VERSION_MISMATCH', 'module requires another Schemaxis version', item['id'],
                 expected=item['coreVersion'], actual=project_version())
        return item

    def input_hashes(self, document):
        from .artifacts import file_digest
        from .observations import at_pointer
        item = self._item(document)
        return {str(private_path(at_pointer(document, pointer))): file_digest(private_path(at_pointer(document, pointer)))
                for pointer in ModuleAdmission(item).input_slots(document)}

    @staticmethod
    def _capture_root(directory):
        identity = hashlib.sha256(str(directory).encode()).hexdigest()[:32]
        return directory.parent/'.schemaxis-module-inputs'/identity, identity

    def _capture(self, document, directory, item):
        from .mcp_inputs import LocalInputs
        from .observations import at_pointer
        admission = ModuleAdmission(item)
        slots = admission.input_slots(document)
        if not slots:
            return copy.deepcopy(document), None, None
        root, namespace = self._capture_root(directory)
        private_path(root)
        root.mkdir(parents=True, mode=0o700)
        root.chmod(0o700)
        policy = CapturePolicy(root, namespace, 1024**3, 64)
        inputs = LocalInputs(policy)
        captured, bindings, sources = [], [], {}
        for pointer in slots:
            source = private_path(at_pointer(document, pointer))
            if source not in sources:
                identity = 'input-'+str(len(captured))
                inputs.import_source(source, identity=identity)
                capture = inputs._capture(identity)
                captured.append(capture)
                sources[source] = identity
            bindings.append((pointer, sources[source]))
        context = InputBindings(namespace, tuple(captured), tuple(bindings))
        return bind_paths(document, context), context, policy

    def _executor(self, item, version, policy):
        receipt = self.manager._receipt(item)
        image = self.manager._image(item['image'], receipt)
        if image is None:
            fail('MODULE_NOT_CACHED', 'module image is unavailable', item['id'])
        profile = CachedProfile(image['Id'], (item['provider'],), (version,),
            IsolationLimits(**item['limits']), item['qualification'], ('captured-input-planning-v1',))
        return ContainerExecutor(ImageResolver((profile,)), admission=ModuleAdmission(item),
                                 engine=self.manager.engine, capture_policy=policy)

    def run(self, document, directory, *, timeout=300):
        from .adaptors import registry
        from .dispatch import cancellation_token, remaining_timeout
        from .publication_metadata import receipt_artifacts, publish_artifacts
        from .schema_snapshots import capture_run
        directory = private_path(directory)
        if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
            fail('OUTPUT_EXISTS', 'module execution requires a new or empty output directory', str(directory))
        if directory.is_relative_to(self.manager.root) or self.manager.root.is_relative_to(directory):
            fail('MODULE_PATH_UNSAFE', 'keep workflow results separate from module storage', str(directory))
        item = self._item(document)
        # Capture relocation must not make an invalid logical path/schema valid.
        registry.plan(document, legacy=True)
        bound, inputs, policy = self._capture(document, directory, item)
        executor = self._executor(item, bound['version'], policy)
        timeout = remaining_timeout(timeout)
        cancellation = Cancellation(cancellation_token(), time.monotonic()+timeout)
        # Planning stays host-safe; the worker independently repeats it before execution.
        plan = registry.plan(bound, legacy=True)
        request = ExecutionRequest('job-'+uuid.uuid4().hex, 'plan-'+uuid.uuid4().hex,
            bound, plan, document_digest(bound), digest(plan), directory/'run', directory.parent,
            (item['provider'],), (), timeout, time.monotonic()+timeout, inputs=inputs)
        outcome = executor.run(request, cancellation)
        checked = executor.verify(VerificationRequest(request), cancellation)
        if checked.response.get('verified') is not True:
            fail('VERIFICATION_FAILED', 'module worker did not verify its result', str(directory))
        receipt = load((directory/'run/verification.json').read_text())
        receipt['artifacts'] = receipt_artifacts(directory/'run')
        record = {'version': 'schemaxis.module-run/1', 'module': item['id'], 'manifestDigest': digest(item),
                  'documentDigest': digest(document), 'workerDocument': bound, 'plan': plan,
                  'inputs': bindings_record(inputs) if inputs else None,
                  'job': request.job_id, 'planId': request.plan_id,
                  'isolation': outcome.isolation, 'verificationIsolation': checked.isolation}
        atomic(directory/'authored.json', encoded(document), exclusive=True)
        capture_run(directory, document)
        atomic(directory/'verification.json', encoded(receipt), exclusive=True)
        publish_artifacts(directory, receipt['artifacts'])
        atomic(directory/RECORD, encoded({'record': record, 'sha256': digest(record)}), exclusive=True)
        return outcome.response

    def verify(self, directory, document=None, *, timeout=300):
        from .dispatch import cancellation_token, remaining_timeout
        from .publication_metadata import verify as verify_metadata, receipt_artifacts
        from .schema_snapshots import verify_run
        directory = private_path(directory)
        logical = read_evidence(directory/'authored.json')
        if document is not None and logical != document:
            fail('VERIFICATION_FAILED', 'module logical input differs from the requested operation')
        item = self._item(logical)
        envelope = read_evidence(directory/RECORD)
        record = envelope.get('record', {})
        if (envelope.get('sha256') != digest(record) or record.get('version') != 'schemaxis.module-run/1'
                or record.get('module') != item['id'] or record.get('manifestDigest') != digest(item)
                or record.get('documentDigest') != digest(logical)):
            fail('VERIFICATION_FAILED', 'retained module identity or logical input differs')
        inputs = bindings_from_record(record['inputs']) if record['inputs'] else None
        policy = None
        if inputs:
            root, namespace = self._capture_root(directory)
            policy = CapturePolicy(root, namespace, 1024**3, 64)
        bound = bind_paths(logical, inputs) if inputs else logical
        if bound != record['workerDocument']:
            fail('VERIFICATION_FAILED', 'worker input differs from the captured logical input')
        verify_run(directory)
        executor = self._executor(item, bound['version'], policy)
        timeout = remaining_timeout(timeout)
        request = ExecutionRequest(record['job'], record['planId'], bound, record['plan'],
            document_digest(bound), digest(record['plan']), directory/'run', directory.parent,
            (item['provider'],), (), timeout, time.monotonic()+timeout, inputs=inputs)
        checked = executor.verify(VerificationRequest(request), Cancellation(cancellation_token(), request.deadline))
        if checked.response.get('verified') is not True:
            fail('VERIFICATION_FAILED', 'fresh module verification did not establish success')
        inner = load((directory/'run/verification.json').read_text())
        inner['artifacts'] = receipt_artifacts(directory/'run')
        if read_evidence(directory/'verification.json') != inner:
            fail('VERIFICATION_FAILED', 'outer publication receipt differs from verified worker evidence')
        verify_metadata(directory, inner['artifacts'])
        return inner


@contextmanager
def runtime(document, *, backend=None, manager=None):
    """Trusted UI/CLI entry point; documents cannot request downloads or backends."""
    if current() is not None:
        yield current()
        return
    manager = manager or ModuleManager()
    settings = manager.settings()
    backend = backend or settings['backend']
    if backend == 'native':
        yield None
        return
    if backend != 'container':
        fail('INVALID_MODULE', 'choose container or native execution')
    if platform_system() != ('Linux', 'x86_64'):
        fail('MODULE_PLATFORM_UNAVAILABLE', 'managed workers currently require a Linux x86-64 execution host')
    with manager.lock(exclusive=True):
        entries = manager._catalogue()
        selected = {}
        session = ModuleSession(manager, entries)
        for child in documents(document):
            item = session._item(child)
            selected[item['id']] = item
        for item in selected.values():
            manager._ensure(item, allow_download=settings['allowDownloads'])
    with manager.lock():
        # Recheck after upgrading/downgrading the lock: cleanup may have intervened.
        for item in selected.values():
            if manager._image(item['image'], manager._receipt(item)) is None:
                fail('MODULE_NOT_CACHED', 'a module was removed before execution; retry', item['id'])
        session = ModuleSession(manager, selected.values())
        token = _current.set(session)
        try:
            yield session
        finally:
            _current.reset(token)


def platform_system():
    import platform
    return platform.system(), platform.machine()


@dataclass(frozen=True)
class CachedProfile(IsolationProfile):
    """A locally verified image content ID, including after an offline load.

    Docker save/load does not retain registry RepoDigests. Installation receipts
    bind the originally checked registry digest to this exact local content ID.
    """
    def __post_init__(self):
        import re
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', self.image):
            raise ValueError('cached workers require an immutable local image content ID')
