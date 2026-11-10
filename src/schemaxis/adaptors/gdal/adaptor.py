# Copyright (C) 2026 David L F Gaden
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
ZONE = {'type': 'object', 'properties': {'id': {'type': 'string', 'minLength': 1, 'maxLength': 32, 'required': True},
        **{k: {'type': 'integer', 'minimum': 0 if k in ('x', 'y') else 1, 'maximum': 4096, 'required': True} for k in ('x', 'y', 'width', 'height')}}}
ZONAL_OPTIONS = {
    'source': OPTIONS['source'], 'epsg': OPTIONS['epsg'], 'units': OPTIONS['units'], 'nodata': OPTIONS['nodata'],
    'zones': {'type': 'array', 'items': ZONE, 'minItems': 1, 'maxItems': reference.MAX_ZONES, 'required': True},
    'missing': {'type': 'enum', 'values': ['exclude', 'refuse'], 'required': True},
    'lossPolicy': OPTIONS['lossPolicy'],
}
FIELDS = {'window': tuple(OPTIONS), 'zonalSummary': tuple(ZONAL_OPTIONS)}
OPERATIONS = tuple(FIELDS)
ALL_FIELDS = tuple(dict.fromkeys(k for names in FIELDS.values() for k in names))
ZONAL_NATIVE = 'osgeo.gdal.Run("raster", "zonal-stats", input=source.tif, zones=zones.geojson, stat=[count,min,max,sum,mean], pixels="default", include_field=["zone"], output_format="GeoJSON"); fresh OGR reopening of summary.geojson'
DECLARATIONS = {'window': {'native': 'osgeo.gdal.Translate(srcWin, width, height, resampleAlg=nearest)', 'kinds': ['image', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k,v in OPTIONS.items()}},
    'zonalSummary': {'native': ZONAL_NATIVE, 'kinds': ['table', 'text'], 'inputs': {}, 'options': {k: {'value': v} for k, v in ZONAL_OPTIONS.items()}}}
LOSSES = ['Nearest-neighbour samples pixel centres without averaging or interpolation; downsampling loses unsampled values and is not conservative.', 'Single-band north-up PixelIsArea UInt16/Int16/finite Float32 uncompressed classic strip GeoTIFF only; unsupported metadata is refused. TIFF strip layout, byte order and descriptive CRS citations may change.', 'EPSG4326 uses x longitude/y latitude in degrees; EPSG3857 uses x easting/y northing in metres. No reprojection, geodesic area or vertical-datum conversion. Band units and nodata are preserved.']
ZONAL_LOSSES = [
    'Each zone is an independent pixel-aligned rectangle of the captured raster grid, authored as zero-based column x, row y, width and height in pixels. Zones are never reprojected, rasterised from arbitrary polygons or unioned: overlapping zones are allowed and summarised independently, and the visits of different zones are not unique pixels.',
    'Statistics are over band values of included pixels. sum is the sum of those values, not an area integral; mean is an unweighted pixel mean. EPSG:4326 angular pixels do not support ground-area weighting, and no land classification, yield, demand, uncertainty or location accuracy is inferred. Units are asserted, never converted.',
    'Nodata pixels are exact sentinel matches of the declared and observed nodata. missing=exclude counts them as missing; missing=refuse refuses any zone containing one. A zone with no valid pixel has valid 0 and null minimum, maximum, sum and mean (native zero sum is normalised to null, only for that exact shape).',
    'Published sum and mean are host values: the correctly rounded exact sum (math.fsum) and that sum divided by the count in double precision. The native sum and mean must lie within a roundoff allowance derived from the exact rational sum of the stored values, and a zone is refused before native work (ZONE_SUM_UNRESOLVABLE) when that allowance exceeds 2**-26 of the exact sum (cancellation). That ceiling is a consistency threshold between native output and the host oracle, not a scientific accuracy claim. Minimum, maximum and counts must match exactly, and published zero is never signed. The CSV carries no units: units and CRS are in zones-summary.json and the publication metadata.',
]


def parse_zonal_plan(document):
    prepared = validate_arguments(ZONAL_OPTIONS, {k: v for k, v in document.items() if k in ZONAL_OPTIONS}, location='$')
    path = Path(prepared['source'])
    if not path.is_absolute() or path.suffix.lower() not in ('.tif', '.tiff') or '\x00' in str(path): fail('INVALID_RASTER_SOURCE', 'select an absolute local GeoTIFF regular file', '$.source')
    if not math.isfinite(prepared['nodata']): fail('INVALID_ARGUMENT', 'nodata must be finite', '$.nodata')
    try: reference.validate_zones(prepared['zones'], None, None)
    except reference.ZoneError as error: fail(error.code, 'author 1 to 16 uniquely named in-grid pixel rectangles', '$.zones' if error.index is None else '$.zones[%d]' % error.index)
    return {'version': 'schemaxis.gdal.plan/1', 'operation': 'zonalSummary', **prepared, 'losses': ZONAL_LOSSES}


def plan(document):
    keys(document, ('version','operation',*ALL_FIELDS), '$')
    if document.get('version') != VERSION: fail('UNSUPPORTED_VERSION', 'select '+VERSION, '$.version')
    operation = document.get('operation')
    if not isinstance(operation, str) or operation not in OPERATIONS: fail('UNKNOWN_FILTER', 'select window or zonalSummary', '$.operation')
    keys(document, ('version','operation',*FIELDS[operation]), '$')
    if operation == 'zonalSummary': return parse_zonal_plan(document)
    prepared=validate_arguments(OPTIONS,{k:v for k,v in document.items() if k in OPTIONS},location='$')
    path=Path(prepared['source'])
    if not path.is_absolute() or path.suffix.lower() not in ('.tif','.tiff') or '\x00' in str(path): fail('INVALID_RASTER_SOURCE','select an absolute local GeoTIFF regular file','$.source')
    if not math.isfinite(prepared['nodata']): fail('INVALID_ARGUMENT','nodata must be finite','$.nodata')
    if prepared['width']*prepared['height']>reference.MAX_PIXELS or prepared['outputWidth']*prepared['outputHeight']>reference.MAX_PIXELS: fail('RASTER_PIXEL_LIMIT','window/output must each have at most 262144 pixels','$')
    return {'version':'schemaxis.gdal.plan/1','operation':'window',**prepared,'losses':LOSSES}


def schema():
    from schemaxis.schema import DRAFT, argument_schema, object_schema
    def branch(name, options):
        return object_schema({'version': {'const': VERSION}, 'operation': {'const': name}, **{k: argument_schema(v) for k, v in options.items()}}, ['version', 'operation', *options])
    window, zonal = branch('window', OPTIONS), branch('zonalSummary', ZONAL_OPTIONS)
    properties = {**window['properties'], **zonal['properties'], 'operation': {'enum': list(OPERATIONS)}}
    return {'$schema': DRAFT, **object_schema(properties, ['version', 'operation', 'source', 'epsg', 'units', 'nodata', 'lossPolicy']), 'oneOf': [window, zonal]}


def query(document):
    return [plan(document)['operation']], {}


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
def config(prepared): return {k: prepared[k] for k in (ZONAL_OPTIONS if prepared['operation'] == 'zonalSummary' else OPTIONS) if k != 'source'}
def zonal_worker_source(): return Path(__file__).with_name('zonal_worker.py').read_text()
ZONAL_STAGES = ('zonal', 'zonal-readback')
ZONAL_PUBLICATIONS = (('zones-summary.csv', 'table'), ('zones-summary.json', 'text'))
CANONICAL = {'sort_keys': True, 'allow_nan': False, 'separators': (',', ':')}


def zonal_inspect(directory, prepared):
    """Independent host oracle over every included pixel, then native zonal-stats evidence and a fresh OGR reopening."""
    source = reference.parse(bounded(directory/'source.tif', limit=8*1024**2))
    try: rows = reference.zonal_expected(source, prepared)
    except ValueError as error: fail('VERIFICATION_FAILED', 'zone oracle refused: '+str(error))
    ids = [z['id'] for z in prepared['zones']]
    expected_zones = reference.zones_geojson(source, prepared['zones'])
    if bounded(directory/'zones.geojson') != json.dumps(expected_zones, **CANONICAL).encode(): fail('VERIFICATION_FAILED', 'retained zone geometry differs from the authored pixel rectangles and source affine', 'zones.geojson')
    native = read(directory, 'zonal.stdout'); reopen = read(directory, 'zonal-readback.stdout')
    if set(native) != {'runtime', 'algorithm', 'raster'} or native['runtime'] != '3.13.3' or native['algorithm'] != 'raster zonal-stats': fail('VERIFICATION_FAILED', 'native zonal runtime/algorithm fields differ')
    if set(reopen) != {'runtime', 'summary', 'zones'} or reopen['runtime'] != '3.13.3': fail('VERIFICATION_FAILED', 'native zonal readback fields differ')
    try:
        reference.compare(source, native['raster'])
        raw = json.loads(bounded(directory/'summary.geojson', limit=1024**2))
        if not isinstance(raw, dict) or set(raw) != {'type', 'name', 'features'} or raw['type'] != 'FeatureCollection' or raw['name'] != 'stats': raise ValueError('native summary envelope differs')
        counted = reference.normalise_native_zones(raw['features'], ids)
        reference.compare_zonal(rows, counted)
        view = reopen['summary']
        if set(view) != {'fields', 'features'} or not isinstance(view['features'], list) or any(set(f) != {'properties', 'ring'} or not isinstance(f['properties'], dict) or f['ring'] is not None for f in view['features']): raise ValueError('fresh native summary view shape differs')
        again = reference.normalise_native_zones([{'type': 'Feature', 'properties': {k: v for k, v in f['properties'].items() if v is not None}, 'geometry': None} for f in view['features']], ids)
        if again != counted: raise ValueError('fresh native reopening differs from the native summary')
        geometry = reopen['zones']
        if geometry['fields'] != ['zone'] or [f['properties'] for f in geometry['features']] != [{'zone': i} for i in ids]: raise ValueError('fresh native zone identity differs')
        corners = [[list(map(float, corner)) for corner in row['corners']] for row in rows]
        for feature, ((x0, y0), (x1, y1)) in zip(geometry['features'], corners):
            if feature['ring'] != [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]: raise ValueError('fresh native zone geometry differs from authored pixel rectangles')
    except (ValueError, TypeError, KeyError) as error:
        fail('VERIFICATION_FAILED', 'zonal native evidence differs from the independent oracle: '+str(error))
    report = {**reference.zonal_report(source, prepared, rows), 'sourceSha256': digest(directory, 'source.tif'), 'losses': ZONAL_LOSSES}
    return report, reference.csv_text(rows)


def inspect(directory, prepared):
    if prepared['operation'] == 'zonalSummary': return zonal_inspect(directory, prepared)[0]
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
    if prepared['operation'] == 'zonalSummary':
        report = read(directory, 'zones-summary.json')
        identity = {'kind': 'table', 'columns': report['columns'], 'nullToken': report['nullToken'], 'valueUnits': report['units'], 'epsg': report['epsg'], 'missingPolicy': report['missingPolicy']}
        return [{'file': str(directory/name), 'kind': kind, 'sha256': digest(directory, name), **({'rows': report['zoneCount'], 'identity': identity} if kind == 'table' else {})} for name, kind in ZONAL_PUBLICATIONS]
    return [{'file': str(directory/name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in [('raster.tif', 'image'), ('raster-summary.json', 'text')]]


def evidence_names(prepared):
    if prepared['operation'] == 'zonalSummary':
        return {'authored.json', 'plan.json', 'source.tif', 'capture.json', 'zonal_worker.py', 'native-config.json', 'zones.geojson', 'summary.geojson'} | {stage+suffix for stage in ZONAL_STAGES for suffix in ('.stdout', '.stderr', '-inputs.json', '-submission.json')}
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
        if prepared['operation'] == 'zonalSummary': return zonal_run(directory, prepared, data, executable, deadline)
        try:
            window = reference.expected(reference.parse(data), prepared)
        except (ValueError, UnicodeError, IndexError, KeyError) as error:
            fail('INVALID_RASTER_CONTENT', 'supply supported intact single-band GeoTIFF with matching metadata and in-bounds window: '+str(error), '$.source')
        violation = reference.extent_violation(window)
        if violation:
            fail('RASTER_EXTENT_INVALID', 'the selected window lies outside the valid '+violation['axis']+' range for EPSG:'+str(violation['epsg'])+'; correct the source CRS/geotransform or choose a window inside it (no reprojection is performed)', '$.source', **violation)
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


NATIVE_ENVIRONMENT = {'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','LANG':'C.UTF-8','GDAL_PAM_ENABLED':'NO','GDAL_DISABLE_READDIR_ON_OPEN':'EMPTY_DIR','GDAL_CACHEMAX':'32','PROJ_NETWORK':'OFF'}


def zonal_run(directory, prepared, data, executable, deadline):
    try: source = reference.parse(data)
    except (ValueError, UnicodeError, IndexError, KeyError) as error:
        fail('INVALID_RASTER_CONTENT', 'supply a supported intact single-band GeoTIFF: '+str(error), '$.source')
    if source['epsg'] != prepared['epsg'] or source['units'] != prepared['units'] or source['nodata'] != prepared['nodata']:
        fail('INVALID_RASTER_CONTENT', 'asserted epsg, units and nodata must match the source metadata; nothing is imposed on the raster', '$.source')
    try: rows = reference.zonal_expected(source, prepared)
    except reference.ZoneError as error: fail(error.code, 'adjust the authored zones, missing policy or source: '+str(error), '$.zones' if error.index is None else '$.zones[%d]' % error.index)
    violation = reference.zone_extent_violation(rows, source['epsg'])
    if violation:
        fail('RASTER_EXTENT_INVALID', 'the selected zones lie outside the valid '+violation['axis']+' range for EPSG:'+str(violation['epsg'])+'; correct the source CRS/geotransform or choose zones inside it (no reprojection is performed)', '$.source', **violation)
    (directory/'source.tif').write_bytes(data)
    atomic_json(directory/'capture.json', {'source': prepared['source'], 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    (directory/'zonal_worker.py').write_text(zonal_worker_source()); atomic_json(directory/'native-config.json', config(prepared))
    (directory/'zones.geojson').write_bytes(json.dumps(reference.zones_geojson(source, prepared['zones']), **CANONICAL).encode())
    for stage in ZONAL_STAGES:
        execute([str(executable), '-I', str(directory/'zonal_worker.py'), stage], directory, stage, deadline-time.monotonic(), NATIVE_ENVIRONMENT)
    report, csv = zonal_inspect(directory, prepared)
    atomic_json(directory/'zones-summary.json', report); (directory/'zones-summary.csv').write_bytes(csv.encode())
    atomic_json(directory/'verification.json', {'artifacts': artifacts(directory, prepared), 'evidence': {name: digest(directory, name) for name in sorted(evidence_names(prepared))}, 'executable': str(executable), 'runtime': 'gdal 3.13.3'})
    result = verify(directory, require_result=False)
    if cancellation_requested(): fail('RUNNER_CANCELLED', 'zonal publication cancelled')
    if time.monotonic() >= deadline: fail('RUNNER_TIMED_OUT', 'zonal summary exceeded its total deadline')
    result['status'] = 'succeeded'; atomic_json(directory/'result.json', result); return result


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
        zonal = prepared['operation'] == 'zonalSummary'
        worker = 'zonal_worker.py' if zonal else 'native-worker.py'
        if bounded(directory/worker).decode() != (zonal_worker_source() if zonal else worker_source()) or read(directory, 'native-config.json') != config(prepared):
            fail('VERIFICATION_FAILED', 'trusted native worker/configuration differs')
        for stage in (ZONAL_STAGES if zonal else ('window', 'readback')):
            submission = read(directory, stage+'-submission.json')
            if submission.get('nativeCommand') != [executable, '-I', str(directory/worker), stage] or type(submission.get('exitCode')) is not int or submission['exitCode'] != 0:
                fail('VERIFICATION_FAILED', 'native command/completion differs', stage)
            if zonal: consumed = ('source.tif', 'zones.geojson') if stage == 'zonal' else ('summary.geojson', 'zones.geojson')
            else: consumed = (source if stage == 'window' else 'raster.tif',)
            if read(directory, stage+'-inputs.json') != {name: digest(directory, name) for name in (*consumed, 'native-config.json', worker)}:
                fail('VERIFICATION_FAILED', 'native consumed-input binding differs', stage)
        if zonal:
            report, csv = zonal_inspect(directory, prepared)
            if read(directory, 'zones-summary.json') != report: fail('VERIFICATION_FAILED', 'zonal summary differs', 'zones-summary.json')
            if bounded(directory/'zones-summary.csv').decode('utf-8') != csv: fail('VERIFICATION_FAILED', 'zonal CSV differs from the independent oracle', 'zones-summary.csv')
            present = {p.name for p in directory.glob('zones-summary*') if not p.name.endswith('.metadata.json')}
            if present != {n for n, _ in ZONAL_PUBLICATIONS}: fail('VERIFICATION_FAILED', 'unexpected zonal publication')
        elif read(directory, 'raster-summary.json') != inspect(directory, prepared): fail('VERIFICATION_FAILED', 'raster summary differs')
        if receipt['artifacts'] != artifacts(directory, prepared): fail('VERIFICATION_FAILED', 'publication membership/digest differs')
        if set(receipt['evidence']) != evidence_names(prepared): fail('VERIFICATION_FAILED', 'evidence membership differs')
        for name in evidence_names(prepared):
            if digest(directory, name) != receipt['evidence'][name]: fail('VERIFICATION_FAILED', 'retained evidence differs', name)
        if zonal: return {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': receipt['runtime'], 'zones': len(prepared['zones']), 'pixelVisits': read(directory, 'zones-summary.json')['pixelVisits']}
        return {'verified': True, 'artifacts': len(receipt['artifacts']), 'runtime': receipt['runtime'], 'pixels': read(directory,'raster-summary.json')['width']*read(directory,'raster-summary.json')['height']}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained raster evidence: '+str(error))


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
