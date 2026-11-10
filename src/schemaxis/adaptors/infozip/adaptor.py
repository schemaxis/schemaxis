"""Bounded stored-ZIP publication bundle of individually selected files, verified byte for byte by the host.

``bundle`` captures one to sixteen explicitly chosen local files under safe flat names, adds a host-written
``manifest.json`` inventory and asks the trusted Info-ZIP ``zip`` 3.0 to store them (method 0) in ``bundle.zip``.
The host then reads the archive with an independent strict physical reader (plus the standard ``zipfile`` module as a
second reader) and compares every archive byte with the held captures. Verification needs no native program: the
host reader checks the whole archive and every member byte against the retained captures and a regenerated manifest,
and the recorded native recipe (launcher, argument array, exit code, input bindings) is checked but never executed.
File contents are opaque: nothing here validates media format, quality, security or privacy, and case preservation
stays in the core storage action.
"""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
import zipfile
import zlib

from schemaxis.artifacts import atomic_json
from schemaxis.configuration import executable as configured_executable
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import execution_deadline, remaining_timeout
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.infozip/1'
OPERATIONS = ('bundle',)
PLAN_VERSION = 'schemaxis.infozip.plan/1'
SUMMARY_VERSION = 'schemaxis.infozip.summary/1'
MANIFEST_VERSION = 'schemaxis.infozip.manifest/1'
MAX_FILES = 16
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024
MAX_PATH = 4096
MAX_LOG_BYTES = 1024 * 1024
OUTPUT_SLACK = 1024 * 1024
STAGE_TIMEOUT = 180
VERIFY_TIMEOUT = 300
EXTENSIONS = ('txt', 'json', 'srt', 'vtt', 'wav', 'flac', 'm4a', 'png', 'html', 'docx', 'epub', 'pdf')
RESERVED = 'con|prn|aux|nul|com[1-9]|lpt[1-9]'      # Windows device basenames, reserved even with an extension
NAME = re.compile(r'(?!(?:%s)\.)[a-z][a-z0-9_-]{0,47}\.(?:%s)' % (RESERVED, '|'.join(EXTENSIONS)))
NAME_PATTERN = '^(?!(?:%s)\\.)[a-z][a-z0-9_-]{0,47}\\.(?:%s)$' % (RESERVED, '|'.join(EXTENSIONS))
MAX_NAME = 48 + 1 + max(map(len, EXTENSIONS))
MANIFEST = 'manifest.json'
ARCHIVE = 'bundle.zip'
SUMMARY = 'bundle-summary.json'
PACK = 'pack'
ARGUMENTS = ['-X', '-0', '-q', ARCHIVE]
IDENTITY = re.compile(r'This is Zip 3\.0 \([A-Za-z]+ \d{1,2}[a-z]{2} \d{4}\), by Info-ZIP\.')
STAGES = ('version', 'bundle')
EPOCH = 315532800                  # 1980-01-01T00:00:00Z: the DOS epoch, so the archive timestamps are fixed
FILE_MODE = 0o600
NATIVE_ENVIRONMENT = {'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC'}
SOURCE_FAULTS = ('INVALID_INFOZIP_SOURCE', 'INVALID_INFOZIP_ARCHIVE', 'INFOZIP_BUDGET')
LOCAL = struct.Struct('<4sHHHHHIIIHH')
CENTRAL = struct.Struct('<4sHHHHHHIIIHHHHHII')
END = struct.Struct('<4sHHHHIIH')
MADE_BY, NEEDED, DOS_TIME, DOS_DATE = 0x031e, 10, 0, 0x0021        # Zip 3.0 on Unix, stored, 1980-01-01 00:00:00
EXTERNAL = (stat.S_IFREG | FILE_MODE) << 16
OVERHEAD = (MAX_FILES + 1) * (LOCAL.size + CENTRAL.size + 2 * MAX_NAME) + END.size
MAX_ARCHIVE_BYTES = MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES + OVERHEAD

OPTIONS = {'files': {
    'type': 'array', 'minItems': 1, 'maxItems': MAX_FILES, 'required': True,
    'items': {'type': 'object', 'properties': {
        'name': {'type': 'string', 'minLength': 1, 'maxLength': MAX_NAME, 'required': True},
        'source': {'type': 'string', 'minLength': 1, 'maxLength': MAX_PATH, 'required': True}}}}}
DECLARATIONS = {'bundle': {
    'native': 'zip -v; zip -X -0 -q bundle.zip <member names in authored order> manifest.json (Info-ZIP Zip 3.0, stored members only); host writes manifest.json and reads bundle.zip back',
    'kinds': ['file', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
INVENTORY = ('Unsigned inventory of the other members of this archive in archive order: name, byte count and SHA-256. '
             'manifest.json lists every member except itself, carries no self-hash and no signature, and does not authenticate the bundle or its origin.')
LOSSES = [
    'One to %d individually selected absolute local regular files, each at most 32 MiB and 64 MiB in total (empty files allowed). Directories, globs, recursive input, symbolic links, devices and FIFOs are refused, and no run directory, receipt or log is added automatically.' % MAX_FILES,
    'Member names are flat portable ASCII: a lowercase letter, then lowercase letters, digits, underscore or hyphen (48 characters at most), then exactly one of .%s. manifest.json is reserved for the inventory the host adds. Original paths, timestamps and permissions are not published: every member carries the fixed 1980-01-01 00:00:00 time and mode 0600.' % ', .'.join(EXTENSIONS),
    'Members are stored (method 0): no compression, no ratio or size-saving claim, no encryption, ZIP64, data descriptors, extra fields, comments, archive prefix or self-extractor. Archive bytes are checked against the captured bytes by an independent host reader; the native zip is the producer, not the verifier.',
    'File bytes are opaque. The bundle does not validate media format, quality, accessibility, security or privacy, and it does not sanitise content. manifest.json is an unsigned inventory, not a signature: a coherent rewrite of the archive and its retained captures verifies as a new archive and does not prove who produced it.',
    'This is a delivery package of chosen publication files. Whole-case preservation and restore (evidence, schema and history stores) stay with the explicit storage preservation action in the core, which this operation neither duplicates nor replaces.']


# ---------------------------------------------------------------- planning
def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    operation = document.get('operation')
    if not isinstance(operation, str) or operation not in OPERATIONS:
        fail('UNKNOWN_FILTER', 'select bundle', '$.operation')
    prepared = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS})
    seen = set()
    for index, item in enumerate(prepared['files']):
        location = '$.files[%d]' % index
        name, source = item['name'], item['source']
        if NAME.fullmatch(name) is None or not name.isascii():
            fail('INVALID_INFOZIP_NAME', 'use a flat portable name: a lowercase letter, lowercase letters, digits, _ or -, and one of .%s' % ', .'.join(EXTENSIONS), location + '.name')
        if name == MANIFEST:
            fail('INVALID_INFOZIP_NAME', MANIFEST + ' is reserved for the inventory the host adds', location + '.name')
        if name.casefold() in seen:
            fail('INVALID_INFOZIP_NAME', 'member names must be unique, ignoring case', location + '.name')
        seen.add(name.casefold())
        if '\0' in source or not os.path.isabs(source):
            fail('INVALID_INFOZIP_SOURCE', 'select an absolute local regular file; no URLs, prefixes or relative paths', location + '.source')
    names = [item['name'] for item in prepared['files']]
    native = {'arguments': ARGUMENTS + names + [MANIFEST], 'compression': 'stored', 'environment': sorted(NATIVE_ENVIRONMENT), 'extraMember': MANIFEST}
    return {'version': PLAN_VERSION, 'operation': 'bundle', **prepared, 'native': native,
            'budget': {'maxFiles': MAX_FILES, 'maxMemberBytes': MAX_MEMBER_BYTES, 'maxTotalBytes': MAX_TOTAL_BYTES, 'maxArchiveBytes': MAX_ARCHIVE_BYTES},
            'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    files = argument_schema(OPTIONS['files'])
    files['items']['properties']['name']['pattern'] = NAME_PATTERN
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': 'bundle'}, 'files': files}, ['version', 'operation', 'files'])}


def query(document):
    return [plan(document)['operation']], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'the publication bundle supports one serial thread', identity)
    return {'threads': 1}


# ---------------------------------------------------------------- bounded host inputs and strict JSON
def bounded(path, code='VERIFICATION_FAILED', limit=MAX_MEMBER_BYTES, location=None):
    """Descriptor-checked bounded read of one regular file; symbolic links, FIFOs and devices are refused."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError('not a bounded regular file')
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('byte budget exceeded')
        return data
    except (OSError, ValueError) as error:
        fail(code, 'select an intact regular file within %d bytes: %s' % (limit, error), location or str(path))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(directory, name, limit=MAX_MEMBER_BYTES, held=None):
    """SHA-256 of a retained file; ``held`` maps names to bytes already read, so one snapshot binds every comparison."""
    if held and name in held:
        return sha(held[name])
    return sha(bounded(Path(directory) / name, limit=limit))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key ' + key)
        result[key] = value
    return result


def finite_number(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('non-finite JSON number ' + text[:20])
    return value


def refuse_constant(name):
    raise ValueError('non-finite JSON constant ' + name)


def strict_json(data, name):
    """Strict UTF-8 JSON: no byte-order mark, duplicate keys, NaN/Infinity, numbers that overflow to infinity or excess depth."""
    try:
        text = data.decode('utf-8')
        if text.startswith('﻿'):
            raise ValueError('byte-order mark')
        return json.loads(text, object_pairs_hook=unique_object, parse_float=finite_number, parse_constant=refuse_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained JSON %s: %s' % (name, str(error)[:80]))


def read_json(directory, name):
    return strict_json(bounded(Path(directory) / name, limit=MAX_LOG_BYTES), name)


def same_json(actual, expected):
    """Typed canonical comparison: 1 is not true and 66 is not 66.0, unlike Python equality."""
    try:
        return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        return False


# ---------------------------------------------------------------- sources, captures and the host manifest
def read_source(path, location):
    """One selected source: descriptor-checked regular file within the member budget, read once and held."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    except OSError as error:
        fail('INVALID_INFOZIP_SOURCE', 'select an existing regular local file (no symbolic link, directory, FIFO or device): %s' % error.strerror, location)
    try:
        stream = os.fdopen(fd, 'rb')
    except OSError as error:
        os.close(fd)
        fail('INVALID_INFOZIP_SOURCE', 'select a regular local file, not a directory: %s' % error.strerror, location)
    with stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            fail('INVALID_INFOZIP_SOURCE', 'select a regular local file, not a directory, FIFO, device or other special file', location)
        if info.st_size > MAX_MEMBER_BYTES:
            fail('INFOZIP_BUDGET', 'file is %d bytes; at most %d per member' % (info.st_size, MAX_MEMBER_BYTES), location)
        data = stream.read(MAX_MEMBER_BYTES + 1)
    if len(data) > MAX_MEMBER_BYTES:
        fail('INFOZIP_BUDGET', 'file grew beyond %d bytes while it was read' % MAX_MEMBER_BYTES, location)
    return data


def read_sources(files):
    """Every selected source, held; the 64 MiB total is enforced before the next file is read."""
    held, total = [], 0
    for index, item in enumerate(files):
        location = '$.files[%d].source' % index
        data = read_source(item['source'], location)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            fail('INFOZIP_BUDGET', 'selected files exceed %d bytes in total' % MAX_TOTAL_BYTES, location)
        held.append(data)
    return held


def manifest_bytes(records):
    """Canonical inventory of the member files: ``records`` are (name, byte count, sha256) in archive order."""
    document = {'version': MANIFEST_VERSION, 'members': [{'name': n, 'bytes': b, 'sha256': h} for n, b, h in records], 'inventory': INVENTORY}
    return (json.dumps(document, sort_keys=True, indent=2) + '\n').encode('ascii')


def member_records(names, contents):
    return [(name, len(data), sha(data)) for name, data in zip(names, contents)]


def archive_limit(total):
    return total + MAX_MANIFEST_BYTES + OVERHEAD


def stage_file(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), FILE_MODE)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
    os.chmod(path, FILE_MODE)
    os.utime(path, (EPOCH, EPOCH))


# ---------------------------------------------------------------- independent strict stored-ZIP physical reader
def parse_archive(data, expected=None, location=ARCHIVE):
    """Strict physical reader of a stored ZIP written by this adaptor; nothing is extracted and no field sizes an allocation.

    Requires an exact end-of-central-directory record at the end (no comment, ZIP64, multi-disk or suffix), a central
    directory that fills the space after the members, and members that tile the bytes from offset 0 to the central
    directory with no prefix, gap or overlap. Every local and central header must carry the canonical Info-ZIP values
    (version, flags 0, method 0, 1980-01-01 time, no extra field or comment, regular mode 0600) and agree with each
    other, names must be unique flat portable ASCII with ``manifest.json`` last, and every CRC-32 is recomputed.
    ``expected`` is a list of (name, bytes) in order; names, sizes and every byte are then compared with it.
    """
    def invalid(message):
        fail('INVALID_INFOZIP_ARCHIVE', 'not a canonical stored ZIP bundle: ' + message, location)
    if len(data) > MAX_ARCHIVE_BYTES:
        fail('INFOZIP_BUDGET', 'archive is larger than %d bytes' % MAX_ARCHIVE_BYTES, location)
    if len(data) < END.size:
        invalid('shorter than an end-of-central-directory record')
    signature, disk, directory_disk, here, total, size, offset, comment = END.unpack_from(data, len(data) - END.size)
    if signature != b'PK\x05\x06':
        invalid('the last 22 bytes are not an end-of-central-directory record (a comment or suffix is not accepted)')
    if comment:
        invalid('an archive comment is not accepted')
    if disk or directory_disk:
        invalid('multi-disk archives are not accepted')
    if 0xffff in (here, total) or 0xffffffff in (size, offset):
        invalid('ZIP64 is not accepted')
    if here != total or not 1 <= total <= MAX_FILES + 1:
        invalid('entry count %d is outside 1-%d or differs between disk and archive' % (total, MAX_FILES + 1))
    central_end = len(data) - END.size
    if offset + size != central_end:
        invalid('the central directory does not end exactly at the end-of-central-directory record')
    view = memoryview(data)
    members, names, position, cursor = [], [], offset, 0
    for index in range(total):
        if position + CENTRAL.size > central_end:
            invalid('central entry %d is truncated' % index)
        (sig, made, needed, flags, method, time, date, crc, compressed, uncompressed, name_length, extra, remark,
         first_disk, internal, external, local) = CENTRAL.unpack_from(data, position)
        if sig != b'PK\x01\x02':
            invalid('central entry %d has no central signature' % index)
        if (made, needed, flags, method, time, date) != (MADE_BY, NEEDED, 0, 0, DOS_TIME, DOS_DATE):
            invalid('central entry %d is not stored, unencrypted, unflagged and dated 1980-01-01 00:00:00' % index)
        if extra or remark or first_disk or internal or external != EXTERNAL:
            invalid('central entry %d carries an extra field, comment, disk number, text flag or non-regular/non-0600 attributes' % index)
        if compressed != uncompressed or uncompressed > MAX_MEMBER_BYTES or not 1 <= name_length <= MAX_NAME:
            invalid('central entry %d has differing or oversized sizes or an out-of-range name length' % index)
        name_end = position + CENTRAL.size + name_length
        if name_end > central_end:
            invalid('central entry %d name extends past the directory' % index)
        raw = bytes(view[position + CENTRAL.size:name_end])
        if not raw.isascii() or (NAME.fullmatch(raw.decode('ascii')) is None):
            invalid('central entry %d name is not a flat portable ASCII name' % index)
        name = raw.decode('ascii')
        if name in names:
            invalid('duplicate member name ' + name)
        if local != cursor:
            invalid('member %s starts at offset %d but the previous member ends at %d (a gap, overlap or reorder)' % (name, local, cursor))
        start = local + LOCAL.size + name_length
        end = start + uncompressed
        if end > offset:
            invalid('member %s extends into or beyond the central directory' % name)
        (lsig, lneeded, lflags, lmethod, ltime, ldate, lcrc, lcompressed, luncompressed, lname, lextra) = LOCAL.unpack_from(data, local)
        if (lsig, lneeded, lflags, lmethod, ltime, ldate) != (b'PK\x03\x04', NEEDED, 0, 0, DOS_TIME, DOS_DATE) or lextra:
            invalid('local header of %s is not canonical (signature, version, flags, method, time, extra field or data descriptor)' % name)
        if (lcrc, lcompressed, luncompressed, lname) != (crc, compressed, uncompressed, name_length) or bytes(view[local + LOCAL.size:start]) != raw:
            invalid('local header of %s disagrees with its central entry' % name)
        if zlib.crc32(view[start:end]) != crc:
            invalid('CRC-32 of %s differs from its bytes' % name)
        members.append({'name': name, 'offset': local, 'dataOffset': start, 'bytes': uncompressed, 'crc32': crc})
        names.append(name)
        cursor, position = end, name_end
    if cursor != offset or position != central_end:
        invalid('members or central entries do not tile the archive exactly (gap, overlap or trailing bytes)')
    if names[-1] != MANIFEST or names.count(MANIFEST) != 1:
        invalid(MANIFEST + ' must appear exactly once, as the last member')
    if expected is not None:
        if [name for name, _ in expected] != names:
            invalid('member names or order differ from the captured files')
        for member, (name, content) in zip(members, expected):
            if member['bytes'] != len(content) or view[member['dataOffset']:member['dataOffset'] + member['bytes']] != content:
                invalid('bytes of %s differ from the captured file' % name)
    second_reader(data, members, location)
    return members


def second_reader(data, members, location):
    """The standard ``zipfile`` module must agree on names, stored method, sizes, CRCs and flags, and re-test every member."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.infolist()
            if archive.comment or [i.filename for i in info] != [m['name'] for m in members]:
                raise ValueError('zipfile lists different members')
            for entry, member in zip(info, members):
                if (entry.compress_type, entry.file_size, entry.compress_size, entry.CRC, entry.flag_bits, entry.extra, entry.header_offset) != (
                        zipfile.ZIP_STORED, member['bytes'], member['bytes'], member['crc32'], 0, b'', member['offset']):
                    raise ValueError('zipfile reads different geometry for ' + member['name'])
            if archive.testzip() is not None:
                raise ValueError('zipfile CRC test failed')
    except (zipfile.BadZipFile, ValueError, OSError, RuntimeError, EOFError, zlib.error) as error:
        fail('INVALID_INFOZIP_ARCHIVE', 'the standard zipfile reader disagrees: ' + str(error)[:80], location)


# ---------------------------------------------------------------- trusted runtime and fixed native stages
def runtime(executable=None):
    """Trusted ``zip``: explicit argument, then invocation context/stored configuration, then SCHEMAXIS_INFOZIP. Never PATH or a receipt."""
    value = executable or configured_executable('infozip') or os.environ.get('SCHEMAXIS_INFOZIP')
    if not isinstance(value, str) or not os.path.isabs(value) or not os.path.isfile(value) or not os.access(value, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute Info-ZIP Zip 3.0 zip executable to create the bundle',
             '$.runtime.infozip', recovery='use --infozip, schemaxis configure infozip, or SCHEMAXIS_INFOZIP (a stored locations.infozip entry also works); verification needs no native program')
    return {'infozip': value}


def launcher(stage, names, command, limit, workdir):
    """Fixed trusted launcher: resource caps, bounded input binding, process record, explicit minimal environment, then exec.

    The Python launcher inherits its caller's environment; only ``NATIVE_ENVIRONMENT`` reaches the native zip, so ZIPOPT,
    UNZIPOPT, HOME and TMPDIR are never passed. ``<stage>-process.json`` records this process id, which execve keeps for
    the native zip, and the argument array immediately before the exec.
    """
    return ('import hashlib,json,os,stat,resource\nfrom pathlib import Path\n'
            'resource.setrlimit(resource.RLIMIT_AS,(2147483648,2147483648))\n'
            'resource.setrlimit(resource.RLIMIT_FSIZE,(%d,%d))\n' % (limit, limit)
            + 'resource.setrlimit(resource.RLIMIT_CPU,(%d,%d))\n' % (STAGE_TIMEOUT, STAGE_TIMEOUT)
            + 'resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))\n'
            + 'names=%r\ncommand=%r\nbindings={}\nroot=os.getcwd()\n' % (list(names), list(command))
            + ('os.chdir(%r)\n' % workdir if workdir else '')
            + 'for name in names:\n'
            '    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n'
            '    with os.fdopen(fd,"rb") as stream:\n'
            '        info=os.fstat(stream.fileno())\n'
            '        if not stat.S_ISREG(info.st_mode) or info.st_size>%d: raise ValueError("invalid native input")\n' % MAX_MEMBER_BYTES
            + '        data=stream.read(%d)\n' % (MAX_MEMBER_BYTES + 1)
            + '    bindings[name]=hashlib.sha256(data).hexdigest()\n'
            + 'Path(root,%r).write_text(json.dumps(bindings,sort_keys=True))\n' % (stage + '-inputs.json')
            + 'Path(root,%r).write_text(json.dumps({"pid":os.getpid(),"argv":command},sort_keys=True))\n' % (stage + '-process.json')
            + 'os.execve(command[0],command,%r)\n' % NATIVE_ENVIRONMENT)


def stage_commands(zip_path, names, total):
    """Stage name -> (argument array, bound input names, native output byte limit, working directory under the run)."""
    return {'version': ([zip_path, '-v'], [], OUTPUT_SLACK, None),
            'bundle': ([zip_path, *ARGUMENTS, *names, MANIFEST], [*names, MANIFEST], archive_limit(total) + OUTPUT_SLACK, PACK)}


def launch(directory, stage, command, names, limit, workdir):
    """One native stage through the shared cancellable runner; every launch consults the cumulative budget."""
    directory = Path(directory)
    path = directory / (stage + '-launcher.py')
    path.write_text(launcher(stage, names, command, limit, workdir))
    try:
        execute([sys.executable, str(path)], directory, stage, remaining_timeout(STAGE_TIMEOUT), {'LANG': 'C.UTF-8'})
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        target = directory / (stage + '.stderr')
        text = bounded(target, 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace').strip()[-300:] if target.exists() else ''
        fail('NATIVE_EXECUTION_FAILED', '%s failed (exit %s): %s' % (Path(command[0]).name, error.fault.observed.get('exitCode'), text), stage)
    return bounded(directory / (stage + '.stdout'), 'NATIVE_EXECUTION_FAILED', MAX_LOG_BYTES).decode('utf-8', 'replace')


def check_identity(text):
    """The Info-ZIP identity line of ``zip -v``; only Zip 3.0 is accepted."""
    lines = [line for line in text.splitlines() if line.startswith('This is Zip')]
    if len(lines) != 1:
        fail('UNSUPPORTED_RUNTIME', 'the executable did not identify itself as Info-ZIP zip (observed %r)' % text[:60], 'version')
    if IDENTITY.fullmatch(lines[0]) is None:
        fail('UNSUPPORTED_RUNTIME', 'require Info-ZIP Zip 3.0 (observed %r); other releases need upstream acceptance' % lines[0][:60], 'version')
    return lines[0]


# ---------------------------------------------------------------- summaries, receipts and evidence
def summarize(members, archive, plan_files):
    records = [{'name': m['name'], 'bytes': m['bytes'], 'crc32': '%08x' % m['crc32'], 'archiveOffset': m['offset'], 'dataOffset': m['dataOffset']} for m in members]
    return {'version': SUMMARY_VERSION, 'operation': 'bundle',
            'archive': {'file': ARCHIVE, 'bytes': len(archive), 'sha256': sha(archive), 'compression': 'stored', 'members': len(members)},
            'members': [{**record, 'sha256': h} for record, (_, _, h) in zip(records[:-1], plan_files[:-1])],
            'manifest': {**records[-1], 'sha256': plan_files[-1][2]},
            'readback': {'strictReader': True, 'zipfileReader': True, 'everyByteCompared': True, 'sourcesRechecked': True},
            'inventory': INVENTORY,
            'verification': ('The host read the complete archive with a strict stored-ZIP physical reader and the standard zipfile module and compared every member byte with the bytes captured '
                             'from the selected files and with the regenerated manifest. The archive is unsigned and its contents are opaque: no media, security or privacy check was made.')}


def publications(directory, held=None):
    return [{'file': str(Path(directory) / name), 'kind': kind, 'sha256': digest(directory, name, MAX_ARCHIVE_BYTES, held)}
            for name, kind in ((ARCHIVE, 'file'), (SUMMARY, 'text'))]


def evidence_names(names):
    found = {'authored.json', 'plan.json', 'captures.json'} | {PACK + '/' + n for n in [*names, MANIFEST]}
    for stage in STAGES:
        found.update(stage + suffix for suffix in ('-launcher.py', '-inputs.json', '-process.json', '-submission.json', '.stdout', '.stderr'))
    return found


def unreferenced(directory, names):
    """Exact top-level and pack membership, including only declared framework sidecars."""
    directory = Path(directory)
    top = {n for n in evidence_names(names) if '/' not in n}
    known = top | {'verification.json', 'result.json', 'schema.snapshot.json', 'publication-metadata.json', 'job.json', PACK, ARCHIVE, SUMMARY,
                   ARCHIVE + '.metadata.json', SUMMARY + '.metadata.json'}
    extra = []
    for path in directory.iterdir():
        if path.name == '.dispatch' or path.name == PACK:
            if path.is_symlink() or not path.is_dir():
                extra.append(path.name)
        elif path.name not in known or path.is_symlink() or not path.is_file():
            extra.append(path.name)
    pack = directory / PACK
    if pack.is_dir() and not pack.is_symlink():
        allowed = {*names, MANIFEST}
        extra.extend(PACK + '/' + p.name for p in pack.iterdir() if p.name not in allowed or p.is_symlink() or not p.is_file())
    return sorted(extra)


# ---------------------------------------------------------------- run
def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'native resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite and in (0,3600]')
    paths = runtime(executable)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'select a fresh bundle publication directory', str(directory))
    try:
        directory.mkdir(parents=True)
    except FileExistsError:
        fail('OUTPUT_EXISTS', 'select a fresh bundle publication directory', str(directory))
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        with execution_deadline(timeout):
            files = prepared['files']
            names = [item['name'] for item in files]
            contents = read_sources(files)
            records = member_records(names, contents)
            manifest = manifest_bytes(records)
            total = sum(len(c) for c in contents)
            (directory / PACK).mkdir()
            for name, data in zip([*names, MANIFEST], [*contents, manifest]):
                stage_file(directory / PACK / name, data)
            atomic_json(directory / 'captures.json', capture_record(files, records, manifest))
            commands = stage_commands(paths['infozip'], names, total)
            check_identity(launch(directory, 'version', *commands['version']))
            launch(directory, 'bundle', *commands['bundle'])
            if bounded(directory / 'bundle.stdout', limit=MAX_LOG_BYTES) or bounded(directory / 'bundle.stderr', limit=MAX_LOG_BYTES):
                fail('NATIVE_EXECUTION_FAILED', 'the quiet native zip stage logged output', 'bundle')
            archive = bounded(directory / PACK / ARCHIVE, 'NATIVE_EXECUTION_FAILED', archive_limit(total), 'bundle')
            expected = list(zip([*names, MANIFEST], [*contents, manifest]))
            members = parse_archive(archive, expected)
            for index, (item, data) in enumerate(zip(files, contents)):
                if read_source(item['source'], '$.files[%d].source' % index) != data:
                    fail('INVALID_INFOZIP_SOURCE', 'the source changed while the bundle was created; rerun with a stable file', '$.files[%d].source' % index)
            (directory / PACK / ARCHIVE).replace(directory / ARCHIVE)
            summary = summarize(members, archive, [*records, (MANIFEST, len(manifest), sha(manifest))])
            atomic_json(directory / SUMMARY, summary)
            atomic_json(directory / 'verification.json', {
                'artifacts': publications(directory), 'evidence': {n: digest(directory, n) for n in sorted(evidence_names(names))},
                'runtime': {'infozip': check_identity(bounded(directory / 'version.stdout', limit=MAX_LOG_BYTES).decode('utf-8', 'replace'))}, 'executables': paths})
            result = verify_semantic(directory, require_result=False)
            remaining_timeout(STAGE_TIMEOUT)
            result = {'status': 'succeeded', **result}
            atomic_json(directory / 'result.json', result)
            return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped:
                error = wrapped
        for name in (ARCHIVE, SUMMARY, 'verification.json'):
            (directory / name).unlink(missing_ok=True)          # no published artifact or success receipt survives a failure
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def capture_record(files, records, manifest):
    return {'files': [{'name': n, 'source': item['source'], 'bytes': b, 'sha256': h} for item, (n, b, h) in zip(files, records)],
            'manifest': {'name': MANIFEST, 'bytes': len(manifest), 'sha256': sha(manifest)}}


# ---------------------------------------------------------------- verification
def converted(action, location):
    """Retained inputs or archives that no longer satisfy the admission rules are verification failures, never input faults."""
    try:
        return action()
    except SchemaxisError as error:
        if error.fault.code not in SOURCE_FAULTS:
            raise
        fail('VERIFICATION_FAILED', 'retained %s is invalid (%s): %s' % (location, error.fault.code, error.fault.message), location, cause=error.fault.to_dict())


def result_claims(result):
    """Every claim of a result record, closed: an unknown, missing, promoted or mistyped field is a difference."""
    return {key: value for key, value in result.items() if key != 'status'}


def verify_semantic(directory, require_result=True):
    """Judge the published bytes from the authored request and the retained captures, natively free.

    The decision is: the published ``bundle.zip`` passes the strict stored-ZIP reader and the standard zipfile reader, and
    every member byte equals the retained capture of that member and the manifest regenerated from those captures. No
    native program runs. Retained files are hash-bound consistency diagnostics: plan, capture record, launchers, input
    bindings, process records and exit codes (never re-executed), summary and the receipt's membership. Retained JSON is
    read strictly and compared by typed canonical form. Receipt executables are inert provenance and are never launched.
    The original source files are not read: a bundle is judged against its own captures, so it verifies after the
    originals have moved. The judgement covers the bytes read during this call; a writer that changes the directory
    afterwards is not guarded against.
    """
    directory = Path(directory).absolute()
    try:
        with execution_deadline(VERIFY_TIMEOUT):
            try:
                prepared = plan(read_json(directory, 'authored.json'))
            except SchemaxisError as error:
                fail('VERIFICATION_FAILED', 'retained authored input is invalid: ' + error.fault.message, str(directory))
            if not same_json(read_json(directory, 'plan.json'), prepared):
                fail('VERIFICATION_FAILED', 'retained plan differs from the authored input')
            recorded_result = read_json(directory, 'result.json') if require_result else None
            if require_result and (not isinstance(recorded_result, dict) or recorded_result.get('status') != 'succeeded'):
                fail('INCOMPLETE_EXECUTION', 'the publication bundle did not complete')
            files = prepared['files']
            names = [item['name'] for item in files]
            extra = unreferenced(directory, names)
            if extra:
                fail('VERIFICATION_FAILED', 'unreferenced files in the publication directory: ' + ', '.join(extra[:8]))
            held = {}
            contents, total = [], 0
            for name in names:
                data = held[PACK + '/' + name] = bounded(directory / PACK / name, limit=MAX_MEMBER_BYTES)
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    fail('VERIFICATION_FAILED', 'retained captures exceed the total byte budget')
                contents.append(data)
            records = member_records(names, contents)
            manifest = held[PACK + '/' + MANIFEST] = bounded(directory / PACK / MANIFEST, limit=MAX_MANIFEST_BYTES)
            if manifest != manifest_bytes(records):
                fail('VERIFICATION_FAILED', 'retained manifest differs from the inventory regenerated from the captured members', MANIFEST)
            if not same_json(read_json(directory, 'captures.json'), capture_record(files, records, manifest)):
                fail('VERIFICATION_FAILED', 'capture record differs from the captured bytes')
            archive = held[ARCHIVE] = bounded(directory / ARCHIVE, limit=archive_limit(total))
            members = converted(lambda: parse_archive(archive, list(zip([*names, MANIFEST], [*contents, manifest]))), ARCHIVE)
            summary = summarize(members, archive, [*records, (MANIFEST, len(manifest), sha(manifest))])
            saved = held[SUMMARY] = bounded(directory / SUMMARY, limit=MAX_LOG_BYTES)
            if not same_json(strict_json(saved, SUMMARY), summary):
                fail('VERIFICATION_FAILED', 'retained summary differs from the recomputed observation')
            receipt = read_json(directory, 'verification.json')
            if type(receipt) is not dict or set(receipt) != {'artifacts', 'evidence', 'executables', 'runtime'}:
                fail('VERIFICATION_FAILED', 'the receipt must hold exactly artifacts, evidence, executables and runtime', 'verification.json')
            if not same_json(receipt.get('artifacts'), publications(directory, held)):
                fail('VERIFICATION_FAILED', 'publication membership or digests differ from the receipt')
            evidence = receipt.get('evidence')
            if not isinstance(evidence, dict) or set(evidence) != evidence_names(names):
                fail('VERIFICATION_FAILED', 'retained evidence membership differs')
            for name in sorted(evidence_names(names)):
                if digest(directory, name, held=held) != evidence[name]:
                    fail('VERIFICATION_FAILED', 'retained evidence differs', name)
            recorded = receipt.get('executables')
            if not isinstance(recorded, dict) or set(recorded) != {'infozip'} or not isinstance(recorded['infozip'], str) or not os.path.isabs(recorded['infozip']):
                fail('VERIFICATION_FAILED', 'receipt executable identity must be absolute provenance')
            runtimes = receipt.get('runtime')
            observed = check_identity(bounded(directory / 'version.stdout', limit=MAX_LOG_BYTES).decode('utf-8', 'replace'))
            if not isinstance(runtimes, dict) or set(runtimes) != {'infozip'} or runtimes['infozip'] != observed:
                fail('VERIFICATION_FAILED', 'recorded runtime identity differs from the retained version output', 'version')
            for stage, (command, bound, limit, workdir) in stage_commands(recorded['infozip'], names, total).items():
                check_recipe(directory, stage, command, bound, limit, workdir, held)
            remaining_timeout(VERIFY_TIMEOUT)
            verified = {'verified': True, 'operation': 'bundle', 'artifacts': 2, 'members': len(members),
                        'bytes': {'archive': len(archive), 'members': total, 'manifest': len(manifest)},
                        'archiveSha256': sha(archive), 'runtime': {'infozip': observed}}
            if require_result and not same_json(result_claims(recorded_result), result_claims(verified)):
                fail('VERIFICATION_FAILED', 'retained result claims differ from the verified observation')
            return verified
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, RecursionError, StopIteration, struct.error) as error:
        fail('VERIFICATION_FAILED', 'invalid retained bundle evidence: %s %s' % (type(error).__name__, str(error)[:80]))


def check_recipe(directory, stage, command, bound, limit, workdir, held):
    """The retained native recipe of one stage: submission, exact launcher, input bindings, process record and log silence."""
    submission = read_json(directory, stage + '-submission.json')
    interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission.get('interpreter'), dict) else None
    native = submission.get('nativeCommand')
    if (not isinstance(interpreter, str) or not os.path.isabs(interpreter) or not isinstance(native, list) or len(native) != 2
            or native[0] != interpreter or Path(native[1]).name != stage + '-launcher.py'
            or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0):
        fail('VERIFICATION_FAILED', 'native command or completion record differs', stage)
    if bounded(directory / (stage + '-launcher.py'), limit=MAX_LOG_BYTES).decode() != launcher(stage, bound, command, limit, workdir):
        fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
    if not same_json(read_json(directory, stage + '-inputs.json'), {name: digest(directory, (PACK + '/' + name) if workdir else name, held=held) for name in bound}):
        fail('VERIFICATION_FAILED', 'native input binding differs', stage)
    process = read_json(directory, stage + '-process.json')
    if not isinstance(process, dict) or set(process) != {'pid', 'argv'} or type(process['pid']) is not int or process['pid'] <= 0 or process['argv'] != command:
        fail('VERIFICATION_FAILED', 'native process record differs from the fixed argument array', stage)
    if stage != 'version' and (bounded(directory / (stage + '.stdout'), limit=MAX_LOG_BYTES) or bounded(directory / (stage + '.stderr'), limit=MAX_LOG_BYTES)):
        fail('VERIFICATION_FAILED', 'a silent native stage logged output', stage)


def reusableInputs(document):
    prepared = plan(document)
    held = read_sources(prepared['files'])
    return {item['source']: sha(data) for item, data in zip(prepared['files'], held)}


def verify(directory, require_result=True):
    return verify_semantic(directory, require_result)


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
