"""Metadata-explicit raster window extraction with independent GeoTIFF verification."""
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import reference

VERSION = 'schemaxis.gdal/1'
OPTIONS = {
    'source': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'required': True},
    **{k: {'type': 'integer', 'minimum': 0 if k in ('x','y') else 1, 'maximum': 4096, 'required': True} for k in ('x','y','width','height','outputWidth','outputHeight')},
    'epsg': {'type': 'enum', 'values': [4326, 3857], 'required': True},
    'units': {'type': 'enum', 'values': ['m','K','1'], 'required': True},
    'nodata': {'type': 'number', 'required': True},
    'resampling': {'type': 'enum', 'values': ['nearest'], 'required': True},
    'lossPolicy': {'type': 'enum', 'values': ['strict'], 'required': True},
}
DECLARATIONS = {'window': {'native': 'osgeo.gdal.Translate(srcWin, width, height, resampleAlg=nearest)', 'kinds': ['image', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k,v in OPTIONS.items()}}}
LOSSES = ['Nearest-neighbour samples pixel centres without averaging or interpolation; downsampling loses unsampled values and is not conservative.', 'Single-band north-up PixelIsArea UInt16/Int16/finite Float32 uncompressed classic strip GeoTIFF only; unsupported metadata is refused. TIFF strip layout, byte order and descriptive CRS citations may change.', 'EPSG4326 uses x longitude/y latitude in degrees; EPSG3857 uses x easting/y northing in metres. No reprojection, geodesic area or vertical-datum conversion. Band units and nodata are preserved.']


def plan(document):
    keys(document, ('version','operation',*OPTIONS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'select '+VERSION, '$.version')
    if document.get('operation') != 'window': fail('UNKNOWN_FILTER', 'select window', '$.operation')
    prepared=validate_arguments(OPTIONS,{k:v for k,v in document.items() if k in OPTIONS},location='$')
    path=Path(prepared['source'])
    if not path.is_absolute() or path.suffix.lower() not in ('.tif','.tiff') or '\x00' in str(path): fail('INVALID_RASTER_SOURCE','select an absolute local GeoTIFF regular file','$.source')
    if not math.isfinite(prepared['nodata']): fail('INVALID_ARGUMENT','nodata must be finite','$.nodata')
    if prepared['width']*prepared['height']>reference.MAX_PIXELS or prepared['outputWidth']*prepared['outputHeight']>reference.MAX_PIXELS: fail('RASTER_PIXEL_LIMIT','window/output must each have at most 262144 pixels','$')
    return {'version':'schemaxis.gdal.plan/1','operation':'window',**prepared,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    return {'$schema': DRAFT, **object_schema({'version': {'const': VERSION}, 'operation': {'const': 'window'}, **{k: argument_schema(v) for k, v in OPTIONS.items()}}, ['version', 'operation', *OPTIONS])}


def query(document):
    plan(document); return ['window'], {}


def resources(document, execution, identity):
    if execution.get('threads', 1) != 1: fail('INVALID_EXECUTION', 'raster extraction uses one serial process', identity)
    return {'threads': 1}


def bounded(path, code='VERIFICATION_FAILED', limit=32*1024**2):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit: raise ValueError('not a bounded regular file')
            data = stream.read(limit+1)
        if len(data) > limit: raise ValueError('file exceeds byte budget')
        return data
    except (OSError, ValueError) as error:
        fail(code, 'select an intact bounded regular file: '+str(error), str(path))


def reusableInputs(document):
    prepared = plan(document)
    return {'raster': hashlib.sha256(bounded(prepared['source'], 'INVALID_RASTER_SOURCE', 8*1024**2)).hexdigest()}


def read(directory, name): return json.loads(bounded(directory/name))
def digest(directory, name): return hashlib.sha256(bounded(directory/name)).hexdigest()
def worker_source(): return Path(__file__).with_name('native_worker.py').read_text()
def config(prepared): return {k: prepared[k] for k in OPTIONS if k != 'source'}


def inspect(directory, prepared):
    source = reference.parse(bounded(directory/'source.tif', limit=8*1024**2))
    expected = reference.expected(source, prepared)
    output = reference.parse(bounded(directory/'raster.tif', limit=8*1024**2))
    native = read(directory,'window.stdout'); reopen = read(directory,'readback.stdout')
    for stage in (native,reopen):
        if set(stage)!={'runtime','raster'} or stage['runtime']!='3.13.3': fail('VERIFICATION_FAILED','native runtime/snapshot fields differ')
    reference.compare(source,native['raster']); reference.compare(expected,output); reference.compare(output,reopen['raster'])
    expected_names={'raster.tif','raster-summary.json'}
    sidecars={name+'.metadata.json' for name in expected_names}
    present={p.name for p in directory.glob('raster*') if p.name not in sidecars}
    if present-expected_names: fail('VERIFICATION_FAILED','unexpected raster publication')
    return {**reference.summary(output),'sourceSha256':digest(directory,'source.tif'),'losses':LOSSES}


def artifacts(directory, prepared):
    return [{'file': str(directory/name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in [('raster.tif', 'image'), ('raster-summary.json', 'text')]]


def evidence_names(prepared):
    return {'authored.json', 'plan.json', 'source.tif', 'capture.json', 'native-worker.py', 'native-config.json'} | {stage+suffix for stage in ('window', 'readback') for suffix in ('.stdout', '.stderr', '-inputs.json', '-submission.json')}


def run(document, directory, *, executable=None, timeout=300):
    prepared = plan(document)
    executable = executable or os.environ.get('SCHEMAXIS_GDAL')
    if not executable or not Path(executable).is_absolute() or not os.access(executable, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'configure an absolute isolated Python interpreter containing GDAL 3.13.3')
    if os.name != 'posix': fail('UNSUPPORTED_PLATFORM', 'POSIX resource caps are required')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600: fail('INVALID_ARGUMENT', 'timeout must be finite in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink(): fail('OUTPUT_EXISTS', 'select a fresh raster extraction directory', str(directory))
    directory.mkdir(parents=True); deadline = time.monotonic()+timeout
    atomic_json(directory/'authored.json', document); atomic_json(directory/'plan.json', prepared)
    atomic_json(directory/'result.json', {'status': 'incomplete', 'verified': False})
    try:
        data = bounded(prepared['source'], 'INVALID_RASTER_SOURCE', 8*1024**2)
        try:
            reference.expected(reference.parse(data), prepared)
        except (ValueError, UnicodeError, IndexError, KeyError) as error:
            fail('INVALID_RASTER_CONTENT', 'supply supported intact single-band GeoTIFF with matching metadata and in-bounds window: '+str(error), '$.source')
        name = 'source.tif'; (directory/name).write_bytes(data)
        atomic_json(directory/'capture.json', {'source': prepared['source'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (directory/'native-worker.py').write_text(worker_source()); atomic_json(directory/'native-config.json', config(prepared))
        for stage in ('window', 'readback'):
            execute([str(executable), '-I', str(directory/'native-worker.py'), stage], directory, stage, deadline-time.monotonic(), {'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','LANG':'C.UTF-8','GDAL_PAM_ENABLED':'NO','GDAL_DISABLE_READDIR_ON_OPEN':'EMPTY_DIR','GDAL_CACHEMAX':'32','PROJ_NETWORK':'OFF'})
        atomic_json(directory/'raster-summary.json', inspect(directory, prepared))
        atomic_json(directory/'verification.json', {'artifacts': artifacts(directory, prepared), 'evidence': {name: digest(directory, name) for name in sorted(evidence_names(prepared))}, 'executable': str(executable), 'runtime': 'gdal 3.13.3'})
        result = verify(directory, require_result=False)
        if cancellation_requested(): fail('RUNNER_CANCELLED', 'raster publication cancelled')
        if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'raster extraction exceeded its total deadline')
        result['status'] = 'succeeded'; atomic_json(directory/'result.json', result); return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED', str(error))
            except SchemaxisError as wrapped: error = wrapped
        atomic_json(directory/'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()}); raise error


def verify(directory, require_result=True):
    directory = Path(directory).absolute()
    try:
        prepared = plan(read(directory, 'authored.json')); receipt = read(directory, 'verification.json')
        if read(directory, 'plan.json') != prepared: fail('VERIFICATION_FAILED', 'effective raster plan differs')
        if require_result and read(directory, 'result.json').get('status') != 'succeeded': fail('INCOMPLETE_EXECUTION', 'raster extraction did not complete')
        source = 'source.tif'; data = bounded(directory/source, limit=8*1024**2)
        if read(directory, 'capture.json') != {'source': prepared['source'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}:
            fail('VERIFICATION_FAILED', 'captured source identity differs')
        executable = receipt['executable']
        if not isinstance(executable, str) or not Path(executable).is_absolute() or receipt['runtime'] != 'gdal 3.13.3': fail('VERIFICATION_FAILED', 'native identity differs')
        if bounded(directory/'native-worker.py').decode() != worker_source() or read(directory, 'native-config.json') != config(prepared):
            fail('VERIFICATION_FAILED', 'trusted native worker/configuration differs')
        for stage in ('window', 'readback'):
            submission = read(directory, stage+'-submission.json')
            if submission.get('nativeCommand') != [executable, '-I', str(directory/'native-worker.py'), stage] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
            consumed = source if stage == 'window' else 'raster.tif'
            if read(directory, stage+'-inputs.json') != {name: digest(directory, name) for name in (consumed, 'native-config.json', 'native-worker.py')}:
                fail('VERIFICATION_FAILED', 'native consumed-input binding differs', stage)
        if read(directory, 'raster-summary.json') != inspect(directory, prepared): fail('VERIFICATION_FAILED', 'raster summary differs')
        if receipt['artifacts'] != artifacts(directory, prepared): fail('VERIFICATION_FAILED', 'publication membership/digest differs')
        if set(receipt['evidence']) != evidence_names(prepared): fail('VERIFICATION_FAILED', 'evidence membership differs')
        for name in evidence_names(prepared):
            if digest(directory, name) != receipt['evidence'][name]: fail('VERIFICATION_FAILED', 'retained evidence differs', name)
        return {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': receipt['runtime'], 'pixels': read(directory,'raster-summary.json')['width']*read(directory,'raster-summary.json')['height']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained raster evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
