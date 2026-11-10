"""Container profile registry (pinned data) and signature-based container detection (standard library only).

``containerprofiles.json`` is data, not code: each container id lists its detection signature, suffixes, size bound, metadata slots,
protected structures, allowed changes, closed native side effects, per-family destination availability and removal recipes. The file is pinned
by digest, so a changed profile is a deliberate, reviewable change. Detection is by signature only; a suffix that disagrees with the detected
container is a note (``EXTENSION_MISMATCH``), never a reason to parse differently.
"""
import hashlib
import json
from pathlib import Path

PROFILES_SHA256 = '9d8c29592782573d231ed5e9dc25755ec84808c8b0be64b84b72217c95b41b4f'
PATH = Path(__file__).with_name('containerprofiles.json')
_CACHE = {}


class PinMismatch(Exception):
    pass


def load():
    if not _CACHE:
        raw = PATH.read_bytes()
        found = hashlib.sha256(raw).hexdigest()
        if found != PROFILES_SHA256:
            raise PinMismatch('containerprofiles.json digest %s does not match the pinned %s' % (found, PROFILES_SHA256))
        _CACHE['profiles'] = json.loads(raw)
    return _CACHE['profiles']


def profile(container):
    """The profile of one container id; a container without a profile fails closed with ``KeyError``."""
    return load()['containers'][container]


def containers():
    return tuple(load()['containers'])


def detect(data):
    """Container family by signature: ``'tiff'`` (TIFF or DNG), ``'png'``, ``'webp'``, ``'heif'`` or ``None``. DNG is told from TIFF by the locator."""
    head = bytes(data[:16])
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if head[:4] in (b'RIFF', b'RF64') and head[8:12] == b'WEBP':
        return 'webp'
    if head[4:8] == b'ftyp':
        return 'heif'
    if head[:4] in (b'II*\0', b'MM\0*', b'II+\0', b'MM\0+'):
        return 'tiff'
    return None


def by_suffix(name):
    """Container ids whose profile lists the suffix of a file name, for the extension-mismatch note only."""
    suffix = Path(str(name)).suffix.lower()
    return [c for c, p in load()['containers'].items() if suffix in p['suffixes']]


def destination(container, family):
    """Whether a metadata family has a destination in the container; an unknown container or family fails closed (``False``)."""
    try:
        return bool(profile(container)['destinations'][family])
    except KeyError:
        return False


CANONICAL = {'tiff': '.tif', 'dng': '.dng', 'png': '.png', 'webp': '.webp', 'heif': '.heic'}


def extension(located):
    """Canonical file extension of a located non-JPEG container (the native writer is told the type by name, so a capture is named by what it is, never by its source suffix); ``None`` for JPEG and XMP."""
    container = located['container']
    if container == 'heif' and located.get('brand') == 'avif':
        return '.avif'
    return CANONICAL.get(container)
