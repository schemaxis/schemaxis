"""Trusted captured-input contract for isolated planning and execution.

Authored values never select host paths or mounts. Pure binding checks precede
route policy; filesystem validation follows that policy under a cooperative
capture lease. The lease coordinates trusted capture writers, not hostile code
running as the host owner. Native workers receive individual read-only files.
"""
from dataclasses import dataclass, field
import copy
import hashlib
import os
from pathlib import Path
import re
import stat

from .observations import fail

MAX_CAPTURES = 64
MAX_SLOTS = 256
MAX_CAPTURE_BYTES = 1024**3
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
_SHA = re.compile(r'sha256:[0-9a-f]{64}\Z')


@dataclass(frozen=True)
class CapturedInput:
    identity: str
    path: Path
    sha256: str
    bytes: int
    device: int
    inode: int


@dataclass(frozen=True)
class InputBindings:
    namespace: str
    captures: tuple[CapturedInput, ...]
    slots: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PlanningRequest:
    operation_id: str
    plan_id: str
    workspace: Path
    document: dict
    providers: tuple[str, ...]
    stage_timeout: float
    deadline: float | None
    inputs: InputBindings | None = None
    locations: dict | None = None
    phase: str = 'capture'


@dataclass(frozen=True)
class PlanningOutcome:
    response: dict
    isolation: dict = field(default_factory=dict)


def validate_identity(value):
    """Validate a bounded opaque capture/namespace identifier without I/O."""
    if not isinstance(value, str) or not _ID.fullmatch(value):
        fail('INVALID_INPUT_BINDINGS', 'use a bounded opaque captured-input identifier')
    return value


def _tokens(pointer):
    if (not isinstance(pointer, str) or not pointer.startswith('/')
            or len(pointer) > 2048 or re.search(r'~(?![01])', pointer)):
        fail('INVALID_INPUT_BINDINGS', 'input slots require canonical non-root JSON pointers')
    tokens = tuple(token.replace('~1', '/').replace('~0', '~') for token in pointer.split('/')[1:])
    if len(tokens) > 64:
        fail('INVALID_INPUT_BINDINGS', 'input slot nesting exceeds the bound')
    return tokens


def validate_bindings(inputs):
    """Validate immutable metadata only: no filesystem reads or adaptor hooks."""
    if (type(inputs) is not InputBindings or not isinstance(inputs.namespace, str)
            or not _ID.fullmatch(inputs.namespace)
            or type(inputs.captures) is not tuple or not 1 <= len(inputs.captures) <= MAX_CAPTURES
            or type(inputs.slots) is not tuple or not 1 <= len(inputs.slots) <= MAX_SLOTS):
        fail('INVALID_INPUT_BINDINGS', 'supply bounded trusted captured-input bindings')
    identities, paths, inodes = set(), set(), set()
    for capture in inputs.captures:
        if (type(capture) is not CapturedInput or not isinstance(capture.identity, str)
                or not _ID.fullmatch(capture.identity) or not isinstance(capture.path, Path)
                or not capture.path.is_absolute() or '..' in capture.path.parts
                or str(capture.path).startswith('//') or '\0' in str(capture.path) or len(str(capture.path)) > 4096
                or not isinstance(capture.sha256, str) or not _SHA.fullmatch(capture.sha256)
                or type(capture.bytes) is not int or not 1 <= capture.bytes <= MAX_CAPTURE_BYTES
                or type(capture.device) is not int or capture.device < 0
                or type(capture.inode) is not int or capture.inode < 1):
            fail('INVALID_INPUT_BINDINGS', 'invalid immutable capture descriptor')
        if (capture.identity in identities or capture.path in paths
                or (capture.device, capture.inode) in inodes):
            fail('INVALID_INPUT_BINDINGS', 'captures must have distinct identities, paths and inodes')
        identities.add(capture.identity); paths.add(capture.path)
        inodes.add((capture.device, capture.inode))
    pointers, referenced = [], set()
    for slot in inputs.slots:
        if type(slot) is not tuple or len(slot) != 2 or not isinstance(slot[1], str) or slot[1] not in identities:
            fail('INVALID_INPUT_BINDINGS', 'slot must identify one declared capture')
        tokens = _tokens(slot[0])
        if any(tokens[:len(other)] == other or other[:len(tokens)] == tokens for other in pointers):
            fail('INVALID_INPUT_BINDINGS', 'input pointers must be distinct and non-overlapping')
        pointers.append(tokens); referenced.add(slot[1])
    if referenced != identities:
        fail('INVALID_INPUT_BINDINGS', 'input closure contains unreferenced captures')
    return inputs


def bindings_record(inputs):
    """Encode trusted plan persistence; this is not an authored-input API."""
    validate_bindings(inputs)
    return {'version': 1, 'namespace': inputs.namespace,
        'captures': [{'identity': item.identity, 'path': str(item.path), 'sha256': item.sha256,
                      'bytes': item.bytes, 'device': item.device, 'inode': item.inode}
                     for item in inputs.captures],
        'slots': [list(item) for item in inputs.slots]}


def bindings_from_record(record):
    """Decode an owned captured-plan record without filesystem access.

    The caller establishes record provenance; no transport may convert authored
    dictionaries into trusted capture context with this helper alone.
    """
    if (type(record) is not dict or set(record) != {'version', 'namespace', 'captures', 'slots'}
            or type(record['version']) is not int or record['version'] != 1
            or type(record['captures']) is not list or not 1 <= len(record['captures']) <= MAX_CAPTURES
            or type(record['slots']) is not list or not 1 <= len(record['slots']) <= MAX_SLOTS):
        fail('INVALID_INPUT_BINDINGS', 'invalid captured-input record envelope')
    validate_identity(record['namespace'])
    captures = []
    for item in record['captures']:
        if (type(item) is not dict
                or set(item) != {'identity', 'path', 'sha256', 'bytes', 'device', 'inode'}
                or type(item['path']) is not str or not 1 <= len(item['path']) <= 4096
                or '\0' in item['path']):
            fail('INVALID_INPUT_BINDINGS', 'invalid captured-input record member')
        # Refuse aliases which Path would silently normalise before validation.
        path = Path(item['path'])
        if str(path) != item['path']:
            fail('INVALID_INPUT_BINDINGS', 'captured paths require canonical spelling')
        captures.append(CapturedInput(item['identity'], path, item['sha256'],
                                     item['bytes'], item['device'], item['inode']))
    slots = []
    for item in record['slots']:
        if type(item) is not list or len(item) != 2:
            fail('INVALID_INPUT_BINDINGS', 'invalid captured-input slot record')
        slots.append(tuple(item))
    return validate_bindings(InputBindings(record['namespace'], tuple(captures), tuple(slots)))


def _slot(document, pointer):
    parent = document
    tokens = _tokens(pointer)
    try:
        for token in tokens[:-1]:
            if type(parent) is list:
                if not re.fullmatch(r'0|[1-9][0-9]*', token): raise ValueError()
                parent = parent[int(token)]
            elif type(parent) is dict:
                parent = parent[token]
            else:
                raise ValueError()
        leaf = tokens[-1]
        if type(parent) is list:
            if not re.fullmatch(r'0|[1-9][0-9]*', leaf): raise ValueError()
            leaf = int(leaf)
        elif type(parent) is not dict:
            raise ValueError()
        return parent, leaf, parent[leaf]
    except (KeyError, IndexError, TypeError, ValueError):
        fail('INVALID_INPUT_BINDINGS', 'input slot does not address the document', pointer)


def bind_document(document, inputs):
    """Replace opaque capture IDs exactly once, before core digest capture.

    This is structural binding, not route admission. A caller must separately
    apply its reviewed pure file-slot policy before any filesystem validation.
    """
    validate_bindings(inputs)
    result = copy.deepcopy(document)
    captures = {item.identity: item for item in inputs.captures}
    for pointer, identity in inputs.slots:
        parent, leaf, value = _slot(result, pointer)
        if value != identity or type(value) is not str:
            fail('INVALID_INPUT_BINDINGS', 'authored input slot must contain its opaque capture ID', pointer)
        parent[leaf] = str(captures[identity].path)
    return result


def check_bound_document(document, inputs):
    """Check saved path bindings without reading either paths or native inputs."""
    validate_bindings(inputs)
    captures = {item.identity: item for item in inputs.captures}
    for pointer, identity in inputs.slots:
        _, _, value = _slot(document, pointer)
        if type(value) is not str or value != str(captures[identity].path):
            fail('INPUT_CAPTURE_CHANGED', 'captured document input differs from its immutable binding', pointer)
    return inputs


@dataclass(frozen=True)
class CapturePolicy:
    root: Path
    namespace: str
    max_bytes: int
    max_files: int

    def __post_init__(self):
        if (not isinstance(self.root, Path) or not self.root.is_absolute() or '..' in self.root.parts
                or str(self.root).startswith('//') or '\0' in str(self.root) or len(str(self.root)) > 4096
                or not isinstance(self.namespace, str) or not _ID.fullmatch(self.namespace)
                or type(self.max_bytes) is not int or not 1 <= self.max_bytes <= MAX_CAPTURE_BYTES
                or type(self.max_files) is not int or not 1 <= self.max_files <= MAX_CAPTURES):
            raise ValueError('Invalid trusted capture policy')

    def lease(self, inputs=None, *, exclusive=False):
        """Hold through container absence; exclusive leases coordinate mutations.

        No-input leases are exclusively for trusted capture creation/deletion.
        A caller must retain durable task/plan references between leased phases.
        """
        if type(exclusive) is not bool or (inputs is None and not exclusive):
            raise ValueError('A capture mutation lease must be exclusive')
        if inputs is not None:
            validate_bindings(inputs)
            if (inputs.namespace != self.namespace or len(inputs.captures) > self.max_files
                    or sum(item.bytes for item in inputs.captures) > self.max_bytes
                    or any(item.path.parent != self.root for item in inputs.captures)):
                fail('INPUT_SCOPE_EXCEEDED', 'captures exceed their owned namespace or capacity')
        return CaptureLease(self, inputs, exclusive)


class CaptureLease:
    def __init__(self, policy, bindings, exclusive):
        try:
            import fcntl
        except ImportError:
            fail('ISOLATION_UNAVAILABLE', 'captured-input leases require supported kernel file locks')
        self.policy, self.bindings = policy, bindings
        self.root_fd, self.lock_fd, self.files = None, None, []
        try:
            root = policy.root
            if root.resolve() != root:
                fail('INPUT_CAPTURE_CHANGED', 'capture root cannot traverse symlinks')
            self.root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.root_stat = os.fstat(self.root_fd)
            if (self.root_stat.st_uid != os.getuid() or stat.S_IMODE(self.root_stat.st_mode) != 0o700):
                fail('INPUT_CAPTURE_CHANGED', 'capture root must be private and owned')
            self.lock_fd = os.open('.capture.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                                   0o600, dir_fd=self.root_fd)
            lock_stat = self.lock_stat = os.fstat(self.lock_fd)
            if (not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1
                    or lock_stat.st_uid != os.getuid() or stat.S_IMODE(lock_stat.st_mode) != 0o600):
                fail('INPUT_CAPTURE_CHANGED', 'capture lease file must be private and owned')
            try:
                fcntl.flock(self.lock_fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                fail('INPUTS_BUSY', 'capture mutation and native readers cannot overlap')
            for capture in bindings.captures if bindings else ():
                descriptor = os.open(capture.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.root_fd)
                self.files.append((capture, descriptor))
            self.recheck()
        except OSError:
            self.close()
            fail('INPUT_CAPTURE_CHANGED', 'capture root or file cannot be safely opened')
        except BaseException:
            self.close()
            raise

    @property
    def captures(self):
        return self.bindings.captures if self.bindings else ()

    def recheck(self):
        if self.root_fd is None:
            raise ValueError('Capture lease is closed')
        root = self.policy.root
        try:
            current_root = root.lstat()
            if (root.resolve() != root or not stat.S_ISDIR(current_root.st_mode)
                    or (current_root.st_dev, current_root.st_ino) != (self.root_stat.st_dev, self.root_stat.st_ino)
                    or current_root.st_uid != os.getuid() or stat.S_IMODE(current_root.st_mode) != 0o700):
                fail('INPUT_CAPTURE_CHANGED', 'capture root changed during its lease')
            lock_stat = os.stat('.capture.lock', dir_fd=self.root_fd, follow_symlinks=False)
            if (not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1
                    or lock_stat.st_uid != os.getuid() or stat.S_IMODE(lock_stat.st_mode) != 0o600
                    or (lock_stat.st_dev, lock_stat.st_ino) != (self.lock_stat.st_dev, self.lock_stat.st_ino)):
                fail('INPUT_CAPTURE_CHANGED', 'capture lease identity changed')
            for capture, descriptor in self.files:
                before = os.fstat(descriptor)
                named = os.stat(capture.path.name, dir_fd=self.root_fd, follow_symlinks=False)
                for details in (before, named):
                    if (not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
                            or details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o444
                            or details.st_dev != capture.device or details.st_dev != self.root_stat.st_dev
                            or details.st_ino != capture.inode
                            or details.st_size != capture.bytes):
                        fail('INPUT_CAPTURE_CHANGED', 'immutable capture identity or permissions changed')
                os.lseek(descriptor, 0, os.SEEK_SET)
                hashed, remaining = hashlib.sha256(), capture.bytes
                while remaining:
                    data = os.read(descriptor, min(65536, remaining))
                    if not data: fail('INPUT_CAPTURE_CHANGED', 'capture ended before its declared size')
                    hashed.update(data); remaining -= len(data)
                after = os.fstat(descriptor)
                if (os.read(descriptor, 1) or 'sha256:'+hashed.hexdigest() != capture.sha256
                        or (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns)):
                    fail('INPUT_CAPTURE_CHANGED', 'capture bytes changed during validation')
        except OSError:
            fail('INPUT_CAPTURE_CHANGED', 'capture disappeared during validation')
        return self.captures

    def close(self):
        for _, descriptor in self.files:
            os.close(descriptor)
        self.files = []
        if self.lock_fd is not None:
            os.close(self.lock_fd); self.lock_fd = None
        if self.root_fd is not None:
            os.close(self.root_fd); self.root_fd = None

    def __enter__(self): return self
    def __exit__(self, *error): self.close()
