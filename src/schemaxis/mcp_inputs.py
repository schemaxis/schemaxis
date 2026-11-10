"""Operator-owned immutable inputs for local declared-document MCP sessions.

Only startup configuration may name source files. Agent calls select opaque
capture or verified resource identities; they never choose a filesystem path.
This is a single-owner local store, not hosted tenant authorisation.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import threading
import uuid

from .execution_inputs import (CapturedInput, CapturePolicy, InputBindings,
                               validate_identity)
from .observations import at_pointer, fail
from .storage import atomic, encoded, load


def _regular(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or path.resolve() != path:
        fail('INPUT_CAPTURE_CHANGED', 'operator input must have a canonical absolute path')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    details = os.fstat(descriptor)
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        os.close(descriptor)
        fail('INPUT_CAPTURE_CHANGED', 'input must be one regular file without links')
    return descriptor, details


def normalise_digest(value):
    if type(value) is not str:
        fail('RESOURCE_CHANGED', 'expected input digest must be a SHA-256 identity')
    if re.fullmatch(r'[0-9a-f]{64}', value):
        value = 'sha256:'+value
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', value):
        fail('RESOURCE_CHANGED', 'expected input digest must be a SHA-256 identity')
    return value


class LocalInputs:
    """Durable capture metadata and bounded copies under a trusted policy."""
    def __init__(self, policy):
        if type(policy) is not CapturePolicy:
            raise ValueError('A trusted capture policy is required')
        self.policy = policy
        self.lock = threading.RLock()
        self.index_path = policy.root / '.mcp-inputs.json'
        # The root must be provisioned privately by the operator, not a tool.
        with policy.lease(exclusive=True):
            if self.index_path.exists():
                fd, info = _regular(self.index_path)
                with os.fdopen(fd, 'rb') as stream:
                    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 128*1024:
                        fail('INPUT_CAPTURE_CHANGED', 'invalid local capture inventory')
                    self.index = load(stream.read(128*1024+1).decode())
            else:
                self.index = {'version': 1, 'namespace': policy.namespace, 'items': {}}
                atomic(self.index_path, encoded(self.index), exclusive=True)
            self._validate_index()

    def _validate_index(self):
        value = self.index
        if (type(value) is not dict or set(value) != {'version', 'namespace', 'items'}
                or type(value['version']) is not int or value['version'] != 1
                or value['namespace'] != self.policy.namespace or type(value['items']) is not dict
                or len(value['items']) > self.policy.max_files):
            fail('INPUT_CAPTURE_CHANGED', 'local capture inventory differs from its policy')
        total = 0
        for identity, item in value['items'].items():
            validate_identity(identity)
            if (type(item) is not dict or set(item) != {'file', 'sha256', 'bytes', 'device', 'inode', 'label'}
                    or type(item['file']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9]{1,12})?', item['file'])
                    or type(item['label']) is not str or len(item['label']) > 128
                    or type(item['sha256']) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', item['sha256'])
                    or type(item['bytes']) is not int or not 0 < item['bytes'] <= self.policy.max_bytes
                    or type(item['device']) is not int or item['device'] < 0
                    or type(item['inode']) is not int or item['inode'] < 1):
                fail('INPUT_CAPTURE_CHANGED', 'invalid local immutable capture descriptor')
            total += item['bytes']
        if total > self.policy.max_bytes:
            fail('INPUT_SCOPE_EXCEEDED', 'local capture inventory exceeds its byte allowance')

    def _capture(self, identity):
        validate_identity(identity)
        item = self.index['items'].get(identity)
        if item is None:
            fail('UNKNOWN_INPUT', 'choose an operator-provided opaque input identity')
        return CapturedInput(identity, self.policy.root/item['file'], item['sha256'],
                             item['bytes'], item['device'], item['inode'])

    def _unchanged_index(self):
        fd, info = _regular(self.index_path)
        with os.fdopen(fd, 'rb') as stream:
            if info.st_size > 128*1024 or load(stream.read(128*1024+1).decode()) != self.index:
                fail('INPUT_CAPTURE_CHANGED', 'capture inventory changed; reconcile before continuing')

    def list(self, service, task_id):
        service.task(task_id)
        with self.lock:
            self._unchanged_index()
            return {'inputs': [{'id': key, 'label': item['label'], 'bytes': item['bytes'],
                                'sha256': item['sha256'], 'suffix': Path(item['file']).suffix}
                               for key, item in sorted(self.index['items'].items())],
                    'scope': 'operator-provided inputs in this single-owner local session'}

    def resolve(self, service, task_id, document, admission):
        service.task(task_id)
        slots = admission.input_slots(document)
        if not slots:
            admission.check(document)
            return None
        with self.lock:
            self._unchanged_index()
            captures, bindings = {}, []
            for slot in slots:
                identity = at_pointer(document, slot.pointer)
                capture = self._capture(identity)
                if (capture.bytes > slot.max_bytes
                        or slot.suffixes and capture.path.suffix.lower() not in slot.suffixes):
                    fail('INPUT_SCOPE_EXCEEDED', 'input does not satisfy this declared slot', slot.pointer)
                captures[identity] = capture
                bindings.append((slot.pointer, identity))
            inputs = InputBindings(self.policy.namespace, tuple(captures.values()), tuple(bindings))
            admission.check(document, context=inputs)
            with self.policy.lease(inputs):
                pass
            return inputs

    def import_source(self, source, *, identity, label=None, expected_digest=None):
        """Trusted operator import, also used after verified resource selection."""
        validate_identity(identity)
        source = Path(source)
        suffix = source.suffix.lower()
        if suffix and not re.fullmatch(r'\.[a-z0-9]{1,12}', suffix):
            fail('INVALID_INPUT_BINDINGS', 'input suffix cannot be represented safely')
        label = label if label is not None else identity
        if type(label) is not str or len(label) > 128:
            fail('INVALID_INPUT_BINDINGS', 'input label must be bounded text')
        if expected_digest is not None:
            expected_digest = normalise_digest(expected_digest)
        with self.lock, self.policy.lease(exclusive=True):
            self._unchanged_index()
            # A durable orphan from an interrupted publication consumes capacity.
            files = [p for p in self.policy.root.iterdir() if not p.name.startswith('.')]
            if identity in self.index['items']:
                fail('INPUT_EXISTS', 'input identity already exists; use a fresh identity')
            if len(files) >= self.policy.max_files:
                fail('INPUT_SCOPE_EXCEEDED', 'local capture file allowance exhausted')
            used = sum(p.lstat().st_size for p in files)
            fd, before = _regular(source)
            target = self.policy.root/(identity+suffix)
            published = False
            created = None
            try:
                if not 0 < before.st_size <= self.policy.max_bytes-used:
                    fail('INPUT_SCOPE_EXCEEDED', 'local capture byte allowance exhausted')
                hashed, size = hashlib.sha256(), 0
                out_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                owned = os.fstat(out_fd)
                created = (owned.st_dev, owned.st_ino)
                with os.fdopen(out_fd, 'wb') as output:
                    while True:
                        data = os.read(fd, min(65536, before.st_size-size+1))
                        if not data:
                            break
                        size += len(data)
                        if size > before.st_size:
                            fail('INPUT_CAPTURE_CHANGED', 'source changed while being captured')
                        output.write(data)
                        hashed.update(data)
                    output.flush()
                    os.fsync(output.fileno())
                after = os.fstat(fd)
                named = source.lstat()
                if (size != before.st_size or any((d.st_dev, d.st_ino, d.st_size, d.st_mtime_ns, d.st_ctime_ns)
                        != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                        for d in (after, named))):
                    fail('INPUT_CAPTURE_CHANGED', 'source identity changed while being captured')
                digest = 'sha256:'+hashed.hexdigest()
                if expected_digest is not None and digest != expected_digest:
                    fail('RESOURCE_CHANGED', 'resource changed before immutable capture')
                target.chmod(0o444)
                info = target.stat()
                item = {'file': target.name, 'sha256': digest, 'bytes': size,
                        'device': info.st_dev, 'inode': info.st_ino, 'label': label}
                updated = {**self.index, 'items': {**self.index['items'], identity: item}}
                # Keep an uncertain publication on disk; never pretend rollback.
                published = True
                atomic(self.index_path, encoded(updated))
                self.index = updated
                return {'id': identity, 'sha256': digest, 'bytes': size, 'suffix': suffix}
            finally:
                os.close(fd)
                if not published and created is not None:
                    try:
                        named = target.lstat()
                    except FileNotFoundError:
                        pass
                    else:
                        if (named.st_dev, named.st_ino) == created:
                            target.unlink()

    def promote(self, service, task_id, resource_id):
        service.task(task_id)
        with service.lock:
            resource = dict(service._resource(resource_id))
            producer = resource['job']
        # Fresh native verification runs in the configured isolated executor.
        service.verify(producer)
        with service.lock:
            resource = dict(service._resource(resource_id))
            result = self.import_source(service.workspace/resource['file'],
                identity='input-'+uuid.uuid4().hex, expected_digest=resource['sha256'])
            service._resource(resource_id)
            return {**result, 'producerJob': producer, 'producerResource': resource_id}
