# Copyright (C) 2026 David L F Gaden
"""Bounded PDF page assembly through QPDF, verified by fresh native observation.

Published bytes are judged against the captured sources by two fresh MuPDF observers and
QPDF's own structural reading; retained sidecars are consistency diagnostics only.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys
import tempfile

from schemaxis.artifacts import atomic_json
from schemaxis.configuration import executable as configured_executable
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import execution_deadline, remaining_timeout
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import inspection
from .inspection import Document, DPI, MAX_SIDE_PIXELS, MAX_TOTAL_PIXELS
from .native_source import source as observer_source

VERSION = 'schemaxis.qpdf/1'
QPDF_IDENTITY = 'qpdf version 12.4.2'
MUPDF_IDENTITY = 'mutool version 1.28.5'
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 32 * 1024 * 1024
MAX_FINAL_BYTES = 64 * 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024
MAX_OBSERVATION_BYTES = 16 * 1024 * 1024
MAX_PAGE_TEXT = 1048576
MAX_TEXT = 4194304
STAGE_TIMEOUT = 120
VERIFY_TIMEOUT = 120
NAME = re.compile(r'^[a-z][a-z0-9-]{0,23}$')

NAME_SPEC = {'type': 'string', 'minLength': 1, 'maxLength': 24, 'required': True}
SOURCE = {'type': 'object', 'properties': {
    'name': NAME_SPEC,
    'path': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}}}
PAGE = {'type': 'object', 'properties': {
    'source': NAME_SPEC,
    'page': {'type': 'integer', 'minimum': 1, 'maximum': inspection.MAX_SOURCE_PAGES, 'required': True},
    'rotate': {'type': 'enum', 'values': [0, 90, 180, 270], 'default': 0}}}
OPTIONS = {
    'sources': {'type': 'array', 'items': SOURCE, 'minItems': 1, 'maxItems': 4, 'required': True},
    'pages': {'type': 'array', 'items': PAGE, 'minItems': 1, 'maxItems': 200, 'required': True}}
DECLARATIONS = {'assemble': {
    'native': 'qpdf --empty --pages FILE PAGE ... -- --rotate=+N:K --remove-page-labels --deterministic-id; '
              'MuPDF PDFDocument.findPage/PDFObject.put/getInheritable, PDFPage.getBounds/toPixmap/toStructuredText',
    'kinds': ['pdf', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
LOSSES = [
    'The output is a new document made only from the selected pages. Document information, XMP metadata, outlines, named destinations, '
    'open actions, document JavaScript, viewer preferences and attachments are discarded; page labels are always removed. This is a recorded '
    'loss, not sanitisation.',
    'Sources with forms or signatures, optional-content layers, tagged structure, output intents, encryption, annotations on selected pages, or '
    'page actions, transitions, beads or page metadata are refused rather than altered.',
    'Page content, fonts, images and graphics are carried unchanged and not recompressed; QPDF prunes resources a page does not use. Rotation is '
    'a relative clockwise quarter turn added to each page\'s effective rotation; MediaBox, CropBox, local optional boxes and UserUnit are preserved.',
    'Verification compares each output page with its captured source page at 36 dpi for exact raster, text and geometry, using MuPDF in separate '
    'processes, plus QPDF structural checks. It is a bounded appearance, text and geometry check, not proof of full semantic equivalence, '
    'accessibility, colour management or PDF conformance.',
    'This route is not a PDF sanitiser or malware boundary. Admission is a bounded allow-list for selected pages and their resources; '
    'content-stream operators and font or image semantics are not scanned.',
    'A successful verification shows the current published bytes satisfy the captured request; it is not a signature or historical attestation.']


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'select ' + VERSION, '$.version')
    if document.get('operation') != 'assemble':
        fail('UNKNOWN_FILTER', 'select assemble', '$.operation')
    prepared = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS}, location='$')
    names, paths = [], []
    for index, entry in enumerate(prepared['sources']):
        at = '$.sources[%d]' % index
        if not NAME.match(entry['name']):
            fail('INVALID_PDF_SOURCE_NAME', 'use 1-24 characters: a lowercase letter, then lowercase letters, digits or hyphens', at + '.name')
        path = Path(entry['path'])
        if not path.is_absolute() or path.suffix.lower() != '.pdf' or '\x00' in entry['path']:
            fail('INVALID_PDF_SOURCE', 'select an absolute local .pdf regular file; URLs and relative paths are unsupported', at + '.path')
        names.append(entry['name'])
        paths.append(str(path))
    if len(set(names)) != len(names):
        fail('INVALID_PDF_SOURCE_NAME', 'source names must be distinct', '$.sources')
    if len(set(paths)) != len(paths):
        fail('INVALID_PDF_SOURCE', 'list each PDF once and refer to it by name from several pages', '$.sources')
    for index, page in enumerate(prepared['pages']):
        if page['source'] not in names:
            fail('INVALID_PDF_PAGES', 'page refers to a source name that is not declared in $.sources', '$.pages[%d].source' % index)
    if {page['source'] for page in prepared['pages']} != set(names):
        fail('INVALID_PDF_SOURCES', 'every declared source must supply at least one page', '$.sources')
    return {'version': 'schemaxis.qpdf.plan/1', 'operation': 'assemble', **prepared, 'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': 'assemble'},
            **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', 'sources', 'pages'])}


def query(document):
    plan(document)
    return ['assemble'], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1:
        fail('INVALID_EXECUTION', 'PDF assembly uses serial native processes', identity)
    return {'threads': 1}


def bounded(path, code='VERIFICATION_FAILED', limit=MAX_SOURCE_BYTES, location=None):
    """One bounded read of a regular, non-link file."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError('not a bounded regular file')
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('file byte budget exceeded')
        return data
    except (ValueError, OSError) as error:
        fail(code, 'select an intact bounded regular file: ' + str(error), location or str(path))


def capture_policy(data, total, code, location):
    """The single capture policy for source bytes: standard header, and a 32 MiB aggregate (16 MiB each is enforced by the bounded read).

    Run applies it while capturing; saved verification applies the same function to the retained captured bytes, so the two cannot
    drift. Returns the running aggregate.
    """
    total += len(data)
    if not data.startswith(b'%PDF-') or total > MAX_TOTAL_SOURCE_BYTES:
        fail(code, 'select PDF files with their standard header, at most 16 MiB each and 32 MiB together', location)
    return total


def reusableInputs(document):
    prepared = plan(document)
    return {entry['name']: hashlib.sha256(bounded(entry['path'], 'INVALID_PDF_SOURCE', MAX_SOURCE_BYTES, '$.sources[%d].path' % i)).hexdigest()
            for i, entry in enumerate(prepared['sources'])}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(directory, name, limit=MAX_LOG_BYTES):
    try:
        return json.loads(bounded(Path(directory) / name, limit=limit))
    except (ValueError, UnicodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained JSON ' + name + ': ' + str(error)[:80])


# ---------------------------------------------------------------- trusted runtimes
def runtime(qpdf=None, mupdf=None):
    """Trusted executables: explicit argument, then invocation context/stored configuration, then the documented environment.

    Receipts, evidence and authored input never supply an executable path.
    """
    paths = {}
    for name, given, variable, identity in (('qpdf', qpdf, 'SCHEMAXIS_QPDF', QPDF_IDENTITY), ('mupdf', mupdf, 'SCHEMAXIS_MUPDF', MUPDF_IDENTITY)):
        value = given or configured_executable(name) or os.environ.get(variable)
        if not isinstance(value, str) or not os.path.isabs(value) or not os.access(value, os.X_OK) or not os.path.isfile(value):
            fail('INTERPRETER_NOT_FOUND', 'configure an absolute %s executable (%s) for %s' % (name, 'qpdf 12.4.2' if name == 'qpdf' else 'MuPDF 1.28.5 mutool', 'run and verify'),
                 '$.runtime.' + name, recovery='use --%s, schemaxis configure, or %s' % (name, variable))
        paths[name] = value
    return paths


def launcher(stage, names, command, memory):
    """Fixed trusted launcher: resource caps, bounded input binding, then exec. Contains no authored text."""
    return ('import hashlib,json,os,stat,resource\nfrom pathlib import Path\n'
            'resource.setrlimit(resource.RLIMIT_AS,(%d,%d))\n' % (memory, memory)
            + 'resource.setrlimit(resource.RLIMIT_FSIZE,(67108864,67108864))\n'
            'resource.setrlimit(resource.RLIMIT_CPU,(120,120))\n'
            + 'names=%r\ncommand=%r\nbindings={}\n' % (list(names), list(command))
            + 'for name in names:\n'
            '    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n'
            '    with os.fdopen(fd,"rb") as stream:\n'
            '        info=os.fstat(stream.fileno())\n'
            '        if not stat.S_ISREG(info.st_mode) or info.st_size>67108864: raise ValueError("invalid native input")\n'
            '        data=stream.read(67108865)\n'
            '    if len(data)>67108864: raise ValueError("native input limit")\n'
            '    bindings[name]=hashlib.sha256(data).hexdigest()\n'
            + 'Path(%r).write_text(json.dumps(bindings,sort_keys=True))\n' % (stage + '-inputs.json')
            + 'os.execvpe(command[0],command,os.environ)\n')


def launch(directory, stage, command, names=(), memory=1 << 30):
    """Run one native stage through the shared cancellable runner; every launch consults the cumulative budget first."""
    directory = Path(directory)
    path = directory / (stage + '-launcher.py')
    path.write_text(launcher(stage, names, command, memory))
    code = 0
    try:
        execute([sys.executable, str(path)], directory, stage, remaining_timeout(STAGE_TIMEOUT), {'LANG': 'C.UTF-8'})
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        code = error.fault.observed.get('exitCode')
        if code == -signal.SIGXFSZ:
            fail('PDF_STRUCTURE_LIMIT', 'native output exceeded the 64 MiB file bound', stage)
        if not isinstance(code, int) or code == 0:
            raise
    streams = []
    for suffix, limit in (('.stdout', MAX_FINAL_BYTES), ('.stderr', MAX_LOG_BYTES)):
        target = directory / (stage + suffix)
        streams.append(bounded(target, 'NATIVE_EXECUTION_FAILED', limit) if target.exists() else b'')
    return code, streams[0], streams[1]


def refuse_qpdf(code, stage, label, exit_code, stderr, fallback):
    """Translate a failed or noisy qpdf read into a declared fault."""
    text = stderr.decode('utf-8', 'replace')
    if 'invalid password' in text:
        fail('ENCRYPTED_PDF', '%s: encrypted PDFs are unsupported; supply an authorized unencrypted copy' % label)
    if exit_code == 3 or 'WARNING' in text or (exit_code == 0 and text.strip()):
        fail(code or 'PDF_REPAIRED', '%s: qpdf reported warnings or needed recovery; supply a structurally intact PDF (%s)' % (label, text.strip()[:80]))
    fail(fallback, '%s: qpdf could not read an intact PDF without recovery (exit %s: %s)' % (label, exit_code, text.strip()[:80]))


def inspect_pdf(paths, work, filename, stem, label, source=True):
    """qpdf --check without recovery, then bounded JSON, for one PDF in the work directory."""
    code, _, error = launch(work, 'check-' + stem, [paths['qpdf'], '--suppress-recovery', '--check', filename], [filename])
    fallback = 'INVALID_PDF_SOURCE' if source else 'VERIFICATION_FAILED'
    if code != 0 or error.strip():
        refuse_qpdf(None if source else 'VERIFICATION_FAILED', 'check-' + stem, label, code, error, fallback)
    code, out, error = launch(work, 'json-' + stem, [paths['qpdf'], '--suppress-recovery', '--json', '--json-key=qpdf',
                                                    '--json-key=pages', '--json-key=encrypt', filename], [filename])
    if code != 0 or error.strip():
        refuse_qpdf(None if source else 'VERIFICATION_FAILED', 'json-' + stem, label, code, error, fallback)
    return Document(inspection.parse(out, label, 'PDF_STRUCTURE_UNSUPPORTED' if source else 'VERIFICATION_FAILED'), label)


def identity(paths, work, stem=''):
    """Pin both runtimes; a missing or different release is a fault, never a skipped check."""
    found = {}
    for name, command, expected, flag in (('qpdf', [paths['qpdf'], '--version'], QPDF_IDENTITY, 'version-qpdf'),
                                          ('mupdf', [paths['mupdf'], '-v'], MUPDF_IDENTITY, 'version-mupdf')):
        code, out, error = launch(work, flag + stem, command)
        lines = (out + error).decode('utf-8', 'replace').strip().splitlines()
        if code != 0 or not lines or lines[0] != expected:
            fail('UNSUPPORTED_RUNTIME', 'this route is qualified against %s; configure that release for %s' % (expected, name), '$.runtime.' + name)
        found[name] = lines[0]
    return '; '.join([found['qpdf'], found['mupdf']])


def admit_sources(paths, work, prepared):
    needed = {}
    for page in prepared['pages']:
        needed.setdefault(page['source'], []).append(page['page'])
    admitted = {}
    for entry in prepared['sources']:
        name = entry['name']
        document = inspect_pdf(paths, work, 'source-%s.pdf' % name, name, 'source ' + name)
        admitted[name] = inspection.admit_source(document, needed[name])
    return admitted


def pnm_digest(path, size):
    data = bounded(path, 'VERIFICATION_FAILED', MAX_FINAL_BYTES)
    try:
        magic, geometry, maximum, pixels = data.split(b'\n', 3)
        width, height = map(int, geometry.split())
        if magic != b'P6' or maximum != b'255' or [width, height] != list(size) or len(pixels) != width * height * 3:
            raise ValueError('header or size')
    except (ValueError, TypeError) as error:
        fail('VERIFICATION_FAILED', 'invalid native RGB raster: ' + str(error))
    finally:
        os.unlink(path)                                     # keeps scratch disk to one observer's rasters
    return sha(data)


RECORD_KEYS = {'page', 'pageCount', 'originalRotate', 'bounds', 'userUnit', 'mediaBox', 'cropBox', 'rotation', 'predicted', 'pixmap', 'text'}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def observer_records(out, jobs, stage):
    try:
        records = json.loads(out)
    except (ValueError, RecursionError, UnicodeError) as error:
        fail('VERIFICATION_FAILED', stage + ': malformed observer JSON ' + str(error)[:60])
    if not isinstance(records, list) or len(records) != len(jobs):
        fail('VERIFICATION_FAILED', stage + ': observer returned a different number of pages')
    for record, (_, page, _) in zip(records, jobs):
        if (not isinstance(record, dict) or set(record) != RECORD_KEYS or type(record['page']) is not int or record['page'] != page
                or type(record['pageCount']) is not int or not 1 <= record['pageCount'] <= inspection.MAX_SOURCE_PAGES
                or not number(record['originalRotate']) or not number(record['rotation'])
                or not isinstance(record['bounds'], list) or len(record['bounds']) != 4 or not all(number(v) for v in record['bounds'])
                or not (record['userUnit'] is None or number(record['userUnit']))
                or not all(isinstance(record[k], list) and len(record[k]) == 2 and all(type(v) is int for v in record[k]) for k in ('predicted', 'pixmap'))
                or not isinstance(record['text'], str)):
            fail('VERIFICATION_FAILED', stage + ': observer record has an unexpected shape')
    return records


OBSERVER_FAULTS = ('ENCRYPTED_PDF', 'PDF_REPAIRED', 'PDF_PAGE_RANGE', 'PDF_PIXEL_LIMIT', 'PDF_PIXEL_MISMATCH', 'PDF_TEXT_LIMIT', 'PDF_REQUIRED')


def observe(paths, work, tag, jobs):
    """One fresh MuPDF process over (file, page, rotation|None) jobs; rasters are hashed, then removed."""
    entries = [{'file': name, 'page': page, 'rotation': rotation, 'output': '%s%d.pnm' % (tag, index)}
               for index, (name, page, rotation) in enumerate(jobs, 1)]
    script = 'observe-%s.js' % tag
    Path(work, script).write_text(observer_source(entries, DPI, MAX_SIDE_PIXELS, MAX_TOTAL_PIXELS, MAX_PAGE_TEXT, MAX_TEXT))
    code, out, error = launch(work, 'observe-' + tag, [paths['mupdf'], 'run', script], sorted({name for name, _, _ in jobs}) + [script], 2 << 30)
    if code != 0:
        text = error.decode('utf-8', 'replace')
        for token in OBSERVER_FAULTS:
            if token in text:
                fail('VERIFICATION_FAILED', 'MuPDF %s observation refused: %s' % (tag, token))
        fail('VERIFICATION_FAILED', 'MuPDF %s observation failed (exit %s): %s' % (tag, code, text.strip()[:100]))
    if len(out) > MAX_OBSERVATION_BYTES:
        fail('PDF_STRUCTURE_LIMIT', 'MuPDF observation exceeds %d bytes' % MAX_OBSERVATION_BYTES)
    records = observer_records(out, jobs, tag)
    for index, record in enumerate(records, 1):
        record['rasterSha256'] = pnm_digest(Path(work, '%s%d.pnm' % (tag, index)), record['pixmap'])
    return records


def observe_all(paths, work, prepared, admitted=None):
    """The single fresh-observation pipeline used by run and verify; returns the published summary.

    work holds source-<name>.pdf and final.pdf as private copies of the captured bytes.
    """
    work = Path(work)
    admitted = admitted or admit_sources(paths, work, prepared)
    positions = [(p['source'], p['page'], p['rotate']) for p in prepared['pages']]
    sizes = [inspection.predicted_pixels(admitted[name]['geometry'][page], rotate) for name, page, rotate in positions]
    inspection.pixel_budget(sizes)
    final = inspect_pdf(paths, work, 'final.pdf', '_final', 'published PDF', source=False)   # '_' cannot occur in a source name
    inspection.check_final(final, positions, admitted)
    expected = observe(paths, work, 'e', [('source-%s.pdf' % name, page, (admitted[name]['geometry'][page]['rotate'] + rotate) % 360)
                                          for name, page, rotate in positions])
    actual = observe(paths, work, 'a', [('final.pdf', index, None) for index in range(1, len(positions) + 1)])
    pages = []
    for index, ((name, page, rotate), size, want, got) in enumerate(zip(positions, sizes, expected, actual), 1):
        source = admitted[name]['geometry'][page]
        where = 'output page %d (source %s page %d, rotate %d)' % (index, name, page, rotate)
        if want['originalRotate'] % 360 != source['rotate']:
            fail('VERIFICATION_FAILED', where + ': MuPDF and QPDF disagree on the source rotation')
        if got['pageCount'] != len(positions) or want['predicted'] != list(size) or got['predicted'] != list(size):
            fail('VERIFICATION_FAILED', where + ': native page count or raster size differs from the prediction')
        if got['rotation'] % 360 != (source['rotate'] + rotate) % 360:
            fail('VERIFICATION_FAILED', where + ': published rotation differs')
        for field in ('bounds', 'pixmap', 'userUnit'):
            if want[field] != got[field]:
                fail('VERIFICATION_FAILED', where + ': native ' + field + ' differs from the captured source page')
        if want['text'] != got['text']:
            fail('VERIFICATION_FAILED', where + ': text differs from the captured source page')
        if want['rasterSha256'] != got['rasterSha256']:
            fail('VERIFICATION_FAILED', where + ': 36 dpi raster differs from the captured source page')
        pages.append({'output': index, 'source': name, 'sourcePage': page, 'rotate': rotate, 'rotation': got['rotation'] % 360,
                      'mediaBox': source['mediaBox'], 'effectiveBox': source['effective'], 'userUnit': source['userUnit'],
                      'pixels': got['pixmap'], 'rasterSha256': got['rasterSha256'], 'textCharacters': len(got['text'])})
    return {'version': 'schemaxis.qpdf.summary/1', 'dpi': DPI, 'pageCount': len(positions),
            'sources': [{'name': name, 'pages': entry['pages'], 'discarded': entry['discarded']} for name, entry in sorted(admitted.items())],
            'pages': pages, 'losses': LOSSES}


# ---------------------------------------------------------------- publication and evidence
STAGE_SUFFIXES = ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr')


def stages(prepared):
    names = [entry['name'] for entry in prepared['sources']]
    return ['version-qpdf', 'version-mupdf', *['check-' + n for n in names], *['json-' + n for n in names], 'assemble']


def evidence_names(prepared):
    names = {'authored.json', 'plan.json', 'capture.json'}
    names.update('source-%s.pdf' % entry['name'] for entry in prepared['sources'])
    names.update(stage + suffix for stage in stages(prepared) for suffix in STAGE_SUFFIXES)
    return names


def publications(directory, final, summary):
    directory = Path(directory)
    return [{'file': str(directory / 'assembled.pdf'), 'kind': 'pdf', 'sha256': sha(final)},
            {'file': str(directory / 'assembly-summary.json'), 'kind': 'text', 'sha256': sha(summary)}]


def encode(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()


def assemble_command(paths, prepared):
    command = [paths['qpdf'], '--suppress-recovery', '--empty', '--pages']
    for page in prepared['pages']:
        command += ['source-%s.pdf' % page['source'], str(page['page'])]
    command.append('--')
    command += ['--rotate=+%d:%d' % (page['rotate'], index) for index, page in enumerate(prepared['pages'], 1) if page['rotate']]
    command += ['--remove-page-labels', '--deterministic-id', '--stream-data=preserve', '--object-streams=preserve', 'assembled.pdf']
    return command


def run(document, directory, *, executable=None, oracle=None, timeout=300):
    prepared = plan(document)
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'this qualification requires POSIX native resource caps')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite and in (0,3600]')
    paths = runtime(executable, oracle)
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'select a fresh PDF assembly directory', str(directory))
    directory.mkdir(parents=True)
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', prepared)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        with execution_deadline(timeout):
            records, total = [], 0
            for index, entry in enumerate(prepared['sources']):
                data = bounded(entry['path'], 'INVALID_PDF_SOURCE', MAX_SOURCE_BYTES, '$.sources[%d].path' % index)
                total = capture_policy(data, total, 'INVALID_PDF_SOURCE', '$.sources[%d].path' % index)
                with open(directory / ('source-%s.pdf' % entry['name']), 'xb') as stream:
                    stream.write(data)
                records.append({'name': entry['name'], 'path': entry['path'], 'bytes': len(data), 'sha256': sha(data)})
            atomic_json(directory / 'capture.json', {'sources': records})
            runtime_identity = identity(paths, directory)
            admitted = admit_sources(paths, directory, prepared)
            positions = [(p['source'], p['page'], p['rotate']) for p in prepared['pages']]
            inspection.pixel_budget([inspection.predicted_pixels(admitted[n]['geometry'][pg], r) for n, pg, r in positions])
            code, _, error = launch(directory, 'assemble', assemble_command(paths, prepared),
                                    ['source-%s.pdf' % e['name'] for e in prepared['sources']])
            if code != 0 or error.strip():
                fail('NATIVE_EXECUTION_FAILED', 'qpdf assembly failed or warned (exit %s): %s' % (code, error.decode('utf-8', 'replace').strip()[:100]))
            final = bounded(directory / 'assembled.pdf', 'NATIVE_EXECUTION_FAILED', MAX_FINAL_BYTES)
            with tempfile.TemporaryDirectory(prefix='schemaxis-qpdf-') as scratch:
                for entry in records:
                    Path(scratch, 'source-%s.pdf' % entry['name']).write_bytes(bounded(directory / ('source-%s.pdf' % entry['name'])))
                Path(scratch, 'final.pdf').write_bytes(final)
                summary = encode(observe_all(paths, scratch, prepared, admitted))
            (directory / 'assembly-summary.json').write_bytes(summary)
            evidence = {name: sha(bounded(directory / name, limit=MAX_FINAL_BYTES)) for name in sorted(evidence_names(prepared))}
            atomic_json(directory / 'verification.json', {'artifacts': publications(directory, final, summary), 'evidence': evidence,
                                                          'runtime': runtime_identity, 'executables': paths})
            remaining_timeout(STAGE_TIMEOUT)
            result = {'status': 'succeeded', 'verified': True, 'pages': len(positions), 'runtime': runtime_identity}
            atomic_json(directory / 'result.json', result)
            return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped:
                error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def verify_semantic(directory, paths, require_result=True):
    """Fresh-native verification of a saved run from its authored request, captured sources and published bytes.

    Checked from current bytes: (1) fresh QPDF/MuPDF observation of every output page against its captured source
    page (the decision); (2) retained diagnostics - plan.json equals the recomputed plan, capture.json matches the captured
    bytes, verification.json lists exactly the two publications with their current digests, assembly-summary.json equals the
    freshly recomputed summary, and the digests of the retained evidence files are unchanged. Native stage logs,
    launchers and submissions are provenance; they are hash-bound but never reinterpreted. Receipt executables are inert.
    """
    directory = Path(directory).absolute()
    try:
        with execution_deadline(VERIFY_TIMEOUT):
            try:
                document = read_json(directory, 'authored.json')
                prepared = plan(document)
            except SchemaxisError as error:
                fail('VERIFICATION_FAILED', 'retained authored input is invalid: ' + error.fault.message, str(directory))
            if read_json(directory, 'plan.json') != prepared:
                fail('VERIFICATION_FAILED', 'retained plan differs from the authored input')
            if require_result and read_json(directory, 'result.json').get('status') != 'succeeded':
                fail('INCOMPLETE_EXECUTION', 'PDF assembly did not complete')
            captured, records, total = {}, [], 0
            for entry in prepared['sources']:
                data = bounded(directory / ('source-%s.pdf' % entry['name']))
                total = capture_policy(data, total, 'VERIFICATION_FAILED', 'retained captured source ' + entry['name'])
                captured[entry['name']] = data
                records.append({'name': entry['name'], 'path': entry['path'], 'bytes': len(data), 'sha256': sha(data)})
            if read_json(directory, 'capture.json') != {'sources': records}:
                fail('VERIFICATION_FAILED', 'captured source records differ from the captured bytes')
            final = bounded(directory / 'assembled.pdf', limit=MAX_FINAL_BYTES)
            summary = bounded(directory / 'assembly-summary.json', limit=MAX_OBSERVATION_BYTES)
            receipt = read_json(directory, 'verification.json', MAX_OBSERVATION_BYTES)
            if receipt.get('artifacts') != publications(directory, final, summary):
                fail('VERIFICATION_FAILED', 'publication membership or digests differ from the receipt')
            with tempfile.TemporaryDirectory(prefix='schemaxis-qpdf-') as scratch:
                for name, data in captured.items():
                    Path(scratch, 'source-%s.pdf' % name).write_bytes(data)
                Path(scratch, 'final.pdf').write_bytes(final)
                runtime_identity = identity(paths, scratch)
                fresh = observe_all(paths, scratch, prepared)
            if fresh != json.loads(summary):
                fail('VERIFICATION_FAILED', 'retained assembly summary differs from fresh native observation')
            evidence = receipt.get('evidence')
            if not isinstance(evidence, dict) or set(evidence) != evidence_names(prepared):
                fail('VERIFICATION_FAILED', 'retained evidence membership differs')
            for name in evidence_names(prepared):
                if sha(bounded(directory / name, limit=MAX_FINAL_BYTES)) != evidence[name]:
                    fail('VERIFICATION_FAILED', 'retained evidence differs', name)
            remaining_timeout(VERIFY_TIMEOUT)               # final host work shares the cumulative budget
            return {'verified': True, 'runtime': runtime_identity, 'pages': len(prepared['pages']), 'artifacts': 2}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained PDF assembly evidence: ' + type(error).__name__ + ' ' + str(error)[:80])


def verify(directory, require_result=True):
    return verify_semantic(directory, runtime(), require_result)


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
