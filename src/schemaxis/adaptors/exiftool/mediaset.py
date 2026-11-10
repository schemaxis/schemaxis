"""Bounded media sets: explicit items or one declared folder, with a complete inclusion/exclusion manifest.

Planning is document-only. At run time a folder is scanned deterministically (byte-order names, no symbolic links followed, depth and
count declared), every scanned entry lands in the manifest with a reason, items are captured through checked descriptors, and the folder
is scanned again after capture: any difference is a structural fault, so a folder that changed during capture cannot be mistaken for the
set that was authored. Per-item problems are item faults; set-level problems (budget, vanished root, changed folder) fail the run.
"""
import hashlib
import os
from pathlib import Path
import re
import stat

from schemaxis.adaptors.exiftool import containers
from schemaxis.errors import fail, keys

MAX_ITEMS = 512
ITEM_BYTES = containers.MAX_BYTES
LARGE_ITEM_BYTES = 256 * 1024 * 1024          # TIFF and DNG (the registry's maxBytes); every other container, JPEG and XMP stay at ITEM_BYTES
LARGE_SUFFIXES = ('.tif', '.tiff', '.dng')


def item_limit(name):
    """The byte bound of one item by its (captured or source) name: 256 MiB for a TIFF or DNG suffix, else 64 MiB. The container itself is decided by signature afterwards."""
    return LARGE_ITEM_BYTES if str(name).lower().endswith(LARGE_SUFFIXES) else ITEM_BYTES


def large_bounds(media):
    """The additive published item bound of a media plan: ``{'maxLargeItemBytes', 'largeItemSuffixes'}`` when the set can hold a TIFF or DNG name (an explicit item path or a listed folder
    extension ending in a large suffix), else ``{}``. ``maxItemBytes`` stays the bound of every other name, so a JPEG-only plan (and its hash) never changes; the rule is the one ``item_limit``
    applies by name at the stat check, the bounded read, capture, the launcher input check, the native file-size limit, the output and replay reads and the stream hash."""
    names = [i['path'] for i in media['items']] if media['kind'] == 'items' else list(media['folder']['extensions'])
    if any(str(n).lower().endswith(LARGE_SUFFIXES) for n in names):
        return {'maxLargeItemBytes': LARGE_ITEM_BYTES, 'largeItemSuffixes': sorted(LARGE_SUFFIXES)}
    return {}


TOTAL_BYTES = 1024 * 1024 * 1024
MAX_SCANNED = 4096
MAX_DEPTH = 2
IMAGE_SUFFIXES = ('.jpg', '.jpeg')
OTHER_IMAGE_SUFFIXES = ('.tif', '.tiff', '.dng', '.png', '.webp', '.heic', '.heif', '.avif')    # E5: opt-in by listing them; detection is by signature, never by suffix
RASTER_SUFFIXES = IMAGE_SUFFIXES + OTHER_IMAGE_SUFFIXES
DEFAULT_SUFFIXES = IMAGE_SUFFIXES + ('.xmp',)                                                    # the default folder scope (and every retained plan hash) stays JPEG plus XMP sidecars
SUFFIXES = DEFAULT_SUFFIXES + OTHER_IMAGE_SUFFIXES
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,31}')
HEX = re.compile(r'[0-9a-f]{64}')
LIMIT_REASONS = ('symlink', 'too-large', 'count-limit', 'invalid-id', 'duplicate-id', 'ambiguous-sidecar', 'unreadable-entry')

SHA = {'type': 'string', 'minLength': 64, 'maxLength': 64}
PATH = {'type': 'string', 'minLength': 1, 'maxLength': 4096}
ITEM = {'type': 'object', 'properties': {'id': {'type': 'string', 'minLength': 1, 'maxLength': 32, 'required': True}, 'path': {**PATH, 'required': True}, 'sha256': SHA, 'sidecar': PATH}}
MEDIA = {'type': 'union', 'required': True, 'options': [
    {'type': 'object', 'properties': {'items': {'type': 'array', 'required': True, 'minItems': 1, 'maxItems': MAX_ITEMS, 'items': ITEM}}},
    {'type': 'object', 'properties': {'folder': {'type': 'object', 'required': True, 'properties': {
        'path': {**PATH, 'required': True}, 'extensions': {'type': 'array', 'minItems': 1, 'maxItems': len(SUFFIXES), 'uniqueItems': True, 'items': {'type': 'enum', 'values': list(SUFFIXES)}},
        'depth': {'type': 'integer', 'minimum': 0, 'maximum': MAX_DEPTH}, 'maxItems': {'type': 'integer', 'minimum': 1, 'maximum': MAX_ITEMS},
        'sidecars': {'type': 'enum', 'values': ['none', 'adjacent']}}}}}]}


def absolute(path, at):
    if '\0' in path or not path.startswith('/') or '..' in Path(path).parts:
        fail('INVALID_PHOTO_SOURCE', 'select an absolute local path without parent references', at)
    return path


def plan_media(media):
    """The effective media-set plan: ``{'kind': 'items', 'items': [...]}`` or ``{'kind': 'folder', 'folder': {...}}`` with every default explicit."""
    if not isinstance(media, dict):
        fail('INVALID_ARGUMENT', 'media must be an object with items or folder', '$.media')
    if 'items' in media:
        keys(media, ('items',), '$.media')
        items, seen, paths = [], set(), {}
        for index, entry in enumerate(media['items']):
            at = '$.media.items[%d]' % index
            keys(entry, ('id', 'path', 'sha256', 'sidecar'), at)
            if not IDENTIFIER.fullmatch(entry['id']):
                fail('INVALID_PHOTO_ID', 'use an ASCII letter followed by up to 31 letters, digits or underscores', at + '.id', value=entry['id'][:64])
            if entry['id'] in seen:
                fail('DUPLICATE_PHOTO_ID', 'item identities must be unique', at + '.id', value=entry['id'])
            seen.add(entry['id'])
            path = absolute(entry['path'], at + '.path')
            if Path(path).suffix.lower() not in SUFFIXES:
                fail('INVALID_PHOTO_SOURCE', 'select a .jpg, .jpeg, .tif, .tiff, .dng, .png, .webp, .heic, .heif, .avif or .xmp file', at + '.path')
            if 'sha256' in entry and not HEX.fullmatch(entry['sha256']):
                fail('INVALID_SHA256', 'use 64 lowercase hexadecimal digits', at + '.sha256')
            if 'sidecar' in entry:
                if Path(path).suffix.lower() == '.xmp':
                    fail('INVALID_SIDECAR', 'an XMP item does not take a sidecar', at + '.sidecar')
                if Path(absolute(entry['sidecar'], at + '.sidecar')).suffix.lower() != '.xmp':
                    fail('INVALID_SIDECAR', 'a sidecar must be an .xmp file', at + '.sidecar')
            normal = os.path.normpath(path)
            if normal in paths:
                fail('DUPLICATE_PHOTO_SOURCE', 'two authored items select the same file', at + '.path', photo=entry['id'], firstPhoto=paths[normal], expected='distinct source file', observed=normal[:200])
            paths[normal] = entry['id']
            items.append({k: entry[k] for k in ('id', 'path', 'sha256', 'sidecar') if k in entry})
        return {'kind': 'items', 'items': items}
    keys(media, ('folder',), '$.media')
    folder = media['folder']
    keys(folder, ('path', 'extensions', 'depth', 'maxItems', 'sidecars'), '$.media.folder')
    extensions = folder.get('extensions', list(DEFAULT_SUFFIXES))
    return {'kind': 'folder', 'folder': {'path': absolute(folder['path'], '$.media.folder.path'), 'extensions': sorted(extensions, key=SUFFIXES.index),
                                         'depth': folder.get('depth', 1), 'maxItems': folder.get('maxItems', 64), 'sidecars': folder.get('sidecars', 'adjacent')}}


def derive_id(stem):
    name = re.sub(r'[^A-Za-z0-9_]', '_', stem)
    if not name or not name[0].isalpha():
        name = 'p_' + name
    return name[:32]


def lstat(path):
    try:
        return os.lstat(path)
    except OSError as error:
        fail('MEDIA_FOLDER_UNREADABLE', 'the media folder or an entry cannot be read: ' + str(error), str(path))


def scan(root, depth):
    """Every entry under the root (depth-limited, no links followed) as sorted dicts with checks and an in-memory change signature."""
    info = lstat(root)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail('INVALID_MEDIA_FOLDER', 'select a real directory, not a link or file', '$.media.folder.path')
    found, pending = [], [(root, '', 0)]
    while pending:
        directory, relative, level = pending.pop(0)
        try:
            names = sorted(os.listdir(directory), key=os.fsencode)
        except OSError as error:
            fail('MEDIA_FOLDER_UNREADABLE', 'a directory cannot be listed: ' + str(error), relative or '.')
        for name in names:
            path, rel = os.path.join(directory, name), (relative + '/' + name) if relative else name
            if len(found) >= MAX_SCANNED:
                fail('MEDIA_FOLDER_LIMIT', 'the folder has more than %d entries within the declared depth; select a narrower folder' % MAX_SCANNED, '$.media.folder.path')
            try:
                st = os.lstat(path)
            except OSError:
                found.append({'path': rel, 'abs': path, 'kind': 'unreadable', 'signature': None, 'bytes': None})
                continue
            kind = 'symlink' if stat.S_ISLNK(st.st_mode) else 'directory' if stat.S_ISDIR(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode) else 'special'
            found.append({'path': rel, 'abs': path, 'kind': kind, 'signature': (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns), 'bytes': st.st_size, 'identity': (st.st_dev, st.st_ino)})
            if kind == 'directory' and not name.startswith('.') and level < depth:
                pending.append((path, rel, level + 1))
    return sorted(found, key=lambda e: os.fsencode(e['path']))


def expand(plan):
    """``(manifest rows, items, signatures)`` of a folder plan: every scanned entry is a row (included, or excluded with a reason)."""
    folder = plan['folder']
    scanned = scan(folder['path'], folder['depth'])
    by_path = {e['path']: e for e in scanned}
    rows = {}

    def exclude(entry, reason, **more):
        rows[entry['path']] = {'path': entry['path'], 'role': 'excluded', 'included': False, 'reason': reason, **more}
    candidates = {}
    for entry in scanned:
        name = entry['path'].rpartition('/')[2]
        if entry['kind'] == 'unreadable':
            exclude(entry, 'unreadable-entry')
        elif entry['kind'] == 'symlink':
            exclude(entry, 'symlink')
        elif entry['kind'] == 'directory':
            exclude(entry, 'hidden' if name.startswith('.') else 'directory-beyond-depth' if entry['path'].count('/') >= folder['depth'] else 'directory-scanned')
        elif entry['kind'] == 'special':
            exclude(entry, 'not-regular')
        elif name.startswith('.'):
            exclude(entry, 'hidden')
        elif Path(name).suffix.lower() not in SUFFIXES:
            exclude(entry, 'extension')
        else:
            candidates[entry['path']] = entry
    wanted = {path: entry for path, entry in candidates.items() if Path(path).suffix.lower() in folder['extensions']}
    for path, entry in candidates.items():
        if path not in wanted and not (folder['sidecars'] == 'adjacent' and Path(path).suffix.lower() == '.xmp'):
            exclude(entry, 'extension')
    claims = {}
    if folder['sidecars'] == 'adjacent':
        for path in wanted:
            if Path(path).suffix.lower() in RASTER_SUFFIXES:
                directory, _, name = path.rpartition('/')
                prefix = directory + '/' if directory else ''
                for option in (prefix + Path(name).stem + '.xmp', prefix + name + '.xmp'):
                    if option in candidates:
                        claims.setdefault(option, []).append(path)
    options = {}
    for sidecar, images in claims.items():
        for image in images:
            options.setdefault(image, []).append(sidecar)
    ambiguous = {image for image, found in options.items() if len(found) > 1 or any(len(claims[s]) > 1 for s in found)}
    for image in sorted(ambiguous):
        exclude(wanted[image], 'ambiguous-sidecar', sidecars=sorted(options[image]))
        for sidecar in options[image]:
            exclude(candidates[sidecar], 'ambiguous-sidecar', image=image)
    paired = {image: found[0] for image, found in options.items() if image not in ambiguous}
    claimed = set(paired.values())
    items, used = [], {}
    for path, entry in wanted.items():
        if path in rows or path in claimed:
            continue
        if entry['bytes'] > item_limit(path):
            exclude(entry, 'too-large', bytes=entry['bytes'])
            continue
        identifier = derive_id(Path(path).stem)
        if not IDENTIFIER.fullmatch(identifier):
            exclude(entry, 'invalid-id')
        elif identifier in used:
            exclude(entry, 'duplicate-id', id=identifier, firstPath=used[identifier])
        elif len(items) >= folder['maxItems']:
            exclude(entry, 'count-limit')
        else:
            used[identifier] = path
            side = candidates[paired[path]] if path in paired else None
            items.append({'id': identifier, 'entry': entry, 'sidecar': side if side is not None and side['bytes'] <= ITEM_BYTES else None})
            rows[path] = {'path': path, 'role': 'item', 'included': True, 'id': identifier}
            if side is not None and side['bytes'] > ITEM_BYTES:
                exclude(side, 'too-large', bytes=side['bytes'])
            elif side is not None:
                rows[side['path']] = {'path': side['path'], 'role': 'sidecar', 'included': True, 'reason': 'sidecar-of:' + identifier, 'id': identifier}
    for path in claimed:
        if path not in rows:
            exclude(candidates[path], 'sidecar-image-not-included', image=[i for i, s in paired.items() if s == path][0])
    for entry in scanned:
        rows.setdefault(entry['path'], {'path': entry['path'], 'role': 'excluded', 'included': False, 'reason': 'extension'})
    return [rows[e['path']] for e in scanned], items, {e['path']: e['signature'] for e in scanned}


def read_file(path, expected_identity, limit, at, **observed):
    """Bounded read through one no-follow descriptor whose identity must equal the pre-checked entry."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError('not a bounded regular file')
            if expected_identity is not None and (info.st_dev, info.st_ino) != tuple(expected_identity):
                raise ValueError('the file identity changed after the pre-read check')
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        if len(data) > limit or len(data) != info.st_size or (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('the file changed while it was read or exceeds its budget')
        return data
    except (OSError, ValueError) as error:
        fail('INVALID_PHOTO_SOURCE', 'select an intact regular file within the byte budget: ' + str(error), at, **observed)


def explicit_stat(path, at, item):
    try:
        info = os.lstat(path)
    except OSError as error:
        fail('INVALID_PHOTO_SOURCE', 'select an intact regular local file: ' + str(error), at, photo=item)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail('INVALID_PHOTO_SOURCE', 'select a regular file, not a link, device or directory', at, photo=item)
    if info.st_size > item_limit(path):
        fail('PHOTO_RESOURCE_LIMIT', 'an item exceeds %d bytes' % item_limit(path), at, photo=item, observed=info.st_size)
    return (info.st_dev, info.st_ino)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def manifest_digest(rows):
    import json
    return sha(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode())
