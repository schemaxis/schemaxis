"""HDF5 scientific data files through h5py 3.16.0 in an isolated process, independently checked.

Every run captures its inputs into a fresh directory, plans and checks all values on the host, writes or
reads HDF5 with a trusted h5py worker in separate processes, then accepts a publication only when the
host's independently computed expected state agrees with (1) a fresh-process h5py readback manifest and
(2) the HDF Group ``h5dump`` XML of the same bytes, parsed by the standard library. Sources are never
modified; edits apply to captured copies.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import time

from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import cancellation_requested
from schemaxis.errors import fail, keys
from schemaxis.native_command import execute
from . import expect, h5xml, model, operations, state
from .model import DECLARATIONS, OPERATIONS, VERSION  # noqa: F401  (registry binding)

RUNTIME = 'h5py 3.16.0 / HDF5 2.0.0 / NumPy 2.5.4'
H5DUMP = 'h5dump: Version 2.2.0'
MAX_EVIDENCE = 256 * 1024 * 1024
XML_ELEMENT_BUDGET = 1024 * 1024
THREADS = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'LANG': 'C.UTF-8', 'HDF5_USE_FILE_LOCKING': 'FALSE'}
IMPLEMENTATION = ('adaptor.py', 'model.py', 'operations.py', 'state.py', 'expect.py', 'h5xml.py', 'meshes.py', 'editing.py', 'series.py', 'parallel.py',
                  'schemas.py', 'native_worker.py')


FIELDS = tuple(name for name in model.ROOT_KEYS if name not in ('version', 'operation'))


def plan(document):
    keys(document, ('version', 'operation', *FIELDS), '$')
    return operations.plan(document)


def schema():
    from .schemas import schema as build
    return build()


def query(document):
    p = plan(document)
    return [p['operation']], {}


def resources(document, execution, identity):
    p = plan(document)
    need = p['ranks'] if p['operation'] == 'parallelWrite' else p['parallel']['ranks'] if p.get('parallel') else 1
    if execution.get('ranks', 1) != 1:
        fail('INVALID_EXECUTION', 'HDF5 MPI ranks are declared by parallelWrite.ranks, not by the scheduler', identity)
    if execution.get('threads', need) != need:
        fail('INVALID_EXECUTION', 'HDF5 reserves one CPU per process: %d for this operation' % need, identity, threads=need)
    return {'threads': need}


# ------------------------------------------------------------------ files
def bounded(path, code='VERIFICATION_FAILED', limit=MAX_EVIDENCE):
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
        fail(code, 'select an intact bounded regular file: ' + str(error), str(path))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key ' + key)
        result[key] = value
    return result


def read(directory, name):
    try:
        return json.loads(bounded(Path(directory) / name), object_pairs_hook=unique_object)
    except ValueError as error:
        fail('VERIFICATION_FAILED', 'retained JSON is invalid: ' + str(error), name)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(directory, name):
    return sha(bounded(Path(directory) / name))


def implementation():
    here = Path(__file__).parent
    return {name: sha((here / name).read_bytes()) for name in IMPLEMENTATION if (here / name).is_file()}


def worker_source():
    return (Path(__file__).parent / 'native_worker.py').read_text()


# ------------------------------------------------------------------ runtime
def runtime(executable=None, h5dump=None):
    from schemaxis.configuration import locations
    configured = locations()
    python = executable or configured.get('hdf5') or os.environ.get('SCHEMAXIS_HDF5')
    tool = h5dump or configured.get('hdf5H5dump') or os.environ.get('SCHEMAXIS_HDF5_H5DUMP')
    for name, value, hint in (('python', python, 'an isolated Python with exactly h5py 3.16.0 (bundled HDF5 2.0.0) and NumPy 2.5.4: --hdf5, schemaxis configure hdf5, or SCHEMAXIS_HDF5'),
                              ('h5dump', tool, 'the HDF Group h5dump 2.2.0 tool used as the independent consumer: --hdf5-h5dump, location hdf5H5dump, or SCHEMAXIS_HDF5_H5DUMP')):
        if not isinstance(value, str) or not os.path.isabs(value) or not os.path.isfile(value) or not os.access(value, os.X_OK):
            fail('INTERPRETER_NOT_FOUND', 'configure ' + hint, '$.runtime.' + name)
    if os.name != 'posix':
        fail('UNSUPPORTED_PLATFORM', 'qualified HDF5 process resource caps require POSIX')
    return {'python': python, 'h5dump': tool}


def mpi_runtime(python=None, mpiexec=None):
    from schemaxis.configuration import locations
    configured = locations()
    python = python or configured.get('hdf5Mpi') or os.environ.get('SCHEMAXIS_HDF5_MPI')
    mpiexec = mpiexec or configured.get('hdf5Mpiexec') or os.environ.get('SCHEMAXIS_HDF5_MPIEXEC')
    for name, value, hint in (('mpiPython', python, 'a Python with h5py 3.16.0 built against parallel HDF5 2.0.0 and mpi4py: --hdf5-mpi or location hdf5Mpi'),
                              ('mpiexec', mpiexec, 'the matching Open MPI 4.1 mpiexec: --hdf5-mpiexec or location hdf5Mpiexec')):
        if not isinstance(value, str) or not os.path.isabs(value) or not os.path.isfile(value) or not os.access(value, os.X_OK):
            fail('INTERPRETER_NOT_FOUND', 'configure ' + hint, '$.runtime.' + name)
    return {'mpiPython': python, 'mpiexec': mpiexec}


HDF5_ROLES = ('externalLink', 'virtualSource', 'copySource', 'reference')
ALLOWED_FILTERS = {1: 'gzip', 2: 'shuffle', 3: 'fletcher32', 4: 'szip', 5: 'nbit', 6: 'scaleoffset', 32000: 'lzf'}
READ_STAGES = ('readback', 'inspect-', 'extract', 'edit', 'compare', 'chunk-list-')


def environment(directory):
    """Native environment: one thread, no file locking, no dynamic filter plugins, no inherited path prefixes."""
    empty = Path(directory) / '.no-plugins'
    empty.mkdir(exist_ok=True)
    return {**THREADS, 'HDF5_PLUGIN_PRELOAD': '::', 'HDF5_PLUGIN_PATH': str(empty), 'HDF5_EXTFILE_PREFIX': '', 'HDF5_VDS_PREFIX': '', 'HDF5_EXT_PREFIX': ''}


def declared_access(directory):
    for candidate in (Path(directory), Path(directory).parent):
        if (candidate / 'plan.json').is_file():
            return read(candidate, 'plan.json').get('access')
    return None


def inject_access(directory):
    access = declared_access(directory)
    path = Path(directory) / 'native-config.json'
    config = read(directory, 'native-config.json') if path.is_file() else {}
    if access and config.get('access') != access:
        config['access'] = access
        atomic_json(path, config)
    return access


def check_access(access, observed, stage_name):
    """The access properties actually in force (read back from the open file) must equal the declared ones."""
    if not access or observed is None:
        return
    want = {}
    if 'chunkCache' in access:
        want['chunkCache'] = access['chunkCache']
    if 'alignment' in access:
        want['alignment'] = access['alignment']
    for key in ('metaBlockBytes', 'pageBufferBytes', 'sieveBufferBytes'):
        if key in access:
            want[key] = access[key]
    got = {k: observed.get(k) for k in want}
    if json.loads(json.dumps(got)) != json.loads(json.dumps(want)):
        fail('VERIFICATION_FAILED', 'the native process did not apply the declared access properties', stage_name, expected=want, observed=got)


def native(paths, directory, name, deadline):
    access = inject_access(directory)
    try:
        execute([paths['python'], '-I', '-B', str(directory / 'native-worker.py'), name], directory, name,
                deadline - time.monotonic(), environment(directory))
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        fault = directory / (name + '-fault.json')
        if fault.is_file():
            record = read(directory, name + '-fault.json')
            code = record.get('code', 'HDF5_NATIVE_FAILED')
            fail(code if isinstance(code, str) and code.startswith('HDF5_') else 'HDF5_NATIVE_FAILED',
                 'h5py refused the operation: ' + str(record.get('message'))[:400], str(record.get('location', '$')), stage=name, **record.get('details', {}))
        fail('HDF5_NATIVE_FAILED', 'the h5py worker failed without a structured refusal; see ' + name + '.stderr', name)
    result = read(directory, name + '-result.json')
    if result.get('runtime', {}).get('h5py') != '3.16.0' or result['runtime'].get('hdf5') != '2.0.0':
        fail('VERIFICATION_FAILED', 'native runtime identity differs', name)
    if access and not name.startswith('preflight-') and result.get('access') is None:
        fail('VERIFICATION_FAILED', 'the native stage did not report its access properties', name)
    check_access(access, result.get('access'), name)
    return result['result']


def stage(paths, directory, name, deadline):
    """Run a worker stage; every stage that reads file values first admits each file it opens (metadata-only closure)."""
    if name.startswith(READ_STAGES):
        config = read(directory, 'native-config.json')
        if name.startswith(('readback', 'inspect-')):
            targets = [config['manifests'][name]['file']]
            settings = config['manifests'][name].get('fileSettings')
        elif name == 'extract':
            targets, settings = [config['source']], None
        elif name.startswith('chunk-list-'):
            targets, settings = [config['chunkLists'][name]['file']], None
        elif name == 'edit':
            targets, settings = [config['working']], None
        else:
            targets, settings = [config['source'], config['reference']], None
        for target in targets:
            admit(paths, directory, target, deadline, settings)
    return native(paths, directory, name, deadline)


def admitted_names(directory):
    """Files a captured HDF5 file may reference: declared dependencies by role, and raw files this run writes."""
    for candidate in (Path(directory), Path(directory).parent):
        if (candidate / 'plan.json').is_file():
            p = read(candidate, 'plan.json')
            names = {d['name']: d['role'] for d in p.get('dependencies', [])}
            names.update({name: 'produced' for name in p.get('rawFiles', [])})
            return names
    return {}


def bare(name):
    return isinstance(name, str) and name and name not in ('.', '..') and '/' not in name and '\\' not in name and '\x00' not in name \
        and '%' not in name and name.strip() == name


def admit(paths, directory, target, deadline, settings=None, depth=0, seen=None):
    """Metadata-only preflight of one file, then host closure before any process reads dataset values.

    The worker opens the file, walks hard links only, never follows soft or external links and reads no dataset
    values: it reports external raw segments, virtual source files and filter ids. Each referenced file must be a
    bare name equal to a captured dependency of the right role (or a raw file this run writes), recursively for
    nested HDF5 dependencies; filters must be on the reviewed built-in list. Otherwise the run is refused.
    """
    directory = Path(directory)
    seen = set() if seen is None else seen
    if target in seen:
        return
    seen.add(target)
    if depth > 4:
        fail('HDF5_MISSING_DEPENDENCY', 'virtual dependencies nest more than four files deep', '$.dependencies', file=target)
    config = read(directory, 'native-config.json') if (directory / 'native-config.json').is_file() else {}
    index = len(config.get('preflights', {}))
    name = 'preflight-%d' % index
    config.setdefault('preflights', {})[name] = {'file': target, 'fileSettings': settings}
    atomic_json(directory / 'native-config.json', config)
    pre = native(paths, directory, name, deadline)
    names = admitted_names(directory)
    nested = []
    for path, rec in sorted(pre['datasets'].items()):
        for code in rec['filters']:
            if code not in ALLOWED_FILTERS:
                fail('HDF5_UNSUPPORTED_FILTER', 'the file uses HDF5 filter %d, which is not a reviewed built-in filter; dynamic filter plugins are never loaded' % code,
                     path, file=target, filter=code)
        for segment in rec['external']:
            if not bare(segment):
                fail('HDF5_UNSAFE_DEPENDENCY_PATH', 'external raw storage names a path outside the captured bundle; only bare captured file names are read',
                     path, file=target, external=str(segment)[:200])
            if names.get(segment) not in ('rawStorage', 'produced') or not (directory / segment).is_file():
                fail('HDF5_MISSING_DEPENDENCY', 'external raw storage reads a file that was not supplied; declare it as a rawStorage dependency with that file name',
                     '$.dependencies', file=segment, dataset=path, source=target)
        for source in rec['virtual']:
            if source == '.':
                continue
            if not bare(source):
                fail('HDF5_UNSAFE_DEPENDENCY_PATH', 'a virtual dataset names a source file outside the captured bundle; only bare captured file names are read',
                     path, file=target, virtual=str(source)[:200])
            if names.get(source) != 'virtualSource' or not (directory / source).is_file():
                fail('HDF5_MISSING_DEPENDENCY', 'a virtual dataset reads a file that was not supplied; declare it as a virtualSource dependency with that file name',
                     '$.dependencies', file=source, dataset=path, source=target)
            nested.append(source)
    for path, (filename, link_target) in sorted(pre.get('externalLinks', {}).items()):
        if not bare(filename):
            fail('HDF5_UNSAFE_DEPENDENCY_PATH', 'an external link names a file outside the captured bundle; such links are never resolved, so the file cannot be adopted',
                 path, file=target, link=str(filename)[:200])
        if (directory / filename).exists() or (directory / filename).is_symlink():
            if names.get(filename) not in HDF5_ROLES or not (directory / filename).is_file():
                fail('HDF5_MISSING_DEPENDENCY', 'an external link names a bundle file that is not a captured HDF5 dependency; declare it as an externalLink dependency',
                     '$.dependencies', file=filename, link=path, source=target)
            nested.append(filename)
    for path, link_target in sorted(pre.get('softLinks', {}).items()):
        if '\x00' in link_target or len(link_target) > 4096:
            fail('HDF5_UNSAFE_DEPENDENCY_PATH', 'a soft link target cannot be represented safely', path, file=target)
    for source in sorted(set(nested)):
        admit(paths, directory, source, deadline, None, depth + 1, seen)
    return pre


def dump(paths, directory, name, target, deadline, driver=None, values=True):
    settings = None
    if driver:
        plan_file = admitted_plan_file(directory)
        settings = plan_file
    admit(paths, directory, target if not driver else (plan_file['name']), deadline, settings)
    command = [paths['h5dump'], '-x', '-p', '-q', 'creation_order', '-m', '%.17g']
    if not values:
        command.insert(1, '-H')
    if driver:
        command.append('--filedriver=' + driver)
    command.append(target)
    try:
        execute(command, directory, name, deadline - time.monotonic(), environment(directory))
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        fail('VERIFICATION_FAILED', 'the independent h5dump consumer could not read the file', name)
    xml = h5xml.parse(bounded(directory / (name + '.stdout')))
    null_spaces(paths, directory, name, target, deadline, driver, xml)
    if values:
        virtual_values(paths, directory, name, target, deadline, driver, xml)
    return xml


def null_candidates(xml):
    return [path for path, rec in sorted(xml['objects'].items()) if rec.get('kind') == 'dataset' and rec.get('shape') is None]


def null_spaces(paths, directory, name, target, deadline, driver, xml, retained=False):
    """h5dump XML prints no dataspace for null-dataspace datasets; confirm each one from h5dump's DDL header (DATASPACE NULL)."""
    for index, path in enumerate(null_candidates(xml)):
        stage_name = '%s-null-%d' % (name, index)
        if not retained:
            command = [paths['h5dump'], '--no-compact-subset', '-H', '-d', path, *(['--filedriver=' + driver] if driver else []), target]
            try:
                execute(command, directory, stage_name, deadline - time.monotonic(), environment(directory))
            except SchemaxisError as error:
                if error.fault.code != 'RUNNER_FAILED':
                    raise
                fail('VERIFICATION_FAILED', 'the independent h5dump consumer could not read a dataset header', path)
        text = bounded(directory / (stage_name + '.stdout')).decode('utf-8', 'replace')
        if not any(line.strip() == 'DATASPACE  NULL' for line in text.splitlines()):
            fail('VERIFICATION_FAILED', 'h5dump reports neither a shape nor a null dataspace', path)
        xml['objects'][path].update(shape=None, maxshape=None, null=True, values=[])


def admitted_plan_file(directory):
    for candidate in (Path(directory), Path(directory).parent):
        if (candidate / 'plan.json').is_file():
            return read(candidate, 'plan.json')['file']
    fail('VERIFICATION_FAILED', 'no plan for the multi-file driver reading', str(directory))


def selected_values(paths, directory, target, path, obj, sel, deadline, label):
    """Independent values of one selection: from the full h5dump reading when within budget, else an h5dump hyperslab read."""
    if obj.get('values') is not None:
        return [obj['values'][i] for i in state.indices(sel, obj['shape'])]
    if obj['type']['class'] not in ('int', 'uint', 'float') or obj['type'].get('dims'):
        fail('HDF5_RESOURCE_LIMIT', 'selections of large non-numeric datasets exceed the independently verified value budget', label)
    rank = len(obj['shape'])
    if sel['kind'] == 'all':
        blocks = [([0] * rank, [1] * rank, list(obj['shape']), [1] * rank)]
    elif sel['kind'] == 'slices':
        blocks = [([a for a, b, c in sel['slices']], [c for a, b, c in sel['slices']], [(b - a + c - 1) // c for a, b, c in sel['slices']], [1] * rank)]
    elif sel['kind'] == 'hyperslab':
        blocks = [(sel['start'], sel['stride'], sel['count'], sel['block'])]
    elif sel['kind'] == 'rows':
        if not sel['rows']:
            return []
        runs = row_runs(sel['rows'])
        if len(runs) > 16:
            span = {'kind': 'slices', 'slices': [[sel['rows'][0], sel['rows'][-1] + 1, 1]] + [[0, n, 1] for n in obj['shape'][1:]]}
            values = selected_values(paths, directory, target, path, obj, span, deadline, label)
            width = model.element_count(obj['shape'][1:])
            return [values[(r - sel['rows'][0]) * width + j] for r in sel['rows'] for j in range(width)]
        blocks = [([lo] + [0] * (rank - 1), [1] * rank, [n] + list(obj['shape'][1:]), [1] * rank) for lo, n in runs]
    else:
        if len(sel['points']) > 256:
            fail('HDF5_RESOURCE_LIMIT', 'point selections of large datasets are limited to 256 independently read points', label)
        blocks = [(list(q), [1] * rank, [1] * rank, [1] * rank) for q in sel['points']]
    if sum(model.element_count([c * b for c, b in zip(count, block)]) for _, _, count, block in blocks) > model.MAX_ELEMENTS:
        fail('HDF5_RESOURCE_LIMIT', 'the selection exceeds the independently verified value budget', label)
    admit(paths, directory, target, deadline)
    out = []
    for n, (start, stride, count, block) in enumerate(blocks):
        name = 'h5dump-subset-%s-%d' % (hashlib.sha256((target + path + label).encode()).hexdigest()[:10], n)
        command = [paths['h5dump'], '--no-compact-subset', '-d', path, '-s', ','.join(map(str, start)), '-S', ','.join(map(str, stride)), '-c', ','.join(map(str, count)),
                   '-k', ','.join(map(str, block)), '-m', '%.17g', '-y', '-w', '0', target]
        try:
            execute(command, directory, name, deadline - time.monotonic(), environment(directory))
        except SchemaxisError as error:
            if error.fault.code != 'RUNNER_FAILED':
                raise
            fail('VERIFICATION_FAILED', 'the independent h5dump consumer could not read the selection', label)
        out += h5xml.ddl_values(bounded(directory / (name + '.stdout')).decode('utf-8'), obj['type'], path)
    return out


def row_runs(rows):
    """Ascending rows as (first, length) runs of consecutive rows."""
    runs = []
    for r in rows:
        if runs and runs[-1][0] + runs[-1][1] == r:
            runs[-1][1] += 1
        else:
            runs.append([r, 1])
    return runs


def retained_reading(directory, name):
    """Rebuild a retained independent reading: XML plus the retained DDL reads of virtual datasets, in the same order."""
    xml = h5xml.parse(bounded(directory / (name + '.stdout')))
    null_spaces(None, directory, name, None, None, None, xml, retained=True)
    index = 0
    for path, rec in sorted(xml['objects'].items()):
        if rec.get('kind') != 'dataset' or rec.get('layout') != 'unknown' or rec.get('values') is not None or rec['type']['class'] not in ('int', 'uint', 'float'):
            continue
        rec['values'] = h5xml.ddl_values(bounded(directory / ('%s-vds-%d.stdout' % (name, index))).decode('utf-8'), rec['type'], path)
        rec['layout'] = 'virtual'
        index += 1
    return xml


def virtual_values(paths, directory, name, target, deadline, driver, xml):
    """h5dump XML prints no data for virtual datasets; read their numeric values through h5dump DDL instead."""
    index = 0
    for path, rec in sorted(xml['objects'].items()):
        if rec.get('kind') != 'dataset' or rec.get('layout') != 'unknown' or rec.get('values') is not None:
            continue
        if rec['type']['class'] not in ('int', 'uint', 'float'):
            continue
        stage_name = '%s-vds-%d' % (name, index)
        index += 1
        command = [paths['h5dump'], '--no-compact-subset', '-d', path, '-m', '%.17g', '-y', '-w', '0', *(['--filedriver=' + driver] if driver else []), target]
        try:
            execute(command, directory, stage_name, deadline - time.monotonic(), environment(directory))
        except SchemaxisError as error:
            if error.fault.code != 'RUNNER_FAILED':
                raise
            fail('VERIFICATION_FAILED', 'the independent h5dump consumer could not read a virtual dataset', path)
        rec['values'] = h5xml.ddl_values(bounded(directory / (stage_name + '.stdout')).decode('utf-8'), rec['type'], path)
        rec['layout'] = 'virtual'


def h5ls_storage(paths, directory, target, deadline, name):
    """Independent storage facts: h5ls -v logical and allocated bytes per dataset (admitted file only)."""
    import re as _re
    admit(paths, directory, target, deadline)
    tool = os.path.join(os.path.dirname(paths['h5dump']), 'h5ls')
    try:
        execute([tool, '-v', '-r', target], directory, name, deadline - time.monotonic(), environment(directory))
    except SchemaxisError as error:
        if error.fault.code != 'RUNNER_FAILED':
            raise
        fail('VERIFICATION_FAILED', 'the independent h5ls consumer could not read the file', name)
    out, current = {}, None
    for line in bounded(directory / (name + '.stdout')).decode('utf-8', 'replace').splitlines():
        m = _re.match(r'^(/(?:\\.|[^\s\\])*)\s+(\S+)', line)
        if m:
            current = h5ls_name(m.group(1)) if m.group(2) == 'Dataset' else None
            continue
        m = _re.match(r'^\s+Storage:\s+(\d+) logical bytes, (\d+) allocated bytes', line)
        if m and current:
            out[current] = (int(m.group(1)), int(m.group(2)))
    return out


def h5ls_name(text):
    """Undo h5ls name escaping: backslash-octal bytes and backslash-quoted characters, decoded as UTF-8."""
    out, i = bytearray(), 0
    while i < len(text):
        c = text[i]
        if c == '\\' and len(text[i + 1:i + 4]) == 3 and all(ch in '01234567' for ch in text[i + 1:i + 4]):
            out.append(int(text[i + 1:i + 4], 8))
            i += 4
        elif c == '\\' and i + 1 < len(text):
            out += text[i + 1].encode('utf-8')
            i += 2
        else:
            out += c.encode('utf-8')
            i += 1
    return out.decode('utf-8', 'replace')


def storage_agreement(readback, storage):
    for path, rec in readback['objects'].items():
        if rec.get('kind') != 'dataset' or rec.get('layout') in ('virtual', 'external') or path not in storage:
            continue
        if storage[path] != (rec.get('logicalBytes'), rec.get('storageBytes')):
            fail('VERIFICATION_FAILED', 'h5ls and h5py disagree about logical or allocated storage', path, h5ls=list(storage[path]),
                 h5py=[rec.get('logicalBytes'), rec.get('storageBytes')])


def h5dump_version(paths, directory, deadline):
    execute([paths['h5dump'], '--version'], directory, 'h5dump-version', deadline - time.monotonic(), environment(directory))
    text = bounded(directory / 'h5dump-version.stdout').decode('utf-8', 'replace').strip()
    if text != H5DUMP:
        fail('INTERPRETER_NOT_FOUND', 'the independent consumer must be HDF Group h5dump 2.2.0', '$.runtime.h5dump', observed=text[:80])
    tool = os.path.join(os.path.dirname(paths['h5dump']), 'h5ls')
    if not os.access(tool, os.X_OK):
        fail('INTERPRETER_NOT_FOUND', 'the HDF Group h5ls 2.2.0 tool must sit beside h5dump', '$.runtime.h5dump')
    execute([tool, '--version'], directory, 'h5ls-version', deadline - time.monotonic(), environment(directory))
    if bounded(directory / 'h5ls-version.stdout').decode('utf-8', 'replace').strip() != 'h5ls: Version 2.2.0':
        fail('INTERPRETER_NOT_FOUND', 'the h5ls beside h5dump must be HDF Group h5ls 2.2.0', '$.runtime.h5dump')
    return text


# ------------------------------------------------------------------ capture
def capture(p, directory):
    captured, records = {}, []
    for item in p.get('inputs', []):
        data = bounded(item['path'], 'INVALID_HDF5_INPUT', model.MAX_INPUT_BYTES)
        if 'sha256' in item and sha(data) != item['sha256']:
            fail('HDF5_INPUT_CHANGED', 'the input bytes differ from the declared sha256', '$.inputs.' + item['id'])
        name = 'input-%s.%s' % (item['id'], item['format'])
        (directory / name).write_bytes(data)
        captured[item['id']] = data
        records.append({'id': item['id'], 'path': item['path'], 'file': name, 'bytes': len(data), 'sha256': sha(data)})
    for item in p.get('dependencies', []):
        data = bounded(item['path'], 'INVALID_HDF5_DEPENDENCY', model.MAX_SOURCE_BYTES)
        if 'sha256' in item and sha(data) != item['sha256']:
            fail('HDF5_INPUT_CHANGED', 'the dependency bytes differ from the declared sha256', '$.dependencies.' + item['id'])
        (directory / item['name']).write_bytes(data)
        captured['dep:' + item['id']] = data
        records.append({'id': item['id'], 'path': item['path'], 'file': item['name'], 'bytes': len(data), 'sha256': sha(data), 'role': item['role']})
    for key in ('source', 'reference'):
        if key in p:
            data = bounded(p[key], 'INVALID_HDF5_SOURCE', model.MAX_SOURCE_BYTES)
            want = p.get('sha256' if key == 'source' else 'referenceSha256')
            if want and sha(data) != want:
                fail('HDF5_INPUT_CHANGED', 'the %s bytes differ from the declared sha256' % key, '$.' + key)
            if data[:8] != b'\x89HDF\r\n\x1a\n' and not any(data[o:o + 8] == b'\x89HDF\r\n\x1a\n' for o in (512, 1024, 2048, 4096, 8192, 16384) if o < len(data)):
                fail('INVALID_HDF5_SOURCE', 'the %s is not an HDF5 file (no superblock signature)' % key, '$.' + key)
            name = key + '.h5'
            (directory / name).write_bytes(data)
            records.append({'id': key, 'path': p[key], 'file': name, 'bytes': len(data), 'sha256': sha(data)})
    atomic_json(directory / 'capture.json', {'captured': records})
    return captured


def captured_bytes(directory, p):
    out = {}
    for item in p.get('inputs', []):
        out[item['id']] = bounded(directory / ('input-%s.%s' % (item['id'], item['format'])))
    for item in p.get('dependencies', []):
        out['dep:' + item['id']] = bounded(directory / item['name'], limit=model.MAX_SOURCE_BYTES)
    return out


# ------------------------------------------------------------------ host values
def host_values(p, captured):
    """Independent element values for every dataset and attribute payload (createFile/writeMeshFields)."""
    parsed, values = {}, {}
    inputs = {i['id']: i for i in p.get('inputs', [])}
    for i, o in enumerate(p['objects']):
        if o['kind'] != 'dataset' or 'data' not in o:
            continue
        if o['data']['source'] == 'external':
            values[o['path']] = external_values(o, captured, {d['id']: d for d in p.get('dependencies', [])}, f'$.objects[{i}]')
            continue
        v = operations.data_values(o['data'], o['type'], o['shape'], f'$.objects[{i}].data', captured, parsed, inputs)
        if v is not None:
            values[o['path']] = v
    return values


def external_values(o, captured, dependencies, at):
    t = model.resolved(o['type'])
    if t['class'] not in ('int', 'uint', 'float'):
        fail('INVALID_HDF5_STORAGE', 'existing raw storage holds fixed-size integer or float elements', at + '.type')
    data = b''
    for seg in o['storage']['external']:
        raw = captured['dep:' + seg['file']]
        if seg['offset'] + seg['size'] > len(raw):
            fail('INVALID_HDF5_STORAGE', 'an external segment extends beyond its raw dependency file', at + '.storage.external', file=seg['file'], bytes=len(raw))
        data += raw[seg['offset']:seg['offset'] + seg['size']]
    n = model.element_count(o['shape'])
    item = {'type': t, 'shape': o['shape'], 'offset': 0}
    return [model.check_element(v, t, at) for v in expect.parse_raw(data, item, at)[:n]]


def dependency_states(p, directory, paths, deadline):
    out = {}
    for d in p.get('dependencies', []):
        if d['role'] in ('virtualSource', 'copySource'):
            _, dxml, dstate = source_state(directory, paths, deadline, d['name'], d['id'])
            agreement(dstate, dxml)
            out[d['id']] = dstate
    return out


def native_objects(p, values):
    objects = []
    for o in p['objects']:
        item = json.loads(json.dumps(o))
        if o['path'] in values:
            item['payload'] = 'o%d' % len(objects)
        objects.append(item)
    return objects


def write_payloads(directory, p, values, objects):
    for o, item in zip(p['objects'], objects):
        if 'payload' in item:
            atomic_json(directory / ('payload-%s.json' % item['payload']), [operations.payload_value(v, o['type']) for v in values[o['path']]])


# ------------------------------------------------------------------ run
def run(document, directory, *, executable=None, h5dump=None, mpiPython=None, mpiexec=None, timeout=300):
    p = plan(document)
    paths = runtime(executable, h5dump)
    if p['operation'] == 'parallelWrite' or p.get('parallel'):
        paths.update(mpi_runtime(mpiPython, mpiexec))
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        fail('INVALID_ARGUMENT', 'timeout must be finite and in (0,3600]')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        fail('OUTPUT_EXISTS', 'select a fresh output directory', str(directory))
    directory.mkdir(parents=True)
    deadline = time.monotonic() + timeout
    atomic_json(directory / 'authored.json', document)
    atomic_json(directory / 'plan.json', p)
    atomic_json(directory / 'result.json', {'status': 'incomplete', 'verified': False})
    try:
        captured = capture(p, directory)
        (directory / 'native-worker.py').write_text(worker_source())
        atomic_json(directory / 'implementation.json', implementation())
        tool = h5dump_version(paths, directory, deadline)
        report = RUNNERS[p['operation']](p, directory, paths, deadline, captured)
        report['runtime'] = {'native': RUNTIME, 'independentConsumer': tool}
        atomic_json(directory / 'hdf5-report.json', report)
        atomic_json(directory / 'verification.json', {'artifacts': artifacts(directory, p),
                                                       'evidence': {name: digest(directory, name) for name in sorted(evidence_names(directory, p))},
                                                       'runtime': RUNTIME, 'independentConsumer': tool})
        result = verify_directory(directory, paths, require_result=False)
        if cancellation_requested():
            fail('RUNNER_CANCELLED', 'HDF5 run cancelled')
        if time.monotonic() >= deadline:
            fail('RUNNER_TIMED_OUT', 'HDF5 run exhausted its total deadline')
        result['status'] = 'succeeded'
        atomic_json(directory / 'result.json', result)
        return result
    except Exception as error:
        if not isinstance(error, SchemaxisError):
            try:
                fail('NATIVE_EXECUTION_FAILED', str(error)[:400])
            except SchemaxisError as wrapped:
                error = wrapped
        atomic_json(directory / 'result.json', {'status': 'failed', 'verified': False, 'fault': error.fault.to_dict()})
        raise error


def driver_arguments(f):
    if f['driver'] == 'family':
        return 'family', f['name'].rsplit('.', 1)[0] + '-%d.h5'
    if f['driver'] == 'split':
        return 'split', f['name'].rsplit('.', 1)[0]
    return None, f['name']


def run_create(p, directory, paths, deadline, captured):
    values = host_values(p, captured)
    deps = dependency_states(p, directory, paths, deadline)
    expected = state.expected_create(p, values, deps)
    atomic_json(directory / 'expected-state.json', expected)
    objects = native_objects(p, values)
    write_payloads(directory, p, values, objects)
    config = {'file': p['file'], 'objects': objects, 'links': p['links'],
              'dependencies': {d['id']: {'name': d['name']} for d in p['dependencies']},
              'manifests': {'readback': {'file': driver_arguments(p['file'])[1], 'fileSettings': p['file']}}}
    if p.get('mesh'):
        config['mesh'] = p['mesh']['native']
    atomic_json(directory / 'native-config.json', config)
    stage(paths, directory, 'build', deadline)
    return check_output(p, directory, paths, deadline, expected)


def check_output(p, directory, paths, deadline, expected):
    readback = stage(paths, directory, 'readback', deadline)
    state.compare_readback(expected, readback)
    driver, target = driver_arguments(p['file'])
    total = sum(len(o.get('values') or []) for o in expected['objects'].values() if o['kind'] == 'dataset')
    xml = dump(paths, directory, 'h5dump-output', target, deadline, driver, values=total <= XML_ELEMENT_BUDGET)
    state.compare_xml(expected, xml)
    check_file_settings(p['file'], readback['file'])
    check_alignment(p.get('access'), readback)
    report = create_report(p, directory, expected, readback['file']['superblock'])
    if p.get('extracts'):
        report['extracts'] = run_extracts(p, directory, paths, deadline, expected, driver_arguments(p['file'])[1])
    if p.get('mesh'):
        from . import meshes
        report['xdmf'] = meshes.check_xdmf(p, directory, expected)
    return report


def netcdf4_view(expected):
    """Whether NetCDF-4 readers (netCDF-C, h5netcdf/xarray) can present every dataset with named dimensions."""
    reasons = []
    for path, rec in sorted(expected['objects'].items()):
        if rec['kind'] != 'dataset' or not rec.get('dims'):
            continue
        scaled = [bool(d['scales']) for d in rec['dims']]
        if any(scaled) and not all(scaled):
            reasons.append('%s mixes axes with and without dimension scales' % path)
        if rec['type']['class'] in ('compound', 'vlen', 'reference', 'opaque', 'complex', 'enum', 'bool') and any(scaled):
            reasons.append('%s has an element type outside the classic NetCDF-4 numeric/string set' % path)
    for path, link in sorted(expected['links'].items()):
        if link['kind'] == 'external':
            reasons.append('%s is an external link; NetCDF-4 readers that traverse the file need its target' % path)
    return {'namedDimensions': not reasons, 'reasons': reasons}


def check_alignment(access, readback, consumer='readback'):
    """With declared alignment, every contiguous dataset at least threshold bytes long starts on an interval boundary."""
    if not access or not access.get('alignment'):
        return
    a = access['alignment']
    for path, rec in readback['objects'].items():
        if rec.get('kind') == 'dataset' and rec.get('offset') is not None and rec.get('storageBytes', 0) >= a['threshold'] and rec['offset'] % a['interval']:
            fail('VERIFICATION_FAILED', consumer + ': dataset storage is not aligned to the declared interval', path, offset=rec['offset'], interval=a['interval'])


def check_file_settings(f, observed):
    if observed['userblock'] != f['userblock']:
        fail('VERIFICATION_FAILED', 'readback: user block size differs', '$.file.userblock', expected=f['userblock'], observed=observed['userblock'])
    allowed = {'earliest': (0, 2), 'v108': (2,)}.get(f['libver'], (3,))
    if observed['superblock'] not in allowed:
        fail('VERIFICATION_FAILED', 'readback: superblock version does not honour the low library-version bound', '$.file.libver',
             expected=list(allowed), observed=observed['superblock'])


# ------------------------------------------------------------------ extraction
def extract_selection(paths, directory, target, e, obj, observed, deadline):
    """Normal-form selection, selected shape and element count of one extract (where rows decided from the independent reading)."""
    at = '$.extracts.' + e['id']
    if 'where' not in e:
        return model.selection(e['selection'] if e['selection']['kind'] != 'slices' else slices_record(e['selection']), obj['shape'], at + '.selection')
    if not obj['shape']:
        fail('INVALID_HDF5_EXTRACT', 'where chooses axis-0 rows; the extracted dataset is a scalar', at + '.where')
    selected = where_rows(paths, directory, target, e, obj, observed, deadline)
    shape = [len(selected), *obj['shape'][1:]]
    return {'kind': 'rows', 'rows': selected}, shape, model.element_count(shape)


def where_rows(paths, directory, target, e, obj, observed, deadline):
    from . import predicates
    conditions, columns = [], []
    for j, c in enumerate(e['where']):
        at = '$.extracts.%s.where[%d]' % (e['id'], j)
        cond = observed['objects'].get(c['dataset'])
        t = predicates.condition_type(c, cond, obj['shape'][0], at)
        values = selected_values(paths, directory, target, c['dataset'], cond, {'kind': 'all'}, deadline, at)
        if 'field' in c:
            index = [f['name'] for f in model.resolved(cond['type'])['fields']].index(c['field'])
            values = [v[index] for v in values]
        if t['class'] == 'enum':
            codes = {m['name']: m['value'] for m in t['members']}
            c = {**c, **({'value': codes[c['value']]} if 'value' in c else {}), **({'values': [codes[v] for v in c['values']]} if 'values' in c else {})}
        conditions.append(c)
        columns.append([predicates.decode(v, t) for v in values])
    return predicates.rows(conditions, columns, obj['shape'][0])


def run_extracts(p, directory, paths, deadline, expected, target):
    items = []
    for e in p['extracts']:
        obj = expected['objects'].get(e['dataset'])
        if obj is None or obj['kind'] != 'dataset':
            fail('INVALID_HDF5_EXTRACT', 'the extracted path is not a dataset in the file', '$.extracts.' + e['id'], path=e['dataset'])
        if obj.get('null'):
            fail('INVALID_HDF5_EXTRACT', 'the dataset has a null dataspace: it holds no elements to select or extract', '$.extracts.' + e['id'] + '.dataset')
        if 'selectedShape' not in e:
            sel, shape, count = extract_selection(paths, directory, target, e, obj, expected, deadline)
            e = {**e, 'selection': sel, 'selectedShape': shape, 'count': count}
            operations.check_extract_type(e, obj['type'], '$.extracts.' + e['id'])
        if e['format'] == 'chunks':
            from . import chunks
            chunks.check_indexable(obj, '$.extracts.' + e['id'])
        item = dict(e)
        item['headers'] = headers(e, obj, expected)
        if e['coordinates'] and e['format'] == 'csv' and obj['dims'] and obj['dims'][0]['scales'] and len(e['selectedShape']) >= 1:
            scale = expected['objects'][obj['dims'][0]['scales'][0]]
            if scale['shape'] != obj['shape'][:1]:
                fail('INVALID_HDF5_EXTRACT', 'the axis-0 dimension scale no longer matches the axis length; extend the scale or set coordinates false',
                     '$.extracts.' + e['id'] + '.coordinates', axis=obj['shape'][0], scale=scale['shape'][0])
            item['coordinateScales'] = {'0': obj['dims'][0]['scales'][0]}
            item['coordinateType'] = expected['objects'][obj['dims'][0]['scales'][0]]['type']
            item['coordinateSelection'] = axis_selection(e['selection'], 0)
        plan_blocks(p, item, obj, '$.extracts.' + e['id'])
        item['datasetShape'] = obj['shape']
        items.append(item)
    config = read(directory, 'native-config.json') if (directory / 'native-config.json').is_file() else {}
    config.update(source=target, extracts=items, **({'io': p['parallel']['io']} if p.get('parallel') else {}))
    atomic_json(directory / 'native-config.json', config)
    if p.get('parallel'):
        from . import parallel
        admit(paths, directory, target, deadline)
        observed = parallel.mpi_stage(paths, directory, 'mpi-extract', deadline, p['parallel']['ranks'])['result']['extracts']
        parallel.check_extract_ranks(directory, p, items)
    else:
        observed = stage(paths, directory, 'extract', deadline)['extracts']
    report = []
    for item, got in zip(items, observed):
        obj = expected['objects'][item['dataset']]
        if item['format'] == 'chunks':
            check_chunk_extract(paths, directory, target, item, obj, deadline, got)
            continue
        want = selected_values(paths, directory, target, item['dataset'], obj, item['selection'], deadline, '$.extracts.' + item['id'])
        want_type = obj['type']
        if 'fields' in item:
            names = [f['name'] for f in obj['type']['fields']]
            pick = [names.index(n) for n in item['fields']]
            want = [[rec[j] for j in pick] if len(pick) > 1 else rec[pick[0]] for rec in want]
            want_type = {'class': 'compound', 'fields': [obj['type']['fields'][j] for j in pick]} if len(pick) > 1 else obj['type']['fields'][pick[0]]['type']
        d = expect.Digest()
        for v in want:
            d.add(v)
        mine = d.result()
        if 'where' in item:
            check_where(item, got.get('whereRows'))
        if got['values']['count'] != mine['count'] or got['values']['sha256'] != mine['sha256'] or got['shape'] != item['selectedShape']:
            fail('VERIFICATION_FAILED', 'extracted values differ from the independently selected values', '$.extracts.' + item['id'])
        if item.get('blocks'):
            stream = got.get('streaming') or {}
            cache = (p['access'].get('chunkCache') or {}).get('bytes', 1024 ** 2)
            bound = 16 * 1024 ** 2 + 4 * p['access']['memoryBytes'] + cache + p['access'].get('sieveBufferBytes', 65536)
            if stream.get('blocks') != len(item['blocks']) or stream.get('largestBlockBytes', 2 ** 62) > p['access']['memoryBytes'] \
                    or stream.get('peakGrowthBytes', 2 ** 62) > bound:
                fail('VERIFICATION_FAILED', 'the extraction did not stay within the declared memory blocks', '$.extracts.' + item['id'], observed=stream)
        coords = None
        if 'coordinateScales' in item:
            scale_path = item['coordinateScales']['0']
            coords = selected_values(paths, directory, target, scale_path, expected['objects'][scale_path], item['coordinateSelection'], deadline,
                                     '$.extracts.' + item['id'] + '.coordinates')
        check_extract_file(directory, item, want, want_type, obj, expected, coords)
    return extracts_report(directory, p['extracts'], expected, p, {item['id']: item['selection'] for item in items})


def check_chunk_extract(paths, directory, target, item, obj, deadline, native=None):
    """A chunk index is checked against the stored bytes it points to, the independent values and h5ls's allocated size."""
    from . import chunks
    values = selected_values(paths, directory, target, item['dataset'], obj, {'kind': 'all'}, deadline, '$.extracts.' + item['id'])
    allocated = h5ls_storage(paths, directory, target, deadline, 'h5ls-chunks-' + item['id']).get(item['dataset'], (None, None))[1]
    summary = chunks.check(directory, target, item, obj, values, allocated)
    if native is not None and native.get('chunks') != summary['count']:
        fail('VERIFICATION_FAILED', 'the native chunk count differs from the published index', '$.extracts.' + item['id'])
    listing = chunk_listing(paths, directory, target, item['dataset'], 'chunk-list-' + item['id'], deadline)
    chunks.check_listing(json.loads(bounded(directory / item['output'])), listing, item['output'])
    return summary


def chunk_listing(paths, directory, target, dataset, name, deadline):
    """HDF5's own chunk records for one dataset of current bytes, from a fresh h5py process (after admission)."""
    config = read(directory, 'native-config.json') if (directory / 'native-config.json').is_file() else {}
    config.setdefault('chunkLists', {})[name] = {'file': target, 'dataset': dataset}
    atomic_json(directory / 'native-config.json', config)
    return stage(paths, directory, name, deadline)


def check_where(item, native):
    """The rows h5py chose for the where conditions equal the rows chosen from the independent reading."""
    from . import predicates
    if native != predicates.digest(item['selection']['rows']):
        fail('VERIFICATION_FAILED', 'h5py and the independent reading chose different rows for where', '$.extracts.' + item['id'] + '.where',
             expected=predicates.digest(item['selection']['rows']), observed=native)


def slices_record(sel):
    return {'kind': 'slices', 'slices': [{k: v for k, v in zip(('start', 'stop', 'step'), s) if v is not None} for s in sel['slices']]}


def axis_selection(sel, axis):
    if sel['kind'] == 'all':
        return {'kind': 'all'}
    if sel['kind'] == 'slices':
        return {'kind': 'slices', 'slices': [sel['slices'][axis]]}
    if sel['kind'] == 'hyperslab':
        return {'kind': 'hyperslab', **{k: [sel[k][axis]] for k in ('start', 'count', 'stride', 'block')}}
    if sel['kind'] == 'rows':
        return {'kind': 'rows', 'rows': sel['rows']}
    return {'kind': 'points', 'points': [[q[axis]] for q in sel['points']]}


def headers(e, obj, expected):
    t = obj['type']
    name = e['dataset'].rsplit('/', 1)[1]
    units = obj['attributes'].get('units', {}).get('values') if e.get('header', 'units') == 'units' else None
    coord = []
    if e['coordinates'] and obj['dims'] and obj['dims'][0]['scales']:
        scale = expected['objects'][obj['dims'][0]['scales'][0]]
        su = scale['attributes'].get('units', {}).get('values') if e.get('header', 'units') == 'units' else None
        coord = [obj['dims'][0]['scales'][0].rsplit('/', 1)[1] + (' [%s]' % su[0] if su else '')]
    if t['class'] == 'compound':
        body = list(e.get('fields', [f['name'] for f in t['fields']]))
    elif len(e['selectedShape']) <= 1:
        body = [name + (' [%s]' % units[0] if units else '')]
    else:
        width = 1
        for s in e['selectedShape'][1:]:
            width *= s
        body = e.get('columns') or ['%s_%d' % (name, j) for j in range(width)]
        if len(body) != width:
            fail('INVALID_HDF5_EXTRACT', 'columns gives one header per selected column', '$.extracts.' + e['id'] + '.columns', columns=width)
    return coord + body


def check_extract_file(directory, item, want, want_type, obj, expected, coords=None):
    data = bounded(directory / item['output'])
    if item['format'] == 'json':
        doc = json.loads(data)
        if doc.get('values') != [expect.natural(v, want_type) for v in want] or doc.get('shape') != item['selectedShape']:
            fail('VERIFICATION_FAILED', 'JSON extract differs from the selected values', item['output'])
        return
    if item['format'] == 'npy':
        t, shape, values = expect.parse_npy(data, item['output'])
        if shape != item['selectedShape'] or [expect.canonical(v, want_type) for v in values] != want:
            fail('VERIFICATION_FAILED', 'NPY extract differs from the selected values', item['output'])
        return
    header, rows = expect.parse_csv(data, ',', item['output'])
    if header != item['headers']:
        fail('VERIFICATION_FAILED', 'CSV extract header differs', item['output'], expected=item['headers'], observed=header)
    offset = 1 if 'coordinateScales' in item else 0
    cells = []
    if want_type['class'] == 'compound':
        for r in rows:
            cells.append([expect.canonical(expect.csv_cell(c, f['type'], item['output']), f['type']) for c, f in zip(r[offset:], want_type['fields'])])
    else:
        for r in rows:
            cells.extend(expect.canonical(expect.csv_cell(c, want_type, item['output']), want_type) for c in r[offset:])
    if cells != want:
        fail('VERIFICATION_FAILED', 'CSV extract cells differ from the selected values', item['output'])
    if offset:
        scale = expected['objects'][item['coordinateScales']['0']]
        if coords is None:
            coords = [scale['values'][i] for i in state.indices(item['coordinateSelection'], scale['shape'])]
        if len(item['selectedShape']) == 1 or want_type['class'] == 'compound':
            pass
        got = [expect.canonical(expect.csv_cell(r[0], scale['type'], item['output']), scale['type']) for r in rows]
        if got != coords:
            fail('VERIFICATION_FAILED', 'CSV coordinate column differs from the dimension scale', item['output'])


# ------------------------------------------------------------------ inspect / extract / compare
def source_state(directory, paths, deadline, name='source.h5', label='source'):
    config = read(directory, 'native-config.json') if (directory / 'native-config.json').is_file() else {}
    config.setdefault('manifests', {})['inspect-' + label] = {'file': name}
    atomic_json(directory / 'native-config.json', config)
    readback = stage(paths, directory, 'inspect-' + label, deadline)
    xml = dump(paths, directory, 'h5dump-' + label, name, deadline, values=within_budget(readback))
    return readback, xml, state_from(readback, xml)


def within_budget(readback):
    total = sum((o.get('values') or {}).get('count', 0) for o in readback['objects'].values() if o['kind'] == 'dataset')
    return total <= XML_ELEMENT_BUDGET


def state_from(readback, xml):
    """Observed state of an existing file: h5py readback for metadata, h5dump XML for literal values."""
    objects, links = {}, {}
    for path, rec in readback['objects'].items():
        out = {'kind': rec['kind'], 'attributes': {k: v for k, v in rec['attributes'].items() if k not in state.RESERVED}}
        if rec['kind'] == 'datatype':
            out['type'] = rec['type']
        if 'trackOrder' in rec and path != '/':
            out['trackOrder'] = rec['trackOrder']
        if rec.get('attributeOrder') is not None:
            out['attributeOrder'] = list(rec['attributeOrder'])
        if rec['kind'] == 'dataset':
            out.update({k: rec.get(k) for k in ('type', 'shape', 'maxshape', 'layout', 'chunks', 'scale', 'dims')})
            if rec.get('null'):
                out['null'] = True
            out['filters'] = sorted(f['name'] for f in rec['filters'])
            out['chunks'] = rec['chunks'] if rec['layout'] == 'chunked' else None
            if rec.get('fillDefined') and 'fill' in rec:
                out['fill'] = rec['fill']
            out['defaultFill'] = rec.get('fill', expect.canonical(expect.default_fill(rec['type']), rec['type']) if rec['type']['class'] not in ('reference',) else None)
            if 'external' in rec:
                out['external'] = rec['external']
            if rec.get('committedType') and rec.get('typeAddress') is not None:
                out['committedTypeAddress'] = rec['typeAddress']
            x = xml['objects'].get(path)
            if x is not None and x.get('kind') == 'alias':
                x = xml['objects'].get(x['of'])
            out['values'] = list(x['values']) if x is not None and x.get('values') is not None and rec['type']['class'] not in ('reference',) else None
            if out['values'] is None:
                out['digest'] = {k: (rec.get('values') or {}).get(k) for k in ('count', 'sha256')}
            elif rec.get('values'):
                out['readbackDigest'] = {k: rec['values'].get(k) for k in ('count', 'sha256')}
            if rec['type']['class'] == 'reference':
                out['observedTargets'] = rec.get('targets') or []
        objects[path] = out
    aliases, canonical_path = {}, {}
    for address, paths in readback.get('addresses', {}).items():
        canonical_path[address] = sorted(paths)[0]
        for path in sorted(paths)[1:]:
            aliases[path] = sorted(paths)[0]
    for rec in objects.values():
        for d in rec.get('dims') or []:
            d['scales'] = [canonical_path.get(x, x) for x in d['scales']]
        if 'committedTypeAddress' in rec:
            rec['committedType'] = canonical_path.get(rec.pop('committedTypeAddress'))
        if 'observedTargets' in rec:
            refs = []
            for t in rec.pop('observedTargets'):
                if t is None:
                    refs.append(None)
                elif t.get('unresolved') or t.get('address') not in canonical_path:
                    refs.append({'unresolved': True})
                else:
                    refs.append({'path': canonical_path[t['address']], **({'points': sorted(t['points'])} if 'points' in t else {})})
            rec['references'] = refs
            rec.pop('digest', None)
    for path, rec in readback['links'].items():
        links[path] = {k: v for k, v in rec.items() if k in ('kind', 'target', 'file')}
    for path, first in aliases.items():
        links[path] = {'kind': 'hard', 'target': first}
    return {'objects': objects, 'links': links}


def run_inspect(p, directory, paths, deadline, captured):
    readback, xml, observed = source_state(directory, paths, deadline)
    agreement(observed, xml)
    storage_agreement(readback, h5ls_storage(paths, directory, 'source.h5', deadline, 'h5ls-source'))
    independent = independent_values(paths, directory, 'source.h5', observed, p['expectations'], deadline)
    decisions = [decide(e, readback, observed, independent) for e in p['expectations']]
    inventory = inventory_of(readback, p['preview'])
    atomic_json(directory / 'inventory.json', inventory)
    met = sum(1 for d in decisions if d['decision'] == 'met')
    unmet = sum(1 for d in decisions if d['decision'] == 'unmet')
    atomic_json(directory / 'expectations.json', {'decisions': decisions, 'met': met, 'unmet': unmet, 'indeterminate': len(decisions) - met - unmet})
    return {'operation': 'inspectFile', 'objects': len(readback['objects']), 'links': len(readback['links']),
            'expectations': {'met': met, 'unmet': unmet, 'indeterminate': len(decisions) - met - unmet}, 'superblock': readback['file']['superblock']}


def inventory_of(readback, preview):
    inventory = {'file': readback['file'], 'objects': {}, 'links': readback['links']}
    for path, rec in sorted(readback['objects'].items()):
        item = {k: rec.get(k) for k in ('kind', 'type', 'shape', 'maxshape', 'layout', 'chunks', 'scale', 'dims', 'external', 'virtual', 'stats', 'allocatedChunks', 'null') if rec.get(k) is not None}
        item['filters'] = [f['name'] for f in rec.get('filters', [])] if rec['kind'] == 'dataset' else None
        item['attributes'] = {k: {'type': v['type'], **({'empty': True} if v.get('empty') else {'shape': v['shape'], 'values': v['values'][:preview]})} for k, v in rec['attributes'].items()}
        if rec['kind'] == 'dataset' and rec.get('values'):
            item['values'] = {'count': rec['values']['count'], 'sha256': rec['values']['sha256'], 'preview': rec['values']['head'][:preview]}
        if rec['kind'] == 'dataset':
            item['storage'] = {'logicalBytes': rec.get('logicalBytes'), 'allocatedBytes': rec.get('storageBytes'),
                               **({'chunks': rec['chunkStats']} if rec.get('chunkStats') else {})}
        inventory['objects'][path] = {k: v for k, v in item.items() if v is not None}
        if rec.get('null'):
            inventory['objects'][path].update(shape=None, maxshape=None)
    aliases = {a: paths for a, paths in readback['addresses'].items() if len(paths) > 1}
    inventory['hardLinkGroups'] = sorted(aliases.values())
    return inventory


def fresh_manifest(paths, scratch, name, target, deadline, settings=None, regions=None):
    """A fresh h5py manifest of current bytes in the verification scratch (admitted first); never a retained one."""
    config = read(scratch, 'native-config.json') if (scratch / 'native-config.json').is_file() else {}
    config.setdefault('manifests', {})[name] = {'file': target, 'fileSettings': settings, **({'regions': regions} if regions else {})}
    atomic_json(scratch / 'native-config.json', config)
    return stage(paths, scratch, name, deadline)


def fresh_source(paths, directory, scratch, name, label, deadline):
    """Fresh h5py and h5dump readings of one captured file, with the retained h5dump reading as a further equality check."""
    if not (scratch / name).is_file():
        shutil.copyfile(directory / name, scratch / name)
    rb = fresh_manifest(paths, scratch, 'inspect-' + label, name, deadline)
    xml = dump(paths, scratch, 'h5dump-fresh-' + label, name, deadline, values=within_budget(rb))
    if (directory / ('h5dump-%s.stdout' % label)).is_file() and xml != retained_reading(directory, 'h5dump-' + label):
        fail('VERIFICATION_FAILED', 'the captured %s no longer matches its retained independent reading' % label)
    return rb, xml, state_from(rb, xml)


def host_stats(values, t):
    """Count, finite count, minimum and maximum from independent canonical values (h5dump), not from the h5py readback."""
    if t['class'] == 'float':
        numbers = [float.fromhex(v) if isinstance(v, str) else float(v) for v in values]
        finite = [x for x in numbers if math.isfinite(x)]
    else:
        finite = list(values)
    return {'count': len(values), 'finite': len(finite), 'minimum': min(finite) if finite else None, 'maximum': max(finite) if finite else None}


def independent_values(paths, directory, target, observed, expectations, deadline):
    """Independent (h5dump) values of every dataset a range/finiteness expectation names, within the per-dataset bound."""
    out = {}
    for e in expectations:
        if not any(key in e for key in ('minimum', 'maximum', 'finite')) or e['path'] in out:
            continue
        obj = observed['objects'].get(e['path'])
        if obj is None or obj['kind'] != 'dataset' or obj['type']['class'] not in ('int', 'uint', 'float') or obj['type'].get('dims'):
            continue
        if obj.get('values') is not None:
            out[e['path']] = obj['values']
        elif model.element_count(obj['shape']) <= model.MAX_ELEMENTS:
            out[e['path']] = selected_values(paths, directory, target, e['path'], obj, {'kind': 'all'}, deadline, '$.expectations.' + e['id'])
    return out


def agreement(observed, xml):
    """The two consumers must agree on what the captured source contains before it is reported."""
    for path, rec in observed['objects'].items():
        x = xml['objects'].get(path)
        if x is None:
            fail('VERIFICATION_FAILED', 'h5dump and h5py disagree about object presence', path)
        if x.get('kind') == 'alias':
            x = xml['objects'].get(x['of'])
        if rec['kind'] == 'dataset':
            xt = h5xml.complex_as_compound(x['type'])
            if not h5xml.same_type(xt, rec['type']) or x['shape'] != rec['shape'] or bool(x.get('null')) != bool(rec.get('null')):
                fail('VERIFICATION_FAILED', 'h5dump and h5py disagree about a dataset type or shape', path, h5py=[rec['type'], rec['shape']], h5dump=[xt, x['shape']])
            if rec.get('values') is not None and rec.get('readbackDigest'):
                d = expect.Digest()
                for v in rec['values']:
                    d.add(v)
                if (d.result()['count'], d.result()['sha256']) != (rec['readbackDigest']['count'], rec['readbackDigest']['sha256']):
                    fail('VERIFICATION_FAILED', 'h5dump and h5py disagree about stored values', path)


def decide(e, readback, observed, independent=None):
    rec = readback['objects'].get(e['path'])
    link = readback['links'].get(e['path'])
    reasons = []
    if not e['present']:
        return {'id': e['id'], 'decision': 'met' if rec is None and link is None else 'unmet', 'reasons': [] if rec is None and link is None else ['present']}
    if rec is None and link is None:
        return {'id': e['id'], 'decision': 'unmet', 'reasons': ['absent']}
    kind = rec['kind'] if rec is not None else link['kind'] + 'Link'
    if 'kind' in e and e['kind'] != kind:
        reasons.append('kind is ' + kind)
    t = (rec or {}).get('type', {})
    if 'class' in e and t.get('class') != e['class']:
        reasons.append('class is %s' % t.get('class'))
    if 'bits' in e and t.get('bits') != e['bits']:
        reasons.append('bits is %s' % t.get('bits'))
    if 'shape' in e and (rec or {}).get('shape') != e['shape']:
        reasons.append('shape is %s' % (rec or {}).get('shape'))
    attrs = (rec or {}).get('attributes', {})
    if 'units' in e and attrs.get('units', {}).get('values') != [e['units']]:
        reasons.append('units are %s' % attrs.get('units', {}).get('values'))
    if 'attribute' in e:
        a = attrs.get(e['attribute'])
        if a is None:
            reasons.append('attribute absent')
        elif 'value' in e:
            want = e['value'] if isinstance(e['value'], list) else [e['value']]
            got = a.get('values')
            if a['type']['class'] == 'float':
                want = [float(v).hex() if isinstance(v, (int, float)) and not isinstance(v, bool) else v for v in want]
            if got != want:
                reasons.append('attribute value is %s' % (got[:8] if got else got))
    if 'compression' in e:
        names = [f['name'] for f in (rec or {}).get('filters', [])]
        present = next((n for n in names if n in ('gzip', 'lzf', 'szip')), 'none')
        if present != e['compression']:
            reasons.append('compression is ' + present)
    if 'minCompressionRatio' in e or 'maxAllocatedBytes' in e:
        if rec is None or rec.get('kind') != 'dataset':
            reasons.append('not a dataset')
        else:
            allocated, logical = rec.get('storageBytes') or 0, rec.get('logicalBytes') or 0
            if 'maxAllocatedBytes' in e and allocated > e['maxAllocatedBytes']:
                reasons.append('allocated bytes %d' % allocated)
            if 'minCompressionRatio' in e:
                if not allocated:
                    return {'id': e['id'], 'decision': 'indeterminate', 'reasons': ['no storage allocated']}
                if logical / allocated < e['minCompressionRatio']:
                    reasons.append('compression ratio %.4g' % (logical / allocated))
    if any(key in e for key in ('minimum', 'maximum', 'finite')):
        values = (independent or {}).get(e['path'])
        if values is None:
            return {'id': e['id'], 'decision': 'indeterminate', 'reasons': ['values exceed the independently read budget or are not numeric']}
        stats = host_stats(values, rec['type'])
        for key in ('minimum', 'maximum'):
            if key in e:
                value = stats[key]
                if value is None:
                    reasons.append(key + ' undefined (no finite values)')
                elif key == 'minimum' and value < e[key] or key == 'maximum' and value > e[key]:
                    reasons.append('%s is %r' % (key, value))
        if 'finite' in e and e['finite'] != (stats['finite'] == stats['count']):
            reasons.append('finite elements %d of %d' % (stats['finite'], stats['count']))
    return {'id': e['id'], 'decision': 'unmet' if reasons else 'met', 'reasons': reasons}


def run_extract(p, directory, paths, deadline, captured):
    readback, xml, observed = source_state(directory, paths, deadline)
    agreement(observed, xml)
    return {'operation': 'extractData', 'extracts': run_extracts(p, directory, paths, deadline, observed, 'source.h5')}


def run_compare(p, directory, paths, deadline, captured):
    left_rb, left_xml, left = source_state(directory, paths, deadline)
    right_rb, right_xml, right = source_state(directory, paths, deadline, 'reference.h5', 'reference')
    agreement(left, left_xml)
    agreement(right, right_xml)
    config = read(directory, 'native-config.json')
    config.update(source='source.h5', reference='reference.h5', tolerance=p['tolerance'], paths=p['tolerance'].get('paths'))
    atomic_json(directory / 'native-config.json', config)
    native = stage(paths, directory, 'compare', deadline)
    mine = host_compare(left, right, p['tolerance'])
    if [(d['path'], d['kind']) for d in native['differences']] != [(d['path'], d['kind']) for d in mine]:
        fail('VERIFICATION_FAILED', 'native and independent comparisons disagree', '$', native=native['differences'][:8], host=mine[:8])
    atomic_json(directory / 'comparison.json', {'equal': not mine, 'differences': mine, 'tolerance': p['tolerance']})
    return {'operation': 'compareFiles', 'equal': not mine, 'differences': len(mine)}


def host_compare(left, right, tol):
    out = []
    paths = tol.get('paths') or sorted(set(left['objects']) | set(right['objects']))
    for path in paths:
        a, b = left['objects'].get(path), right['objects'].get(path)
        if a is None or b is None:
            out.append({'path': path, 'kind': 'presence', 'source': a is not None, 'reference': b is not None})
            continue
        if a['kind'] != b['kind']:
            out.append({'path': path, 'kind': 'objectKind'})
            continue
        if tol['attributes'] and a['attributes'] != b['attributes']:
            out.append({'path': path, 'kind': 'attributes'})
        if a['kind'] != 'dataset':
            continue
        if a['type'] != b['type'] or a['shape'] != b['shape']:
            out.append({'path': path, 'kind': 'typeOrShape'})
            continue
        if tol['storage'] and (a['layout'], a['chunks'], a['filters']) != (b['layout'], b['chunks'], b['filters']):
            out.append({'path': path, 'kind': 'storage'})
        if a['type']['class'] in ('int', 'uint', 'float'):
            if a['values'] is None or b['values'] is None:
                fail('HDF5_RESOURCE_LIMIT', 'compared datasets exceed the independently verified value budget', path)
            bad = 0
            for x, y in zip(a['values'], b['values']):
                fx = float.fromhex(x) if isinstance(x, str) else float(x)
                fy = float.fromhex(y) if isinstance(y, str) else float(y)
                if math.isnan(fx) and math.isnan(fy):
                    continue
                if not abs(fx - fy) <= tol['absolute'] + tol['relative'] * abs(fy):
                    bad += 1
            if bad:
                out.append({'path': path, 'kind': 'values', 'count': bad})
        elif a.get('values') != b.get('values') or a.get('digest') != b.get('digest'):
            out.append({'path': path, 'kind': 'values', 'count': None})
    return out


# ------------------------------------------------------------------ edit
def run_edit(p, directory, paths, deadline, captured):
    from . import editing
    return editing.run(p, directory, paths, deadline, captured)


def run_mesh(p, directory, paths, deadline, captured):
    from . import meshes
    return meshes.run(p, directory, paths, deadline, captured)


def run_series(p, directory, paths, deadline, captured):
    from . import series
    return series.run(p, directory, paths, deadline, captured)


def run_parallel(p, directory, paths, deadline, captured):
    from . import parallel
    return parallel.run(p, directory, paths, deadline, captured)


RUNNERS = {'parallelWrite': run_parallel, 'createFile': run_create, 'inspectFile': run_inspect, 'extractData': run_extract, 'compareFiles': run_compare,
           'editFile': run_edit, 'writeMeshFields': run_mesh, 'appendSeries': run_series}


# ------------------------------------------------------------------ publication and verification
def publications(directory, p):
    op = p['operation']
    out = []
    if op in ('createFile', 'editFile', 'writeMeshFields', 'appendSeries', 'parallelWrite'):
        f = p['file']
        if f['driver'] == 'family':
            stem = f['name'].rsplit('.', 1)[0]
            members = sorted(path.name for path in directory.glob(stem + '-*.h5'))
            out += [(m, 'file') for m in members]
        elif f['driver'] == 'split':
            stem = f['name'].rsplit('.', 1)[0]
            out += [(stem + '-m.h5', 'file'), (stem + '-r.h5', 'file')]
        else:
            out.append((f['name'], 'file'))
        out += [(name, 'file') for name in p.get('rawFiles', [])]
        out += [(d['name'], 'file') for d in p.get('dependencies', []) if d['role'] in ('virtualSource', 'externalLink', 'rawStorage')]
        if op == 'writeMeshFields':
            out.append((p['xdmf'], 'file'))
    if op == 'inspectFile':
        out += [('inventory.json', 'text'), ('expectations.json', 'text')]
    if op == 'compareFiles':
        out.append(('comparison.json', 'text'))
    for e in p.get('extracts', []):
        out.append((e['output'], 'table' if e['format'] == 'csv' else 'file'))
    out.append(('hdf5-report.json', 'text'))
    return out


def artifacts(directory, p):
    return [{'file': str(directory / name), 'kind': kind, 'sha256': digest(directory, name)} for name, kind in publications(directory, p)]


def evidence_names(directory, p):
    names = {'authored.json', 'plan.json', 'capture.json', 'native-worker.py', 'native-config.json', 'implementation.json', 'h5dump-version.stdout',
             'h5ls-version.stdout'}
    names |= {path.name for path in directory.iterdir() if path.is_file() and (path.name.startswith('payload-') or path.name.startswith('input-')
              or path.name.endswith('-result.json') or path.name.endswith('-submission.json') or path.name.startswith('mpi-') and '-rank-' in path.name or path.name.startswith('preflight-') and path.name.endswith('-result.json') or path.name.startswith(('h5dump-', 'h5ls-')) and path.name.endswith('.stdout') and '-fresh' not in path.name
              or path.name in ('source.h5', 'reference.h5'))}
    return names - {name for name, _ in publications(directory, p)}


def verify(directory, require_result=True):
    return verify_directory(Path(directory).absolute(), runtime(), require_result)


def verify_directory(directory, paths, require_result=True):
    directory = Path(directory).absolute()
    try:
        try:
            p = plan(read(directory, 'authored.json'))
        except SchemaxisError as error:
            fail('VERIFICATION_FAILED', 'retained authored input is invalid: ' + error.fault.message)
        if read(directory, 'plan.json') != json.loads(json.dumps(p)):
            fail('VERIFICATION_FAILED', 'retained plan differs from the authored input')
        if read(directory, 'implementation.json') != implementation():
            fail('VERIFICATION_FAILED', 'HDF5 adaptor implementation changed; rerun with current code')
        if bounded(directory / 'native-worker.py').decode() != worker_source():
            fail('VERIFICATION_FAILED', 'trusted worker differs')
        if require_result:
            result = read(directory, 'result.json')
            if result.get('status') != 'succeeded' or result.get('verified') is not True:
                fail('INCOMPLETE_EXECUTION', 'HDF5 run did not complete')
        receipt = read(directory, 'verification.json')
        if receipt.get('runtime') != RUNTIME:
            fail('VERIFICATION_FAILED', 'native runtime identity differs')
        if receipt.get('artifacts') != artifacts(directory, p):
            fail('VERIFICATION_FAILED', 'publication membership or digests differ')
        names = evidence_names(directory, p)
        if set(receipt.get('evidence', {})) != names:
            fail('VERIFICATION_FAILED', 'evidence membership differs', missing=sorted(names - set(receipt.get('evidence', {})))[:8],
                 extra=sorted(set(receipt.get('evidence', {})) - names)[:8])
        for name in sorted(names):
            if receipt['evidence'][name] != digest(directory, name):
                fail('VERIFICATION_FAILED', 'retained evidence differs', name)
        capture_record = read(directory, 'capture.json')['captured']
        for item in capture_record:
            if digest(directory, item['file']) != item['sha256']:
                fail('VERIFICATION_FAILED', 'captured input bytes differ from their capture record', item['file'])
        fresh = fresh_check(directory, p, paths)
        return {'verified': True, 'operation': p['operation'], 'artifacts': len(receipt['artifacts']), 'runtime': RUNTIME,
                'independentConsumer': H5DUMP, 'freshlyChecked': fresh}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError, UnicodeError, OverflowError, RecursionError) as error:
        fail('VERIFICATION_FAILED', 'invalid retained HDF5 evidence: ' + str(error)[:300])


def plan_blocks(p, item, obj, at):
    """Attach memory-bounded streaming blocks or per-rank blocks to one normalised extract item."""
    access = p.get('access') or {}
    if item.get('format') == 'chunks':
        return
    if p.get('parallel'):
        item['parallelBlocks'] = operations.split_blocks(item['selection'], obj['shape'], parts=p['parallel']['ranks'], at=at)
    elif 'memoryBytes' in access:
        width = model.element_count(item['selectedShape'][1:]) if len(item['selectedShape']) > 1 else 1
        if 'fields' in item:
            fields = [f for f in obj['type']['fields'] if f['name'] in item['fields']]
            types = [f['type'] for f in fields]
        else:
            types = [obj['type']]
        if any(model.variable_size(t) for t in types):
            fail('INVALID_HDF5_ACCESS', 'memoryBytes bounds fixed-size elements only; this selection holds variable-length strings, '
                 'sequences or references whose payload size is not known before reading (select fixed-size fields or omit memoryBytes)', at,
                 type=types[0] if len(types) == 1 else {'class': 'compound', 'fields': fields})
        size = sum(model.type_size(t) for t in types)
        row_bytes = max(1, width * size)
        if row_bytes > access['memoryBytes']:
            fail('INVALID_HDF5_ACCESS', 'one axis-0 row of the selection is larger than memoryBytes', at, rowBytes=row_bytes)
        item['blocks'] = operations.split_blocks(item['selection'], obj['shape'], rows_per_block=access['memoryBytes'] // row_bytes, at=at)


def extracts_report(directory, extracts, observed, p=None, selections=None):
    out = []
    for e in extracts:
        obj = observed['objects'][e['dataset']]
        if 'where' in e:
            sel = selections[e['id']]
            shape = [len(sel['rows']), *obj['shape'][1:]]
        else:
            sel, shape, count = model.selection(e['selection'] if e['selection']['kind'] != 'slices' else slices_record(e['selection']), obj['shape'], '$')
        rec = {'id': e['id'], 'file': e['output'], 'format': e['format'], 'shape': shape, 'count': len(state.indices(sel, obj['shape'])),
               'sha256': digest(directory, e['output'])}
        if 'where' in e:
            rec['where'] = {'rows': len(sel['rows']), 'of': obj['shape'][0]}
        if e['format'] == 'chunks':
            listed = json.loads(bounded(directory / e['output']))['chunks']
            rec['chunks'] = {'count': len(listed), 'bytes': sum(c['size'] for c in listed)}
        if p is not None:
            item = {**e, 'selection': sel, 'selectedShape': shape}
            plan_blocks(p, item, obj, '$')
            if item.get('blocks'):
                rec['blocks'] = len(item['blocks'])
            if item.get('parallelBlocks'):
                rec['rankRows'] = [len(state.indices(b, obj['shape'])) // max(1, model.element_count(shape[1:]) if len(shape) > 1 else 1) for b in item['parallelBlocks']]
        out.append(rec)
    return out


def create_report(p, directory, expected, superblock):
    total = sum(len(o.get('values') or []) for o in expected['objects'].values() if o['kind'] == 'dataset')
    report = {'operation': p['operation'], 'file': p['file']['name'], 'objects': len(expected['objects']), 'links': len(expected['links']),
              'datasets': {path: {'type': o['type'], 'shape': o['shape'], 'count': len(o['values']) if o.get('values') is not None else None}
                           for path, o in sorted(expected['objects'].items()) if o['kind'] == 'dataset'},
              'independentValues': total <= XML_ELEMENT_BUDGET, 'superblock': superblock}
    report['netcdf4'] = netcdf4_view(expected)
    return report


def same_report(directory, report):
    report = {**report, 'runtime': {'native': RUNTIME, 'independentConsumer': H5DUMP}}
    if read(directory, 'hdf5-report.json') != json.loads(json.dumps(report)):
        fail('VERIFICATION_FAILED', 'the published report differs from a report rebuilt from freshly verified facts', 'hdf5-report.json')


def recheck_extracts(paths, directory, scratch, target, extracts, observed, deadline):
    """Every published extract file equals the selection read independently from current bytes (h5dump values or hyperslab reads)."""
    selections = {}
    for e in extracts:
        obj = observed['objects'].get(e['dataset'])
        if obj is None or obj['kind'] != 'dataset':
            fail('VERIFICATION_FAILED', 'an extracted dataset is missing from the current file', e['dataset'])
        sel, shape, count = extract_selection(paths, scratch, target, e, obj, observed, deadline)
        selections[e['id']] = sel
        item = {**e, 'selection': sel, 'selectedShape': shape, 'count': count}
        if 'where' in e:
            retained = next(x for x in read(directory, 'extract-result.json')['result']['extracts'] if x['id'] == e['id'])
            check_where(item, retained.get('whereRows'))
        if e['format'] == 'chunks':
            shutil.copy2(directory / e['output'], scratch / e['output'])
            check_chunk_extract(paths, scratch, target, item, obj, deadline)
            continue
        want = selected_values(paths, scratch, target, e['dataset'], obj, sel, deadline, '$.extracts.' + e['id'])
        want_type = obj['type']
        if 'fields' in e:
            names = [f['name'] for f in obj['type']['fields']]
            pick = [names.index(n) for n in e['fields']]
            want = [[rec[j] for j in pick] if len(pick) > 1 else rec[pick[0]] for rec in want]
            want_type = {'class': 'compound', 'fields': [obj['type']['fields'][j] for j in pick]} if len(pick) > 1 else obj['type']['fields'][pick[0]]['type']
        item['headers'] = headers(item, obj, observed)
        coords = None
        if e['coordinates'] and e['format'] == 'csv' and obj['dims'] and obj['dims'][0]['scales']:
            item['coordinateScales'] = {'0': obj['dims'][0]['scales'][0]}
            item['coordinateSelection'] = axis_selection(sel, 0)
            scale_path = obj['dims'][0]['scales'][0]
            coords = selected_values(paths, scratch, target, scale_path, observed['objects'][scale_path], item['coordinateSelection'], deadline, '$')
        check_extract_file(directory, item, want, want_type, obj, observed, coords)
    return selections


def fresh_check(directory, p, paths):
    """Re-run the independent consumer on current bytes and recompare with freshly recomputed expectations."""
    deadline = time.monotonic() + 600
    op = p['operation']
    scratch = directory / '.verify'
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    shutil.copyfile(directory / 'native-worker.py', scratch / 'native-worker.py')
    for d in p.get('dependencies', []):
        shutil.copyfile(directory / d['name'], scratch / d['name'])
    for receipt in sorted(directory.glob('*-result.json')):
        record = read(directory, receipt.name)
        if isinstance(record, dict) and record.get('access') is not None:
            check_access(p.get('access'), record['access'], receipt.name)
    try:
        if op in ('createFile', 'writeMeshFields', 'parallelWrite'):
            values = host_values(p, captured_bytes(directory, p))
            deps = {}
            for d in p.get('dependencies', []):
                if d['role'] == 'virtualSource':
                    deps[d['id']] = fresh_source(paths, directory, scratch, d['name'], d['id'], deadline)[2]
            expected = state.expected_create(p, values, deps)
            if json.loads(json.dumps(expected)) != read(directory, 'expected-state.json'):
                fail('VERIFICATION_FAILED', 'the retained expected state differs from a fresh computation')
            driver, target = driver_arguments(p['file'])
            total = sum(len(o.get('values') or []) for o in expected['objects'].values() if o['kind'] == 'dataset')
            for name, kind in publications(directory, p):
                if kind == 'file' and not (scratch / name).exists():
                    shutil.copyfile(directory / name, scratch / name)
            xml = dump(paths, scratch, 'h5dump-fresh', target, deadline, driver, values=total <= XML_ELEMENT_BUDGET)
            state.compare_xml(expected, xml)
            rb = fresh_manifest(paths, scratch, 'readback', target, deadline, p['file'])
            state.compare_readback(expected, rb)
            check_file_settings(p['file'], rb['file'])
            check_alignment(p.get('access'), rb)
            if p.get('extracts'):
                for e in p['extracts']:
                    obj = expected['objects'][e['dataset']]
                    if e['format'] == 'chunks':
                        shutil.copyfile(directory / e['output'], scratch / e['output'])
                        check_chunk_extract(paths, scratch, target, e, obj, deadline)
                        continue
                    want = [obj['values'][i] for i in state.indices(e['selection'], obj['shape'])]
                    want_type = obj['type']
                    if 'fields' in e:
                        names = [f['name'] for f in obj['type']['fields']]
                        pick = [names.index(n) for n in e['fields']]
                        want = [[rec[j] for j in pick] if len(pick) > 1 else rec[pick[0]] for rec in want]
                        want_type = {'class': 'compound', 'fields': [obj['type']['fields'][j] for j in pick]} if len(pick) > 1 else obj['type']['fields'][pick[0]]['type']
                    item = {**e, 'headers': headers(e, obj, expected)}
                    if e['coordinates'] and e['format'] == 'csv' and obj['dims'] and obj['dims'][0]['scales']:
                        item['coordinateScales'] = {'0': obj['dims'][0]['scales'][0]}
                        item['coordinateSelection'] = axis_selection(e['selection'], 0)
                    check_extract_file(directory, item, want, want_type, obj, expected)
            report = create_report(p, directory, expected, rb['file']['superblock'])
            if p.get('extracts'):
                report['extracts'] = extracts_report(directory, p['extracts'], expected, p)
            if op == 'writeMeshFields':
                from . import meshes
                report['xdmf'] = meshes.check_xdmf(p, directory, expected)
                report['mesh'] = meshes.mesh_report(p, values)
            if op == 'parallelWrite':
                from . import parallel
                report['parallel'] = parallel.fresh_check(directory, p)
            same_report(directory, report)
            return ['h5dump-output', 'readback-output', 'report', *[e['id'] for e in p.get('extracts', [])]]
        if op == 'editFile':
            from . import editing
            return editing.fresh_check(directory, scratch, p, paths, deadline)
        if op == 'appendSeries':
            from . import series
            return series.fresh_check(directory, scratch, p, paths, deadline)
        rb, xml, observed = fresh_source(paths, directory, scratch, 'source.h5', 'source', deadline)
        agreement(observed, xml)
        if op == 'inspectFile':
            storage_agreement(rb, h5ls_storage(paths, scratch, 'source.h5', deadline, 'h5ls-fresh-source'))
            if read(directory, 'inventory.json') != json.loads(json.dumps(inventory_of(rb, p['preview']))):
                fail('VERIFICATION_FAILED', 'the published inventory differs from a fresh reading of the captured source')
            independent = independent_values(paths, scratch, 'source.h5', observed, p['expectations'], deadline)
            decisions = [decide(e, rb, observed, independent) for e in p['expectations']]
            met = sum(1 for d in decisions if d['decision'] == 'met')
            unmet = sum(1 for d in decisions if d['decision'] == 'unmet')
            if read(directory, 'expectations.json') != {'decisions': decisions, 'met': met, 'unmet': unmet, 'indeterminate': len(decisions) - met - unmet}:
                fail('VERIFICATION_FAILED', 'published expectation decisions differ from a fresh decision')
            same_report(directory, {'operation': 'inspectFile', 'objects': len(rb['objects']), 'links': len(rb['links']),
                                    'expectations': {'met': met, 'unmet': unmet, 'indeterminate': len(decisions) - met - unmet},
                                    'superblock': rb['file']['superblock']})
        if op == 'extractData':
            selections = recheck_extracts(paths, directory, scratch, 'source.h5', p['extracts'], observed, deadline)
            if p.get('parallel'):
                from . import parallel
                items = []
                for e in p['extracts']:
                    obj = observed['objects'][e['dataset']]
                    sel, shape, _ = model.selection(e['selection'] if e['selection']['kind'] != 'slices' else slices_record(e['selection']), obj['shape'], '$')
                    item = {**e, 'selection': sel, 'selectedShape': shape, 'datasetShape': obj['shape']}
                    plan_blocks(p, item, obj, '$')
                    items.append(item)
                parallel.check_extract_ranks(directory, p, items)
            same_report(directory, {'operation': 'extractData', 'extracts': extracts_report(directory, p['extracts'], observed, p, selections)})
        if op == 'compareFiles':
            left = observed
            right = fresh_source(paths, directory, scratch, 'reference.h5', 'reference', deadline)[2]
            mine = host_compare(left, right, p['tolerance'])
            if read(directory, 'comparison.json') != {'equal': not mine, 'differences': mine, 'tolerance': p['tolerance']}:
                fail('VERIFICATION_FAILED', 'published comparison differs from a fresh independent comparison')
            same_report(directory, {'operation': 'compareFiles', 'equal': not mine, 'differences': len(mine)})
        return ['h5dump-source', 'readback-source', 'report']
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


from schemaxis.adaptor_runtime import bind as _bind_runtime  # noqa: E402
_bind_runtime(globals())


def reusableInputs(document):
    p = plan(document)
    out = {}
    for item in p.get('inputs', []) + p.get('dependencies', []):
        out[item['path']] = sha(bounded(item['path'], 'INVALID_HDF5_INPUT', model.MAX_SOURCE_BYTES))
    for key in ('source', 'reference'):
        if key in p:
            out[p[key]] = sha(bounded(p[key], 'INVALID_HDF5_SOURCE', model.MAX_SOURCE_BYTES))
    return out
