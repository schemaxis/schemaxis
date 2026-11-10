"""Bounded scanned-page OCR: Tesseract runs natively, the host rechecks its TSV evidence.

One local opaque RGB8 PNG page, one explicitly pinned English LSTM model and an explicit page segmentation produce a
machine-draft text, word boxes with native confidence and an inspectable summary. The native CLI and its files are
untrusted: the TSV is parsed by a strict independent reader, text is compared with it under a stated policy, and every
published file is rebuilt from that checked evidence. Hashes and structure never certify what the page says, so every
result carries a review statement.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import time

from schemaxis import png as shared_png
from schemaxis.adaptors.tesseract import tsv
from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.tesseract/1'
OPERATION = 'recognizePage'
RUNTIME = 'tesseract 5.5.3'
IMAGE_LIMIT = 16 * 1024 * 1024
MAX_SIDE = 4096
MAX_PIXELS = 4096 * 1024
MODEL_LIMIT = 64 * 1024 * 1024
ORIGIN_LIMIT = 4 * 1024 * 1024
NATIVE_TEXT_LIMIT = 1024 * 1024
NATIVE_TSV_LIMIT = 4 * 1024 * 1024
JSON_LIMIT = 8 * 1024 * 1024
LOG_LIMIT = 4 * 1024 * 1024
RUNTIME_FILE_LIMIT = 1024 ** 3
MAX_RUNTIME_FILES = 64
HEX = re.compile(r'[0-9a-f]{64}')
SEGMENTATION = {'uniform-block': 6, 'single-line': 7}
NATIVE_CONFIG = ('tessedit_create_txt=1', 'tessedit_create_tsv=1')
IMAGE_FILE = 'captured-page.png'
MODEL_FILE = 'tessdata/eng.traineddata'
STAGES = ('version', 'libraries', 'recognize')
SHA = {'type': 'string', 'minLength': 64, 'maxLength': 64}
PATH = {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True}
OPTIONS = {
    'image': {'type': 'object', 'required': True, 'properties': {'path': PATH, 'sha256': SHA}},
    'model': {'type': 'object', 'required': True, 'properties': {'path': PATH, 'sha256': {**SHA, 'required': True}}},
    'origin': {'type': 'object', 'properties': {'kind': {'type': 'enum', 'values': ['mupdf-review'], 'required': True}, 'summary': PATH,
                                                'page': {'type': 'integer', 'minimum': 1, 'maximum': 128, 'required': True}}},
    'language': {'type': 'enum', 'values': ['eng'], 'default': 'eng'},
    'pageSegmentation': {'type': 'enum', 'values': list(SEGMENTATION), 'default': 'uniform-block'},
    'dpi': {'type': 'integer', 'minimum': 70, 'maximum': 2400}}
DECLARATIONS = {OPERATION: {
    'native': 'tesseract captured-page.png native --tessdata-dir tessdata -l eng --oem 1 --psm PSM [--dpi DPI] -c tessedit_create_txt=1 -c tessedit_create_tsv=1',
    'kinds': ['text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
REVIEW = ('Machine-draft optical character recognition. Hashes, strict structure and text/TSV agreement prove only that these files '
          'were derived consistently from the recorded native run on the recorded pixels; they do not show that the text is what '
          'the page says. Word confidence is the recogniser\'s own uncalibrated 0-100 score, not an accuracy or probability. '
          'A person must review the text and boxes against the page image before relying on them.')
LOSSES = [
    'One local opaque 8-bit RGB PNG page, non-interlaced and without alpha or tRNS, at most 16MiB, 4096 pixels per side and 4,194,304 pixels; no alpha, palette, grey, 16-bit, interlaced, animated, TIFF/JPEG, multipage, PDF or remote input. Colour profiles and gamma are ignored by the recogniser and not applied.',
    'One explicit English fast-or-best LSTM model supplied as a local regular file pinned by SHA-256 (at most 64MiB, engine mode 1). It is captured into the run and hashed before and after the native run; the SHA-256 pin identifies the bytes, and nothing verifies that the model is actually English; global traineddata, TESSDATA_PREFIX, configuration files and authored native flags are never used.',
    'Explicit page segmentation only (uniform-block is --psm 6, single-line is --psm 7). A wrong choice for the layout can yield fewer words, no text or wrong text; no automatic layout analysis, orientation detection, columns, tables, handwriting or non-English scripts are offered.',
    'Native CPU, one thread, fixed output configuration (text and TSV), no dictionary or user words, no whitelist, no hOCR/ALTO/PDF output. Output is Tesseract 5.5.3 observed behaviour on the recorded pixels only.',
    'Coordinates are whole pixels with a top-left origin in the source image: the page record must equal the image size and every box must lie inside it; right and bottom edges are exclusive. Boxes are the recogniser\'s own and are not independently segmented.',
    'Confidence is native decimal text from 0 to 100, uncalibrated. Text is the TSV words in native record order, joined by single spaces and newlines; recognition accuracy, spelling, reading order for complex layouts and content truth are not certified.',
    'The result identifies pixels, not a page. Origin is retained only when a MuPDF review summary is declared and its page entry matches the image width, height and RGB-pixel SHA-256; the MuPDF run itself is not re-verified here and an image without an origin has no page, document or capture identity.']


# ---------------------------------------------------------------- planning
def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected ' + VERSION, '$.version')
    if document.get('operation') != OPERATION: fail('UNKNOWN_OPERATION', 'select ' + OPERATION, '$.operation')
    p = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS})
    checks = [('image', p['image']['path'], '.png', 'INVALID_IMAGE_SOURCE', '$.image.path'), ('model', p['model']['path'], '.traineddata', 'INVALID_MODEL', '$.model.path')]
    if 'origin' in p: checks.append(('origin', p['origin']['summary'], '.json', 'INVALID_ORIGIN_SOURCE', '$.origin.summary'))
    for name, path, suffix, code, at in checks:
        if '\0' in path or not path.startswith('/') or '..' in Path(path).parts or Path(path).suffix.lower() != suffix:
            fail(code, f'select an absolute local {suffix} path without parent references', at)
    for name in ('image', 'model'):
        if 'sha256' in p[name] and not HEX.fullmatch(p[name]['sha256']): fail('INVALID_SHA256', 'use 64 lowercase hexadecimal digits', f'$.{name}.sha256')
    settings = {'engine': 'lstm', 'oem': 1, 'psm': SEGMENTATION[p['pageSegmentation']], 'threads': 1, 'nativeConfig': list(NATIVE_CONFIG),
                'densitySource': 'authored' if 'dpi' in p else 'png-declared-or-native-estimate'}
    return {'version': 'schemaxis.tesseract.plan/1', 'operation': OPERATION, **p, 'settings': settings,
            'budget': {'maxImageBytes': IMAGE_LIMIT, 'maxSide': MAX_SIDE, 'maxPixels': MAX_PIXELS, 'maxModelBytes': MODEL_LIMIT, 'maxWords': tsv.MAX_WORDS,
                       'maxWordCharacters': tsv.MAX_TEXT_CHARACTERS, 'maxTsvBytes': NATIVE_TSV_LIMIT, 'maxTextBytes': NATIVE_TEXT_LIMIT},
            'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': OPERATION},
        **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', 'image', 'model'])}


def query(document): plan(document);return [OPERATION], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: fail('INVALID_EXECUTION', 'OCR runs one serial native thread', identity)
    return {'threads': 1}


def plan_hash(p): return hashlib.sha256(json.dumps(p, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


# ---------------------------------------------------------------- bounded host inputs
def bounded(path, code='VERIFICATION_FAILED', limit=JSON_LIMIT, follow=False, location=None):
    try:
        fd = os.open(path, os.O_RDONLY | (0 if follow else getattr(os, 'O_NOFOLLOW', 0)) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit: raise ValueError('not a bounded regular file')
            data = stream.read(limit + 1)
        if len(data) > limit: raise ValueError('file byte budget exceeded')
        return data
    except (OSError, ValueError) as error: fail(code, 'select an intact regular file within the byte budget: ' + str(error), location or str(path))


def stream_capture(path, limit, code, target=None, follow=True, checkpoint=None, location=None):
    """Hash (and optionally copy) through one open descriptor; the identity records what was actually read."""
    out = None
    try:
        fd = os.open(path, os.O_RDONLY | (0 if follow else getattr(os, 'O_NOFOLLOW', 0)) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit: raise ValueError('not a bounded regular file')
            if target is not None: out = os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb')
            digest = hashlib.sha256();count = 0
            for block in iter(lambda: stream.read(1 << 20), b''):
                if checkpoint: checkpoint()
                count += len(block)
                if count > limit: raise ValueError('byte budget exceeded')
                digest.update(block)
                if out: out.write(block)
            after = os.fstat(stream.fileno())
        if out: out.close()
        if count != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino): raise ValueError('file changed while it was read')
        return {'sha256': digest.hexdigest(), 'bytes': count, 'device': before.st_dev, 'inode': before.st_ino, 'mtimeNs': before.st_mtime_ns}
    except (OSError, ValueError) as error:
        if out and not out.closed: out.close()
        fail(code, 'select an intact regular file within the byte budget: ' + str(error), location or str(path))


def sha(data): return hashlib.sha256(data).hexdigest()
def whole(value): return type(value) is int


def strict_json(data, at, code='VERIFICATION_FAILED'):
    def pairs(items):
        if len({k for k, _ in items}) != len(items): raise ValueError('duplicate JSON key')
        return dict(items)
    def constant(name): raise ValueError('non-finite JSON number ' + name)
    try:
        text = data.decode('utf-8')
        if text.startswith('﻿'): raise ValueError('byte-order mark')
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as error: fail(code, 'evidence is not strict UTF-8 JSON: ' + str(error), at)


def same_json(actual, expected):
    try: return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError, RecursionError): return False


def encode_json(value): return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')
def read(directory, name): return strict_json(bounded(directory / name), name)
def digest(directory, name, limit=JSON_LIMIT): return sha(bounded(directory / name, limit=limit))


def evidence_limit(name): return MODEL_LIMIT if name in (MODEL_FILE, IMAGE_FILE) else JSON_LIMIT


# ---------------------------------------------------------------- image admission
def admit_image(data, code='INVALID_IMAGE_DATA', at='$.image.path'):
    """Header policy first (so an unsupported colour type is named, not called corrupt), then the shared bounded decoder."""
    if len(data) < 33 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR' or struct.unpack_from('>I', data, 8)[0] != 13:
        fail(code, 'expected a complete PNG file', at)
    width, height, depth, colour, compression, filtering, interlace = struct.unpack_from('>IIBBBBB', data, 16)
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE and width * height <= MAX_PIXELS):
        fail('IMAGE_RESOURCE_LIMIT', f'image is {width}x{height}; at most {MAX_SIDE} pixels per side and {MAX_PIXELS} pixels are supported', at, width=width, height=height)
    if colour != 2 or depth != 8:
        fail('UNSUPPORTED_IMAGE', 'only opaque 8-bit RGB PNG (colour type 2) is supported; alpha, palette, grey and 16-bit images are refused, never flattened', at, colourType=colour, bitDepth=depth)
    if interlace != 0: fail('UNSUPPORTED_IMAGE', 'interlaced PNG is unsupported; re-export it non-interlaced', at, interlace=interlace)
    chunks, offset = {}, 8
    try:
        while offset < len(data):
            length, kind = struct.unpack_from('>I4s', data, offset)
            chunks.setdefault(kind, data[offset + 8:offset + 8 + length]);offset += length + 12
    except struct.error: fail(code, 'truncated PNG chunk structure', at)
    if b'acTL' in chunks or b'tRNS' in chunks: fail('UNSUPPORTED_IMAGE', 'animated or transparency-keyed PNG is unsupported', at)
    try: decoded_width, decoded_height, rgba = shared_png.decode(data)
    except SchemaxisError as error: raise SchemaxisError(Fault(code, error.fault.message, at, error.fault.phase, error.fault.retryable, error.fault.observed, 'select a complete bounded opaque RGB PNG')) from None
    rgb = bytearray(3 * decoded_width * decoded_height)
    rgb[0::3], rgb[1::3], rgb[2::3] = rgba[0::4], rgba[1::4], rgba[2::4]
    density = None
    if b'pHYs' in chunks and len(chunks[b'pHYs']) == 9:
        x, y, unit = struct.unpack('>IIB', chunks[b'pHYs'])
        if unit == 1 and x == y and x > 0: density = round(x * 2.54 / 100)
    return {'width': decoded_width, 'height': decoded_height, 'bytes': len(data), 'sha256': sha(data), 'rgbSha256': sha(bytes(rgb)), 'declaredDensityDpi': density}


def capture_image(p, loader, at='$.image.path'):
    data = loader()
    info = admit_image(data, at=at)
    if 'sha256' in p['image'] and p['image']['sha256'] != info['sha256']: fail('IMAGE_HASH_MISMATCH', 'image bytes differ from the pinned sha256', at, observed=info['sha256'])
    return data, info


# ---------------------------------------------------------------- origin (optional, never inferred from pixels)
def origin_document(p, summary_bytes, image):
    """Bind a declared MuPDF review-summary page entry to the image by its pixel identity; refuse any disagreement."""
    if 'origin' not in p: return {'state': 'unknown', 'statement': 'Pixel-only input: no page, document or capture identity is asserted.'}
    at = '$.origin'
    summary = strict_json(summary_bytes, at, 'ORIGIN_INVALID')
    if not isinstance(summary, dict) or not isinstance(summary.get('pages'), list) or not isinstance(summary.get('sourceSha256'), str) or not HEX.fullmatch(summary['sourceSha256']):
        fail('ORIGIN_INVALID', 'origin summary must be a MuPDF review summary with pages and a source SHA-256', at)
    entries = [e for e in summary['pages'] if isinstance(e, dict) and e.get('page') == p['origin']['page'] and whole(e.get('page'))]
    if len(entries) != 1: fail('ORIGIN_MISMATCH', 'origin summary has no single entry for the declared page', at + '.page', page=p['origin']['page'])
    entry = entries[0]
    if (entry.get('width'), entry.get('height'), entry.get('rgbSha256')) != (image['width'], image['height'], image['rgbSha256']):
        fail('ORIGIN_MISMATCH', 'the declared summary page does not describe these pixels (width, height or RGB SHA-256 differ)', at, declaredPage=p['origin']['page'])
    for key in ('pageCount', 'dpi', 'rotation'):
        if not whole(summary.get(key)): fail('ORIGIN_INVALID', f'origin summary {key} must be an integer', at)
    return {'state': 'declared-bound-to-pixels', 'kind': 'mupdf-review', 'summarySha256': sha(summary_bytes), 'pdfSha256': summary['sourceSha256'], 'page': entry['page'],
            'pageCount': summary['pageCount'], 'renderDpi': summary['dpi'], 'rotation': summary['rotation'],
            'statement': 'The declared summary page entry has the same width, height and RGB-pixel SHA-256 as the captured image; the MuPDF run itself is not re-verified here.'}


def reusableInputs(document):
    p = plan(document)
    _, info = capture_image(p, lambda: bounded(p['image']['path'], 'INVALID_IMAGE_SOURCE', IMAGE_LIMIT, location='$.image.path'))
    result = {'image': info['sha256'], 'model': stream_capture(p['model']['path'], MODEL_LIMIT, 'INVALID_MODEL', location='$.model.path')['sha256']}
    if 'origin' in p: result['origin'] = sha(bounded(p['origin']['summary'], 'INVALID_ORIGIN_SOURCE', ORIGIN_LIMIT, location='$.origin.summary'))
    return result


# ---------------------------------------------------------------- native command and launcher
def commands(executable, p):
    recognize = [executable, IMAGE_FILE, 'native', '--tessdata-dir', 'tessdata', '-l', p['language'], '--oem', '1', '--psm', str(p['settings']['psm']),
                 *(['--dpi', str(p['dpi'])] if 'dpi' in p else []), *[x for item in NATIVE_CONFIG for x in ('-c', item)]]
    return {'version': [executable, '--version'], 'libraries': [executable, '--version'], 'recognize': recognize}


def stage_inputs(stage): return [IMAGE_FILE, MODEL_FILE] if stage == 'recognize' else []


def launcher(directory, stage, command, p):
    """Trusted launcher: binds inputs by hash, fixes the environment and resource caps, never trusts ambient configuration."""
    environment = {'LANG': 'C.UTF-8', 'OMP_NUM_THREADS': '1', 'OMP_THREAD_LIMIT': '1', **({'LD_TRACE_LOADED_OBJECTS': '1'} if stage == 'libraries' else {})}
    return ('import hashlib,json,os,resource,stat\nfrom pathlib import Path\n'
        + f'command={command!r}\nnames={stage_inputs(stage)!r}\nenvironment={environment!r}\nbindings={{"files":{{}}}}\n'
        + 'resource.setrlimit(resource.RLIMIT_CPU,(600,600))\nresource.setrlimit(resource.RLIMIT_FSIZE,(16777216,16777216))\nresource.setrlimit(resource.RLIMIT_AS,(8589934592,8589934592))\nresource.setrlimit(resource.RLIMIT_CORE,(0,0))\n'
        + 'for name in names:\n    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,"O_NONBLOCK",0))\n'
        + '    with os.fdopen(fd,"rb") as stream:\n        info=os.fstat(stream.fileno())\n'
        + f'        if not stat.S_ISREG(info.st_mode) or info.st_size>{MODEL_LIMIT}: raise ValueError("invalid native input")\n'
        + '        h=hashlib.sha256();count=0\n        for block in iter(lambda:stream.read(1<<20),b""):\n            count+=len(block);h.update(block)\n'
        + '        if count!=info.st_size: raise ValueError("native input changed while read")\n    bindings["files"][name]=h.hexdigest()\n'
        + 'bindings["ldLibraryPath"]=os.environ.get("LD_LIBRARY_PATH")\n'
        + f'Path({stage + "-inputs.json"!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        + 'env=dict(environment)\nif bindings["ldLibraryPath"] is not None: env["LD_LIBRARY_PATH"]=bindings["ldLibraryPath"]\n'
        + 'os.execve(command[0],command,env)\n')


def qualified_runtime(directory, code='UNSUPPORTED_NATIVE_VERSION'):
    text = bounded(directory / 'version.stdout', code, 4096).decode('utf-8', 'replace')
    if text.split('\n')[0] != RUNTIME: fail(code, 'configure the qualified Tesseract 5.5.3 executable', 'version', observed=text[:200])
    return RUNTIME


def library_paths(directory):
    found = []
    for line in bounded(directory / 'libraries.stdout', 'VERIFICATION_FAILED', LOG_LIMIT).decode('utf-8', 'replace').splitlines():
        line = line.strip()
        if not line or line.startswith('linux-vdso') or line.startswith('statically linked'): continue
        match = re.fullmatch(r'(\S+) => (/.+?) \(0x[0-9a-f]+\)', line) or re.fullmatch(r'()(/.+?) \(0x[0-9a-f]+\)', line)
        if not match: fail('RUNTIME_UNRESOLVED', 'dynamic dependency cannot be resolved to a local file', 'libraries', observed=line[:200])
        found.append((match.group(1) or Path(match.group(2)).name, match.group(2)))
    if len(found) > MAX_RUNTIME_FILES: fail('RUNTIME_RESOURCE_LIMIT', 'too many dynamic dependencies', 'libraries')
    return sorted(found)


def runtime_identity(directory, executable, checkpoint=None):
    files = [{'name': 'tesseract', 'path': executable}, *({'name': n, 'path': q} for n, q in library_paths(directory))]
    for item in files: item.update({k: v for k, v in stream_capture(item['path'], RUNTIME_FILE_LIMIT, 'RUNTIME_RESOURCE_LIMIT', checkpoint=checkpoint).items() if k in ('sha256', 'bytes')})
    return files


# ---------------------------------------------------------------- checked results
def documents(directory, p, image, origin):
    """All publications from independent evidence: native TSV (strict reader) and text (agreement policy) only."""
    tsv_bytes = bounded(directory / 'native.tsv', 'VERIFICATION_FAILED', NATIVE_TSV_LIMIT)
    text_bytes = bounded(directory / 'native.txt', 'VERIFICATION_FAILED', NATIVE_TEXT_LIMIT)
    parsed = tsv.parse(tsv_bytes, image['width'], image['height'])
    if not parsed['words']:
        if tsv.native_lines(text_bytes): tsv.refuse('native text has content but the TSV has no words', 'native.txt')
        fail('OCR_NO_TEXT', 'the recogniser reported no words on this page with the chosen segmentation; no empty draft is published', 'native.tsv', pageSegmentation=p['pageSegmentation'])
    text = tsv.agree(parsed, text_bytes)
    words = [{k: w[k] for k in ('index', 'block', 'paragraph', 'line', 'word', 'box', 'confidence', 'text')} for w in parsed['words']]
    review = {'machineDraft': True, 'ocrTruthCertified': False, 'humanReviewRequired': True, 'accuracyCertified': False, 'confidenceCalibrated': False, 'statement': REVIEW}
    words_doc = {'version': 'schemaxis.tesseract.words/1', 'imageSha256': image['sha256'], 'page': {'width': image['width'], 'height': image['height']},
                 'coordinates': {'origin': 'top-left', 'unit': 'pixel', 'box': 'left, top, width, height; right and bottom edges exclusive', 'sameAsSourceImage': True},
                 'confidence': {'scale': 'native decimal 0-100', 'calibrated': False}, 'wordCount': len(words), 'words': words, 'review': review}
    words_bytes = encode_json(words_doc)
    confidences = [w['confidence'] for w in words]
    settings = p['settings']
    summary = {'version': 'schemaxis.tesseract.summary/1', 'status': 'machine-draft', 'runtime': RUNTIME,
               'image': {k: image[k] for k in ('sha256', 'bytes', 'width', 'height', 'rgbSha256', 'declaredDensityDpi')}, 'origin': origin,
               'model': {'language': p['language'], 'sha256': p['model']['sha256'], 'bytes': read(directory, 'model.json')['bytes'], 'engine': 'lstm'},
               'settings': {'engine': settings['engine'], 'oem': 1, 'psm': settings['psm'], 'pageSegmentation': p['pageSegmentation'], 'language': p['language'],
                            'dpi': p.get('dpi'), 'densitySource': settings['densitySource'], 'threads': 1, 'nativeConfig': list(NATIVE_CONFIG)},
               'counts': {'blocks': parsed['blocks'], 'paragraphs': parsed['paragraphs'], 'lines': parsed['lineCount'], 'words': len(words)},
               'confidence': {'min': min(confidences), 'max': max(confidences), 'scale': 'native decimal 0-100', 'calibrated': False},
               'lines': parsed['lines'], 'textSha256': sha(text.encode('utf-8')), 'wordsSha256': sha(words_bytes),
               'nativeTsvSha256': sha(tsv_bytes), 'nativeTextSha256': sha(text_bytes),
               'policy': {'readingOrder': tsv.READING_ORDER, 'coordinates': 'top-left whole pixels; page record equals image size; boxes inside parents',
                          'text': 'canonical text is the TSV lines; native text must agree'},
               'review': review, 'losses': LOSSES}
    return {'page.txt': text.encode('utf-8'), 'words.json': words_bytes, 'ocr-summary.json': encode_json(summary)}, summary


PUBLISHED = (('page.txt', 'text'), ('words.json', 'text'), ('ocr-summary.json', 'text'))


def artifacts(directory): return [{'file': str(directory / n), 'kind': kind, 'sha256': digest(directory, n)} for n, kind in PUBLISHED]


def evidence_names(p):
    names = {'authored.json', 'plan.json', 'captures.json', IMAGE_FILE, MODEL_FILE, 'model.json', 'runtime.json', 'native.tsv', 'native.txt',
             *[s + x for s in STAGES for x in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr')]}
    if 'origin' in p: names.add('origin-summary.json')
    return names


def membership(directory, p):
    from schemaxis.run_paths import MANIFEST
    published = [n for n, _ in PUBLISHED]
    expected = {n for n in evidence_names(p) if '/' not in n} | {*published, 'verification.json', 'result.json', 'schema.snapshot.json', MANIFEST, 'job.json'}
    expected |= {name + '.metadata.json' for name in published}
    for path in directory.iterdir():
        if path.name in ('.dispatch', 'tessdata'):
            if path.is_symlink() or not path.is_dir(): fail('VERIFICATION_FAILED', 'owned member is not a directory', path.name)
        elif path.name not in expected or path.is_symlink() or not path.is_file(): fail('VERIFICATION_FAILED', 'unexpected or nonregular retained OCR member', path.name)
    members = sorted(x.name for x in (directory / 'tessdata').iterdir())
    if members != ['eng.traineddata'] or (directory / MODEL_FILE).is_symlink() or not (directory / MODEL_FILE).is_file(): fail('VERIFICATION_FAILED', 'retained model directory membership differs', 'tessdata')


def native_failure(directory, error):
    stderr = directory / 'recognize.stderr'
    text = bounded(stderr, 'VERIFICATION_FAILED', LOG_LIMIT).decode('utf-8', 'replace') if stderr.is_file() else ''
    for token in ('Failed loading language', 'Could not initialize tesseract', 'Error opening data file', 'read_params_file', 'LSTM requested'):
        if token in text: fail('MODEL_UNUSABLE', 'the pinned model could not be loaded as an English LSTM model by this runtime', '$.model.path', token=token)
    raise error


def run(document, directory, *, executable=None, timeout=300):
    p = plan(document);executable = executable or os.environ.get('SCHEMAXIS_TESSERACT') or shutil.which('tesseract')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK): fail('INTERPRETER_NOT_FOUND', 'configure an absolute Tesseract 5.5.3 executable')
    if os.name != 'posix': fail('UNSUPPORTED_PLATFORM', 'native resource caps require POSIX')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600: fail('INVALID_ARGUMENT', 'timeout must be finite in (0,3600]')
    deadline = time.monotonic() + timeout;directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'select a fresh output directory', str(directory))
    directory.mkdir(parents=True);atomic_json(directory / 'authored.json', document);atomic_json(directory / 'plan.json', p)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    def checkpoint():
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'OCR cancelled')
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'OCR exhausted its total deadline')
    try:
        checkpoint()
        data, image = capture_image(p, lambda: bounded(p['image']['path'], 'INVALID_IMAGE_SOURCE', IMAGE_LIMIT, location='$.image.path'))
        (directory / IMAGE_FILE).write_bytes(data)
        atomic_json(directory / 'captures.json', {'source': p['image']['path'], 'image': image});del data
        if 'origin' in p:
            summary = bounded(p['origin']['summary'], 'INVALID_ORIGIN_SOURCE', ORIGIN_LIMIT, location='$.origin.summary')
            (directory / 'origin-summary.json').write_bytes(summary);origin_document(p, summary, image)
        checkpoint()
        (directory / 'tessdata').mkdir()
        model = stream_capture(p['model']['path'], MODEL_LIMIT, 'INVALID_MODEL', directory / MODEL_FILE, checkpoint=checkpoint, location='$.model.path')
        if model['sha256'] != p['model']['sha256']: fail('MODEL_HASH_MISMATCH', 'model bytes differ from the pinned sha256', '$.model.sha256', observed=model['sha256'])
        checkpoint()
        runtime_files = None
        for stage, command in commands(str(executable), p).items():
            path = directory / (stage + '-launcher.py');path.write_text(launcher(directory, stage, command, p))
            try: execute([sys.executable, str(path)], directory, stage, deadline - time.monotonic(), {'LANG': 'C.UTF-8', 'OMP_NUM_THREADS': '1', 'OMP_THREAD_LIMIT': '1'})
            except SchemaxisError as error:
                if stage == 'recognize': native_failure(directory, error)
                raise
            if stage == 'version': qualified_runtime(directory)
            if stage == 'libraries': runtime_files = runtime_identity(directory, str(executable), checkpoint=checkpoint)
        checkpoint()
        if runtime_identity(directory, str(executable), checkpoint=checkpoint) != runtime_files: fail('RUNTIME_CHANGED', 'executable or dynamic dependency bytes changed during the run')
        after = stream_capture(p['model']['path'], MODEL_LIMIT, 'INVALID_MODEL', checkpoint=checkpoint, location='$.model.path')
        if {k: after[k] for k in model} != model: fail('MODEL_CHANGED', 'model bytes or file identity changed during the native run', '$.model.path')
        if digest(directory, MODEL_FILE, MODEL_LIMIT) != model['sha256']: fail('MODEL_CHANGED', 'retained model copy differs from the pinned bytes', MODEL_FILE)
        atomic_json(directory / 'model.json', {'path': p['model']['path'], **model, 'after': {k: after[k] for k in model}})
        atomic_json(directory / 'runtime.json', {'executable': str(executable), 'files': runtime_files})
        for name in ('native.tsv', 'native.txt'):
            if not (directory / name).is_file(): fail('OCR_OUTPUT_MISSING', 'the native run exited without producing ' + name, name)
        files, _ = documents(directory, p, image, origin_document(p, bounded(directory / 'origin-summary.json', limit=ORIGIN_LIMIT) if 'origin' in p else None, image))
        for name, data in files.items(): (directory / name).write_bytes(data)
        atomic_json(directory / 'verification.json', {'executable': str(executable), 'runtime': qualified_runtime(directory), 'planSha256': plan_hash(p), 'artifacts': artifacts(directory),
            'evidence': {n: digest(directory, n, evidence_limit(n)) for n in sorted(evidence_names(p))}})
        result = verify(directory, require_result=False)
        checkpoint()
        result['status'] = 'succeeded';atomic_json(directory / 'result.json', result);return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()});raise error


def verify(directory, require_result=True):
    """Offline: rechecks retained evidence only. No native process is ever launched and receipt values are not trusted."""
    directory = Path(directory).absolute()
    try:
        p = plan(read(directory, 'authored.json'));receipt = read(directory, 'verification.json')
        if not isinstance(receipt, dict) or set(receipt) != {'executable', 'runtime', 'planSha256', 'artifacts', 'evidence'} or not isinstance(receipt['evidence'], dict): fail('VERIFICATION_FAILED', 'native receipt member set differs')
        if not same_json(read(directory, 'plan.json'), p) or receipt['planSha256'] != plan_hash(p): fail('VERIFICATION_FAILED', 'effective OCR plan differs from the authored input or receipt')
        if require_result and read(directory, 'result.json').get('status') != 'succeeded': fail('INCOMPLETE_EXECUTION', 'OCR did not complete')
        membership(directory, p)
        data = bounded(directory / IMAGE_FILE, limit=IMAGE_LIMIT);image = admit_image(data, 'VERIFICATION_FAILED', IMAGE_FILE)
        if 'sha256' in p['image'] and p['image']['sha256'] != image['sha256']: fail('VERIFICATION_FAILED', 'captured image differs from the pinned sha256')
        if not same_json(read(directory, 'captures.json'), {'source': p['image']['path'], 'image': image}): fail('VERIFICATION_FAILED', 'image source/capture binding differs')
        model = read(directory, 'model.json')
        if (not isinstance(model, dict) or set(model) != {'path', 'sha256', 'bytes', 'device', 'inode', 'mtimeNs', 'after'} or model['sha256'] != p['model']['sha256'] or model['path'] != p['model']['path']
                or not isinstance(model['after'], dict) or not same_json(model['after'], {k: model[k] for k in ('sha256', 'bytes', 'device', 'inode', 'mtimeNs')})): fail('VERIFICATION_FAILED', 'model identity changed or differs from the pin')
        if not all(whole(model[k]) and model[k] >= 0 for k in ('device', 'inode', 'mtimeNs', 'bytes')) or not 0 < model['bytes'] <= MODEL_LIMIT: fail('VERIFICATION_FAILED', 'retained model identity has invalid numeric fields')
        retained = bounded(directory / MODEL_FILE, limit=MODEL_LIMIT)
        if sha(retained) != p['model']['sha256'] or len(retained) != model['bytes']: fail('VERIFICATION_FAILED', 'retained model copy differs from the pinned bytes')
        del retained
        origin = origin_document(p, bounded(directory / 'origin-summary.json', limit=ORIGIN_LIMIT) if 'origin' in p else None, image)
        executable = receipt['executable']
        if not isinstance(executable, str) or not Path(executable).is_absolute(): fail('VERIFICATION_FAILED', 'native executable identity must be absolute')
        for stage, command in commands(executable, p).items():
            submission = read(directory, stage + '-submission.json');path = directory / (stage + '-launcher.py')
            interpreter = submission.get('interpreter', {}).get('executable') if isinstance(submission, dict) and isinstance(submission.get('interpreter'), dict) else None
            if not isinstance(interpreter, str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand') != [interpreter, str(path)] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0: fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
            if bounded(path).decode() != launcher(directory, stage, command, p): fail('VERIFICATION_FAILED', 'trusted native launcher differs', stage)
            bindings = read(directory, stage + '-inputs.json');expected = {'files': {n: digest(directory, n, evidence_limit(n)) for n in stage_inputs(stage)}}
            if not isinstance(bindings, dict) or set(bindings) != {*expected, 'ldLibraryPath'} or bindings['files'] != expected['files'] or not (bindings['ldLibraryPath'] is None or isinstance(bindings['ldLibraryPath'], str)): fail('VERIFICATION_FAILED', 'native image/model input binding differs', stage)
        if receipt['runtime'] != qualified_runtime(directory, 'VERIFICATION_FAILED'): fail('VERIFICATION_FAILED', 'require qualified Tesseract 5.5.3 runtime identity')
        files = read(directory, 'runtime.json')
        if not isinstance(files, dict) or set(files) != {'executable', 'files'} or files['executable'] != executable or not isinstance(files['files'], list) or not files['files'] or [(f.get('name'), f.get('path')) for f in files['files'][1:]] != library_paths(directory) or (files['files'][0].get('name'), files['files'][0].get('path')) != ('tesseract', executable): fail('VERIFICATION_FAILED', 'runtime dependency identity differs from the loader trace')
        if not all(isinstance(f, dict) and set(f) == {'name', 'path', 'sha256', 'bytes'} and isinstance(f['sha256'], str) and HEX.fullmatch(f['sha256']) and whole(f['bytes']) and 0 < f['bytes'] <= RUNTIME_FILE_LIMIT for f in files['files']): fail('VERIFICATION_FAILED', 'runtime file hashes are malformed')
        expected, summary = documents(directory, p, image, origin)
        for name, content in expected.items():
            if bounded(directory / name, limit=JSON_LIMIT) != content: fail('VERIFICATION_FAILED', 'published OCR file differs from independently checked native evidence', name)
        if receipt['artifacts'] != artifacts(directory): fail('VERIFICATION_FAILED', 'OCR publication membership/digest differs')
        if set(receipt['evidence']) != evidence_names(p): fail('VERIFICATION_FAILED', 'native evidence membership differs')
        for n in evidence_names(p):
            if digest(directory, n, evidence_limit(n)) != receipt['evidence'][n]: fail('VERIFICATION_FAILED', 'retained native evidence differs', n)
        fresh = {'verified': True, 'artifacts': len(PUBLISHED), 'runtime': RUNTIME, 'words': summary['counts']['words'], 'lines': summary['counts']['lines'],
                 'imageSha256': image['sha256'], 'modelSha256': p['model']['sha256'], 'originState': origin['state'], 'draftStatus': 'machine-draft', 'ocrTruthCertified': False, 'humanReviewRequired': True}
        if require_result and not same_json(read(directory, 'result.json'), {**fresh, 'status': 'succeeded'}): fail('VERIFICATION_FAILED', 'retained result differs from independent reopening')
        return fresh
    except SchemaxisError as error:
        if error.fault.code in ('VERIFICATION_FAILED', 'INCOMPLETE_EXECUTION'): raise
        fail('VERIFICATION_FAILED', 'retained OCR evidence violates its contract (' + error.fault.code + ')', error.fault.location, cause=error.fault.to_dict())
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeDecodeError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained OCR evidence: ' + str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
