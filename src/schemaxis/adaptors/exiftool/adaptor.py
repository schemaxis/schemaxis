"""Read-only selected-metadata inventory of 1 to 16 captured baseline JPEG field photos with ExifTool 13.55.

Each photo is captured into the run, admitted by an independent standard-library structural reader (width/height from the
JPEG frame header; IFD0 Make/Model/Orientation; ExifIFD DateTimeOriginal/OffsetTimeOriginal) and only then given to a
genuine ExifTool process with a fixed argument list. ExifTool is untrusted: its group-qualified JSON for exactly the
selected tags is compared field by field with the independent reader, a second fresh process must repeat it byte for
byte, and every published file is rebuilt from the reader's values. Nothing here writes, rotates, strips or decodes an
image, reads GPS or other tags, uses filesystem times, or certifies when, where or by whom a photo was taken.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time

from schemaxis.adaptors.exiftool import jpeg, options
from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.exiftool/1'
OPERATION = 'inventoryPhotos'
WORKBENCH_OPERATIONS = tuple(options.OPTIONS)
WRITE_OPERATIONS = tuple(options.WRITE_OPTIONS)
# The public order keeps every E1/E2 operation (and so every E1/E2 message, enum and schema address that Studio guidance is keyed by) where it was; E3 appends.
HOST_OPERATIONS = tuple(options.E4_HOST_OPTIONS)
OPERATION_ORDER = (OPERATION, *WORKBENCH_OPERATIONS[:3], *WRITE_OPERATIONS[:2], *WORKBENCH_OPERATIONS[3:], *WRITE_OPERATIONS[2:], *HOST_OPERATIONS)
WORKBENCH_KEYS = tuple(sorted(set().union(*options.OPTIONS.values(), *options.WRITE_OPTIONS.values(), *options.E4_HOST_OPTIONS.values()) - {'version', 'operation', 'photos'}))
RUNTIME = 'exiftool 13.55'
PERL = '/usr/bin/perl'
MAX_PHOTOS = 16
PHOTO_LIMIT = jpeg.MAX_BYTES
TOTAL_LIMIT = 16 * 1024 * 1024
JSON_LIMIT = 8 * 1024 * 1024
LOG_LIMIT = 4 * 1024 * 1024
RUNTIME_FILE_LIMIT = 256 * 1024 * 1024
MAX_RUNTIME_FILES = 1024
NULL_TOKEN = '\\N'
CSV_FORMAT = 'schemaxis.calc.typed-csv/1'
HEX = re.compile(r'[0-9a-f]{64}')
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,31}')
STAGES = ('version', 'libraries', 'modules', 'extract', 'repeat')
PHOTO_DIRECTORY = 'captured'
SELECTED = ('IFD0:Make', 'IFD0:Model', 'IFD0:Orientation', 'ExifIFD:DateTimeOriginal', 'ExifIFD:OffsetTimeOriginal',
            'File:ImageWidth', 'File:ImageHeight', 'File:EncodingProcess', 'File:BitsPerSample', 'File:ColorComponents',
            'ExifTool:Warning', 'ExifTool:Error')
FRAME_FACTS = {'File:EncodingProcess': '0', 'File:BitsPerSample': '8', 'File:ColorComponents': '3'}
MODULE_PROBE = 'require Image::ExifTool; print qq($_\\t$INC{$_}\\n) for sort keys %INC;'
COLUMNS = (('id', 'text', False), ('width', 'number', False), ('height', 'number', False), ('orientation', 'number', True),
           ('cameraMake', 'text', True), ('cameraModel', 'text', True), ('capturedLocal', 'text', True),
           ('utcOffset', 'text', True), ('capturedUtc', 'text', True))
SHA = {'type': 'string', 'minLength': 64, 'maxLength': 64}
PATH = {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}
OPTIONS = {'photos': {'type': 'array', 'required': True, 'minItems': 1, 'maxItems': MAX_PHOTOS, 'items': {
    'type': 'object', 'properties': {'id': {'type': 'string', 'minLength': 1, 'maxLength': 32, 'required': True}, 'path': PATH, 'sha256': SHA}}}}
DECLARATIONS = {OPERATION: {
    'native': 'perl exiftool -config "" -json -n -a -G1:4 -e -q -IFD0:Make -IFD0:Model -IFD0:Orientation -ExifIFD:DateTimeOriginal -ExifIFD:OffsetTimeOriginal '
              '-File:ImageWidth -File:ImageHeight -File:EncodingProcess -File:BitsPerSample -File:ColorComponents -ExifTool:Warning -ExifTool:Error captured/ID.jpg...',
    'kinds': ['text', 'table'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}, **options.DECLARATIONS}
REVIEW = ('Observed selected metadata only. A camera can record a wrong clock, zone, orientation or make; ExifTool and the independent reader '
          'agree on what bytes say, not on when, where or by whom the photograph was taken. Timestamps are camera-recorded wall time '
          '(never filesystem times); a UTC value exists only where the same file records an explicit offset. Orientation is the stored '
          'EXIF code, not applied pixels. A person must reconcile photos with field observations before publication.')
LOSSES = [
    '1 to 16 local regular baseline sequential 8-bit three-component JPEG/JFIF files, at most 8MiB each and 16MiB in total; progressive, extended, lossless, arithmetic, greyscale, CMYK, multi-frame, multi-scan, trailing-data, RAW, HEIC and other formats are refused. Success certifies marker/length structure only: entropy data is scanned for a well-formed end, never decoded, so there is no pixel-decode, image-quality or visual-truth claim.',
    'Selected fields only: JPEG frame width/height, IFD0 Make/Model/Orientation and ExifIFD DateTimeOriginal/OffsetTimeOriginal. GPS, thumbnails, MakerNotes, XMP, IPTC, ICC, sub-seconds, CreateDate, lens, serial numbers and every other tag are UNASSESSED: they are neither read into the outputs nor claimed absent, and ExifTool is asked for group-qualified selected raw tags only (no composite or inferred tags).',
    'Every selected value must be absent or well formed; absence is an explicit null, never a filesystem time, CreateDate or zero. A duplicate selected tag, a second Exif segment, a cyclic or over-long IFD chain, a bad count, offset or type, an out-of-range orientation, a calendar-invalid date or an unsupported offset refuses the named authored photo before ExifTool starts. Make and Model must be printable ASCII without leading or trailing blanks and not equal to the null token; such strings are never normalized.',
    'Capture time is a camera-recorded wall time without a zone (capturedLocal) and is never labelled UTC; capturedUtc is exact arithmetic from the recorded wall time and offset only where OffsetTimeOriginal is present. No device time zone is inferred and no time, place or authorship is certified. Orientation is the EXIF code 1-8 and is not applied to the pixels.',
    'Read-only: images are never written, rotated, stripped or re-encoded; no face identification, geolocation, thumbnail extraction or source authentication is offered. Hashes identify the bytes captured for this run, not their origin.',
    'The typed inventory.csv holds exactly the columns id, width, height, orientation, cameraMake, cameraModel, capturedLocal, utcOffset and capturedUtc; absent values are the null token \\N. A Calc typed-table consumer needs at least two present values in every number column, so a workbook handoff needs at least two photos and at least two orientation codes.',
    'ExifTool 13.55 (production release, GitHub tag commit de11d240) runs through the system Perl with a clean fixed environment, one thread and no user configuration. The script, every library file under its lib directory, the Perl binary, loaded shared libraries and eagerly loaded Perl modules are hashed before and after; modules loaded lazily by Perl itself are not enumerated.']


# ---------------------------------------------------------------- planning
def workbench(document):
    return isinstance(document, dict) and document.get('operation') in WORKBENCH_OPERATIONS


def writer(document):
    return isinstance(document, dict) and document.get('operation') in WRITE_OPERATIONS


def host(document):
    return isinstance(document, dict) and document.get('operation') in HOST_OPERATIONS


def plan(document):
    keys(document, ('version', 'operation', 'photos', *WORKBENCH_KEYS), '$')  # the closed root envelope of every operation; each operation then checks its own subset
    if workbench(document):
        from schemaxis.adaptors.exiftool import workbench as wb
        return wb.plan(document)
    if writer(document):
        from schemaxis.adaptors.exiftool import editing
        return editing.plan(document)
    if host(document):
        from schemaxis.adaptors.exiftool import e4host
        return e4host.plan(document)
    if isinstance(document, dict) and isinstance(document.get('operation'), str) and document['operation'] != OPERATION and set(document) & set(WORKBENCH_KEYS):
        # a workbench-shaped document that names an operation this adaptor does not offer: say so, rather than listing its keys as unsupported
        fail('UNKNOWN_OPERATION', 'select ' + ', '.join(OPERATION_ORDER), '$.operation', value=document['operation'][:64])
    keys(document, ('version', 'operation', 'photos'), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version')
    if document.get('operation') != OPERATION: fail('UNKNOWN_OPERATION', 'select ' + OPERATION, '$.operation')
    p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS})
    seen = set()
    paths = {}
    for index, photo in enumerate(p['photos']):
        at = f'$.photos[{index}]'
        if not IDENTIFIER.fullmatch(photo['id']): fail('INVALID_PHOTO_ID', 'use an ASCII letter followed by up to 31 letters, digits or underscores', at + '.id', value=photo['id'][:64])
        if photo['id'] in seen: fail('DUPLICATE_PHOTO_ID', 'photo identities must be unique', at + '.id', value=photo['id'])
        seen.add(photo['id'])
        path = photo['path']
        if '\0' in path or not path.startswith('/') or '..' in Path(path).parts or Path(path).suffix.lower() not in ('.jpg', '.jpeg'):
            fail('INVALID_PHOTO_SOURCE', 'select an absolute local .jpg or .jpeg path without parent references', at + '.path')
        if 'sha256' in photo and not HEX.fullmatch(photo['sha256']): fail('INVALID_SHA256', 'use 64 lowercase hexadecimal digits', at + '.sha256')
        normal = os.path.normpath(path)
        if normal in paths: fail('DUPLICATE_PHOTO_SOURCE', 'two authored photos select the same file; select each source file once (distinct files with identical bytes remain allowed)', at + '.path', photo=photo['id'], firstPhoto=paths[normal], expected='distinct source file', observed=normal[:200])
        paths[normal] = photo['id']
    return {'version': 'schemaxis.exiftool.plan/1', 'operation': OPERATION, **p,
            'settings': {'selectedTags': list(SELECTED), 'duplicateGrouping': 'G1:4', 'numericValues': True, 'composite': False, 'userConfiguration': False, 'threads': 1},
            'budget': {'maxPhotos': MAX_PHOTOS, 'maxPhotoBytes': PHOTO_LIMIT, 'maxTotalBytes': TOTAL_LIMIT, 'maxSegments': jpeg.MAX_SEGMENTS,
                       'maxIfdEntries': jpeg.MAX_IFD_ENTRIES, 'maxStringCharacters': jpeg.MAX_STRING},
            'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    from schemaxis.adaptors.exiftool import workbench as wb
    inventory = object_schema({'version': {'const': VERSION}, 'operation': {'const': OPERATION},
        **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', 'photos'])
    from schemaxis.adaptors.exiftool import e4host, editing
    extra, written, hosted = wb.schema(), editing.schema(), e4host.schema()

    def union(a, b):
        """The root schema of a key that two operation groups both declare: equal schemas stay as they are, otherwise either group's alternatives (each operation branch below keeps its own strict schema)."""
        return a if a == b else {'anyOf': [*a.get('anyOf', [a]), *b.get('anyOf', [b])]}
    shared = {k: union(written['properties'][k], v) for k, v in hosted['properties'].items() if k in written['properties'] and k != 'operation'}
    properties = {**inventory['properties'], **extra['properties'], **written['properties'], **{k: v for k, v in hosted['properties'].items() if k not in written['properties'] and k != 'operation'}, **shared, 'operation': {'enum': list(OPERATION_ORDER)}}
    branches = {branch['properties']['operation']['const']: branch for branch in [inventory, *extra['oneOf'], *written['oneOf'], *hosted['oneOf']]}
    return {'$schema': DRAFT, **object_schema(properties, ['version', 'operation']), 'oneOf': [branches[name] for name in OPERATION_ORDER]}


def query(document): return [plan(document)['operation']], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: fail('INVALID_EXECUTION', 'metadata inspection runs one serial native thread', identity)
    return {'threads': 1}


def plan_hash(p): return hashlib.sha256(json.dumps(p, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


# ---------------------------------------------------------------- bounded host inputs
def bounded(path, code='VERIFICATION_FAILED', limit=JSON_LIMIT, follow=False, location=None, identity=None, **observed):
    try:
        fd = os.open(path, os.O_RDONLY | (0 if follow else getattr(os, 'O_NOFOLLOW', 0)) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit: raise ValueError('not a bounded regular file')
            if identity is not None and (info.st_dev, info.st_ino) != tuple(identity): raise ValueError('file identity changed after the pre-read check')
            data = stream.read(limit + 1)
        if len(data) > limit: raise ValueError('file byte budget exceeded')
        return data
    except (OSError, ValueError) as error: fail(code, 'select an intact regular file within the byte budget: ' + str(error), location or str(path), **observed)


def stream_capture(path, limit, code, follow=True, checkpoint=None, location=None):
    """Hash through one open descriptor; the identity records what was actually read."""
    try:
        fd = os.open(path, os.O_RDONLY | (0 if follow else getattr(os, 'O_NOFOLLOW', 0)) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit: raise ValueError('not a bounded regular file')
            digest = hashlib.sha256();count = 0
            for block in iter(lambda: stream.read(1 << 20), b''):
                if checkpoint: checkpoint()
                count += len(block)
                if count > limit: raise ValueError('byte budget exceeded')
                digest.update(block)
            after = os.fstat(stream.fileno())
        if count != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino): raise ValueError('file changed while it was read')
        return {'sha256': digest.hexdigest(), 'bytes': count}
    except (OSError, ValueError) as error: fail(code, 'select an intact regular file within the byte budget: ' + str(error), location or str(path))


def sha(data): return hashlib.sha256(data).hexdigest()
def whole(value): return type(value) is int


class Number(str):
    """JSON number token kept as text, so 1.50 and 007-like values are compared exactly and never rounded."""


def strict_json(data, at, code='VERIFICATION_FAILED', tokens=False):
    def pairs(items):
        if len({k for k, _ in items}) != len(items): raise ValueError('duplicate JSON key')
        return dict(items)
    def constant(name): raise ValueError('non-finite JSON number ' + name)
    try:
        text = data.decode('utf-8')
        if text.startswith('﻿'): raise ValueError('byte-order mark')
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, **({'parse_int': Number, 'parse_float': Number} if tokens else {}))
    except (UnicodeDecodeError, ValueError, RecursionError) as error: fail(code, 'evidence is not strict UTF-8 JSON: ' + str(error), at)


def same_json(actual, expected):
    try: return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError): return False


def encode_json(value): return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')
def read(directory, name): return strict_json(bounded(directory / name), name)
def digest(directory, name, limit=JSON_LIMIT): return sha(bounded(directory / name, limit=limit))
def photo_file(photo): return f'{PHOTO_DIRECTORY}/{photo["id"]}.jpg'
def evidence_limit(name): return PHOTO_LIMIT if name.startswith(PHOTO_DIRECTORY + '/') else JSON_LIMIT


# ---------------------------------------------------------------- photo admission (independent reader, before any native process)
def admit_photo(data, index, photo):
    at = f'$.photos[{index}].path'
    facts = jpeg.parse(data, at, photo['id'])
    for name, field in (('make', 'IFD0:Make'), ('model', 'IFD0:Model')):
        if facts[name] == NULL_TOKEN: fail('INVALID_EXIF_VALUE', field + ' equals the reserved null token of the typed inventory', at, photo=photo['id'], field=field)
    if 'sha256' in photo and photo['sha256'] != sha(data): fail('PHOTO_HASH_MISMATCH', 'photo bytes differ from the pinned sha256', f'$.photos[{index}].sha256', photo=photo['id'], observed=sha(data))
    return {'bytes': len(data), 'sha256': sha(data), **facts}


def prestat_photos(p):
    """Size, device+inode, link and regularity of EVERY selected source, and the aggregate budget, before any content is read."""
    stats, total, seen = [], 0, {}
    for index, photo in enumerate(p['photos']):
        at = f'$.photos[{index}].path'
        try: info = os.lstat(photo['path'])
        except OSError as error: fail('INVALID_PHOTO_SOURCE', 'select an intact regular local file: ' + str(error), at, photo=photo['id'])
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode): fail('INVALID_PHOTO_SOURCE', 'select a regular file, not a link, device or directory', at, photo=photo['id'])
        if info.st_size > PHOTO_LIMIT: fail('PHOTO_RESOURCE_LIMIT', f'a photo exceeds {PHOTO_LIMIT} bytes', at, photo=photo['id'], observed=info.st_size)
        identity = (info.st_dev, info.st_ino)
        if identity in seen: fail('DUPLICATE_PHOTO_SOURCE', 'two authored photos reach the same file (alias, link or hard link); select each source file once (distinct files with identical bytes remain allowed)', at, photo=photo['id'], firstPhoto=seen[identity], expected='distinct source file', observed='same device and inode')
        seen[identity] = photo['id']
        total += info.st_size
        if total > TOTAL_LIMIT: fail('PHOTO_RESOURCE_LIMIT', f'photos exceed {TOTAL_LIMIT} bytes in total', at, photo=photo['id'], observed=total)
        stats.append(identity)
    return stats


def capture_photos(p, checkpoint=None):
    identities, captured, total = prestat_photos(p), [], 0
    for index, photo in enumerate(p['photos']):
        if checkpoint: checkpoint()
        data = bounded(photo['path'], 'INVALID_PHOTO_SOURCE', PHOTO_LIMIT, location=f'$.photos[{index}].path', photo=photo['id'], identity=identities[index])
        total += len(data)
        if total > TOTAL_LIMIT: fail('PHOTO_RESOURCE_LIMIT', f'photos exceed {TOTAL_LIMIT} bytes in total', f'$.photos[{index}].path', photo=photo['id'])
        captured.append((data, admit_photo(data, index, photo)))
    return captured


def reusableInputs(document):
    if workbench(document):
        from schemaxis.adaptors.exiftool import workbench as wb
        return wb.reusableInputs(document)
    if writer(document):
        from schemaxis.adaptors.exiftool import editing
        return editing.reusableInputs(document)
    if host(document):
        from schemaxis.adaptors.exiftool import e4host
        return e4host.reusableInputs(document)
    p = plan(document)
    return {photo['id']: sha(data) for photo, (data, _) in zip(p['photos'], capture_photos(p))}


# ---------------------------------------------------------------- native commands and launcher
def commands(script, p):
    lib = str(Path(script).parent / 'lib')
    extract = [PERL, script, '-config', '', '-json', '-n', '-a', '-G1:4', '-e', '-q', *['-' + tag for tag in SELECTED], *[photo_file(x) for x in p['photos']]]
    return {'version': [PERL, script, '-config', '', '-ver'], 'libraries': [PERL, '-e', '1'], 'modules': [PERL, '-I', lib, '-e', MODULE_PROBE],
            'extract': extract, 'repeat': list(extract)}


def stage_inputs(stage, p): return [photo_file(x) for x in p['photos']] if stage in ('extract', 'repeat') else []


def launcher(directory, stage, command, p):
    """Trusted launcher: binds inputs by hash, fixes a clean environment and resource caps, never trusts ambient Perl or ExifTool configuration."""
    environment = {'LANG': 'C', 'LC_ALL': 'C', **({'LD_TRACE_LOADED_OBJECTS': '1'} if stage == 'libraries' else {})}
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'
        + f'command={command!r}\nnames={stage_inputs(stage, p)!r}\nenvironment={environment!r}\nbindings={{"files":{{}}}}\n'
        + 'resource.setrlimit(resource.RLIMIT_CPU,(300,300))\nresource.setrlimit(resource.RLIMIT_FSIZE,(16777216,16777216))\nresource.setrlimit(resource.RLIMIT_AS,(4294967296,4294967296))\nresource.setrlimit(resource.RLIMIT_CORE,(0,0))\n'
        + 'for name in names:\n    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,"O_NONBLOCK",0))\n'
        + '    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        + f'        if not stat.S_ISREG(info.st_mode) or info.st_size>{PHOTO_LIMIT}: raise ValueError("invalid native input")\n'
        + '        h=hashlib.sha256();count=0\n        for block in iter(lambda:stream.read(1<<20),b""):\n            count+=len(block);h.update(block)\n'
        + '        if count!=info.st_size: raise ValueError("native input changed while read")\n    bindings["files"][name]=h.hexdigest()\n'
        + f'Path({stage + "-inputs.json"!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        + 'os.execve(command[0],command,dict(environment))\n')


def qualified_runtime(directory, code='UNSUPPORTED_NATIVE_VERSION'):
    text = bounded(directory / 'version.stdout', code, 4096).decode('utf-8', 'replace')
    if text != '13.55\n': fail(code, 'configure the qualified ExifTool 13.55 production release', 'version', observed=text[:200])
    return RUNTIME


def loader_paths(directory):
    found = []
    for line in bounded(directory / 'libraries.stdout', 'VERIFICATION_FAILED', LOG_LIMIT).decode('utf-8', 'replace').splitlines():
        line = line.strip()
        if not line or line.startswith('linux-vdso') or line.startswith('statically linked'): continue
        match = re.fullmatch(r'(\S+) => (/.+?) \(0x[0-9a-f]+\)', line) or re.fullmatch(r'()(/.+?) \(0x[0-9a-f]+\)', line)
        if not match: fail('RUNTIME_UNRESOLVED', 'dynamic dependency cannot be resolved to a local file', 'libraries', observed=line[:200])
        found.append((match.group(1) or Path(match.group(2)).name, match.group(2)))
    return sorted(found)


def module_paths(directory):
    found = []
    for line in bounded(directory / 'modules.stdout', 'VERIFICATION_FAILED', LOG_LIMIT).decode('utf-8', 'replace').splitlines():
        name, separator, path = line.partition('\t')
        if not separator or not name or not path.startswith('/'): fail('RUNTIME_UNRESOLVED', 'loaded Perl module cannot be resolved to a local file', 'modules', observed=line[:200])
        found.append((name, path))
    if not any(name == 'Image/ExifTool.pm' for name, _ in found): fail('RUNTIME_UNRESOLVED', 'the probe did not load Image::ExifTool', 'modules')
    return sorted(found)


def library_tree(script, checkpoint=None):
    root = Path(script).parent / 'lib'
    members = []
    for base, directories, names in os.walk(root, followlinks=False):
        directories.sort()
        for name in sorted(names):
            path = Path(base) / name
            if path.is_symlink(): fail('RUNTIME_UNRESOLVED', 'ExifTool library members must be regular files, not links', str(path.relative_to(root)))
            members.append(path)
            if len(members) > MAX_RUNTIME_FILES: fail('RUNTIME_RESOURCE_LIMIT', 'ExifTool library tree has too many files', 'lib')
    if not members: fail('RUNTIME_UNRESOLVED', 'the ExifTool lib directory is empty or absent next to the script', str(root))
    return [{'name': str(x.relative_to(root)), **stream_capture(x, RUNTIME_FILE_LIMIT, 'RUNTIME_RESOURCE_LIMIT', follow=False, checkpoint=checkpoint)} for x in members]


def runtime_identity(directory, script, checkpoint=None):
    def hashed(name, path): return {'name': name, 'path': path, **stream_capture(path, RUNTIME_FILE_LIMIT, 'RUNTIME_RESOURCE_LIMIT', checkpoint=checkpoint)}
    files = [hashed('perl', PERL), hashed('exiftool', script), *(hashed(n, q) for n, q in loader_paths(directory)), *(hashed(n, q) for n, q in module_paths(directory))]
    library = library_tree(script, checkpoint)
    return {'files': files, 'library': {'files': len(library), 'bytes': sum(x['bytes'] for x in library), 'manifestSha256': sha(encode_json(library)), 'members': library}}


# ---------------------------------------------------------------- independent expectations and native comparison
def expectation(facts):
    """The group-qualified raw observations ExifTool must report for one photo, from the independent reader only."""
    expected = {'File:ImageWidth': str(facts['width']), 'File:ImageHeight': str(facts['height']), **FRAME_FACTS}
    for key, name in (('IFD0:Make', 'make'), ('IFD0:Model', 'model'), ('ExifIFD:DateTimeOriginal', 'original'), ('ExifIFD:OffsetTimeOriginal', 'offset')):
        if facts[name] is not None: expected[key] = facts[name]
    if facts['orientation'] is not None: expected['IFD0:Orientation'] = str(facts['orientation'])
    return expected


NUMERIC = frozenset({'IFD0:Orientation', 'File:ImageWidth', 'File:ImageHeight', 'File:EncodingProcess', 'File:BitsPerSample', 'File:ColorComponents'})


def compare_native(stdout, p, facts, at='extract'):
    """Strict comparison of ExifTool's JSON with the independent reader; returns the scoped raw observations."""
    rows = strict_json(stdout, at + '.stdout', 'NATIVE_OBSERVATION_MISMATCH', tokens=True)
    if not isinstance(rows, list) or len(rows) != len(p['photos']): fail('NATIVE_OBSERVATION_MISMATCH', 'ExifTool did not report exactly one record per authored photo', at, records=len(rows) if isinstance(rows, list) else None)
    observed = []
    for index, (row, photo, fact) in enumerate(zip(rows, p['photos'], facts)):
        where = f'$.photos[{index}]'
        if not isinstance(row, dict) or row.get('SourceFile') != photo_file(photo): fail('NATIVE_OBSERVATION_MISMATCH', 'ExifTool record order or source differs from the authored photo order', where, photo=photo['id'])
        extra = sorted(set(row) - set(SELECTED) - {'SourceFile'})
        if extra: fail('NATIVE_OBSERVATION_MISMATCH', 'ExifTool reported keys outside the selected group-qualified tags (a duplicate tag appears as a Copy key)', where, photo=photo['id'], keys=extra[:8])
        for key in ('ExifTool:Warning', 'ExifTool:Error'):
            if key in row: fail('NATIVE_REPORTED_PROBLEM', 'ExifTool reported a warning or error for the photo', where, photo=photo['id'], key=key, text=str(row[key])[:200])
        expected = expectation(fact)
        scoped = {k: v for k, v in row.items() if k != 'SourceFile'}
        if set(scoped) != set(expected): fail('NATIVE_OBSERVATION_MISMATCH', 'ExifTool selected-tag presence differs from the independent reader', where, photo=photo['id'], missing=sorted(set(expected) - set(scoped)), unexpected=sorted(set(scoped) - set(expected)))
        for key, wanted in expected.items():
            value = scoped[key]
            numeric = isinstance(value, Number)
            if not isinstance(value, str) or (key in NUMERIC and not numeric) or value != wanted or (numeric and key not in NUMERIC and value != wanted):
                fail('NATIVE_OBSERVATION_MISMATCH', 'ExifTool value differs from the independent reader', where + '.' + key, photo=photo['id'], expected=wanted, observed=str(value)[:80])
        observed.append({k: str(v) for k, v in sorted(scoped.items())})
    return observed


# ---------------------------------------------------------------- checked publications
def rows_for(photos, facts):
    table = []
    for photo, fact in zip(photos, facts):
        zoned = fact['original'] is not None and fact['offset'] is not None
        utc = jpeg.utc_text(fact['original'], jpeg.check_offset(fact['offset'], '$', photo['id'])) if zoned else None
        table.append([photo['id'], fact['width'], fact['height'], fact['orientation'], fact['make'], fact['model'],
                      jpeg.local_text(fact['original']) if fact['original'] is not None else None, fact['offset'], utc])
    return table


def quote(text): return '"' + text.replace('"', '""') + '"'


def csv_bytes(table):
    lines = [','.join(quote(name) for name, _, _ in COLUMNS)]
    for row in table: lines.append(','.join(NULL_TOKEN if v is None else quote(v) if isinstance(v, str) else str(v) for v in row))
    return ('\n'.join(lines) + '\n').encode('utf-8')


def documents(directory, p, facts, native):
    """All publications from the independent reader; native values only had to agree before this point."""
    table = rows_for(p['photos'], facts)
    csv = csv_bytes(table)
    review = {'observedMetadataOnly': True, 'captureTimeCertified': False, 'locationOrAuthorshipCertified': False, 'filesystemTimesUsed': False, 'pixelDecodeClaimed': False, 'humanReviewRequired': True, 'statement': REVIEW}
    metadata = {'version': 'schemaxis.exiftool.metadata/1', 'status': 'observed-selected-metadata', 'runtime': RUNTIME,
                'scope': {'selectedTags': list(SELECTED), 'ignored': 'every other tag, segment and metadata family is unassessed, including GPS, thumbnails, MakerNotes, XMP, IPTC and ICC',
                          'orientation': 'stored EXIF code 1-8; not applied to pixels', 'time': 'camera-recorded wall time without a zone; capturedUtc only from an explicit recorded offset',
                          'jpeg': 'baseline sequential 8-bit three-component structure only; entropy data is not decoded'},
                'photoCount': len(facts), 'inventory': {'file': 'inventory.csv', 'sha256': sha(csv), 'format': CSV_FORMAT, 'nullToken': NULL_TOKEN, 'columns': [name for name, _, _ in COLUMNS]},
                'photos': [{'id': photo['id'], 'order': index + 1, 'sha256': fact['sha256'], 'bytes': fact['bytes'], 'width': fact['width'], 'height': fact['height'],
                            'byteOrder': fact.get('byteOrder'), 'observed': {'orientation': fact['orientation'], 'cameraMake': fact['make'], 'cameraModel': fact['model'],
                            'dateTimeOriginal': fact['original'], 'offsetTimeOriginal': fact['offset']}, 'nativeObservations': raw}
                           for index, (photo, fact, raw) in enumerate(zip(p['photos'], facts, native))],
                'review': review, 'losses': LOSSES}
    return {'metadata.json': encode_json(metadata), 'inventory.csv': csv}, metadata


PUBLISHED = (('metadata.json', 'text'), ('inventory.csv', 'table'))


def artifacts(directory):
    records = [{'file': str(directory / n), 'kind': kind, 'sha256': digest(directory, n)} for n, kind in PUBLISHED]
    records[1].update(identity={'kind': 'table', 'format': CSV_FORMAT, 'nullToken': NULL_TOKEN}, losses=LOSSES,
                      verificationScope='Selected metadata rebuilt from an independent JPEG/EXIF reader and agreeing with ExifTool; not a general CSV validator or capture-truth check.')
    return records


def evidence_names(p):
    return {'authored.json', 'plan.json', 'captures.json', 'runtime.json', *[photo_file(x) for x in p['photos']],
            *[s + x for s in STAGES for x in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr')]}


def membership(directory, p):
    from schemaxis.run_paths import MANIFEST
    published = [n for n, _ in PUBLISHED]
    expected = {n for n in evidence_names(p) if '/' not in n} | {*published, 'verification.json', 'result.json', 'schema.snapshot.json', MANIFEST, 'job.json'}
    expected |= {name + '.metadata.json' for name in published}
    for path in directory.iterdir():
        if path.name in ('.dispatch', PHOTO_DIRECTORY):
            if path.is_symlink() or not path.is_dir(): fail('VERIFICATION_FAILED', 'owned member is not a directory', path.name)
        elif path.name not in expected or path.is_symlink() or not path.is_file(): fail('VERIFICATION_FAILED', 'unexpected or nonregular retained photo member', path.name)
    if sorted(x.name for x in (directory / PHOTO_DIRECTORY).iterdir()) != sorted(Path(photo_file(x)).name for x in p['photos']): fail('VERIFICATION_FAILED', 'retained photo membership differs', PHOTO_DIRECTORY)
    for x in (directory / PHOTO_DIRECTORY).iterdir():
        if x.is_symlink() or not x.is_file(): fail('VERIFICATION_FAILED', 'retained photo is not a regular file', PHOTO_DIRECTORY + '/' + x.name)


def run(document, directory, *, executable=None, timeout=300):
    if workbench(document):
        from schemaxis.adaptors.exiftool import workbench as wb
        return wb.run(document, directory, executable=executable, timeout=timeout)
    if writer(document):
        from schemaxis.adaptors.exiftool import editing
        return editing.run(document, directory, executable=executable, timeout=timeout)
    if host(document):
        from schemaxis.adaptors.exiftool import e4host
        return e4host.run(document, directory, executable=executable, timeout=timeout)
    p = plan(document);executable = executable or os.environ.get('SCHEMAXIS_EXIFTOOL') or shutil.which('exiftool')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.R_OK) or not Path(executable).is_file(): fail('INTERPRETER_NOT_FOUND', 'configure an absolute ExifTool 13.55 script path (--exiftool)')
    if not Path(PERL).is_file() or not os.access(PERL, os.X_OK): fail('INTERPRETER_NOT_FOUND', 'ExifTool needs the system Perl at ' + PERL)
    if os.name != 'posix': fail('UNSUPPORTED_PLATFORM', 'native resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600: fail('INVALID_ARGUMENT', 'timeout must be finite in (0,3600]')
    executable = str(executable);deadline = time.monotonic() + timeout;directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'select a fresh output directory', str(directory))
    directory.mkdir(parents=True);atomic_json(directory / 'authored.json', document);atomic_json(directory / 'plan.json', p)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    def checkpoint():
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'metadata inspection cancelled')
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'metadata inspection exhausted its total deadline')
    try:
        checkpoint()
        captured = capture_photos(p, checkpoint);facts = [info for _, info in captured]
        (directory / PHOTO_DIRECTORY).mkdir()
        for photo, (data, _) in zip(p['photos'], captured): (directory / photo_file(photo)).write_bytes(data)
        atomic_json(directory / 'captures.json', {'photos': [{'id': x['id'], 'source': x['path'], 'sha256': f['sha256'], 'bytes': f['bytes']} for x, f in zip(p['photos'], facts)]})
        del captured
        checkpoint();runtime = None
        for stage, command in commands(executable, p).items():
            path = directory / (stage + '-launcher.py');path.write_text(launcher(directory, stage, command, p))
            execute([sys.executable, str(path)], directory, stage, deadline - time.monotonic(), {'LANG': 'C.UTF-8'})
            if stage == 'version': qualified_runtime(directory)
            if stage == 'modules': runtime = runtime_identity(directory, executable, checkpoint)
        checkpoint()
        if runtime_identity(directory, executable, checkpoint) != runtime: fail('RUNTIME_CHANGED', 'ExifTool, Perl or a dependency changed during the run')
        for photo, fact in zip(p['photos'], facts):
            if stream_capture(photo['path'], PHOTO_LIMIT, 'PHOTO_CHANGED', location='$.photos.path')['sha256'] != fact['sha256']: fail('PHOTO_CHANGED', 'a source photo changed during the native run', '$.photos.path', photo=photo['id'])
            if digest(directory, photo_file(photo), PHOTO_LIMIT) != fact['sha256']: fail('PHOTO_CHANGED', 'a retained photo copy changed during the native run', photo_file(photo))
        atomic_json(directory / 'runtime.json', {'executable': executable, **runtime})
        if bounded(directory / 'extract.stderr', limit=LOG_LIMIT) or bounded(directory / 'extract.stdout', limit=JSON_LIMIT) != bounded(directory / 'repeat.stdout', limit=JSON_LIMIT):
            fail('NATIVE_OBSERVATION_MISMATCH', 'the second fresh ExifTool process did not repeat the first byte for byte, or the first wrote to stderr', 'repeat')
        native = compare_native(bounded(directory / 'extract.stdout'), p, facts)
        files, _ = documents(directory, p, facts, native)
        for name, data in files.items(): (directory / name).write_bytes(data)
        atomic_json(directory / 'verification.json', {'executable': executable, 'runtime': qualified_runtime(directory), 'planSha256': plan_hash(p), 'artifacts': artifacts(directory),
            'evidence': {n: digest(directory, n, evidence_limit(n)) for n in sorted(evidence_names(p))}})
        result = verify(directory, require_result=False)
        checkpoint()
        result['status'] = 'succeeded';atomic_json(directory / 'result.json', result);return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()});raise error


def verify(directory, require_result=True, *, executable=None):
    """Offline: rechecks retained evidence only. No native process is launched and receipt values are not trusted."""
    directory = Path(directory).absolute()
    if workbench(read(directory, 'authored.json')):
        from schemaxis.adaptors.exiftool import workbench as wb
        return wb.verify(directory, require_result, executable=executable)
    if writer(read(directory, 'authored.json')):
        from schemaxis.adaptors.exiftool import editing
        return editing.verify(directory, require_result, executable=executable)
    if host(read(directory, 'authored.json')):
        from schemaxis.adaptors.exiftool import e4host
        return e4host.verify(directory, require_result, executable=executable)
    try:
        p = plan(read(directory, 'authored.json'));receipt = read(directory, 'verification.json')
        if not isinstance(receipt, dict) or set(receipt) != {'executable', 'runtime', 'planSha256', 'artifacts', 'evidence'} or not isinstance(receipt['evidence'], dict): fail('VERIFICATION_FAILED', 'native receipt member set differs')
        if not same_json(read(directory, 'plan.json'), p) or receipt['planSha256'] != plan_hash(p): fail('VERIFICATION_FAILED', 'effective inspection plan differs from the authored input or receipt')
        if require_result and read(directory, 'result.json').get('status') != 'succeeded': fail('INCOMPLETE_EXECUTION', 'metadata inspection did not complete')
        membership(directory, p)
        facts = []
        for index, photo in enumerate(p['photos']):
            data = bounded(directory / photo_file(photo), limit=PHOTO_LIMIT);facts.append(admit_photo(data, index, photo))
        if not same_json(read(directory, 'captures.json'), {'photos': [{'id': x['id'], 'source': x['path'], 'sha256': f['sha256'], 'bytes': f['bytes']} for x, f in zip(p['photos'], facts)]}): fail('VERIFICATION_FAILED', 'photo source/capture binding differs')
        executable = receipt['executable']
        if not isinstance(executable, str) or not Path(executable).is_absolute(): fail('VERIFICATION_FAILED', 'native executable identity must be absolute')
        for stage, command in commands(executable, p).items():
            submission = read(directory, stage + '-submission.json');path = directory / (stage + '-launcher.py')
            interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission, dict) and isinstance(submission.get('interpreter'), dict) else None
            if not isinstance(interpreter, str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand') != [interpreter, str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0: fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
            if bounded(path).decode() != launcher(directory, stage, command, p): fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
            bindings = read(directory, stage + '-inputs.json');expected = {'files': {n: digest(directory, n, evidence_limit(n)) for n in stage_inputs(stage, p)}}
            if not same_json(bindings, expected): fail('VERIFICATION_FAILED', 'native photo input binding differs', stage)
        if receipt['runtime'] != qualified_runtime(directory, 'VERIFICATION_FAILED'): fail('VERIFICATION_FAILED', 'require qualified ExifTool 13.55 runtime identity')
        runtime = read(directory, 'runtime.json')
        if not isinstance(runtime, dict) or set(runtime) != {'executable', 'files', 'library'} or runtime['executable'] != executable or not isinstance(runtime['files'], list) or not isinstance(runtime['library'], dict): fail('VERIFICATION_FAILED', 'runtime identity member set differs')
        wanted = [('perl', PERL), ('exiftool', executable), *loader_paths(directory), *module_paths(directory)]
        if [(f.get('name'), f.get('path')) for f in runtime['files'] if isinstance(f, dict)] != wanted or len(runtime['files']) != len(wanted): fail('VERIFICATION_FAILED', 'runtime dependency identity differs from the loader and module traces')
        library = runtime['library']
        if set(library) != {'files', 'bytes', 'manifestSha256', 'members'} or not isinstance(library['members'], list) or not library['members'] or library['files'] != len(library['members']) or library['manifestSha256'] != sha(encode_json(library['members'])): fail('VERIFICATION_FAILED', 'ExifTool library manifest is malformed')
        if not all(isinstance(f, dict) and set(f) >= {'name', 'sha256', 'bytes'} and isinstance(f['sha256'], str) and HEX.fullmatch(f['sha256']) and whole(f['bytes']) and 0 <= f['bytes'] <= RUNTIME_FILE_LIMIT for f in [*runtime['files'], *library['members']]) or library['bytes'] != sum(f['bytes'] for f in library['members']): fail('VERIFICATION_FAILED', 'runtime file hashes are malformed')
        if bounded(directory / 'extract.stderr', limit=LOG_LIMIT) or bounded(directory / 'extract.stdout') != bounded(directory / 'repeat.stdout'): fail('VERIFICATION_FAILED', 'the repeated fresh process differs from the first, or the first wrote to stderr', 'repeat')
        native = compare_native(bounded(directory / 'extract.stdout'), p, facts)
        expected, metadata = documents(directory, p, facts, native)
        for name, content in expected.items():
            if bounded(directory / name, limit=JSON_LIMIT) != content: fail('VERIFICATION_FAILED', 'published inventory file differs from independently checked evidence', name)
        if not same_json(receipt['artifacts'], artifacts(directory)): fail('VERIFICATION_FAILED', 'inventory publication membership/digest differs')
        if set(receipt['evidence']) != evidence_names(p): fail('VERIFICATION_FAILED', 'native evidence membership differs')
        for n in evidence_names(p):
            if digest(directory, n, evidence_limit(n)) != receipt['evidence'][n]: fail('VERIFICATION_FAILED', 'retained native evidence differs', n)
        fresh = {'verified': True, 'artifacts': len(PUBLISHED), 'runtime': RUNTIME, 'photos': len(facts), 'inventorySha256': sha(expected['inventory.csv']),
                 'photoSha256': [f['sha256'] for f in facts], 'observedMetadataOnly': True, 'captureTimeCertified': False, 'humanReviewRequired': True}
        if require_result and not same_json(read(directory, 'result.json'), {**fresh, 'status': 'succeeded'}): fail('VERIFICATION_FAILED', 'retained result differs from independent reopening')
        return fresh
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED', 'INCOMPLETE_EXECUTION'): raise
        fail('VERIFICATION_FAILED', 'retained inventory evidence violates its contract (' + error.fault.code + ': ' + error.fault.message + ')', error.fault.location, cause=error.fault.to_dict())
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeDecodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained inventory evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
