"""Shared durable JSON and recursive native-runtime packaging."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

# Archive folder for licence and notice files (plugins below plugins/<distribution>);
# the hyphen keeps it out of the importable namespace.
LICENCES = 'schemaxis-licences'


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def _distribution(name):
    from importlib.metadata import PackageNotFoundError, distribution
    try:
        return distribution(name)
    except PackageNotFoundError:
        return None


def _checkout_root():
    """The source checkout that holds this core, or ``None`` for an installed wheel."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / 'pyproject.toml').is_file() and (root / 'LICENSE').is_file() else None


def _installed_licences(dist):
    """``(relative name, bytes)`` for a distribution's recorded licence files."""
    if dist is None:
        return []
    names = dist.metadata.get_all('License-File') or []
    found = []
    for name in names:
        # Metadata 2.4 stores them below dist-info/licenses; older tools at its root.
        for candidate in ('licenses/' + name, name):
            text = dist.read_text(candidate)
            if text is not None:
                found.append((name, text.encode('utf-8')))
                break
    return found


def licence_files():
    """The core's ``LICENSE``, ``NOTICE``, ``COPYRIGHT`` and ``LICENSES/*`` as ``(name, bytes)``."""
    root = _checkout_root()
    if root is None:
        return _installed_licences(_distribution('schemaxis'))
    paths = [root / name for name in ('LICENSE', 'NOTICE', 'COPYRIGHT')]
    paths += sorted((root / 'LICENSES').glob('*')) if (root / 'LICENSES').is_dir() else []
    return [(path.relative_to(root).as_posix(), path.read_bytes()) for path in paths if path.is_file()]


def runtime_archive():
    """Zip of the core, admitted plugin packages and their notices for native processes.

    Plugin entry points are recorded in ``schemaxis/adaptors/runtime-plugins.json``;
    the registry honours that host-written list only when imported from the archive.
    """
    source_root = Path(__file__).resolve().parents[1]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        from .adaptors.registry import ADAPTORS, RUNTIME_PLUGINS
        plugins = sorted((name, item) for name, item in ADAPTORS.items()
                         if item.get('source', 'builtin') != 'builtin')
        packages = ({'schemaxis'} | {p for item in ADAPTORS.values() for p in item.get('runtimePackages', [])}
                    | {item['package'] for _, item in plugins})
        bundled = 'schemaxis/adaptors/' + RUNTIME_PLUGINS
        for package in sorted(packages):
            folder = source_root / package.replace(".", "/")
            if not folder.is_dir():
                # An external adaptor package installed outside the core source tree.
                from importlib.resources import files
                folder = Path(str(files(package)))
            base = folder.parents[package.count('.')]
            for path in sorted(folder.rglob("*")):
                if not path.is_file() or path.suffix not in ('.py', '.json', '.txt'):
                    continue
                name = path.relative_to(base).as_posix()
                if name == bundled:
                    continue
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
            if not (folder / '__init__.py').exists():
                archive.writestr(zipfile.ZipInfo(package.replace('.', '/') + '/__init__.py'), '')
        entries = [{'id': name, 'package': item['package'],
                    'distribution': item['source'].partition(':')[2] or 'unknown'} for name, item in plugins]
        notices = [(bundled, (json.dumps({'version': 1, 'plugins': entries}, indent=2) + '\n').encode())]
        notices += [(LICENCES + '/' + name, data) for name, data in licence_files()]
        for distribution in sorted({entry['distribution'] for entry in entries}):
            notices += [(LICENCES + '/plugins/' + distribution + '/' + name, data)
                        for name, data in _installed_licences(_distribution(distribution))]
        for name, data in notices:
            archive.writestr(zipfile.ZipInfo(name), data, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()
