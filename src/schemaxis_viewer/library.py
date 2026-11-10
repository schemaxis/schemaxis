"""Local collection inventories and recent folder references; no media is copied."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading

MAX_FILES = 50000


def inventory(inputs):
    """Stable relative paths; discovered links never escape a selected root."""
    files, seen = [], set()
    for index, raw in enumerate(inputs):
        source = Path(raw).expanduser().resolve(strict=True)
        if not (source.is_dir() or source.is_file()):
            raise ValueError(f'Not a regular file or folder: {raw}')
        candidates = source.rglob('*') if source.is_dir() else [source]
        root = f'{index + 1}-{source.name}' if source.is_dir() else 'selected-files'
        for path in candidates:
            if source.is_dir() and '.output-index' in path.relative_to(source).parts:
                continue
            if not path.is_file():
                continue
            real = path.resolve()
            if source.is_dir() and not real.is_relative_to(source):
                continue
            if real in seen:
                continue
            seen.add(real)
            relative = path.relative_to(source).as_posix() if source.is_dir() else path.name
            files.append({'id': str(len(files)), 'name': f'{root}/{relative}' if source.is_dir() else relative,
                          'relativePath': relative, 'root': root, 'rootLabel': source.name if source.is_dir() else 'Selected files',
                          'size': path.stat().st_size, 'scope': root, '_path': real})
            if len(files) > MAX_FILES:
                raise ValueError(f'Collection exceeds {MAX_FILES} files; select a smaller folder')
    files.sort(key=lambda item: item['name'])
    for index, item in enumerate(files):
        item['id'] = str(index)
    return files


def source_folders(inputs):
    result = []
    for index, raw in enumerate(inputs):
        path = Path(raw).expanduser().resolve(strict=True)
        if not path.is_dir():
            continue
        folders = []
        for child in path.rglob('*'):
            if '.output-index' in child.relative_to(path).parts:
                continue
            if child.is_dir() and not child.is_symlink():
                folders.append(child.relative_to(path).as_posix())
                if len(folders) > MAX_FILES:
                    raise ValueError('Too many subfolders; choose a smaller folder')
        result.append({'root': f'{index + 1}-{path.name}', 'label': path.name, 'folders': folders})
    return result


def collection_kind(paths):
    """Recognise Schemaxis output membership without importing its runtime."""
    for raw in paths:
        manifest = Path(raw)/'publication-metadata.json'
        try:
            if manifest.stat().st_size > 2 * 1024 * 1024:
                continue
            value = json.loads(manifest.read_text())
            if isinstance(value, dict) and value.get('version') == 'schemaxis.artifact-metadata/1' and isinstance(value.get('publications'), list):
                return 'run'
        except (OSError, ValueError):
            pass
    return 'collection'


def history_file():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'schemaxis/viewer-recent.json'


class LocalLibrary:
    def __init__(self, history=None):
        self.lock = threading.RLock()
        self.collections = {}
        self.history = Path(history) if history else None
        self.recent = []
        self.preferences = {'theme': 'system', 'sidebarCollapsed': False}
        if self.history:
            try:
                saved = json.loads(self.history.read_text()[:256000])
                if isinstance(saved, dict):
                    preferences = saved.get('preferences', {})
                    if preferences.get('theme') in ('light', 'dark', 'system'):
                        self.preferences['theme'] = preferences['theme']
                    if type(preferences.get('sidebarCollapsed')) is bool:
                        self.preferences['sidebarCollapsed'] = preferences['sidebarCollapsed']
                    saved = saved.get('recent', [])
                self.recent = [row for row in saved if isinstance(row, dict) and isinstance(row.get('paths'), list)
                               and all(isinstance(p, str) for p in row['paths'])][:40]
            except (OSError, ValueError, TypeError):
                pass

    def register(self, paths, *, label=None, kind=None, key=None, expected=None):
        resolved = [str(Path(path).expanduser().resolve(strict=True)) for path in paths]
        kind = kind or collection_kind(resolved)
        records = inventory(resolved)
        sources = source_folders(resolved)
        expected = expected or {}
        for record in records:
            path = record['_path']
            fingerprint = path.stat()
            digest = expected.get(str(path))
            if digest:
                with path.open('rb') as stream:
                    digestor = hashlib.sha256()
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digestor.update(block)
                    actual = digestor.hexdigest()
                if actual != digest:
                    raise ValueError(f'Publication changed after verification: {path.name}')
            record['_fingerprint'] = (fingerprint.st_size, fingerprint.st_mtime_ns)
        identity = key or secrets.token_urlsafe(12)
        title = label or ', '.join(Path(path).name for path in resolved) or 'Local collection'
        row = {'id': identity, 'label': title, 'kind': kind, 'paths': resolved,
               'viewed': datetime.now(timezone.utc).isoformat(), 'count': len(records)}
        if kind == 'run':
            row['expected'] = expected
        with self.lock:
            self.collections[identity] = {'info': row, 'records': records, 'sources': sources}
            self.recent = [row, *[old for old in self.recent if old.get('paths') != resolved]][:40]
            self._save()
        return identity

    def _save(self):
        if self.history:
            temporary = None
            try:
                self.history.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.history.with_suffix('.tmp-' + secrets.token_hex(4))
                temporary.write_text(json.dumps({'recent': self.recent, 'preferences': self.preferences}))
                temporary.replace(self.history)
            except OSError:
                if temporary:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    def set_preferences(self, values):
        if not isinstance(values, dict) or set(values) - {'theme', 'sidebarCollapsed'}:
            raise ValueError('Unknown viewer preference')
        if 'theme' in values and values['theme'] not in ('light', 'dark', 'system'):
            raise ValueError('Choose light, dark or system')
        if 'sidebarCollapsed' in values and type(values['sidebarCollapsed']) is not bool:
            raise ValueError('Sidebar preference must be a boolean')
        with self.lock:
            self.preferences.update(values)
            self._save()
            return dict(self.preferences)

    def listing(self):
        with self.lock:
            return {'preferences': dict(self.preferences), 'recent': list(self.recent), 'collections': [entry['info'] | {'sources': entry['sources']} for entry in self.collections.values()]}

    def sources(self, identity):
        with self.lock:
            return self.collections[identity]['sources']

    def records(self, identity, prefix):
        with self.lock:
            if identity not in self.collections:
                recent = next((row for row in self.recent if row.get('id') == identity), None)
                if recent is None:
                    raise KeyError(identity)
                self.register(recent['paths'], label=recent.get('label'), kind=recent.get('kind', 'collection'), key=identity, expected=recent.get('expected'))
            collection = self.collections[identity]
            return [{key: value for key, value in row.items() if not key.startswith('_')} |
                    {'id': f'{identity}-{row["id"]}', 'url': f'{prefix}file/{identity}/{row["id"]}'}
                    for row in collection['records']]

    def file(self, identity, index):
        with self.lock:
            if not str(index).isdecimal():
                raise KeyError(index)
            row = self.collections[identity]['records'][int(index)]
            observed = row['_path'].stat()
            if (observed.st_size, observed.st_mtime_ns) != row['_fingerprint']:
                raise ValueError('Selected file changed; reopen the folder to refresh')
            return row['_path']


def browse(directory=None):
    """List names for a local folder chooser; file bytes require an explicit open."""
    path = Path(directory).expanduser().resolve(strict=True) if directory else Path.home()
    if not path.is_dir():
        raise ValueError('Choose a folder')
    children = []
    for child in path.iterdir():
        if child.is_dir() and not child.name.startswith('.'):
            children.append({'name': child.name, 'path': str(child)})
        if len(children) > 5000:
            raise ValueError('Too many folders; enter a more specific path')
    return {'directory': str(path), 'parent': str(path.parent),
            'folders': sorted(children, key=lambda child: child['name'].casefold())}
