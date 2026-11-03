# Copyright (C) 2026 David L F Gaden
"""Closed report model, trusted Pandoc AST and independent document inspection."""
import base64
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
import zlib

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute

VERSION = 'schemaxis.pandoc/1'
MAX_BYTES = 16 * 1024 * 1024
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 2048, 'required': True}
CELL = {**TEXT, 'maxLength': 256}
PARAGRAPH = {'type': 'object', 'properties': {
    'kind': {'type': 'enum', 'values': ['paragraph'], 'required': True}, 'text': TEXT}}
TABLE = {'type': 'object', 'properties': {
    'kind': {'type': 'enum', 'values': ['table'], 'required': True},
    'columns': {'type': 'array', 'items': CELL, 'minItems': 1, 'maxItems': 8, 'required': True},
    'rows': {'type': 'array', 'items': {'type': 'array', 'items': CELL, 'minItems': 1, 'maxItems': 8},
             'minItems': 1, 'maxItems': 64, 'required': True}}}
IMAGE = {'type': 'object', 'properties': {
    'kind': {'type': 'enum', 'values': ['image'], 'required': True},
    'source': {**TEXT, 'maxLength': 4096}, 'alt': {**TEXT, 'maxLength': 256},
    'widthMm': {'type': 'number', 'minimum': 10, 'maximum': 150, 'default': 80}}}
CONTENT = {'type': 'union', 'options': [PARAGRAPH, TABLE, IMAGE]}
SECTION = {'type': 'object', 'properties': {
    'heading': {**TEXT, 'maxLength': 160},
    'level': {'type': 'integer', 'minimum': 1, 'maximum': 3, 'default': 1},
    'content': {'type': 'array', 'items': CONTENT, 'minItems': 1, 'maxItems': 32, 'required': True}}}
OPTIONS = {'title': {**TEXT, 'maxLength': 160},
    'sections': {'type': 'array', 'items': SECTION, 'minItems': 1, 'maxItems': 32, 'required': True}}
DECLARATIONS = {'report': {'native': 'Pandoc JSON AST: Header / Para / Table / Image; html5 / docx writers; docx reader',
    'kinds': ['text', 'file'], 'inputs': {}, 'options': {k: {'value': v} for k, v in OPTIONS.items()}}}
LOSSES = ['Plain text only: no authored markup, scripts, links, formulas, citations, lists, styles or filters.',
    'Tables contain one header row and rectangular text cells; no merged cells, numeric types or formula semantics.',
    'Default Pandoc typography and pagination are not an exact page-layout contract; no PDF publication or visual equivalence claim.',
    'PNG bytes and alt text are retained; image display width is millimetres, aspect ratio is retained, and colour management/accessibility conformance are not certified.',
    'Section order and heading levels are preserved; generated identifiers and writer metadata are not authored interchange contracts.']


def plain(value, location):
    if value != value.strip() or any(ord(c) < 32 or 127 <= ord(c) <= 159 or c in '\ufffe\uffff' or 0xD800 <= ord(c) <= 0xDFFF or c in '\u2028\u2029' for c in value) or '  ' in value or any(c.isspace() and c != ' ' for c in value):
        fail('INVALID_REPORT_TEXT', 'use nonempty plain text with single spaces, no control characters or line breaks', location)
    return value


def plan(document):
    keys(document, ('version', 'operation', *OPTIONS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'expected ' + VERSION)
    if document.get('operation') != 'report': fail('UNKNOWN_FILTER', 'select report')
    prepared = validate_arguments(OPTIONS, {k: v for k, v in document.items() if k in OPTIONS})
    plain(prepared['title'], '$.title')
    previous = 0; count = 0; characters = len(prepared['title']); images = 0
    for i, section in enumerate(prepared['sections']):
        at = f'$.sections[{i}]'; level = section['level']
        if level > previous + 1: fail('INVALID_HEADING_ORDER', 'begin with level 1 and increase by at most one; descending levels may skip', at + '.level')
        previous = level; plain(section['heading'], at + '.heading'); characters += len(section['heading'])
        for j, block in enumerate(section['content']):
            where = at + f'.content[{j}]'; count += 1
            if block['kind'] == 'paragraph': plain(block['text'], where + '.text'); characters += len(block['text'])
            elif block['kind'] == 'table':
                if any(len(row) != len(block['columns']) for row in block['rows']):
                    fail('INVALID_REPORT_TABLE', 'each row must have exactly one text cell per declared column', where + '.rows')
                for r, row in enumerate([block['columns'], *block['rows']]):
                    for c, value in enumerate(row): plain(value, where + f'.cells[{r}][{c}]'); characters += len(value)
            else:
                plain(block['alt'], where + '.alt'); images += 1
                source = Path(block['source'])
                if not source.is_absolute() or source.suffix.lower() != '.png':
                    fail('INVALID_REPORT_IMAGE', 'select an absolute local PNG path; remote URLs and other formats are unsupported', where + '.source')
    if count > 128 or characters > 65536 or images > 8:
        fail('REPORT_RESOURCE_LIMIT', 'report permits at most 128 content blocks, 65536 text characters and 8 images', '$.sections')
    return {'version': 'schemaxis.pandoc.plan/1', 'operation': 'report', **prepared, 'losses': LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': 'report'},
        **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', 'title', 'sections'])}


def query(document):
    plan(document); return ['report'], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: fail('INVALID_EXECUTION', 'report rendering uses one process thread', identity)
    return {'threads': 1}


def bounded(path, code='VERIFICATION_FAILED', limit=MAX_BYTES):
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit: raise ValueError('not a bounded regular file')
            data = stream.read(limit + 1)
        if len(data) > limit: raise ValueError('byte budget exceeded')
        return data
    except (OSError, ValueError) as error:
        fail(code, 'select intact bounded regular evidence: ' + str(error), str(path))


def png(data, location):
    """Validate closed 8-bit non-interlaced RGB/RGBA PNG and bounded scanline data."""
    try:
        if data[:8] != b'\x89PNG\r\n\x1a\n': raise ValueError('PNG signature')
        position = 8; chunks = []; compressed = bytearray(); width = height = colour = None
        while position < len(data):
            length = struct.unpack('>I', data[position:position+4])[0]; kind = data[position+4:position+8]
            body = data[position+8:position+8+length]; crc = data[position+8+length:position+12+length]
            if length > 4*1024*1024 or len(body) != length or len(crc) != 4 or struct.unpack('>I', crc)[0] != zlib.crc32(kind+body): raise ValueError('chunk CRC/length')
            chunks.append(kind); position += length+12
            if kind == b'IHDR':
                width,height,depth,colour,compression,filtering,interlace = struct.unpack('>IIBBBBB', body)
                if not 1 <= width <= 2048 or not 1 <= height <= 2048 or width*height > 1048576 or depth != 8 or colour not in (2,6) or (compression,filtering,interlace) != (0,0,0): raise ValueError('unsupported dimensions/colour/interlace')
            elif kind == b'IDAT': compressed.extend(body)
            elif kind != b'IEND': raise ValueError('only IHDR/IDAT/IEND chunks are supported; export a plain RGB/RGBA PNG')
        if chunks[1:-1] != [b'IDAT'] * (len(chunks)-2) or chunks[0] != b'IHDR' or chunks[-1] != b'IEND' or chunks.count(b'IHDR') != 1 or chunks.count(b'IEND') != 1 or b'IDAT' not in chunks or body or position != len(data): raise ValueError('chunk order')
        expected = (width*(3 if colour == 2 else 4)+1)*height
        inflater = zlib.decompressobj(); decoded = inflater.decompress(bytes(compressed), expected+1)
        if len(decoded) != expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail: raise ValueError('scanline size')
        stride = width*(3 if colour == 2 else 4)+1
        if any(decoded[y*stride] > 4 for y in range(height)): raise ValueError('PNG filter')
        return {'width': width, 'height': height, 'sha256': hashlib.sha256(data).hexdigest()}
    except (ValueError, IndexError, struct.error, zlib.error, TypeError) as error:
        fail('INVALID_REPORT_IMAGE', 'use a plain bounded 8-bit RGB/RGBA PNG: ' + str(error), location)


def image_blocks(prepared):
    for i, section in enumerate(prepared['sections']):
        for j, block in enumerate(section['content']):
            if block['kind'] == 'image': yield i, j, block


def reusableInputs(document):
    prepared = plan(document)
    return {f'image-{i}-{j}': hashlib.sha256(bounded(b['source'], 'INVALID_REPORT_IMAGE', 4*1024*1024)).hexdigest()
            for i,j,b in image_blocks(prepared)}


def inlines(text):
    result = []
    for index, word in enumerate(text.split(' ')):
        if index: result.append({'t': 'Space'})
        result.append({'t': 'Str', 'c': word})
    return result


def ast(prepared, api, directory):
    blocks = []; attr = ['', [], []]
    for i, section in enumerate(prepared['sections']):
        blocks.append({'t': 'Header', 'c': [section['level'], [f'section-{i+1}', [], []], inlines(section['heading'])]})
        for j, block in enumerate(section['content']):
            if block['kind'] == 'paragraph': blocks.append({'t': 'Para', 'c': inlines(block['text'])})
            elif block['kind'] == 'image':
                blocks.append({'t': 'Para', 'c': [{'t': 'Image', 'c': [['', [], [['width', f'{block["widthMm"]}mm']]],
                    inlines(block['alt']), ['data:image/png;base64,'+base64.b64encode(bounded(directory/f'image-{i}-{j}.png')).decode('ascii'), '']]}]})
            else:
                def row(values):
                    return [attr, [[attr, {'t': 'AlignDefault'}, 1, 1, [{'t': 'Plain', 'c': inlines(value)}]] for value in values]]
                blocks.append({'t': 'Table', 'c': [attr, [None, []], [[{'t': 'AlignDefault'}, {'t': 'ColWidthDefault'}] for _ in block['columns']],
                    [attr, [row(block['columns'])]], [[attr, 0, [], [row(r) for r in block['rows']]]], [attr, []]]})
    return {'pandoc-api-version': api, 'meta': {'title': {'t': 'MetaInlines', 'c': inlines(prepared['title'])}}, 'blocks': blocks}


def read(directory, name): return json.loads(bounded(directory/name))
def digest(directory, name): return hashlib.sha256(bounded(directory/name)).hexdigest()


def expected(prepared):
    blocks = []
    for i, section in enumerate(prepared['sections']):
        blocks.append({'kind': 'heading', 'level': section['level'], 'text': section['heading']})
        for j, block in enumerate(section['content']):
            if block['kind'] == 'paragraph': blocks.append({'kind': 'paragraph', 'text': block['text']})
            elif block['kind'] == 'table': blocks.append({'kind': 'table', 'rows': [block['columns'], *block['rows']]})
            else: blocks.append({'kind': 'image', 'alt': block['alt'], 'sha256': digest(prepared['_directory'], f'image-{i}-{j}.png'),
                                'widthMm': block['widthMm']})
    return blocks


def artifacts(directory):
    return [{'file': str(directory/name), 'kind': kind, 'sha256': digest(directory, name)}
            for name,kind in [('report.html','text'),('report.docx','file'),('report-summary.json','text')]]


def commands(executable):
    native = {'version': [executable, '--version'],
        'api': [executable, '--from=markdown', '--to=json', '--output=api.json', 'empty.txt'],
        'html': [executable, '--from=json', '--to=html5', '--wrap=none', '--standalone', '--embed-resources', '--sandbox', '--output=report.html', 'report-input.json'],
        'docx': [executable, '--from=json', '--to=docx', '--standalone', '--sandbox', '--output=report.docx', 'report-input.json'],
        'reopen': [executable, '--from=docx', '--to=json', '--sandbox', '--extract-media=reopened', '--output=reopened.json', 'report.docx']}
    return {stage: command+['--data-dir=native-data','+RTS','-M512M','-RTS'] for stage,command in native.items()}


def stage_inputs(stage, prepared):
    if stage == 'api': return ['empty.txt']
    if stage in ('html', 'docx'): return ['report-input.json']
    if stage == 'reopen': return ['report.docx']
    return []


def launcher(directory, stage, command, prepared):
    paths = [str(directory/name) for name in stage_inputs(stage, prepared)]
    return ('import hashlib,json,os,stat\nfrom pathlib import Path\n'
        + f'paths={paths!r}\ncommand={command!r}\nbindings={{}}\n'
        + 'for name in paths:\n'
        + '    fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))\n'
        + '    with os.fdopen(fd,"rb") as stream:\n'
        + f'        info=os.fstat(stream.fileno())\n        if not stat.S_ISREG(info.st_mode) or info.st_size>{MAX_BYTES}: raise ValueError("invalid native report input")\n'
        + f'        data=stream.read({MAX_BYTES+1})\n        if len(data)>{MAX_BYTES}: raise ValueError("report input limit")\n'
        + '    bindings[name]=hashlib.sha256(data).hexdigest()\n'
        + f'Path({str(directory/(stage+"-inputs.json"))!r}).write_text(json.dumps(bindings,sort_keys=True))\n'
        + 'os.execvpe(command[0],command,os.environ)\n')


def launch(directory, stage, command, prepared, deadline):
    script=directory/(stage+'-launcher.py');script.write_text(launcher(directory,stage,command,prepared))
    execute([sys.executable,str(script)],directory,stage,deadline-time.monotonic(),{'LANG':'C.UTF-8'})


def inspect(directory, prepared):
    from .inspection import html_report, docx_report, ast_report
    model = expected({**prepared, '_directory': directory})
    html_report(bounded(directory/'report.html').decode(), prepared['title'], model)
    docx_report(bounded(directory/'report.docx'), prepared['title'], model)
    ast_report(read(directory,'reopened.json'), directory, prepared['title'], model)
    return {'title': prepared['title'], 'sections': len(prepared['sections']), 'blocks': len(model),
            'tables': sum(b['kind']=='table' for b in model), 'images': sum(b['kind']=='image' for b in model), 'losses': LOSSES}


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_PANDOC') or shutil.which('pandoc')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute Pandoc executable')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite and in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'select a fresh report directory', str(directory))
    directory.mkdir(parents=True); atomic_json(directory/'authored.json',document); atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False}); deadline=time.monotonic()+timeout
    try:
        captured={}; captured_bytes=0
        for i,j,block in image_blocks(prepared):
            data=bounded(block['source'],'INVALID_REPORT_IMAGE',4*1024*1024); captured_bytes+=len(data)
            if captured_bytes>8*1024*1024: fail('REPORT_RESOURCE_LIMIT','combined captured PNG bytes exceed8MiB','$.sections')
            name=f'image-{i}-{j}.png'
            captured[name]={'source':block['source'],**png(data,block['source'])}; (directory/name).write_bytes(data)
        atomic_json(directory/'captures.json',captured); (directory/'empty.txt').write_text(''); (directory/'native-data').mkdir()
        native=commands(str(executable))
        for stage in ('version','api'):
            launch(directory,stage,native[stage],prepared,deadline)
        api=read(directory,'api.json')['pandoc-api-version']
        atomic_json(directory/'report-input.json',ast(prepared,api,directory))
        for stage in ('html','docx','reopen'):
            launch(directory,stage,native[stage],prepared,deadline)
        summary=inspect(directory,prepared); atomic_json(directory/'report-summary.json',summary)
        names=['authored.json','plan.json','captures.json','empty.txt','api.json','report-input.json','reopened.json']
        names += list(captured)
        for stage in native: names += [stage+'-launcher.py',stage+'-inputs.json',stage+'-submission.json',stage+'.stdout',stage+'.stderr']
        names += sorted(str(p.relative_to(directory)) for p in (directory/'reopened').rglob('*') if p.is_file()) if (directory/'reopened').exists() else []
        atomic_json(directory/'verification.json',{'artifacts':artifacts(directory),'evidence':{name:digest(directory,name) for name in names},
                    'executable':str(executable),'runtime':bounded(directory/'version.stdout').decode().splitlines()[0]})
        result=verify(directory,require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED','report publication cancelled')
        if time.monotonic()>=deadline: fail('RUNNER_TIMED_OUT','report exhausted its total deadline')
        result['status']='succeeded'; atomic_json(directory/'result.json',result); return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED',str(error))
            except SchemaxisError as wrapped: error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict()}); raise error


def verify(directory,require_result=True):
    directory=Path(directory).absolute()
    try:
        prepared=plan(read(directory,'authored.json')); receipt=read(directory,'verification.json')
        if not isinstance(receipt.get('executable'),str) or not Path(receipt['executable']).is_absolute(): fail('VERIFICATION_FAILED','native executable identity must be absolute')
        if read(directory,'plan.json')!=prepared: fail('VERIFICATION_FAILED','effective report plan differs')
        if require_result and read(directory,'result.json').get('status')!='succeeded': fail('INCOMPLETE_EXECUTION','report did not complete')
        data_dir=directory/'native-data'
        if data_dir.is_symlink() or not data_dir.is_dir() or any(data_dir.iterdir()): fail('VERIFICATION_FAILED','isolated native data directory differs')
        captures=read(directory,'captures.json'); names=set(); captured_bytes=0
        for i,j,block in image_blocks(prepared):
            name=f'image-{i}-{j}.png'; names.add(name)
            data=bounded(directory/name,limit=4*1024*1024);captured_bytes+=len(data)
            if captured_bytes>8*1024*1024: fail('VERIFICATION_FAILED','combined captured image byte limit exceeded')
            if captures.get(name)!={'source':block['source'],**png(data,name)}:
                fail('VERIFICATION_FAILED','captured image/source binding differs',name)
        if set(captures)!=names: fail('VERIFICATION_FAILED','image capture membership differs')
        api=read(directory,'api.json')['pandoc-api-version']
        if bounded(directory/'empty.txt') or read(directory,'report-input.json')!=ast(prepared,api,directory):
            fail('VERIFICATION_FAILED','trusted AST differs from authored report')
        for stage,command in commands(receipt['executable']).items():
            submission=read(directory,stage+'-submission.json')
            interpreter=submission.get('interpreter',{}).get('executable')
            script=directory/(stage+'-launcher.py')
            if not isinstance(interpreter,str) or not Path(interpreter).is_absolute() or submission.get('nativeCommand')!=[interpreter,str(script)] or type(submission.get('exitCode'))is not int or submission['exitCode']!=0:
                fail('VERIFICATION_FAILED','native command/completion differs',stage)
            if bounded(script).decode()!=launcher(directory,stage,command,prepared): fail('VERIFICATION_FAILED','trusted native launcher differs',stage)
            if read(directory,stage+'-inputs.json')!={str(directory/name):digest(directory,name) for name in stage_inputs(stage,prepared)}:
                fail('VERIFICATION_FAILED','native stage consumed different report input bytes',stage)
        runtime=bounded(directory/'version.stdout').decode().splitlines()[0]
        if not re.fullmatch(r'pandoc \d+\.\d+(?:\.\d+){0,2}',runtime) or receipt['runtime']!=runtime:
            fail('VERIFICATION_FAILED','Pandoc runtime identity differs')
        summary=inspect(directory,prepared)
        if read(directory,'report-summary.json')!=summary: fail('VERIFICATION_FAILED','report summary differs')
        if receipt['artifacts']!=artifacts(directory): fail('VERIFICATION_FAILED','publication membership/digest differs')
        required={'authored.json','plan.json','captures.json','empty.txt','api.json','report-input.json','reopened.json',*names}
        for stage in commands(receipt['executable']): required.update((stage+'-launcher.py',stage+'-inputs.json',stage+'-submission.json',stage+'.stdout',stage+'.stderr'))
        reopened=read(directory,'reopened.json')
        required.update(b['c'][0]['c'][2][0] for b in reopened['blocks'] if b['t'] in ('Para','Plain') and len(b['c'])==1 and b['c'][0]['t']=='Image')
        if required!=set(receipt['evidence']): fail('VERIFICATION_FAILED','native evidence membership differs')
        for name in required:
            if Path(name).is_absolute() or '..' in Path(name).parts or digest(directory,name)!=receipt['evidence'][name]:
                fail('VERIFICATION_FAILED','retained native evidence differs',name)
        return {'verified':True,'artifacts':3,'runtime':runtime,**{k:summary[k] for k in ('sections','blocks','tables','images')}}
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as error:
        fail('VERIFICATION_FAILED','invalid retained report evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
