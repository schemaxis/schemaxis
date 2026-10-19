"""Explicit, non-destructive storage inventory and portable case preservation.

No application ownership or cross-process run lifecycle is inferred. Source
removal, installation removal and derived-data pruning are deliberately absent.
"""
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import time
import zipfile

from .errors import SchemaxisError, fail
from .storage import atomic, digest, encoded, load

PROTOCOL = 'schemaxis.storage-plan/1'
BUNDLE = 'schemaxis.storage-bundle/1'
MANIFEST = 'storage-manifest.json'
LOCKS = ('session.lock', 'agent.lock', 'scheduler-owner.lock', '.coordinator.lock')
MAX_MANIFEST = 8 * 1024 * 1024
MAX_RESTORE = 8 * 1024**3


def _path(value):
    path = Path(value).expanduser().absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            fail('UNSAFE_STORAGE_PATH', 'symlinks are not accepted for storage operations', str(part))
    return path.resolve()


def _hash(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _manifest_file(path):
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        fail('INVALID_STORAGE_ARCHIVE', 'backup manifest must be a regular file', str(path))
    with path.open('rb') as stream:
        payload = stream.read(MAX_MANIFEST + 1)
    if len(payload) > MAX_MANIFEST:
        fail('INVALID_STORAGE_ARCHIVE', 'manifest exceeds eight MiB', str(path))
    return _validate_manifest(load(payload.decode('utf-8')))


def _tree(root):
    """Inventory regular files only; never follow links or special devices."""
    files, directories = {}, []
    def unreadable(error):
        raise error
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=unreadable):
        for name in sorted(dirs + names):
            path = Path(directory)/name
            mode = path.lstat().st_mode
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                fail('UNSAFE_STORAGE_PATH', 'case contains a link or special file', str(path))
            if stat.S_ISDIR(mode):
                directories.append(relative)
            else:
                files[relative] = {'bytes': path.stat().st_size, 'sha256': _hash(path),
                                   'mode': stat.S_IMODE(mode) & 0o777}
    return {'files': dict(sorted(files.items())), 'directories': sorted(directories)}


def _directory_bytes(root):
    """Measure configured directories without hashing large native binaries."""
    total = 0
    def unreadable(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=unreadable):
        dirs[:] = [name for name in dirs if not (Path(directory)/name).is_symlink()]
        for name in files:
            path = Path(directory)/name
            mode = path.lstat().st_mode
            if stat.S_ISREG(mode):
                total += path.stat().st_size
    return total


def _activity(root, source):
    """Refuse known owners; lack of a lock never proves a run is inactive."""
    owners = [source, *[p for p in source.parents if p == root or root in p.parents]]
    owners += [p.parent for p in source.rglob('*.lock') if not p.is_symlink()]
    for directory in set(owners):
        for name in LOCKS:
            path = directory/name
            if not path.exists():
                continue
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                fail('UNSAFE_STORAGE_PATH', 'lock must be a regular file', str(path))
            try:
                import fcntl
                with path.open('rb') as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(stream, fcntl.LOCK_UN)
            except (ImportError, BlockingIOError, PermissionError):
                fail('STORAGE_ACTIVE_OR_UNKNOWN', 'workspace owner is active or cannot be checked', str(path))
    if any(source.rglob('.schema-export-incomplete')):
        fail('STORAGE_INCOMPLETE', 'an incomplete schema export is not an archival source', str(source))


def _dependencies(source):
    from .schema_snapshots import read
    return [{'manifest': p.relative_to(source).as_posix(), 'bytes': len(payload),
             'sha256': hashlib.sha256(payload).hexdigest()}
            for p in sorted(source.rglob('*.snapshot.json')) for payload in [read(p)]]


def inspect(root, *, installations=True):
    """Read selected storage; unknown ownership/usage is never labelled unused."""
    root = _path(root)
    if not root.is_dir():
        fail('INVALID_STORAGE_ROOT', 'select an existing directory', str(root))
    from .schema_snapshots import inspect as inspect_schemas
    runs, faults = [], []
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory)/d).is_symlink())
        if 'authored.json' not in files:
            continue
        path = Path(directory)
        try:
            tree = _tree(path)
            runs.append({'path': path.relative_to(root).as_posix(),
                         'bytes': sum(item['bytes'] for item in tree['files'].values()),
                         'files': len(tree['files']), 'modifiedAt': path.stat().st_mtime,
                         'activity': 'unknown', 'regeneration': 'not established',
                         'derivedRemovalCandidates': [], 'schemaReferences': _dependencies(path)})
        except Exception as error:
            faults.append({'path': path.relative_to(root).as_posix(), 'message': str(error)})
    configured = []
    if installations:
        from .configuration import load as configuration
        from .adaptors.registry import ADAPTORS
        for key, values in sorted(configuration()['locations'].items()):
            for value in values if isinstance(values, list) else [values]:
                path = Path(value).expanduser()
                record = {'provider': key, 'path': str(path), 'ownership': 'external or unknown',
                          'lastUsedAt': None, 'recordedUseCount': None, 'installationBytes': None,
                          'dependencies': None, 'managedRemovalSupported': False,
                          'guidance': 'Use the application distributor or package manager; this configuration records locations only.'}
                try:
                    if path.is_symlink():
                        record.update(pathKind='symlink', measuredPathBytes=None)
                    elif path.is_file():
                        record.update(pathKind='file', measuredPathBytes=path.stat().st_size)
                    elif path.is_dir():
                        record.update(pathKind='directory', measuredPathBytes=_directory_bytes(path),
                                      measurementScope='regular files below configured directory; symlink targets excluded')
                    else:
                        record.update(pathKind='missing', measuredPathBytes=None)
                except (OSError, ValueError, SchemaxisError) as error:
                    record.update(pathKind='unreadable', measuredPathBytes=None, fault=str(error))
                if key in ADAPTORS:
                    record['declaredRuntime'] = ADAPTORS[key].get('runtimeFamily')
                    record['declaredExecutables'] = ADAPTORS[key].get('executables', [])
                configured.append(record)
    return {'root': str(root), 'runs': runs, 'faults': faults, 'schemas': inspect_schemas(root),
            'installations': configured,
            'limitations': ['Run sizes overlap when workflow attempts are nested; do not sum them.',
                           'No reliable installation ownership/usage or universal active-run ledger exists.',
                           'No source deletion, installation removal or derived-data pruning is implemented.']}


def _seal(plan):
    return {**plan, 'confirmation': digest(plan)}


def plan(root=None, runs=(), *, action='backup', destination, archive=None,
         older_than_days=0, max_bytes=MAX_RESTORE):
    if action not in ('backup', 'archive', 'compress', 'restore'):
        fail('INVALID_STORAGE_ACTION', 'choose backup, archive, compress or restore')
    if not isinstance(destination, (str, Path)) or not str(destination):
        fail('INVALID_STORAGE_PLAN', 'destination must be a nonempty path')
    if not isinstance(runs, (list, tuple)) or any(not isinstance(run, str) or not run for run in runs):
        fail('INVALID_STORAGE_PLAN', 'runs must be an explicit list of nonempty paths')
    destination = _path(destination)
    if destination.exists():
        fail('OUTPUT_EXISTS', 'choose a new destination', str(destination))
    if action == 'restore':
        if root is not None or runs:
            fail('INVALID_STORAGE_PLAN', 'restore selects an archive or backup, not source runs')
        if not isinstance(archive, (str, Path)) or not str(archive):
            fail('INVALID_STORAGE_PLAN', 'restore needs an archive or backup path')
        source = _path(archive)
        if not source.is_dir() and not source.is_file():
            fail('INVALID_STORAGE_ARCHIVE', 'select a regular ZIP file or backup directory', str(source))
        if type(max_bytes) is not int or max_bytes <= 0:
            fail('INVALID_STORAGE_PLAN', 'max_bytes must be a positive integer')
        if source.is_dir():
            manifest = _manifest_file(source/MANIFEST)
            _verify_bundle(source, manifest)
            archive_digest = digest(_tree(source))
        else:
            manifest = verify_archive(source, max_bytes=max_bytes)
            archive_digest = _hash(source)
        if sum(v['bytes'] for v in manifest['files'].values()) > max_bytes:
            fail('INVALID_STORAGE_ARCHIVE', 'backup exceeds the selected restoration byte limit')
        if destination.is_relative_to(source) or source.is_relative_to(destination):
            fail('INVALID_STORAGE_SELECTION', 'restore destination must be outside its backup', str(destination))
        return _seal({'version': PROTOCOL, 'action': action, 'archive': str(source),
                      'archiveDigest': archive_digest, 'destination': str(destination),
                      'restoredBytes': sum(v['bytes'] for v in manifest['files'].values()),
                      'maxBytes': max_bytes, 'sourceDeletionBytes': 0, 'verification': 'byte membership and schema integrity'})
    if not isinstance(root, (str, Path)) or not str(root):
        fail('INVALID_STORAGE_PLAN', 'an explicit storage root is required')
    if archive is not None:
        fail('INVALID_STORAGE_PLAN', 'archive input is only valid for restoration')
    root = _path(root)
    if not root.is_dir() or not runs:
        fail('INVALID_STORAGE_PLAN', 'select an existing root and at least one run')
    if type(older_than_days) not in (int, float) or not math.isfinite(older_than_days) or older_than_days < 0:
        fail('INVALID_STORAGE_PLAN', 'older_than_days must be finite and nonnegative')
    selected = []
    for run in runs:
        source = _path(root/run)
        if source == root or not source.is_relative_to(root) or not (source/'authored.json').is_file():
            fail('INVALID_STORAGE_SELECTION', 'select a case directory below root containing authored.json', str(source))
        if destination.is_relative_to(source) or source.is_relative_to(destination):
            fail('INVALID_STORAGE_SELECTION', 'destination must be outside selected cases', str(destination))
        if any(source == prior or source.is_relative_to(prior) or prior.is_relative_to(source) for prior in selected):
            fail('INVALID_STORAGE_SELECTION', 'duplicate or overlapping run selections are not accepted', str(source))
        _activity(root, source)
        selected.append(source)
    sources = []
    for source in sorted(selected):
        tree = _tree(source)
        newest = max([source.stat().st_mtime, *[p.stat().st_mtime for p in source.rglob('*')]])
        if time.time() - newest < older_than_days * 86400:
            fail('STORAGE_TOO_RECENT', 'selected case does not meet the minimum age', str(source))
        sources.append({'path': source.relative_to(root).as_posix(), 'tree': tree,
                        'bytes': sum(v['bytes'] for v in tree['files'].values()),
                        'schemaDependencies': _dependencies(source)})
    return _seal({'version': PROTOCOL, 'action': action, 'root': str(root), 'sources': sources,
                  'destination': str(destination), 'olderThanDays': older_than_days,
                  'sourceBytes': sum(s['bytes'] for s in sources), 'sourceDeletionBytes': 0,
                  'expectedNetSavingsBytes': 0, 'compressedBytesEstimate': None,
                  'dependencyEffect': 'All schema dependencies copied into a portable destination; originals retained.',
                  'reversibility': 'Sources retained; destination is additional storage.',
                  'activity': 'No known held workspace locks; universal inactivity cannot be established.'})


def _manifest(bundle, sources):
    tree = _tree(bundle/'data')
    return {'version': BUNDLE, 'files': {'data/'+k: v for k, v in tree['files'].items()},
            'directories': ['data', *['data/'+v for v in tree['directories']]],
            'sources': sources, 'verification': 'byte membership and schema integrity; no new native qualification'}


def _member(name):
    if not isinstance(name, str) or not name:
        fail('INVALID_STORAGE_ARCHIVE', 'archive member path must be a nonempty string')
    path = PurePosixPath(name)
    if ('\\' in name or ':' in name or path.is_absolute()
            or '..' in path.parts or name != path.as_posix() or path.parts[0] != 'data'):
        fail('INVALID_STORAGE_ARCHIVE', 'unsafe archive member path', str(name))


def _validate_manifest(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'files', 'directories', 'sources', 'verification'}
            or value['version'] != BUNDLE or not isinstance(value['files'], dict)
            or not isinstance(value['directories'], list) or len(value['files']) > 100000
            or len(value['directories']) > 100000):
        fail('INVALID_STORAGE_ARCHIVE', 'invalid storage manifest')
    for name, info in value['files'].items():
        _member(name)
        if (not isinstance(info, dict) or set(info) != {'bytes', 'sha256', 'mode'}
                or type(info['bytes']) is not int or info['bytes'] < 0
                or type(info['mode']) is not int or not 0 <= info['mode'] <= 0o777
                or not isinstance(info['sha256'], str) or len(info['sha256']) != 64
                or any(v not in '0123456789abcdef' for v in info['sha256'])):
            fail('INVALID_STORAGE_ARCHIVE', 'invalid file identity', name)
    for name in value['directories']:
        _member(name)
    if len(set(value['directories'])) != len(value['directories']) or set(value['files']) & set(value['directories']):
        fail('INVALID_STORAGE_ARCHIVE', 'duplicate or conflicting directory membership')
    directories = set(value['directories'])
    if 'data' not in directories or any(str(PurePosixPath(name).parent) not in directories
            for name in [*value['files'], *directories] if name != 'data'):
        fail('INVALID_STORAGE_ARCHIVE', 'manifest omits a parent directory')
    return value


def _archive_manifest(archive):
    members = archive.infolist()
    names = [member.filename for member in members]
    if len(members) > 100001 or len(names) != len(set(names)) or names.count(MANIFEST) != 1:
        fail('INVALID_STORAGE_ARCHIVE', 'too many/duplicate members or missing manifest')
    if archive.getinfo(MANIFEST).file_size > MAX_MANIFEST:
        fail('INVALID_STORAGE_ARCHIVE', 'manifest exceeds eight MiB')
    with archive.open(MANIFEST) as stream:
        payload = stream.read(MAX_MANIFEST + 1)
    if len(payload) > MAX_MANIFEST:
        fail('INVALID_STORAGE_ARCHIVE', 'manifest exceeds eight MiB')
    manifest = _validate_manifest(load(payload.decode('utf-8')))
    if set(names) != set(manifest['files']) | {MANIFEST}:
        fail('INVALID_STORAGE_ARCHIVE', 'archive membership differs from manifest')
    return manifest


def verify_archive(path, *, max_bytes=MAX_RESTORE):
    """Check exact membership and streamed checksums without extracting anything."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            manifest = _archive_manifest(archive)
            if sum(v['bytes'] for v in manifest['files'].values()) > max_bytes:
                fail('INVALID_STORAGE_ARCHIVE', 'archive exceeds the selected restoration byte limit')
            for member in members:
                if member.filename == MANIFEST:
                    continue
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or member.is_dir() or (stat.S_IFMT(mode) and not stat.S_ISREG(mode)):
                    fail('INVALID_STORAGE_ARCHIVE', 'only regular file members are allowed', member.filename)
                expected = manifest['files'][member.filename]
                if member.file_size != expected['bytes']:
                    fail('INVALID_STORAGE_ARCHIVE', 'member byte count differs', member.filename)
                sha256 = hashlib.sha256()
                with archive.open(member) as stream:
                    for block in iter(lambda: stream.read(1024*1024), b''):
                        sha256.update(block)
                if sha256.hexdigest() != expected['sha256']:
                    fail('INVALID_STORAGE_ARCHIVE', 'member hash differs', member.filename)
            return manifest
    except (OSError, ValueError, zipfile.BadZipFile, KeyError, UnicodeError, RuntimeError) as error:
        fail('INVALID_STORAGE_ARCHIVE', 'archive cannot be verified: ' + str(error), str(path))


def _copy_bounded(source, output, expected_bytes, remaining):
    """Enforce actual extraction bytes even if an archive changes while open."""
    copied = 0
    while True:
        block = source.read(min(1024*1024, expected_bytes-copied+1, remaining-copied+1))
        if not block:
            break
        copied += len(block)
        if copied > expected_bytes or copied > remaining:
            fail('INVALID_STORAGE_ARCHIVE', 'actual extracted bytes exceed the reviewed bounds')
        output.write(block)
    if copied != expected_bytes:
        fail('INVALID_STORAGE_ARCHIVE', 'actual extracted byte count differs')
    return copied


def _extract_files(bundle, manifest, opener, max_bytes):
    total = 0
    for directory in manifest['directories']:
        (bundle/directory).mkdir(parents=True, exist_ok=True)
    for name, info in manifest['files'].items():
        target = bundle/name
        with opener(name) as source, target.open('xb') as output:
            total += _copy_bounded(source, output, info['bytes'], max_bytes-total)
        target.chmod(info['mode'])


def _verify_bundle(bundle, manifest, *, publishing=False):
    if (bundle/'.storage-incomplete').exists() and not publishing:
        fail('STORAGE_INCOMPLETE', 'incomplete backup must be inspected and repaired before restoration', str(bundle))
    if {p.name for p in bundle.iterdir()} - {MANIFEST, 'data', '.storage-incomplete'}:
        fail('INVALID_STORAGE_ARCHIVE', 'unexpected backup root members')
    actual = _manifest(bundle, manifest['sources'])
    if actual != manifest:
        fail('INVALID_STORAGE_ARCHIVE', 'restored membership or content differs')
    _dependencies(bundle/'data')


def apply_plan(saved, confirmation):
    """Recheck an explicit digest-bound plan and publish only to a new destination."""
    if not isinstance(saved, dict) or saved.get('version') != PROTOCOL:
        fail('INVALID_STORAGE_PLAN', 'expected a storage plan')
    if (saved.get('action') not in ('backup', 'archive', 'compress', 'restore')
            or not isinstance(saved.get('destination'), str) or not saved['destination']
            or saved.get('sourceDeletionBytes') != 0):
        fail('INVALID_STORAGE_PLAN', 'invalid action/destination or unsupported source deletion')
    if saved['action'] == 'restore':
        if (not isinstance(saved.get('archive'), str) or not saved['archive']
                or type(saved.get('maxBytes')) is not int or saved['maxBytes'] <= 0):
            fail('INVALID_STORAGE_PLAN', 'restore plan needs an archive and positive byte limit')
    elif (not isinstance(saved.get('root'), str) or not saved['root']
            or not isinstance(saved.get('sources'), list) or not saved['sources']
            or any(not isinstance(source, dict) or not isinstance(source.get('path'), str)
                   or not source['path'] for source in saved['sources'])
            or type(saved.get('olderThanDays')) not in (int, float)):
        fail('INVALID_STORAGE_PLAN', 'preservation plan needs root, selected cases and minimum age')
    unsigned = {k: v for k, v in saved.items() if k != 'confirmation'}
    if not isinstance(confirmation, str) or saved.get('confirmation') != confirmation or digest(unsigned) != confirmation:
        fail('STORAGE_CONFIRMATION_REQUIRED', 'supply the unchanged reviewed plan confirmation digest')
    if saved['action'] == 'restore':
        fresh = plan(action='restore', destination=saved['destination'], archive=saved['archive'], max_bytes=saved['maxBytes'])
    else:
        fresh = plan(saved['root'], [s['path'] for s in saved['sources']], action=saved['action'],
                     destination=saved['destination'], older_than_days=saved['olderThanDays'])
    if fresh != saved:
        fail('STALE_STORAGE_PLAN', 'source content or dependencies changed; inspect and plan again')
    destination = _path(saved['destination'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.schemaxis-storage-', dir=destination.parent) as temporary:
        bundle = Path(temporary)/'bundle'
        bundle.mkdir()
        if saved['action'] == 'restore':
            archive_path = Path(saved['archive'])
            if archive_path.is_dir():
                manifest = _manifest_file(archive_path/MANIFEST)
                _extract_files(bundle, manifest, lambda name: (archive_path/name).open('rb'), saved['maxBytes'])
            else:
                # Verify and extract from one open descriptor: replacing its path
                # cannot replace the reviewed stream. Actual bytes remain bounded.
                with archive_path.open('rb') as stream:
                    verified = verify_archive(stream, max_bytes=saved['maxBytes'])
                    with zipfile.ZipFile(stream) as archive:
                        manifest = _archive_manifest(archive)
                        if manifest != verified:
                            fail('STALE_STORAGE_PLAN', 'archive manifest changed before extraction')
                        _extract_files(bundle, manifest, archive.open, saved['maxBytes'])
            atomic(bundle/MANIFEST, encoded(manifest), exclusive=True)
            current_digest = digest(_tree(archive_path)) if archive_path.is_dir() else _hash(archive_path)
            if current_digest != saved['archiveDigest']:
                fail('STALE_STORAGE_PLAN', 'backup changed during restoration; source retained')
        else:
            from .schema_snapshots import export_run
            for source in saved['sources']:
                export_run(Path(saved['root'])/source['path'], bundle/'data'/source['path'])
            manifest = _manifest(bundle, [s['path'] for s in saved['sources']])
            atomic(bundle/MANIFEST, encoded(manifest), exclusive=True)
            # Copying a changing producer is not a consistent archival snapshot.
            fresh = plan(saved['root'], [s['path'] for s in saved['sources']], action=saved['action'],
                         destination=saved['destination'], older_than_days=saved['olderThanDays'])
            if fresh != saved:
                fail('STALE_STORAGE_PLAN', 'source changed while copying; originals retained')
        _verify_bundle(bundle, manifest)
        if saved['action'] in ('archive', 'compress'):
            compressed = Path(temporary)/'archive.zip'
            compression = zipfile.ZIP_DEFLATED if saved['action'] == 'compress' else zipfile.ZIP_STORED
            with zipfile.ZipFile(compressed, 'w', compression=compression, compresslevel=6 if compression else None) as archive:
                archive.write(bundle/MANIFEST, MANIFEST)
                for name in manifest['files']:
                    archive.write(bundle/name, name)
            verify_archive(compressed, max_bytes=max(MAX_RESTORE, sum(v['bytes'] for v in manifest['files'].values())))
            # Exclusive hardlink publishes a complete file without overwriting a racer.
            try:
                os.link(compressed, destination)
            except FileExistsError:
                fail('OUTPUT_EXISTS', 'destination was claimed by another operation', str(destination))
            stored_bytes = destination.stat().st_size
        else:
            # mkdir is the exclusive claim; files are moved inside our new directory.
            try:
                destination.mkdir()
            except FileExistsError:
                fail('OUTPUT_EXISTS', 'destination was claimed by another operation', str(destination))
            marker = destination/'.storage-incomplete'
            marker.write_text('Incomplete preservation; keep all sources.\n')
            for item in bundle.iterdir():
                shutil.move(str(item), destination/item.name)
            _verify_bundle(destination, manifest, publishing=True)
            marker.unlink()
            stored_bytes = sum(v['bytes'] for v in _tree(destination)['files'].values())
    return {'status': 'verified', 'action': saved['action'], 'destination': str(destination),
            'storedBytes': stored_bytes, 'contentBytes': sum(v['bytes'] for v in manifest['files'].values()),
            'compressionSavingsBytes': sum(v['bytes'] for v in manifest['files'].values())-stored_bytes,
            'netAdditionalStorageBytes': stored_bytes,
            'sourceDeletionBytes': 0, 'sourcesRetained': True, 'verification': manifest['verification']}


def create_policy(path, *, name, root, runs, destination, every_days, first_due,
                  older_than_days=0, action='compress'):
    """Persist an opt-in plan-only policy; does not install a worker or timer."""
    from .scheduler import instant, iso
    if (not isinstance(name, str) or not name or len(name) > 80
            or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name)):
        fail('INVALID_STORAGE_POLICY', 'policy name must use letters, digits, underscores or hyphens')
    if type(every_days) not in (int, float) or not math.isfinite(every_days) or not 0 < every_days <= 3650:
        fail('INVALID_STORAGE_POLICY', 'every_days must be finite and between zero and 3650')
    if action not in ('backup', 'archive', 'compress'):
        fail('INVALID_STORAGE_POLICY', 'policies support backup, archive or compress')
    start = instant(first_due)
    suffix = '' if action == 'backup' else '.zip'
    target = _path(destination)/name/('scheduled-' + str(int(start)) + suffix)
    # Validate all selections and destinations now; the minimum age is applied
    # when due plans are requested, so a new case may mature under a policy.
    checked = plan(root, runs, action=action, destination=target)
    if type(older_than_days) not in (int, float) or not math.isfinite(older_than_days) or older_than_days < 0:
        fail('INVALID_STORAGE_POLICY', 'older_than_days must be finite and nonnegative')
    policy = {'version': 'schemaxis.storage-policy/1', 'mode': 'plan-only', 'name': name,
              'root': checked['root'], 'runs': [s['path'] for s in checked['sources']],
              'destination': str(_path(destination)), 'action': action,
              'trigger': {'kind': 'interval', 'start': iso(start), 'seconds': every_days*86400},
              'olderThanDays': older_than_days,
              'execution': 'No worker installed. Run storage policy due explicitly; review and apply its plan separately.'}
    atomic(_path(path), encoded(policy), exclusive=True)
    return policy


def due_policy(path, *, now=None):
    """Return this interval's due plan without applying, scheduling or deleting."""
    from .scheduler import instant, iso, next_due
    with _path(path).open('rb') as stream:
        payload = stream.read(1024*1024+1)
    if len(payload) > 1024*1024:
        fail('INVALID_STORAGE_POLICY', 'policy exceeds one MiB')
    policy = load(payload.decode('utf-8'))
    fields = {'version', 'mode', 'name', 'root', 'runs', 'destination', 'action', 'trigger', 'olderThanDays', 'execution'}
    if (not isinstance(policy, dict) or set(policy) != fields
            or policy.get('version') != 'schemaxis.storage-policy/1' or policy.get('mode') != 'plan-only'
            or any(not isinstance(policy.get(key), str) or not policy[key] for key in ('name', 'root', 'destination'))
            or len(policy['name']) > 80
            or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in policy['name'])
            or policy['action'] not in ('backup', 'archive', 'compress')
            or not isinstance(policy['runs'], list) or not policy['runs']
            or any(not isinstance(run, str) or not run for run in policy['runs'])
            or type(policy['olderThanDays']) not in (int, float)
            or not math.isfinite(policy['olderThanDays']) or policy['olderThanDays'] < 0
            or not isinstance(policy['trigger'], dict)
            or set(policy['trigger']) != {'kind', 'start', 'seconds'}
            or policy['trigger'].get('kind') != 'interval'):
        fail('INVALID_STORAGE_POLICY', 'expected a plan-only storage policy')
    trigger = policy['trigger']
    start = instant(trigger['start'])
    current = time.time() if now is None else instant(now)
    seconds = trigger['seconds']
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        fail('INVALID_STORAGE_POLICY', 'invalid interval')
    following = next_due(trigger, current)
    result = {'mode': 'plan-only', 'workerInstalled': False,
              'nextDueAt': iso(following) if following is not None else None, 'plan': None, 'skipped': []}
    if current < start:
        return result
    due = start + math.floor((current-start)/seconds)*seconds
    result['dueAt'] = iso(due)
    eligible = []
    root = _path(policy['root'])
    selected = []
    for run in policy['runs']:
        source = _path(root/run)
        if (source == root or not source.is_relative_to(root) or not (source/'authored.json').is_file()
                or any(source == prior or source.is_relative_to(prior) or prior.is_relative_to(source) for prior in selected)):
            fail('INVALID_STORAGE_SELECTION', 'policy must select distinct case paths below its root', str(source))
        selected.append(source)
        newest = max([source.stat().st_mtime, *[p.stat().st_mtime for p in source.rglob('*')]])
        if current-newest < policy['olderThanDays']*86400:
            result['skipped'].append({'run': run, 'reason': 'minimum age not reached'})
        else:
            eligible.append(run)
    if eligible:
        suffix = '' if policy['action'] == 'backup' else '.zip'
        destination = Path(policy['destination'])/policy['name']/('scheduled-' + str(int(due)) + suffix)
        result['plan'] = plan(policy['root'], eligible, action=policy['action'], destination=destination)
    return result
