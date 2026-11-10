"""User-managed OCI application modules; never an authored execution endpoint."""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid

from .container_executor import DockerEngine, IsolationLimits, IsolationProfile
from .errors import fail
from .storage import atomic, encoded, load, digest
from .artifacts import file_digest

FORMAT = 'schemaxis.app-module/1'
ID = re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')


def private_path(path):
    path = Path(path).expanduser().absolute()
    if path.resolve() != path:
        fail('MODULE_PATH_UNSAFE', 'managed paths must not traverse symbolic links', str(path))
    return path


def regular(path):
    path = private_path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        fail('MODULE_PATH_UNSAFE', 'expected an owned regular file', str(path))
    return info


def read_json(path):
    info = regular(path)
    if info.st_size > 1024*1024:
        fail('INVALID_MODULE', 'module configuration exceeds one MiB', str(path))
    return load(Path(path).read_text(encoding='utf-8'))


def manifest(value):
    required = {'version', 'id', 'provider', 'applicationVersion', 'coreVersion', 'image',
                'platform', 'routes', 'qualification', 'limits', 'inputFiles'}
    if (not isinstance(value, dict) or set(value) != required or value['version'] != FORMAT
            or not isinstance(value['id'], str) or not ID.fullmatch(value['id'])
            or not isinstance(value['provider'], str) or not ID.fullmatch(value['provider'])
            or any(not isinstance(value[k], str) or not value[k].strip() or len(value[k]) > 256
                   for k in ('applicationVersion', 'coreVersion', 'qualification'))
            or value['qualification'].lower() in ('pending', 'unqualified', 'fixture-only')
            or value['platform'] != 'linux/amd64'
            or not isinstance(value['routes'], list) or not 1 <= len(value['routes']) <= 64
            or any(not isinstance(v, str) or not v for v in value['routes'])
            or len(set(value['routes'])) != len(value['routes'])
            or not isinstance(value['limits'], dict) or set(value['limits']) != set(asdict(IsolationLimits()))
            or not isinstance(value['inputFiles'], dict) or set(value['inputFiles']) != set(value['routes'])):
        fail('INVALID_MODULE', 'supply a complete qualified digest-pinned application module')
    try:
        image = value['image']
        if isinstance(image, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', image):
            image = 'local.invalid/module@'+image
        IsolationProfile(image, (value['provider'],), tuple(value['routes']),
                         IsolationLimits(**value['limits']), value['qualification'])
    except (TypeError, ValueError) as error:
        fail('INVALID_MODULE', str(error))
    for patterns in value['inputFiles'].values():
        if (not isinstance(patterns, list) or len(patterns) > 64 or len(set(map(str, patterns))) != len(patterns)
                or any(not isinstance(p, str) or not p.startswith('/') or len(p) > 1024
                       or re.search(r'~(?![01])', p) for p in patterns)):
            fail('INVALID_MODULE', 'inputFiles requires bounded JSON pointer patterns for every route')
    return load(encoded(value).decode())


class ModuleManager:
    def __init__(self, root=None, *, engine=None):
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))
        self.root = private_path(root or os.environ.get('SCHEMAXIS_MODULE_HOME', base/'schemaxis/modules'))
        self.engine = engine if engine is not None else DockerEngine()

    def _prepare(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.root.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            fail('MODULE_PATH_UNSAFE', 'module home must be private and owned', str(self.root))
        for name in ('catalogue', 'receipts', 'downloads'):
            path = private_path(self.root/name)
            path.mkdir(exist_ok=True, mode=0o700)

    @contextmanager
    def lock(self, *, exclusive=False):
        import fcntl
        self._prepare()
        path = self.root/'.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            regular(path)
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                fail('MODULES_BUSY', 'a module operation or workflow is active; retry when it finishes')
            yield
        finally:
            os.close(fd)

    def _path(self, category, identity, suffix='.json'):
        if not isinstance(identity, str) or not ID.fullmatch(identity):
            fail('INVALID_MODULE', 'choose a bounded module identity')
        return private_path(self.root/category/(identity+suffix))

    def _catalogue(self):
        entries = sorted((self.root/'catalogue').glob('*.json'))
        if len(entries) > 256:
            fail('INVALID_MODULE', 'module catalogue exceeds 256 entries')
        result = [manifest(read_json(path)) for path in entries]
        if any(path.stem != item['id'] for path, item in zip(entries, result)):
            fail('INVALID_MODULE', 'catalogue filename differs from its module identity')
        return result

    def register(self, value):
        value = manifest(value)
        with self.lock(exclusive=True):
            for other in self._catalogue():
                if other['id'] != value['id'] and set(other['routes']) & set(value['routes']):
                    fail('MODULE_CONFLICT', 'another module already supplies this route', other['id'])
            path = self._path('catalogue', value['id'])
            if path.exists() and read_json(path) != value:
                fail('MODULE_CONFLICT', 'use a new module identity for a changed manifest', value['id'])
            atomic(path, encoded(value))
        return {'registered': value['id'], 'manifestDigest': digest(value), 'image': value['image']}

    def _command(self, arguments, *, timeout=30):
        result = self.engine.command(arguments, timeout=timeout)
        if result.returncode:
            fail('MODULE_ENGINE_FAILED', 'container engine refused the module operation', arguments[0],
                 operation=arguments[:2], detail=result.stderr.decode(errors='replace')[-2048:])
        return result.stdout

    def _image(self, image, receipt=None):
        result = self.engine.command(['image', 'inspect', image], timeout=30)
        if result.returncode:
            # A daemon error is not evidence that the image is absent.
            self._command(['info', '--format', '{{.OSType}}'])
            if not receipt:
                return None
            result = self.engine.command(['image', 'inspect', receipt['imageId']], timeout=30)
            if result.returncode:
                return None
        records = load(result.stdout.decode())
        if not isinstance(records, list) or len(records) != 1:
            fail('MODULE_ENGINE_FAILED', 'engine returned an ambiguous image')
        record = records[0]
        if ((image not in record.get('RepoDigests', []) and image != record.get('Id')
                and (not receipt or receipt['imageId'] != record.get('Id')))
                or record.get('Os') != 'linux'
                or record.get('Architecture') != 'amd64'
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', record.get('Id', ''))
                or type(record.get('Size')) is not int or record['Size'] < 0):
            fail('MODULE_IMAGE_MISMATCH', 'installed image differs from its pinned module', image)
        return record

    def _receipt(self, item):
        path = self._path('receipts', item['id'])
        if not path.exists():
            return None
        value = read_json(path)
        if (not isinstance(value, dict) or set(value) != {'manifestDigest', 'imageId', 'engineId', 'owned', 'archiveSha256'}
                or value['manifestDigest'] != digest(item) or type(value['owned']) is not bool
                or not isinstance(value['engineId'], str) or not value['engineId']
                or not isinstance(value['imageId'], str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', value['imageId'])
                or value['archiveSha256'] is not None and (not isinstance(value['archiveSha256'], str)
                    or not re.fullmatch('[0-9a-f]{64}', value['archiveSha256']))):
            fail('INVALID_MODULE', 'managed installation receipt differs', item['id'])
        return value

    def _engine_identity(self):
        identity = self._command(['info', '--format', '{{.ID}}']).decode().strip()
        if not identity or len(identity) > 256:
            fail('MODULE_ENGINE_FAILED', 'container engine omitted its identity')
        return identity

    def _archive(self, item, receipt):
        path = self._path('downloads', item['id'], '.tar')
        if not path.exists():
            return None
        regular(path)
        sha = file_digest(path)
        if not receipt or sha != receipt['archiveSha256']:
            fail('MODULE_DOWNLOAD_CHANGED', 'cached download differs from its receipt', item['id'])
        return path

    def _ensure(self, item, *, allow_download=True, keep_download=False):
        receipt = self._receipt(item)
        image = self._image(item['image'], receipt)
        engine_id = self._engine_identity()
        owned = bool(receipt and image and receipt['engineId'] == engine_id
                     and receipt['owned'] and receipt['imageId'] == image['Id'])
        archive = self._archive(item, receipt)
        if image is None:
            if archive:
                self._command(['image', 'load', '--input', str(archive)], timeout=900)
            elif allow_download:
                if item['image'].startswith('sha256:'):
                    fail('MODULE_NOT_CACHED', 'local content-ID modules require their existing image or saved archive', item['id'])
                self._command(['image', 'pull', '--quiet', '--platform', item['platform'], item['image']], timeout=900)
            else:
                fail('MODULE_NOT_CACHED', 'download this module before running offline', item['id'])
            image = self._image(item['image'], receipt if archive else None)
            if image is None:
                fail('MODULE_IMAGE_MISMATCH', 'module transfer did not produce its pinned image', item['id'])
            owned = True
        value = {'manifestDigest': digest(item), 'imageId': image['Id'], 'engineId': engine_id, 'owned': owned,
                 'archiveSha256': receipt['archiveSha256'] if receipt else None}
        atomic(self._path('receipts', item['id']), encoded(value))
        if keep_download and archive is None:
            path = self._path('downloads', item['id'], '.tar')
            temporary = self.root/'downloads'/('.'+uuid.uuid4().hex+'.tar')
            try:
                self._command(['image', 'save', '--output', str(temporary), item['image']], timeout=900)
                regular(temporary)
                value['archiveSha256'] = file_digest(temporary)
                os.replace(temporary, path)
                atomic(self._path('receipts', item['id']), encoded(value))
            finally:
                temporary.unlink(missing_ok=True)
        return item

    def fetch(self, identities, *, keep_download=False, allow_download=True):
        with self.lock(exclusive=True):
            entries = {item['id']: item for item in self._catalogue()}
            if not identities or set(identities)-entries.keys():
                fail('UNKNOWN_MODULE', 'select registered modules', available=sorted(entries))
            for identity in dict.fromkeys(identities):
                self._ensure(entries[identity], keep_download=keep_download, allow_download=allow_download)
        return {'ready': list(dict.fromkeys(identities))}

    def settings(self):
        path = private_path(self.root/'settings.json')
        value = read_json(path) if path.exists() else {'backend': 'container', 'allowDownloads': True}
        if (not isinstance(value, dict) or set(value) != {'backend', 'allowDownloads'}
                or value['backend'] not in ('container', 'native') or type(value['allowDownloads']) is not bool):
            fail('INVALID_MODULE', 'invalid application module preferences')
        return value

    def configure(self, *, backend, allow_downloads):
        if backend not in ('container', 'native') or type(allow_downloads) is not bool:
            fail('INVALID_MODULE', 'choose container or native execution and a download preference')
        with self.lock(exclusive=True):
            atomic(self.root/'settings.json', encoded({'backend': backend, 'allowDownloads': allow_downloads}))
        return self.settings()

    def inventory(self):
        with self.lock():
            rows = []
            for item in self._catalogue():
                receipt = self._receipt(item)
                image = self._image(item['image'], receipt)
                archive = self._archive(item, receipt)
                rows.append({'id': item['id'], 'provider': item['provider'],
                    'applicationVersion': item['applicationVersion'], 'image': item['image'],
                    'manifestDigest': digest(item), 'installed': image is not None,
                    'owned': bool(receipt and image and receipt['owned'] and receipt['imageId'] == image['Id']
                                  and receipt['engineId'] == self._engine_identity()),
                    'imageId': image['Id'] if image else None, 'imageBytes': image['Size'] if image else 0,
                    'downloadBytes': archive.stat().st_size if archive else 0,
                    'routes': item['routes']})
            return {'modules': rows, 'settings': self.settings(), 'home': str(self.root),
                    'sizeScope': 'Image sizes include shared layers; disk reclamation is engine-dependent.',
                    'preserved': ['module catalogue', 'settings', 'native applications', 'projects', 'inputs', 'results']}

    def _cleanup_plan(self, identities, *, downloads=False):
        entries = {item['id']: item for item in self._catalogue()}
        if not identities or set(identities)-entries.keys():
            fail('UNKNOWN_MODULE', 'select registered modules explicitly', available=sorted(entries))
        rows = []
        for identity in sorted(set(identities)):
            item = entries[identity]
            receipt = self._receipt(item)
            image = self._image(item['image'], receipt)
            archive = self._archive(item, receipt)
            engine_id = self._engine_identity()
            owned = bool(receipt and image and receipt['owned'] and receipt['imageId'] == image['Id']
                         and receipt['engineId'] == engine_id)
            shared = []
            for other in entries.values():
                if other['id'] in identities or image is None:
                    continue
                other_receipt = self._receipt(other)
                if (other_receipt and other_receipt['engineId'] == engine_id
                        and other_receipt['imageId'] == image['Id']):
                    shared.append(other['id'])
            named_reference = bool(image and item['image'] in image.get('RepoDigests', []))
            removable = owned and not shared and (named_reference or not image.get('RepoTags'))
            containers = self._command(['container', 'ls', '-a', '--filter', 'ancestor='+image['Id'],
                                        '--format', '{{.ID}}']).decode().split() if image else []
            rows.append({'id': identity, 'image': item['image'], 'imageId': image['Id'] if image else None,
                         'removeImage': removable, 'blockedByContainers': containers, 'sharedWith': sorted(shared),
                         'removalReference': (item['image'] if item['image'] in image.get('RepoDigests', [])
                             else image['Id']) if image else None,
                         'otherTags': image.get('RepoTags', []) if image else [],
                         'removeDownload': bool(downloads and archive),
                         'archiveSha256': receipt['archiveSha256'] if receipt and archive else None,
                         'manifestDigest': digest(item), 'engineId': engine_id})
        plan = {'version': 'schemaxis.module-cleanup/1', 'home': str(self.root),
                'downloads': bool(downloads), 'modules': rows,
                'preserved': ['catalogue', 'settings', 'system applications', 'projects', 'inputs', 'results']}
        return {**plan, 'confirmation': digest(plan)}

    def cleanup_plan(self, identities, *, downloads=False):
        with self.lock():
            return self._cleanup_plan(identities, downloads=downloads)

    def clear(self, plan, confirmation):
        with self.lock(exclusive=True):
            if (not isinstance(plan, dict) or not isinstance(plan.get('modules'), list)
                    or not plan['modules'] or any(not isinstance(row, dict) or 'id' not in row for row in plan['modules'])
                    or type(plan.get('downloads')) is not bool):
                fail('STALE_MODULE_PLAN', 'review a current cache cleanup plan')
            current = self._cleanup_plan([row['id'] for row in plan['modules']], downloads=plan['downloads'])
            if current != plan or confirmation != current['confirmation']:
                fail('STALE_MODULE_PLAN', 'cache changed; review a fresh cleanup plan')
            if any(row['blockedByContainers'] for row in current['modules']):
                fail('MODULES_BUSY', 'selected images are referenced by containers; stop/remove those containers first')
            removed = []
            removed_references = set()
            for row in current['modules']:
                if row['removeImage'] and row['removalReference'] not in removed_references:
                    self._command(['image', 'rm', row['removalReference']])
                    removed_references.add(row['removalReference'])
                if row['removeDownload']:
                    self._path('downloads', row['id'], '.tar').unlink()
                    receipt = read_json(self._path('receipts', row['id']))
                    receipt['archiveSha256'] = None
                    atomic(self._path('receipts', row['id']), encoded(receipt))
                removed.append(row['id'])
            return {'cleared': removed, 'preserved': current['preserved'],
                    'downloadsPreserved': not current['downloads']}
