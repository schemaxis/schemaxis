"""Trusted h5py worker; copied into the run directory and never imported by the host.

Run as: python -I -B native-worker.py STAGE   (working directory = run directory)
Stages: build (createFile/writeMeshFields), edit (editFile), readback/inspect (fresh read-only manifest of
one file), extract (selections to CSV/NPY/JSON), swmr-writer / swmr-reader (appendSeries), compare.
native-config.json carries the host-normalised plan; payload-*.json carry host-materialised element
values. Structured refusals go to STAGE-fault.json with exit status 3. The host owns every decision.
"""
import hashlib
import json
import math
import os
import sys
import time

REQUIRED = {'h5py': '3.16.0', 'hdf5': '2.0.0', 'numpy': '2.5.4'}
FILTERS = {1: 'gzip', 2: 'shuffle', 3: 'fletcher32', 4: 'szip', 5: 'nbit', 6: 'scaleoffset', 32000: 'lzf'}
PREVIEW = 64
ACCESS = {}
OBSERVED_ACCESS = {}
MERGE_COMMITTED_DTYPE = 0x0040
MAX_LINKS = 100000


class Fault(Exception):
    def __init__(self, code, message, location='$', **details):
        super().__init__(message)
        self.payload = {'code': code, 'message': message, 'location': location, 'details': details}


def write_json(name, value):
    with open(name + '.tmp', 'w') as stream:
        stream.write(json.dumps(value, indent=1, allow_nan=False, sort_keys=True) + '\n')
    os.replace(name + '.tmp', name)


def read_json(name):
    with open(name) as stream:
        return json.load(stream)


def runtime_identity():
    try:
        import h5py
        import numpy
    except ImportError as error:
        raise Fault('HDF5_UNSUPPORTED_RUNTIME', 'h5py 3.16.0 and NumPy 2.5.4 are not importable: ' + str(error), '$.runtime')
    while h5py.h5pl.size():
        h5py.h5pl.remove(0)
    if os.environ.get('HDF5_PLUGIN_PRELOAD') != '::':
        raise Fault('HDF5_UNSUPPORTED_RUNTIME', 'dynamic filter plugins must be disabled (HDF5_PLUGIN_PRELOAD=::)', '$.runtime')
    observed = {'h5py': h5py.version.version, 'hdf5': h5py.version.hdf5_version, 'numpy': numpy.__version__}
    for key, want in REQUIRED.items():
        if observed[key] != want:
            raise Fault('HDF5_UNSUPPORTED_RUNTIME', 'qualified for %s %s only' % (key, want), '$.runtime', observed=observed[key])
    return {**observed, 'python': sys.version.split()[0], 'pid': os.getpid(), 'h5pyLocation': os.path.dirname(h5py.__file__),
            'mpi': bool(h5py.get_config().mpi), 'pluginPaths': int(h5py.h5pl.size()), 'pluginPreload': os.environ.get('HDF5_PLUGIN_PRELOAD')}


# ---------------------------------------------------------------- types
def np_dtype(t, named=None):
    import h5py
    import numpy as np
    cls = t['class']
    if cls == 'named':
        return np_dtype(t['resolved'])
    dims = t.get('dims')
    if dims:
        inner = np_dtype({k: v for k, v in t.items() if k != 'dims'})
        return np.dtype((inner, tuple(dims)))
    order = '>' if t.get('order') == 'big' else '<'
    if cls == 'int':
        return np.dtype(order + 'i%d' % (t['bits'] // 8))
    if cls == 'uint':
        return np.dtype(order + 'u%d' % (t['bits'] // 8))
    if cls == 'float':
        return np.dtype(order + 'f%d' % (t['bits'] // 8))
    if cls == 'complex':
        return np.dtype(order + 'c%d' % (t['bits'] // 8))
    if cls == 'bool':
        return np.dtype('?')
    if cls == 'string':
        if 'length' in t:
            return h5py.string_dtype(t['encoding'], t['length'])
        return h5py.string_dtype(t['encoding'])
    if cls == 'enum':
        base = np.dtype(order + ('i' if t['signed'] else 'u') + str(t['bits'] // 8))
        return h5py.enum_dtype({m['name']: m['value'] for m in t['members']}, basetype=base)
    if cls == 'compound':
        return np.dtype([(f['name'], np_dtype(f['type'])) for f in t['fields']])
    if cls == 'vlen':
        return h5py.vlen_dtype(np_dtype(t['base']))
    if cls == 'array':
        return np_dtype(t['base'])
    if cls == 'reference':
        return h5py.ref_dtype if t['reference'] == 'object' else h5py.regionref_dtype
    if cls == 'opaque':
        return h5py.opaque_dtype(np.dtype('V%d' % t['size']))
    raise Fault('HDF5_TYPE_UNSUPPORTED', 'unsupported type class ' + cls)


def describe(dtype):
    """Normalised type descriptor of a dtype read from a file (same vocabulary as the host plan)."""
    import h5py
    import numpy as np
    if dtype.subdtype is not None:
        base, shape = dtype.subdtype
        return {**describe(base), 'dims': list(shape)}
    s = h5py.check_string_dtype(dtype)
    if s is not None:
        out = {'class': 'string', 'encoding': s.encoding}
        if s.length is not None:
            out['length'] = s.length
        return out
    e = h5py.check_enum_dtype(dtype)
    if e is not None:
        if dtype == np.dtype('?') or set(e) == {'FALSE', 'TRUE'} and dtype.itemsize == 1:
            return {'class': 'bool'}
        return {'class': 'enum', 'bits': dtype.itemsize * 8, 'signed': dtype.kind == 'i', 'order': order(dtype),
                'members': sorted(({'name': k, 'value': int(v)} for k, v in e.items()), key=lambda m: m['value'])}
    v = h5py.check_vlen_dtype(dtype)
    if v is not None:
        return {'class': 'vlen', 'base': describe(v)}
    r = h5py.check_ref_dtype(dtype)
    if r is not None:
        return {'class': 'reference', 'reference': 'object' if r is h5py.Reference else 'region'}
    if h5py.check_opaque_dtype(dtype):
        return {'class': 'opaque', 'size': dtype.itemsize}
    if dtype.names:
        return {'class': 'compound', 'fields': [{'name': n, 'type': describe(dtype.fields[n][0])} for n in dtype.names]}
    if dtype.kind == 'b':
        return {'class': 'bool'}
    kind = {'i': 'int', 'u': 'uint', 'f': 'float', 'c': 'complex'}.get(dtype.kind)
    if kind is None:
        raise Fault('HDF5_TYPE_UNSUPPORTED', 'unsupported stored type ' + str(dtype))
    return {'class': kind, 'bits': dtype.itemsize * 8, 'order': order(dtype)}


def order(dtype):
    if dtype.byteorder == '>' or dtype.byteorder == '=' and sys.byteorder == 'big':
        return 'big'
    return 'little'


def canonical(value, d):
    """Canonical element from a NumPy/h5py value of descriptor d (mirrors the host vocabulary)."""
    import numpy as np
    cls = d['class']
    if d.get('dims'):
        inner = {k: v for k, v in d.items() if k != 'dims'}
        return [canonical(x, inner) for x in np.asarray(value).reshape(-1)]
    if cls in ('int', 'uint', 'enum', 'bitfield'):
        return int(value)
    if cls == 'float':
        return float(value).hex()
    if cls == 'complex':
        c = complex(value)
        return [c.real.hex(), c.imag.hex()]
    if cls == 'bool':
        return bool(value)
    if cls == 'string':
        return value.decode(d['encoding']) if isinstance(value, bytes) else str(value)
    if cls == 'compound':
        return [canonical(value[f['name']], f['type']) for f in d['fields']]
    if cls == 'vlen':
        return [canonical(x, d['base']) for x in value]
    if cls == 'opaque':
        return bytes(value).hex()
    return None


def natural(value):
    if isinstance(value, list):
        return [natural(v) for v in value]
    if isinstance(value, str) and (value.startswith('0x') or value.startswith('-0x') or value in ('nan', 'inf', '-inf')):
        x = float.fromhex(value) if 'x' in value else float(value)
        return x if math.isfinite(x) else repr(x)
    return value


def element_iter(array, d):
    flat = array.reshape(-1) if array.ndim else array.reshape(1)
    for value in flat:
        yield canonical(value, d)


def summarise(elements):
    h = hashlib.sha256(b'[')
    count, head = 0, []
    for e in elements:
        if count:
            h.update(b',')
        h.update(json.dumps(e, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode())
        if len(head) < PREVIEW:
            head.append(e)
        count += 1
    h.update(b']')
    return {'count': count, 'sha256': h.hexdigest(), 'head': head}


# ---------------------------------------------------------------- values
def payload(name):
    return read_json('payload-%s.json' % name)


def materialise(values, t, shape):
    """Host-checked canonical-free values -> NumPy array of the declared dtype."""
    import numpy as np
    dt = np_dtype(t)
    rt = t['resolved'] if t['class'] == 'named' else t
    cls = rt['class']
    n = 1
    for s in shape:
        n *= s
    if cls == 'compound':
        rows = [tuple(convert_field(v, f['type']) for v, f in zip(rec, rt['fields'])) for rec in values]
        return np.array(rows, dtype=dt).reshape(shape)
    if cls == 'vlen':
        out = np.empty(n, dtype=dt)
        base = np_dtype(rt['base'])
        for i, v in enumerate(values):
            out[i] = np.array([convert_field(x, rt['base']) for x in v], dtype=base)
        return out.reshape(shape)
    if cls == 'string':
        out = np.empty(n, dtype=dt)
        for i, v in enumerate(values):
            out[i] = v.encode(rt['encoding']) if 'length' in rt else v
        return out.reshape(shape)
    if cls == 'opaque':
        return np.frombuffer(b''.join(bytes.fromhex(v) for v in values), dtype=np.dtype('V%d' % rt['size'])).reshape(shape).astype(dt)
    if cls == 'array' or rt.get('dims'):
        base = rt['base'] if cls == 'array' else {k: v for k, v in rt.items() if k != 'dims'}
        dims = base.get('dims', rt.get('dims'))
        inner = {k: v for k, v in base.items() if k != 'dims'}
        flat = [convert_field(x, inner) for v in values for x in v]
        return np.array(flat, dtype=np_dtype(inner)).reshape(tuple(shape) + tuple(dims))
    if cls == 'complex':
        return np.array([complex(float(a), float(b)) for a, b in values], dtype=dt).reshape(shape)
    if cls == 'float':
        return np.array([float(v) for v in values], dtype=np.float64).astype(dt).reshape(shape)
    return np.array(values, dtype=dt).reshape(shape)


def convert_field(v, t):
    if t.get('dims'):
        return [convert_field(x, {k: y for k, y in t.items() if k != 'dims'}) for x in v]
    cls = t['class']
    if cls == 'complex':
        return complex(float(v[0]), float(v[1]))
    if cls == 'string':
        return v.encode(t['encoding'])
    if cls == 'float':
        return float(v)
    return v


def generate(data, t, shape):
    import numpy as np
    rt = t['resolved'] if t['class'] == 'named' else t
    n = 1
    for s in shape:
        n *= s
    dt = np_dtype(rt)
    if data['source'] == 'range':
        if rt['class'] == 'float':
            values = float(data['start']) + np.arange(n, dtype=np.float64) * float(data['step'])
        else:
            values = np.array([int(data['start']) + i * int(data['step']) for i in range(n)], dtype=object) if rt['bits'] == 64 and rt['class'] == 'uint' \
                else int(data['start']) + np.arange(n, dtype=np.int64) * int(data['step'])
        return np.asarray(values).astype(dt).reshape(shape)
    start, stop = float(data['start']), float(data['stop'])
    step = (stop - start) / (n - 1)
    values = start + np.arange(n, dtype=np.float64) * step
    values[-1] = stop
    return values.astype(dt).reshape(shape)


def selection_key(sel):
    import h5py
    kind = sel['kind']
    if kind == 'all':
        return ()
    if kind == 'slices':
        return tuple(slice(a, b, c) for a, b, c in sel['slices'])
    if kind == 'hyperslab':
        return tuple(h5py.MultiBlockSlice(start=s, count=c, stride=st, block=b)
                     for s, c, st, b in zip(sel['start'], sel['count'], sel['stride'], sel['block']))
    return None


def read_selection(source, sel, ds=None, dtype=None):
    """Read a normal-form selection from a dataset (or an h5py field view of it, with its dataset and memory dtype)."""
    import numpy as np
    ds = source if ds is None else ds
    dtype = ds.dtype if dtype is None else dtype
    if sel['kind'] == 'rows':
        if not sel['rows']:
            return np.empty((0, *ds.shape[1:]), dtype=dtype)
        return source[sel['rows']]
    if sel['kind'] == 'points':
        if ds.ndim == 1:
            idx = [p[0] for p in sel['points']]
            uniq = sorted(set(idx))
            data = source[uniq] if uniq else source[[]]
            lookup = {v: i for i, v in enumerate(uniq)}
            return np.array([data[lookup[i]] for i in idx], dtype=data.dtype)
        return np.array([source[tuple(p)] for p in sel['points']], dtype=dtype)
    key = selection_key(sel)
    return source[key] if key else source[()]


def write_selection(ds, sel, array, fields=()):
    """Write a normal-form selection; with compound field names only those members are converted and written (h5py partial write),
    so the other members of every selected record keep their stored values."""
    if sel['kind'] == 'points':
        if fields:
            for i, p in enumerate(sel['points']):
                ds[tuple(slice(c, c + 1) for c in p) + fields] = array[i:i + 1].reshape((1,) * len(p) + array.shape[1:])
            return
        flat = array.reshape(-1)
        for i, p in enumerate(sel['points']):
            ds[tuple(p)] = flat[i]
        return
    key = selection_key(sel)
    if fields:
        target = ds.fields(list(fields) if len(fields) > 1 else fields[0])
        shape = target[key].shape if key else target[()].shape
        ds[(key or (Ellipsis,)) + fields] = array.reshape(shape)
        return
    if key:
        ds[key] = array.reshape(ds[key].shape) if not sel['kind'] == 'all' else array
    else:
        ds[()] = array


# ---------------------------------------------------------------- access tuning
def access_kwargs():
    """File access properties declared by the plan (chunk cache, page buffer, metadata block, alignment)."""
    kw = {}
    cache = ACCESS.get('chunkCache')
    if cache:
        kw.update(rdcc_nbytes=cache['bytes'], rdcc_nslots=cache['slots'], rdcc_w0=cache['preemption'])
    if 'pageBufferBytes' in ACCESS:
        kw['page_buf_size'] = ACCESS['pageBufferBytes']
    if 'metaBlockBytes' in ACCESS:
        kw['meta_block_size'] = ACCESS['metaBlockBytes']
    if ACCESS.get('alignment'):
        kw.update(alignment_threshold=ACCESS['alignment']['threshold'], alignment_interval=ACCESS['alignment']['interval'])
    return kw


FAPL_KEYS = ('libver', 'rdcc_nslots', 'rdcc_nbytes', 'rdcc_w0', 'locking', 'page_buf_size', 'min_meta_keep', 'min_raw_keep',
             'alignment_threshold', 'alignment_interval', 'meta_block_size')
FCPL_KEYS = ('track_order', 'track_times', 'fs_strategy', 'fs_persist', 'fs_threshold', 'fs_page_size')


def open_file(name, mode, **kw):
    """h5py.File with the declared access properties. A declared sieve buffer is set on the same file access property
    list h5py builds for File (make_fapl), then the file is opened or created exactly as File does (make_fcpl, make_fid)."""
    import h5py
    options = {**kw, **access_kwargs()}
    if 'sieveBufferBytes' not in ACCESS:
        return h5py.File(name, mode, **options)
    from h5py._hl import files
    driver, swmr, userblock = options.pop('driver', None), options.pop('swmr', False), options.pop('userblock_size', None)
    fapl_args = {k: options.pop(k) for k in FAPL_KEYS if k in options}
    fcpl_args = {k: options.pop(k) for k in FCPL_KEYS if k in options}
    fapl = files.make_fapl(driver, **fapl_args, **options)
    fapl.set_sieve_buf_size(ACCESS['sieveBufferBytes'])
    fcpl = files.make_fcpl(**fcpl_args) if mode in ('w', 'w-', 'x') else None
    return h5py.File(files.make_fid(files.filename_encode(name), mode, userblock, fapl, fcpl, swmr=swmr))


def observe_access(f):
    """Record the access properties actually in force on an opened file (read back from its access property list)."""
    if OBSERVED_ACCESS:
        return
    fapl = f.id.get_access_plist()
    cache = fapl.get_cache()
    OBSERVED_ACCESS.update({'chunkCache': {'slots': int(cache[1]), 'bytes': int(cache[2]), 'preemption': float(cache[3])},
                            'alignment': {'threshold': int(fapl.get_alignment()[0]), 'interval': int(fapl.get_alignment()[1])},
                            'metaBlockBytes': int(fapl.get_meta_block_size()), 'pageBufferBytes': int(fapl.get_page_buffer_size()[0]),
                            'sieveBufferBytes': int(fapl.get_sieve_buf_size())})


def rss_peak():
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


# ---------------------------------------------------------------- building
def file_kwargs(f, mode):
    kw = {'libver': (f['libver'], f['libverHigh'])}
    if mode == 'w':
        kw['track_order'] = f['trackOrder']
        if f['userblock']:
            kw['userblock_size'] = f['userblock']
        if f['spaceStrategy'] != 'default':
            kw['fs_strategy'] = f['spaceStrategy']
            if f['spaceStrategy'] == 'page':
                kw['fs_page_size'] = f['pageBytes']
    driver = f['driver']
    if driver != 'sec2':
        kw['driver'] = driver
    if driver == 'core':
        kw['backing_store'] = True
    if driver == 'family':
        kw['memb_size'] = f['memberBytes']
    if driver == 'split':
        kw['meta_ext'], kw['raw_ext'] = b'-m.h5', b'-r.h5'
    return kw


def file_name(f):
    stem = f['name'].rsplit('.', 1)[0]
    if f['driver'] == 'family':
        return stem + '-%d.h5'
    if f['driver'] == 'split':
        return stem
    return f['name']


def create_attribute(obj, a):
    import h5py
    import numpy as np
    t = a['type']
    if a.get('empty'):
        obj.attrs.create(a['name'], h5py.Empty(np_dtype(t)))
        return
    values = payload(a['payload']) if 'payload' in a else a['values']
    array = materialise(values, t, a['shape'])
    obj.attrs.create(a['name'], array, shape=tuple(a['shape']), dtype=np_dtype(t))


def dataset_value(o, f):
    data = o['data']
    src = data['source']
    if src in ('values', 'input'):
        return materialise(payload(o['payload']), o['type'], o['shape'])
    if src in ('range', 'linspace'):
        return generate(data, o['type'], o['shape'])
    if src == 'copy':
        return f[data['dataset']][()]
    return None



def storage_kwargs(o, f, ctx):
    import h5py
    s = o['storage']
    kw = {'track_times': s.get('trackTimes', False)}
    layout = s['layout']
    if layout == 'chunked':
        kw['chunks'] = True if s['chunks'] == 'auto' else tuple(s['chunks'])
        comp = s['compression']
        if comp == 'gzip':
            kw['compression'], kw['compression_opts'] = 'gzip', s['level']
        elif comp == 'lzf':
            kw['compression'] = 'lzf'
        elif comp == 'szip':
            kw['compression'], kw['compression_opts'] = 'szip', (s['szipMethod'], s['szipPixels'])
        if s.get('shuffle'):
            kw['shuffle'] = True
        if s.get('fletcher32'):
            kw['fletcher32'] = True
        if 'scaleOffset' in s:
            kw['scaleoffset'] = s['scaleOffset']
    if 'maxshape' in o and o['maxshape'] != o['shape']:
        kw['maxshape'] = tuple(None if m == 'unlimited' else m for m in o['maxshape'])
    if 'fillValue' in s:
        rt = o['type']['resolved'] if o['type']['class'] == 'named' else o['type']
        kw['fillvalue'] = materialise([s['fillValue']], rt, [])[()]
    if layout == 'external':
        kw['external'] = [(e['path'], e['offset'], e['size']) for e in s['external']]
    return kw


def low_level_dataset(parent, name, o, kw, value):
    """Create through the low-level API when layout compact or explicit fill/alloc times are needed."""
    import h5py
    import numpy as np
    s = o['storage']
    dcpl = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
    if o.get('trackOrder'):
        dcpl.set_attr_creation_order(h5py.h5p.CRT_ORDER_TRACKED | h5py.h5p.CRT_ORDER_INDEXED)
    shape = tuple(o['shape'])
    maxshape = tuple(h5py.h5s.UNLIMITED if m == 'unlimited' else m for m in o['maxshape'])
    space = h5py.h5s.create_simple(shape, maxshape) if shape else h5py.h5s.create(h5py.h5s.SCALAR)
    dt = np_dtype(o['type'])
    tid = h5py.h5t.py_create(dt, logical=True)
    if o['type']['class'] == 'named':
        tid = parent.file[o['type']['path']].id
    layout = s['layout']
    if layout == 'compact':
        dcpl.set_layout(h5py.h5d.COMPACT)
    elif layout == 'chunked':
        chunks = kw.get('chunks')
        if chunks is True:
            chunks = h5py.filters.guess_chunk(shape, maxshape, dt.itemsize)
        dcpl.set_chunk(tuple(chunks))
        if s.get('nbit'):
            dcpl.set_filter(h5py.h5z.FILTER_NBIT, h5py.h5z.FLAG_OPTIONAL)
        if s.get('shuffle'):
            dcpl.set_shuffle()
        if s['compression'] == 'gzip':
            dcpl.set_deflate(s['level'])
        elif s['compression'] == 'lzf':
            dcpl.set_filter(h5py.h5z.FILTER_LZF, h5py.h5z.FLAG_OPTIONAL)
        elif s['compression'] == 'szip':
            dcpl.set_szip(h5py.h5z.SZIP_NN_OPTION_MASK if s['szipMethod'] == 'nn' else h5py.h5z.SZIP_EC_OPTION_MASK, s['szipPixels'])
        if 'scaleOffset' in s:
            if dt.kind == 'f':
                dcpl.set_scaleoffset(h5py.h5z.SO_FLOAT_DSCALE, s['scaleOffset'])
            else:
                dcpl.set_scaleoffset(h5py.h5z.SO_INT, s['scaleOffset'])
        if s.get('fletcher32'):
            dcpl.set_fletcher32()
    if 'fillValue' in s:
        dcpl.set_fill_value(np.asarray(kw['fillvalue'], dtype=dt))
    if 'fillTime' in s:
        dcpl.set_fill_time({'ifSet': h5py.h5d.FILL_TIME_IFSET, 'alloc': h5py.h5d.FILL_TIME_ALLOC, 'never': h5py.h5d.FILL_TIME_NEVER}[s['fillTime']])
    if 'allocTime' in s:
        dcpl.set_alloc_time({'early': h5py.h5d.ALLOC_TIME_EARLY, 'incremental': h5py.h5d.ALLOC_TIME_INCR, 'late': h5py.h5d.ALLOC_TIME_LATE}[s['allocTime']])
    dcpl.set_obj_track_times(bool(s.get('trackTimes', False)))
    dsid = h5py.h5d.create(parent.id, name.encode(), tid, space, dcpl=dcpl)
    ds = h5py.Dataset(dsid)
    if value is not None:
        ds[()] = value
    return ds


def create_object(f, o, ctx):
    import h5py
    path = o['path']
    if o['kind'] == 'group':
        kw = {'track_order': o['trackOrder']} if 'trackOrder' in o else {}
        obj = f.require_group(path) if path not in f else f[path]
        if kw and path not in ctx['created']:
            del f[path]
            obj = f.create_group(path, **kw)
        ctx['created'].add(path)
    elif o['kind'] == 'datatype':
        f[path] = np_dtype(o['type'])
        obj = f[path]
    else:
        parent_path, name = path.rsplit('/', 1)
        parent_group = f.require_group(parent_path or '/')
        if 'virtual' in o:
            obj = create_virtual(f, parent_group, name, o, ctx)
        elif o.get('empty'):
            dtype = f[o['type']['path']] if o['type']['class'] == 'named' else np_dtype(o['type'])
            obj = parent_group.create_dataset(name, shape=None, dtype=dtype, **({'track_order': True} if o.get('trackOrder') else {}))
        else:
            value = dataset_value(o, f)
            kw = storage_kwargs(o, f, ctx)
            if o.get('trackOrder'):
                kw['track_order'] = True
            s = o['storage']
            if s['layout'] == 'compact' or 'fillTime' in s or 'allocTime' in s or o['type']['class'] == 'named' or s.get('nbit'):
                obj = low_level_dataset(parent_group, name, o, kw, value)
            else:
                obj = parent_group.create_dataset(name, shape=tuple(o['shape']), dtype=np_dtype(o['type']), data=value, **kw)
            if o['data']['source'] == 'references':
                ctx['references'].append(o)
        if 'scale' in o:
            obj.make_scale(o['scale'])
    for a in o.get('attributes', []):
        create_attribute(obj, a)
    return obj



def create_virtual(f, parent_group, name, o, ctx):
    import h5py
    v = o['virtual']
    layout = h5py.VirtualLayout(shape=tuple(o['shape']), dtype=np_dtype(o['type']),
                                maxshape=tuple(None if m == 'unlimited' else m for m in o['maxshape']))
    for s in v['sources']:
        if s['file'] == '.':
            src = f[s['dataset']]
            vs = h5py.VirtualSource('.', s['dataset'], shape=src.shape, dtype=src.dtype)
        else:
            dep = ctx['dependencies'][s['file']]
            with h5py.File(dep['name'], 'r') as other:
                src = other[s['dataset']]
                vs = h5py.VirtualSource(dep['name'], s['dataset'], shape=src.shape, dtype=src.dtype)
        sk = selection_key(s['select'])
        tk = selection_key(s['at'])
        piece = vs[sk] if sk else vs
        if tk:
            layout[tk] = piece
        else:
            layout[...] = piece
    kw = {}
    if 'fill' in v:
        rt = o['type']['resolved'] if o['type']['class'] == 'named' else o['type']
        kw['fillvalue'] = materialise([v['fill']], rt, [])[()]
    return parent_group.create_virtual_dataset(name, layout, **kw)


def create_link(f, link):
    import h5py
    if link['kind'] == 'soft':
        f[link['path']] = h5py.SoftLink(link['target'])
    elif link['kind'] == 'external':
        f[link['path']] = h5py.ExternalLink(link['file'], link['target'])
    else:
        f[link['path']] = f[link['target']]


def fill_references(f, o):
    import h5py
    import numpy as np
    ds = f[o['path']]
    flat = ds.reshape(-1) if False else None
    targets = o['data']['targets']
    values = []
    for t in targets:
        target = f[t['path']]
        if o['type']['reference'] == 'object':
            values.append(target.ref)
        else:
            key = selection_key(t['selection'])
            if t['selection']['kind'] == 'points':
                values.append(target.regionref[tuple(np.array(t['selection']['points']).T.tolist())] if target.ndim > 1 else target.regionref[[p[0] for p in t['selection']['points']]])
            else:
                values.append(target.regionref[key] if key else target.regionref[...])
    arr = np.empty(len(values), dtype=ds.dtype)
    for i, v in enumerate(values):
        arr[i] = v
    ds[...] = arr.reshape(ds.shape)


def build(config):
    import h5py
    f_settings = config['file']
    ctx = {'created': set(), 'references': [], 'dependencies': config.get('dependencies', {})}
    with open_file(file_name(f_settings), 'w', **file_kwargs(f_settings, 'w')) as f:
        observe_access(f)
        for a in f_settings['attributes']:
            create_attribute(f, a)
        for o in config['objects']:
            create_object(f, o, ctx)
        for link in config.get('links', []):
            create_link(f, link)
        for o in ctx['references']:
            fill_references(f, o)
        for o in config['objects']:
            for d in o.get('dimensions', []):
                ds = f[o['path']]
                for s in d['scales']:
                    ds.dims[d['axis']].attach_scale(f[s])
                if 'label' in d:
                    ds.dims[d['axis']].label = d['label']
        if config.get('mesh'):
            write_xdmf_companion(config)
    if f_settings['userblock'] and config.get('userblockText') is not None:
        with open(f_settings['name'], 'r+b') as stream:
            stream.write(config['userblockText'].encode('utf-8'))
    return {'file': f_settings['name']}


def write_xdmf_companion(config):
    with open(config['mesh']['xdmf'], 'w', encoding='utf-8') as stream:
        stream.write(config['mesh']['xml'])


# ---------------------------------------------------------------- manifest
def address(obj):
    import h5py
    info = h5py.h5o.get_info(obj if isinstance(obj, h5py.h5t.TypeID) else obj.id)
    token = getattr(info, 'token', None)
    if token is not None:
        return bytes(token).hex() if not isinstance(token, (int, str)) else str(token)
    return str(info.addr)


def attribute_record(obj, name):
    import h5py
    aid = h5py.h5a.open(obj.id, name.encode())
    space = aid.get_space()
    dtype = aid.dtype
    d = describe(dtype)
    if space.get_simple_extent_type() == h5py.h5s.NULL:
        return {'type': d, 'empty': True}
    value = obj.attrs[name]
    import numpy as np
    shape = list(space.shape)
    if d['class'] == 'reference':
        arr = np.asarray(value).reshape(-1)
        return {'type': d, 'shape': shape, 'values': [reference_target(obj.file, r, d) for r in arr]}
    arr = np.asarray(value, dtype=dtype) if not d.get('dims') else np.asarray(value)
    return {'type': d, 'shape': shape, 'values': list(element_iter(arr, d))}


def reference_target(f, ref, d):
    import h5py
    if not ref:
        return None
    try:
        target = f[ref]
    except (KeyError, ValueError, OSError, RuntimeError):
        return {'unresolved': True}
    out = {'address': address(target), 'path': target.name}
    if d['reference'] == 'region':
        space = h5py.h5r.get_region(ref, target.id) if hasattr(h5py.h5r, 'get_region') else None
        if space is not None:
            out['points'] = selected_points(space)
    return out


def selected_points(space):
    import h5py
    import itertools
    kind = space.get_select_type()
    if kind == h5py.h5s.SEL_POINTS:
        return [list(map(int, p)) for p in space.get_select_elem_pointlist()]
    if kind == h5py.h5s.SEL_ALL:
        return [list(p) for p in itertools.product(*[range(n) for n in space.shape])]
    if kind == h5py.h5s.SEL_HYPERSLABS:
        points = set()
        for block in space.get_select_hyper_blocklist():
            import numpy as np
            block = [int(x) for x in np.asarray(block).reshape(-1)]
            rank = len(block) // 2
            lo, hi = block[:rank], block[rank:]
            for p in itertools.product(*[range(a, b + 1) for a, b in zip(lo, hi)]):
                points.add(tuple(int(x) for x in p))
        return [list(p) for p in sorted(points)]
    return []


def stored_type(ds):
    """Type descriptor of a dataset as stored: the NumPy-level description, with HDF5 classes NumPy cannot express (bitfield) taken
    from the stored datatype itself. Shared by every dataset whatever its dataspace."""
    import h5py
    tid = ds.id.get_type()
    if tid.get_class() == h5py.h5t.BITFIELD:
        return {'class': 'bitfield', 'bits': tid.get_size() * 8, 'order': 'big' if tid.get_order() == h5py.h5t.ORDER_BE else 'little'}
    return describe(ds.dtype)


def stored_layout(dcpl):
    """Layout and filter pipeline from the dataset creation property list, whatever the dataspace."""
    import h5py
    layout = {h5py.h5d.CONTIGUOUS: 'contiguous', h5py.h5d.CHUNKED: 'chunked', h5py.h5d.COMPACT: 'compact',
              h5py.h5d.VIRTUAL: 'virtual'}.get(dcpl.get_layout(), 'unknown')
    if layout == 'contiguous' and dcpl.get_external_count():
        layout = 'external'
    filters = []
    for i in range(dcpl.get_nfilters()):
        code, flags, values, name = dcpl.get_filter(i)
        filters.append({'name': FILTERS.get(code, 'filter-%d' % code), 'code': int(code), 'values': [int(v) for v in values]})
    return layout, filters


def null_record(ds, d, layout, filters):
    """A null-dataspace dataset (h5py.Empty): stored type, layout and attributes, no shape and no elements."""
    record = {'kind': 'dataset', 'type': d, 'shape': None, 'maxshape': None, 'null': True, 'layout': layout, 'chunks': None,
              'filters': filters, 'scale': None, 'dims': [], 'committedType': ds.id.get_type().committed(), 'offset': None,
              'storageBytes': int(ds.id.get_storage_size()), 'logicalBytes': 0, 'missingFiles': [], 'values': summarise(iter(()))}
    if record['committedType']:
        record['typeAddress'] = address(ds.id.get_type())
    return record


def dataset_record(ds, f, budget):
    import h5py
    import numpy as np
    dcpl = ds.id.get_create_plist()
    d = stored_type(ds)
    layout, filters = stored_layout(dcpl)
    if ds.shape is None:
        return null_record(ds, d, layout, filters)
    record = {'kind': 'dataset', 'type': d, 'shape': list(ds.shape),
              'maxshape': ['unlimited' if m is None else int(m) for m in (ds.maxshape or ())],
              'layout': layout, 'chunks': list(ds.chunks) if ds.chunks else None, 'filters': filters,
              'fillTime': {h5py.h5d.FILL_TIME_IFSET: 'ifSet', h5py.h5d.FILL_TIME_ALLOC: 'alloc', h5py.h5d.FILL_TIME_NEVER: 'never'}.get(dcpl.get_fill_time()),
              'allocTime': {h5py.h5d.ALLOC_TIME_EARLY: 'early', h5py.h5d.ALLOC_TIME_INCR: 'incremental', h5py.h5d.ALLOC_TIME_LATE: 'late'}.get(dcpl.get_alloc_time()),
              'fillDefined': dcpl.fill_value_defined() == h5py.h5d.FILL_VALUE_USER_DEFINED,
              'scale': h5py.h5ds.get_scale_name(ds.id).decode('utf-8') if ds.is_scale and h5py.h5ds.get_scale_name(ds.id) is not None else ('' if ds.is_scale else None),
              'dims': [], 'committedType': ds.id.get_type().committed(),
              'offset': int(ds.id.get_offset()) if ds.id.get_offset() is not None else None, 'storageBytes': int(ds.id.get_storage_size()),
              'logicalBytes': int(ds.id.get_type().get_size()) * int(ds.size if ds.shape else 1)}
    if layout == 'chunked':
        sizes, skipped = [], 0
        for i in range(min(int(ds.id.get_num_chunks()), 100000)):
            info = ds.id.get_chunk_info(i)
            sizes.append(int(info.size))
            skipped += 1 if info.filter_mask else 0
        record['chunkStats'] = {'count': len(sizes), 'minBytes': min(sizes) if sizes else 0, 'maxBytes': max(sizes) if sizes else 0,
                                'skippedFilters': skipped}
    if record['committedType']:
        record['typeAddress'] = address(ds.id.get_type())
    if d['class'] not in ('vlen', 'reference') and not (d['class'] == 'string' and 'length' not in d) and record['fillDefined']:
        record['fill'] = canonical(ds.fillvalue, d) if not d.get('dims') else None
    if layout == 'external':
        record['external'] = [[e[0].decode() if isinstance(e[0], bytes) else e[0], int(e[1]), int(e[2])] for e in ds.external]
    if layout == 'virtual':
        record['virtual'] = [{'file': m.file_name, 'dataset': m.dset_name, 'count': int(m.vspace.get_select_npoints())} for m in ds.virtual_sources()]
    for axis in range(ds.ndim):
        dim = ds.dims[axis]
        record['dims'].append({'label': dim.label, 'scales': [address(s) for s in dim.values()]})
    n = int(np.prod(ds.shape)) if ds.shape else 1
    needed = [e[0] for e in record.get('external', [])] + [m['file'] for m in record.get('virtual', []) if m['file'] != '.']
    record['missingFiles'] = sorted({name for name in needed if not os.path.isfile(name)})
    if record['missingFiles']:
        record['values'] = None
        return record
    if n <= budget['elements']:
        budget['elements'] -= n
        if d['class'] == 'reference':
            arr = ds[()] if ds.shape else np.array([ds[()]])
            targets = [reference_target(f, r, d) for r in np.asarray(arr).reshape(-1)[:65536]]
            record['targets'] = targets
            record['values'] = summarise(targets)
        else:
            arr = ds[()]
            arr = np.asarray(arr)
            record['values'] = summarise(element_iter(arr, d))
            if d['class'] in ('int', 'uint', 'float') and n:
                finite = np.isfinite(arr) if d['class'] == 'float' else np.ones(arr.shape, bool)
                record['stats'] = {'finite': int(finite.sum()), 'nan': int(np.isnan(arr).sum()) if d['class'] == 'float' else 0,
                                   'minimum': canonical(arr[finite].min(), d) if finite.any() else None,
                                   'maximum': canonical(arr[finite].max(), d) if finite.any() else None}
        if layout == 'chunked' and not record.get('virtual'):
            try:
                record['allocatedChunks'] = int(ds.id.get_num_chunks())
            except Exception:
                record['allocatedChunks'] = None
    else:
        record['values'] = None
    return record


def manifest(name, config):
    import h5py
    import numpy as np
    budget = {'elements': config.get('valueBudget', 16 * 1024 * 1024)}
    out = {'objects': {}, 'links': {}, 'file': {}}
    kw = {}
    fsettings = config.get('fileSettings') or {}
    if fsettings.get('driver') in ('family', 'split'):
        kw = {k: v for k, v in file_kwargs(fsettings, 'r').items() if k in ('driver', 'memb_size', 'meta_ext', 'raw_ext')}
    with open_file(name, 'r', **kw) as f:
        observe_access(f)
        out['file'] = {'libver': list(f.libver), 'userblock': int(f.userblock_size), 'driver': f.driver,
                       'superblock': int(f.id.get_create_plist().get_version()[0])}
        root = f['/']
        out['objects']['/'] = {'kind': 'group', 'address': address(root), 'attributes': attributes(root),
                               'trackOrder': bool(root.id.get_create_plist().get_link_creation_order()), 'attributeOrder': attribute_order(root)}

        def visit(path, link):
            full = '/' + path
            if isinstance(link, h5py.SoftLink):
                out['links'][full] = {'kind': 'soft', 'target': link.path}
                return None
            if isinstance(link, h5py.ExternalLink):
                out['links'][full] = {'kind': 'external', 'file': link.filename, 'target': link.path}
                return None
            obj = f.get(full)
            if obj is None:
                out['links'][full] = {'kind': 'unresolved'}
                return None
            try:
                return describe_object(obj, full, rec_out=out, f=f, budget=budget, config=config, np=np)
            except Fault as fault:
                failures.append(fault)
                return 'stop'
            except (KeyError, ValueError, OSError, RuntimeError, TypeError) as error:
                failures.append(Fault('HDF5_UNREADABLE_OBJECT', 'the object cannot be read consistently: %s' % str(error)[:200], full))
                return 'stop'

        def describe_object(obj, full, rec_out, f, budget, config, np):
            rec = {'address': address(obj), 'attributes': attributes(obj)}
            if not isinstance(obj, h5py.Datatype):
                rec['attributeOrder'] = attribute_order(obj)
            if isinstance(obj, h5py.Group):
                rec['kind'] = 'group'
                rec['trackOrder'] = bool(obj.id.get_create_plist().get_link_creation_order())
            elif isinstance(obj, h5py.Datatype):
                rec['kind'] = 'datatype'
                rec['type'] = describe(obj.dtype)
            else:
                rec.update(dataset_record(obj, f, budget))
                rec['trackOrder'] = rec['attributeOrder'] is not None
                if full in config.get('regions', {}):
                    d = describe(obj.dtype)
                    rec['regions'] = [{k: v for k, v in summarise(element_iter(np.asarray(read_selection(obj, sel)), d)).items() if k != 'head'}
                                      for sel in config['regions'][full]]
            rec_out['objects'][full] = rec
            return None
        failures = []
        f.visititems_links(visit)
        if failures:
            raise failures[0]
        for full, rec in out['links'].items():
            if rec['kind'] == 'soft':
                target = rec['target'] if rec['target'].startswith('/') else (full.rsplit('/', 1)[0] or '') + '/' + rec['target']
                rec['resolves'] = target.rstrip('/') in out['objects'] or target == '/'
        out['addresses'] = {}
        for path, rec in out['objects'].items():
            out['addresses'].setdefault(rec['address'], []).append(path)
    return out


RESERVED = ('DIMENSION_LIST', 'REFERENCE_LIST')


def attributes(obj):
    return {name: attribute_record(obj, name) for name in obj.attrs if name not in RESERVED}


def attribute_order(obj):
    """Attribute names in creation order when the object tracks it (h5py then iterates in creation order), else None."""
    import h5py
    if not obj.id.get_create_plist().get_attr_creation_order() & h5py.h5p.CRT_ORDER_TRACKED:
        return None
    return [name for name in obj.attrs if name not in RESERVED]


# ---------------------------------------------------------------- admission
def preflight(target):
    """Metadata only: walk hard links, never follow soft/external links, read no dataset or attribute values."""
    import h5py
    settings = target.get('fileSettings')
    kw, name = {}, target['file']
    if settings and settings.get('driver') in ('family', 'split'):
        kw = {k: v for k, v in file_kwargs(settings, 'r').items() if k in ('driver', 'memb_size', 'meta_ext', 'raw_ext')}
        name = file_name(settings)
    out = {'datasets': {}, 'softLinks': {}, 'externalLinks': {}}
    with h5py.File(name, 'r', **kw) as f:
        count = [0]

        def visit(path, link):
            full = '/' + path
            count[0] += 1
            if count[0] > MAX_LINKS:
                return 'stop'
            if isinstance(link, h5py.SoftLink):
                out['softLinks'][full] = link.path
                return None
            if isinstance(link, h5py.ExternalLink):
                out['externalLinks'][full] = [link.filename, link.path]
                return None
            oid = h5py.h5o.open(f.id, full.encode())
            if isinstance(oid, h5py.h5d.DatasetID):
                dcpl = oid.get_create_plist()
                external = [dcpl.get_external(i)[0].decode('utf-8', 'replace') for i in range(dcpl.get_external_count())]
                virtual = []
                if dcpl.get_layout() == h5py.h5d.VIRTUAL:
                    virtual = [dcpl.get_virtual_filename(i) for i in range(dcpl.get_virtual_count())]
                filters = [int(dcpl.get_filter(i)[0]) for i in range(dcpl.get_nfilters())]
                out['datasets'][full] = {'external': external, 'virtual': virtual, 'filters': filters}
            return None
        f.visititems_links(visit)
    if count[0] > MAX_LINKS:
        raise Fault('HDF5_RESOURCE_LIMIT', 'the file holds more than %d links; inspect a smaller file or subset it first' % MAX_LINKS, '$.source')
    return out


# ---------------------------------------------------------------- extraction
def read_item(f, item, sel):
    """Selected values (and field subset) of one extract for one normal-form selection.

    Field subsets are read directly (HDF5 converts only the chosen members); streamed blocks of records are read as packed
    records, and a block whose in-memory size would exceed memoryBytes is refused before any value is read.
    """
    import numpy as np
    ds = f[item['dataset']]
    d = describe(ds.dtype)
    names = item.get('fields') or (list(ds.dtype.names) if ds.dtype.names and item.get('blocks') else None)
    if names:
        single = 'fields' in item and len(names) == 1
        memory = ds.dtype.fields[names[0]][0] if single else np.dtype([(n, ds.dtype.fields[n][0]) for n in names])
        source = ds.fields(names[0] if single else names)
    else:
        memory, source = ds.dtype, ds
    if item.get('blocks') and memory.itemsize * selection_count(ds, sel) > ACCESS.get('memoryBytes', 2 ** 62):
        raise Fault('HDF5_RESOURCE_LIMIT', 'a streamed block would hold %d bytes in memory, more than memoryBytes'
                    % (memory.itemsize * selection_count(ds, sel)), '$.extracts.' + item['id'], itemSize=memory.itemsize)
    data = read_selection(source, sel, ds, memory)
    if 'fields' in item:
        d = {'class': 'compound', 'fields': [next(fd for fd in d['fields'] if fd['name'] == name) for name in item['fields']]}
        if len(item['fields']) == 1:
            d = d['fields'][0]['type']
    return np.asarray(data), d


def selection_count(ds, sel):
    """Elements in one normal-form selection of a dataset."""
    if sel['kind'] == 'all':
        return int(ds.size)
    if sel['kind'] == 'points':
        return len(sel['points'])
    if sel['kind'] == 'rows':
        return len(sel['rows']) * math.prod(ds.shape[1:])
    if sel['kind'] == 'slices':
        return math.prod(len(range(a, b, c)) for a, b, c in sel['slices'])
    return math.prod(c * b for c, b in zip(sel['count'], sel['block']))


def coords_for(f, item, sel):
    import numpy as np
    coords = {}
    if item.get('coordinateScales'):
        for axis, scale in item['coordinateScales'].items():
            coords[axis] = np.asarray(read_selection(f[scale], axis0(sel))).reshape(-1)
    return coords


def axis0(sel):
    if sel['kind'] == 'all':
        return {'kind': 'all'}
    if sel['kind'] == 'slices':
        return {'kind': 'slices', 'slices': [sel['slices'][0]]}
    if sel['kind'] == 'hyperslab':
        return {'kind': 'hyperslab', **{k: [sel[k][0]] for k in ('start', 'count', 'stride', 'block')}}
    if sel['kind'] == 'rows':
        return sel
    return {'kind': 'points', 'points': [[q[0]] for q in sel['points']]}


class Accumulator:
    def __init__(self):
        self.hash = hashlib.sha256(b'[')
        self.count = 0
        self.head = []

    def add(self, e):
        if self.count:
            self.hash.update(b',')
        self.hash.update(json.dumps(e, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode())
        if len(self.head) < PREVIEW:
            self.head.append(e)
        self.count += 1

    def result(self):
        h = self.hash.copy()
        h.update(b']')
        return {'count': self.count, 'sha256': h.hexdigest(), 'head': self.head}


def stream_item(f, item):
    """Memory-bounded extraction: read and write one axis-0 block at a time, never the whole selection."""
    import numpy as np
    name = item['output']
    acc = Accumulator()
    baseline = rss_peak()
    largest, rows = 0, 0
    npy = None
    with open(name + '.tmp', 'w', encoding='utf-8', newline='') if item['format'] != 'npy' else open(os.devnull, 'w') as stream:
        for n, sel in enumerate(item['blocks']):
            data, d = read_item(f, item, sel)
            largest = max(largest, int(data.nbytes))
            for e in element_iter(data, d):
                acc.add(e)
            if item['format'] == 'csv':
                text = csv_text(item, data, d, coords_for(f, item, sel))
                stream.write(text if n == 0 else text.split('\n', 1)[1])
            elif item['format'] == 'json':
                if n == 0:
                    stream.write('{"shape": %s, "type": %s, "values": [' % (json.dumps(item['selectedShape']), json.dumps(d, sort_keys=True)))
                body = ', '.join(json.dumps(natural(v), allow_nan=False) for v in element_iter(data, d))
                stream.write((', ' if n and body and rows else '') + body)
            else:
                if npy is None:
                    npy = open(name + '.tmp.npy', 'wb')
                    header = {'descr': np.lib.format.dtype_to_descr(data.dtype), 'fortran_order': False, 'shape': tuple(item['selectedShape'])}
                    np.lib.format.write_array_header_1_0(npy, header)
                npy.write(np.ascontiguousarray(data).tobytes())
            rows += len(data) if data.ndim else 1
            del data
        if item['format'] == 'json':
            stream.write(']}\n')
    if item['format'] == 'npy':
        npy.close()
        os.replace(name + '.tmp.npy', name)
    else:
        os.replace(name + '.tmp', name)
    return {'id': item['id'], 'shape': list(item['selectedShape']), 'values': acc.result(),
            'streaming': {'blocks': len(item['blocks']), 'largestBlockBytes': largest, 'peakGrowthBytes': max(0, rss_peak() - baseline)}}


def extract(config):
    import h5py
    results = []
    with open_file(config['source'], 'r') as f:
        observe_access(f)
        for item in config['extracts']:
            chosen = where_digest(f, item) if 'where' in item else None
            if item['format'] == 'chunks':
                results.append(chunk_index(f, item))
            elif item.get('blocks'):
                results.append(stream_item(f, item))
            else:
                data, d = read_item(f, item, item['selection'])
                write_extract(item, data, d, coords_for(f, item, item['selection']))
                results.append({'id': item['id'], 'shape': list(data.shape), 'type': d, 'values': summarise(element_iter(data, d))})
            if chosen is not None:
                results[-1]['whereRows'] = chosen
    return results


def chunk_listing(ds, at):
    """HDF5's own record of every allocated chunk (direct chunk interface): position, file offset, size, filter mask, byte digest."""
    if ds.chunks is None:
        raise Fault('HDF5_EXTRACT_UNSUPPORTED', 'a chunk index needs a chunked dataset', at)
    dcpl = ds.id.get_create_plist()
    filters = [FILTERS.get(dcpl.get_filter(k)[0], 'filter-%d' % dcpl.get_filter(k)[0]) for k in range(dcpl.get_nfilters())]
    listed = []
    for k in range(ds.id.get_num_chunks()):
        info = ds.id.get_chunk_info(k)
        mask, raw = ds.id.read_direct_chunk(info.chunk_offset)
        listed.append({'offset': [int(o) for o in info.chunk_offset], 'byteOffset': int(info.byte_offset), 'size': int(info.size),
                       'filterMask': int(mask), 'sha256': hashlib.sha256(raw).hexdigest()})
    return {'dataset': ds.name, 'shape': list(ds.shape), 'chunkShape': list(ds.chunks), 'type': describe(ds.dtype), 'filters': filters, 'chunks': listed}


def chunk_index(f, item):
    """Write the chunk index of one extract."""
    index = {**chunk_listing(f[item['dataset']], '$.extracts.%s.format' % item['id']), 'dataset': item['dataset']}
    write_json(item['output'], index)
    return {'id': item['id'], 'shape': [len(index['chunks'])], 'chunks': len(index['chunks'])}


def chunk_list(target):
    """A fresh listing of one dataset's chunks from current bytes, for verification of a published index."""
    import h5py
    with open_file(target['file'], 'r') as f:
        observe_access(f)
        return chunk_listing(f[target['dataset']], '$')


def where_digest(f, item):
    """Rows (count and digest) where every condition holds, evaluated here with h5py and NumPy in bounded row blocks."""
    import numpy as np
    n = f[item['dataset']].shape[0]
    keep = np.ones(n, dtype=bool)
    for c in item['where']:
        ds = f[c['dataset']]
        source = ds.fields(c['field']) if 'field' in c else ds
        dtype = ds.dtype.fields[c['field']][0] if 'field' in c else ds.dtype
        for lo in range(0, n, 1 << 20):
            hi = min(n, lo + (1 << 20))
            keep[lo:hi] &= condition_mask(np.asarray(source[lo:hi]), dtype, c)
    rows = [int(r) for r in np.flatnonzero(keep)]
    return {'count': len(rows), 'sha256': hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()}


def condition_mask(a, dtype, c):
    """Rows of one block meeting one condition; integer operands take the dataset's exact integer type (never a float)."""
    import h5py
    import numpy as np
    op = c['op']
    enum = h5py.check_enum_dtype(dtype)
    text = h5py.check_string_dtype(dtype)
    if text is not None:
        a = np.array([x.decode(text.encoding) if isinstance(x, bytes) else str(x) for x in a.tolist()], dtype=object)
        value, values = c.get('value'), c.get('values')
    elif enum is not None and not (dtype == np.dtype('?') or set(enum) == {'FALSE', 'TRUE'} and dtype.itemsize == 1):
        value = enum[c['value']] if 'value' in c else None
        values = [enum[v] for v in c['values']] if 'values' in c else None
    elif dtype.kind == 'f':
        a = a.astype('<f8')
        value, values = c.get('value'), c.get('values')
    elif dtype.kind == 'b' or enum is not None:
        a = a.astype(bool)
        value, values = c.get('value'), c.get('values')
    else:
        value, values = c.get('value'), c.get('values')
    upper = c.get('upper')
    if a.dtype.kind in 'iu':
        exact = a.dtype.type
        value = None if value is None else exact(value)
        upper = None if upper is None else exact(upper)
        values = None if values is None else np.array(values, dtype=a.dtype)
    if op == 'eq':
        return np.asarray(a == value, dtype=bool)
    if op == 'ne':
        return np.asarray(a != value, dtype=bool)
    if op == 'lt':
        return a < value
    if op == 'le':
        return a <= value
    if op == 'gt':
        return a > value
    if op == 'ge':
        return a >= value
    if op == 'between':
        return (a >= value) & (a <= upper)
    if op == 'in':
        return np.array([x in values for x in a.tolist()], dtype=bool) if a.dtype == object else np.isin(a, values)
    if op == 'finite':
        return np.isfinite(a)
    return np.isnan(a)


def mpi_extract(config):
    """Each rank reads its axis-0 block of every selection through the mpio driver; rank 0 gathers in rank order and writes."""
    import h5py
    import numpy as np
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    identity = mpi_identity(comm, h5py)
    rank = identity['rank']
    results, rows = [], {}
    with open_file(config['source'], 'r', driver='mpio', comm=comm) as f:
        observe_access(f)
        identity['driver'] = f.driver
        for item in config['extracts']:
            sel = item['parallelBlocks'][rank]
            ds = f[item['dataset']]
            if config['io'] == 'collective':
                with ds.collective:
                    part, d = read_item(f, item, sel)
            else:
                part, d = read_item(f, item, sel)
            rows[item['id']] = int(len(part)) if part.ndim else 1
            parts = comm.gather(part, root=0)
            if rank == 0:
                data = np.concatenate([p for p in parts if p.size or p.ndim == 0]) if any(p.size for p in parts) else parts[0]
                data = data.reshape(item['selectedShape'])
                write_extract(item, data, d, coords_for(f, item, item['selection']))
                results.append({'id': item['id'], 'shape': list(data.shape), 'type': d, 'values': summarise(element_iter(data, d))})
    identity['rows'] = rows
    identity['io'] = config['io']
    write_json('mpi-extract-rank-%d.json' % rank, identity)
    comm.Barrier()
    return {'extracts': results}


def write_extract(item, data, d, coords):
    import numpy as np
    name = item['output']
    if item['format'] == 'npy':
        np.save(name + '.tmp.npy', np.ascontiguousarray(data), allow_pickle=False)
        os.replace(name + '.tmp.npy', name)
    elif item['format'] == 'json':
        write_json(name, {'shape': list(data.shape), 'type': d, 'values': [natural(v) for v in element_iter(data, d)]})
    else:
        with open(name + '.tmp', 'w', encoding='utf-8', newline='') as stream:
            stream.write(item['csvText'](data, d, coords) if callable(item.get('csvText')) else csv_text(item, data, d, coords))
        os.replace(name + '.tmp', name)


def csv_cell(value, d):
    cls = d['class']
    if cls == 'float':
        x = float(value)
        if math.isnan(x):
            return 'nan'
        if math.isinf(x):
            return 'inf' if x > 0 else '-inf'
        return repr(x)
    if cls in ('int', 'uint', 'enum'):
        return str(int(value))
    if cls == 'bool':
        return 'true' if value else 'false'
    if cls == 'string':
        text = value.decode(d['encoding']) if isinstance(value, bytes) else str(value)
        return '"' + text.replace('"', '""') + '"'
    raise Fault('HDF5_EXTRACT_UNSUPPORTED', 'CSV cells hold numeric, bool, enum or string values')


def csv_text(item, data, d, coords):
    import numpy as np
    headers = item['headers']
    lines = [','.join('"' + h.replace('"', '""') + '"' if any(c in h for c in ',"\n\r') or h != h.strip() else h for h in headers)]
    if d['class'] == 'compound':
        rows = data.reshape(-1)
        axis0 = coords.get('0')
        for i, rec in enumerate(rows):
            cells = ([csv_cell(axis0[i], item['coordinateType'])] if axis0 is not None else []) + [csv_cell(rec[f['name']], f['type']) for f in d['fields']]
            lines.append(','.join(cells))
    elif data.ndim <= 1:
        flat = data.reshape(-1)
        axis0 = coords.get('0')
        for i, v in enumerate(flat):
            cells = ([csv_cell(axis0[i], item['coordinateType'])] if axis0 is not None else []) + [csv_cell(v, d)]
            lines.append(','.join(cells))
    else:
        rows = data.reshape(data.shape[0], -1)
        axis0 = coords.get('0')
        for i, row in enumerate(rows):
            cells = ([csv_cell(axis0[i], item['coordinateType'])] if axis0 is not None else []) + [csv_cell(v, d) for v in row]
            lines.append(','.join(cells))
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- editing
def edit(config):
    import h5py
    import numpy as np
    f_settings = config['file']
    name = config['working']
    ctx = {'created': set(), 'references': [], 'dependencies': config.get('dependencies', {})}
    log = []
    with open_file(name, 'r+') as f:
        observe_access(f)
        for i, e in enumerate(config['edits']):
            action = e['action']
            try:
                apply_edit(f, e, ctx)
            except Fault:
                raise
            except (KeyError, ValueError, TypeError, OSError, RuntimeError) as error:
                if 'message is too large' in str(error):
                    raise Fault('HDF5_ATTRIBUTE_TOO_LARGE', 'the attribute exceeds the 64 KiB compact attribute message of this object; '
                                'objects that track attribute creation order, or were written with libver v108 or later, store large '
                                'attributes densely; put the attribute on such an object (for example one created with trackOrder true)', '$.edits[%d]' % i)
                raise Fault('HDF5_EDIT_REFUSED', '%s refused by HDF5: %s' % (action, error), '$.edits[%d]' % i)
            log.append({'index': i, 'action': action})
        for o in ctx['references']:
            fill_references(f, o)
    if config.get('repack'):
        repack(name, f_settings['name'], f_settings)
        os.remove(name)
    else:
        os.replace(name, f_settings['name'])
    return {'applied': log}


def copy_chunks(src, dst, at):
    """Write every stored chunk of src into dst unchanged (no decompression or recompression); layouts must match exactly."""
    def pipeline(ds):
        dcpl = ds.id.get_create_plist()
        return [(int(c), int(flags), tuple(int(v) for v in values)) for c, flags, values, _ in (dcpl.get_filter(k) for k in range(dcpl.get_nfilters()))]
    if src.chunks is None or src.chunks != dst.chunks or src.shape != dst.shape or src.dtype != dst.dtype or pipeline(src) != pipeline(dst):
        raise Fault('HDF5_CHUNK_LAYOUT_MISMATCH', 'copyChunks needs identical shape, chunk shape, element type and filter pipeline', at)
    grid = math.prod(-(-n // c) for n, c in zip(src.shape, src.chunks))
    if src.id.get_num_chunks() != grid:
        raise Fault('HDF5_CHUNK_LAYOUT_MISMATCH', 'copyChunks needs every chunk of the source allocated (%d of %d are)' % (src.id.get_num_chunks(), grid), at)
    for k in range(grid):
        offset = src.id.get_chunk_info(k).chunk_offset
        mask, raw = src.id.read_direct_chunk(offset)
        dst.id.write_direct_chunk(offset, raw, mask)


def apply_edit(f, e, ctx):
    import h5py
    import numpy as np
    action = e['action']
    if action == 'create':
        create_object(f, e['object'], ctx)
        for d in e['object'].get('dimensions', []):
            ds = f[e['object']['path']]
            for s in d['scales']:
                ds.dims[d['axis']].attach_scale(f[s])
            if 'label' in d:
                ds.dims[d['axis']].label = d['label']
    elif action == 'delete':
        detach_for_delete(f, e['path'])
        del f[e['path']]
    elif action == 'move':
        parent_path = e['to'].rsplit('/', 1)[0] or '/'
        f.require_group(parent_path)
        f.move(e['path'], e['to'])
    elif action == 'copy':
        other = h5py.File(e['fromName'], 'r') if 'fromName' in e else None
        source = other if other is not None else f
        try:
            parent_path = e['to'].rsplit('/', 1)[0] or '/'
            f.require_group(parent_path)
            source.copy(source[e['path']], f, name=e['to'], shallow=e['shallow'], expand_soft=e['expandSoft'],
                        expand_external=False, expand_refs=False, without_attrs=e['withoutAttributes'])
            if not e['withoutAttributes']:
                pairs = [(sp, e['to'] + sp[len(e['path']):]) for sp in dataset_paths(source, e['path'])]
                rebuild_dims(f, source, pairs, e['path'], e['to'], same_file=other is None)
        finally:
            if other is not None:
                other.close()
    elif action == 'link':
        parent_path = e['link']['path'].rsplit('/', 1)[0] or '/'
        f.require_group(parent_path)
        create_link(f, e['link'])
    elif action == 'setAttribute':
        obj = f[e['path']]
        if e['attribute']['name'] in obj.attrs:
            del obj.attrs[e['attribute']['name']]
        create_attribute(obj, e['attribute'])
    elif action == 'deleteAttribute':
        del f[e['path']].attrs[e['name']]
    elif action == 'renameAttribute':
        obj = f[e['path']]
        aid = h5py.h5a.open(obj.id, e['name'].encode())
        space, tid = aid.get_space(), aid.get_type()
        if space.get_simple_extent_type() == h5py.h5s.NULL:
            obj.attrs.create(e['newName'], h5py.Empty(aid.dtype))
        else:
            data = np.empty(space.shape, dtype=aid.dtype)
            aid.read(data)
            new = h5py.h5a.create(obj.id, e['newName'].encode(), tid, space)
            new.write(data)
        del obj.attrs[e['name']]
    elif action == 'write':
        ds = f[e['path']]
        values = payload(e['payload'])
        array = materialise(values, e.get('fieldType', e['type']), e['selectedShape'])
        write_selection(ds, e['selection'], array, tuple(e.get('fields', ())))
    elif action == 'resize':
        f[e['path']].resize(tuple(e['shape']))
    elif action == 'copyChunks':
        copy_chunks(f[e['path']], f[e['to']], '$.edits[%d]' % e['index'])
    elif action == 'append':
        ds = f[e['path']]
        axis = e['axis']
        values = payload(e['payload'])
        array = materialise(values, e['type'], e['appendShape'])
        old = ds.shape[axis]
        new = list(ds.shape)
        new[axis] = old + array.shape[axis]
        ds.resize(tuple(new))
        key = [slice(None)] * ds.ndim
        key[axis] = slice(old, new[axis])
        ds[tuple(key)] = array
    elif action == 'makeScale':
        f[e['path']].make_scale(e.get('name', ''))
    elif action == 'attachScale':
        f[e['path']].dims[e['axis']].attach_scale(f[e['scale']])
    elif action == 'detachScale':
        f[e['path']].dims[e['axis']].detach_scale(f[e['scale']])
    elif action == 'relayout':
        relayout(f, e)


def relayout(f, e):
    import h5py
    path = e['path']
    old = f[path]
    temp = path + '__schemaxis_relayout'
    o = {'path': temp, 'kind': 'dataset', 'type': e['type'], 'shape': list(old.shape), 'maxshape': e['maxshape'],
         'storage': e['storage'], 'data': {'source': 'fill'}, 'attributes': []}
    o['trackOrder'] = attribute_order(old) is not None
    kw = storage_kwargs(o, f, {})
    if o['trackOrder']:
        kw['track_order'] = True
    parent_path, name = temp.rsplit('/', 1)
    group = f[parent_path or '/']
    if e['storage']['layout'] == 'compact' or 'fillTime' in e['storage'] or 'allocTime' in e['storage'] or e['storage'].get('nbit'):
        new = low_level_dataset(group, name, o, kw, old[()])
    else:
        new = group.create_dataset(name, shape=old.shape, dtype=old.dtype, data=old[()], **kw)
    for key, value in old.attrs.items():
        if key in ('DIMENSION_LIST', 'REFERENCE_LIST', 'CLASS', 'NAME'):
            continue
        new.attrs.create(key, value, dtype=old.attrs.get_id(key).dtype)
    if old.is_scale:
        raise Fault('HDF5_EDIT_REFUSED', 'relayout of a dimension scale would detach its datasets; relayout the datasets instead', path)
    scales = [[s for s in old.dims[a].values()] for a in range(old.ndim)]
    labels = [old.dims[a].label for a in range(old.ndim)]
    for a, items in enumerate(scales):
        for s in items:
            old.dims[a].detach_scale(s)
    del f[path]
    f.move(temp, path)
    new = f[path]
    for a, items in enumerate(scales):
        for s in items:
            new.dims[a].attach_scale(s)
        if labels[a]:
            new.dims[a].label = labels[a]


def detach_for_delete(f, root):
    """Detach dimension scales to or from deleted datasets so no scale keeps back-references to unnamed objects."""
    import h5py
    inside = lambda path: path == root or path.startswith(root.rstrip('/') + '/')
    by_address = paths_by_address(f)
    doomed = {a for a, paths in by_address.items() if all(inside(p) for p in paths)}
    for path in dataset_paths(f, '/'):
        ds = f[path]
        for axis in range(ds.ndim):
            for scale in list(ds.dims[axis].values()):
                if address(ds) in doomed or address(scale) in doomed:
                    ds.dims[axis].detach_scale(scale)


def dataset_paths(f, root):
    import h5py
    out = []
    obj = f[root]
    if isinstance(obj, h5py.Dataset):
        return [root]

    def visit(name, item):
        if isinstance(item, h5py.Dataset):
            out.append(root.rstrip('/') + '/' + name)
    obj.visititems(visit)
    return sorted(out)


def paths_by_address(f):
    import h5py
    table = {}

    def visit(name, link):
        if isinstance(link, h5py.HardLink):
            obj = f.get('/' + name)
            if obj is not None:
                table.setdefault(address(obj), []).append('/' + name)
    f.visititems_links(visit)
    return {k: sorted(v) for k, v in table.items()}


def rebuild_dims(dst, src, pairs, root, to, same_file):
    """Reattach scales on copied datasets: scales inside the copied tree map to their copies, others stay shared."""
    by_address = paths_by_address(src)
    inside = lambda path: path == root or path.startswith(root.rstrip('/') + '/')
    plan = []
    for sp, dp in pairs:
        s = src[sp]
        axes = []
        for axis in range(s.ndim):
            targets = []
            for scale in s.dims[axis].values():
                candidates = by_address.get(address(scale), [scale.name])
                mapped = [to + c[len(root):] for c in candidates if inside(c)]
                if mapped:
                    targets.append(mapped[0])
                elif same_file:
                    targets.append(candidates[0])
            axes.append(targets)
        plan.append((dp, axes))
    for dp, _ in plan:
        d = dst[dp]
        for name in ('DIMENSION_LIST', 'REFERENCE_LIST'):
            if name in d.attrs:
                del d.attrs[name]
    for dp, axes in plan:
        d = dst[dp]
        for axis, targets in enumerate(axes):
            for target in targets:
                d.dims[axis].attach_scale(dst[target])


def repack(source, target, f_settings):
    """Fresh-file rewrite that preserves hard-link aliasing, dimension scales and references."""
    import h5py
    import numpy as np
    with open_file(source, 'r') as src, open_file(target, 'w', **file_kwargs(f_settings, 'w')) as dst:
        for key in src.attrs:
            dst.attrs.create(key, src.attrs[key], dtype=src.attrs.get_id(key).dtype)
        for key, a in src.attrs.items():
            pass
        ocp = h5py.h5p.create(h5py.h5p.OBJECT_COPY)
        ocp.set_copy_object(MERGE_COMMITTED_DTYPE)
        committed = []

        def find(path, obj):
            if isinstance(obj, h5py.Datatype):
                committed.append(path.split('/')[0])
        src.visititems(find)
        names = sorted(src, key=lambda n: (n not in committed, n))
        for name in names:
            link = src.get(name, getlink=True)
            if isinstance(link, (h5py.SoftLink, h5py.ExternalLink)):
                dst[name] = link
            else:
                h5py.h5o.copy(src.id, name.encode(), dst.id, name.encode(), copypl=ocp)
        aliases = paths_by_address(src)
        for paths in aliases.values():
            first = paths[0]
            for other in paths[1:]:
                if other in dst and not other.startswith(first + '/'):
                    del dst[other]
                    dst[other] = dst[first]
        rebuild_dims(dst, src, [(p, p) for p in dataset_paths(src, '/')], '/', '/', same_file=False)
        for p in dataset_paths(src, '/'):
            ds = src[p]
            r = h5py.check_ref_dtype(ds.dtype)
            if r is None or ds.shape is None:
                continue
            values = np.asarray(ds[()]).reshape(-1)
            out = np.empty(values.shape, dtype=ds.dtype)
            for i, ref in enumerate(values):
                if not ref:
                    out[i] = ref
                    continue
                try:
                    target_obj = src[ref]
                    named = aliases.get(address(target_obj))
                except (KeyError, ValueError, OSError, RuntimeError):
                    named = None
                if not named:
                    out[i] = h5py.Reference() if r is h5py.Reference else h5py.RegionReference()
                    continue
                path = named[0]
                if r is h5py.Reference:
                    out[i] = dst[path].ref
                else:
                    space = h5py.h5r.get_region(ref, target_obj.id)
                    out[i] = h5py.h5r.create(dst[path].id, b'.', h5py.h5r.DATASET_REGION, space)
            dst[p][...] = out.reshape(ds.shape)


# ---------------------------------------------------------------- SWMR
def swmr_writer(config):
    import h5py
    import numpy as np
    s = config['series']
    f_settings = config['file']
    dt = np_dtype(s['type'])
    width = s['width']
    shape = (0,) if width == 1 else (0, width)
    maxshape = (None,) if width == 1 else (None, width)
    chunks = (s['chunkRows'],) if width == 1 else (s['chunkRows'], width)
    kw = {'compression': s['compression']} if s['compression'] != 'none' else {}
    timeline = []
    with open_file(f_settings['name'], 'w', libver='latest') as f:
        observe_access(f)
        group_path = s['dataset'].rsplit('/', 1)[0] or '/'
        f.require_group(group_path)
        ds = f.create_dataset(s['dataset'], shape=shape, maxshape=maxshape, chunks=chunks, dtype=dt, track_times=False, **kw)
        if 'units' in s:
            ds.attrs['units'] = s['units']
        if config['swmr']:
            f.swmr_mode = True
        write_json('swmr-ready.json', {'pid': os.getpid(), 'swmr': bool(f.swmr_mode)})
        for i, batch in enumerate(config['batches']):
            values = payload(batch['payload'])
            rows = len(values) // width
            array = materialise(values, s['type'], [rows] if width == 1 else [rows, width])
            old = ds.shape[0]
            ds.resize(old + rows, axis=0)
            ds[old:old + rows] = array
            ds.flush()
            f.flush()
            timeline.append({'batch': i, 'rows': old + rows, 'time': time.monotonic()})
            write_json('swmr-progress.json', {'batches': i + 1, 'rows': old + rows})
            deadline = time.monotonic() + config.get('readerWait', 5.0)
            while config['readers'] and time.monotonic() < deadline:
                acks = [p for p in os.listdir('.') if p.startswith('swmr-ack-') and p.endswith('-%d.json' % i)]
                if len(acks) >= config['readers']:
                    break
                time.sleep(0.02)
    return {'timeline': timeline}


def swmr_reader(config, index):
    import h5py
    import numpy as np
    s = config['series']
    deadline = time.monotonic() + config.get('readerTimeout', 30.0)
    while not os.path.exists('swmr-ready.json'):
        if time.monotonic() > deadline:
            raise Fault('HDF5_SWMR_TIMEOUT', 'writer never became ready', '$.swmr')
        time.sleep(0.02)
    observed = []
    d = None
    with open_file(config['file']['name'], 'r', libver='latest', swmr=True) as f:
        observe_access(f)
        ds = f[s['dataset']]
        d = describe(ds.dtype)
        seen = 0
        total = len(config['batches'])
        while seen < total:
            if time.monotonic() > deadline:
                raise Fault('HDF5_SWMR_TIMEOUT', 'reader did not observe every batch', '$.swmr', observed=seen)
            try:
                progress = read_json('swmr-progress.json')
            except (OSError, ValueError):
                time.sleep(0.02)
                continue
            if progress['batches'] <= seen:
                time.sleep(0.02)
                continue
            ds.refresh()
            rows = ds.shape[0]
            data = ds[:rows]
            observed.append({'batch': seen, 'rows': int(rows), 'values': summarise(element_iter(np.asarray(data), d))})
            write_json('swmr-ack-%d-%d.json' % (index, seen), {'rows': int(rows)})
            seen += 1
    return {'reader': index, 'observed': observed}


# ---------------------------------------------------------------- comparison
def compare(config):
    left = manifest(config['source'], {'valueBudget': 16 * 1024 * 1024})
    right = manifest(config['reference'], {'valueBudget': 16 * 1024 * 1024})
    import h5py
    import numpy as np
    differences = []
    tol = config['tolerance']
    paths = config.get('paths') or sorted(set(left['objects']) | set(right['objects']))
    with open_file(config['source'], 'r') as a, open_file(config['reference'], 'r') as b:
        for path in paths:
            la, rb = left['objects'].get(path), right['objects'].get(path)
            if la is None or rb is None:
                differences.append({'path': path, 'kind': 'presence', 'source': la is not None, 'reference': rb is not None})
                continue
            if la['kind'] != rb['kind']:
                differences.append({'path': path, 'kind': 'objectKind'})
                continue
            if tol['attributes'] and la['attributes'] != rb['attributes']:
                differences.append({'path': path, 'kind': 'attributes', 'names': sorted(set(la['attributes']) ^ set(rb['attributes'])) or sorted(
                    n for n in la['attributes'] if la['attributes'][n] != rb['attributes'].get(n))})
            if la['kind'] != 'dataset':
                continue
            if la['type'] != rb['type'] or la['shape'] != rb['shape']:
                differences.append({'path': path, 'kind': 'typeOrShape', 'source': [la['type'], la['shape']], 'reference': [rb['type'], rb['shape']]})
                continue
            if tol['storage'] and (la['layout'], la['chunks'], la['filters']) != (rb['layout'], rb['chunks'], rb['filters']):
                differences.append({'path': path, 'kind': 'storage'})
            if la.get('null'):
                continue
            if la['type']['class'] in ('int', 'uint', 'float'):
                x, y = np.asarray(a[path][()], dtype=np.float64), np.asarray(b[path][()], dtype=np.float64)
                both_nan = np.isnan(x) & np.isnan(y)
                diff = np.abs(x - y)
                limit = tol['absolute'] + tol['relative'] * np.abs(y)
                bad = ~both_nan & ~(diff <= limit)
                if bad.any():
                    idx = np.argwhere(bad)
                    differences.append({'path': path, 'kind': 'values', 'count': int(bad.sum()),
                                        'first': [int(v) for v in idx[0]] if idx.size else [], 'maxAbsolute': float(np.nanmax(np.where(bad, diff, 0)))})
            elif la.get('values') != rb.get('values'):
                differences.append({'path': path, 'kind': 'values', 'count': None})
    return {'differences': differences, 'compared': len(paths), 'equal': not differences}


# ---------------------------------------------------------------- MPI
def mpi_identity(comm, h5py):
    from mpi4py import MPI
    if not h5py.get_config().mpi:
        raise Fault('HDF5_UNSUPPORTED_RUNTIME', 'parallelWrite needs h5py built with MPI (HDF5_MPI=ON)', '$.runtime')
    return {'rank': comm.Get_rank(), 'size': comm.Get_size(), 'pid': os.getpid(), 'host': MPI.Get_processor_name(),
            'mpi': MPI.Get_library_version().strip().split(',')[0][:40], 'mpi4py': __import__('mpi4py').__version__}


def mpi_write(config):
    import h5py
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    identity = mpi_identity(comm, h5py)
    rank = identity['rank']
    f_settings = config['file']
    rows = {}
    kw = {k: v for k, v in file_kwargs(f_settings, 'w').items() if k in ('libver', 'track_order')}
    with h5py.File(f_settings['name'], 'w', driver='mpio', comm=comm, **kw) as f:
        identity['driver'] = f.driver
        for a in f_settings['attributes']:
            create_attribute(f, a)
        for o in config['objects']:
            if o['kind'] != 'dataset':
                create_object(f, o, {'created': set(), 'references': [], 'dependencies': {}})
                continue
            parent_path, name = o['path'].rsplit('/', 1)
            group = f.require_group(parent_path or '/')
            kwargs = storage_kwargs(o, f, {})
            s = o['storage']
            if s.get('nbit') or 'fillTime' in s or 'allocTime' in s:
                ds = low_level_dataset(group, name, o, kwargs, None)
            else:
                ds = group.create_dataset(name, shape=tuple(o['shape']), dtype=np_dtype(o['type']), **kwargs)
            for a in o.get('attributes', []):
                create_attribute(ds, a)
            lo, hi = config['partitions'][o['path']][rank]
            full = dataset_value(o, f)
            if full is not None:
                if config['io'] == 'collective':
                    with ds.collective:
                        ds[lo:hi] = full[lo:hi]
                else:
                    ds[lo:hi] = full[lo:hi]
            rows[o['path']] = [lo, hi]
    identity['rows'] = rows
    identity['io'] = config['io']
    write_json('mpi-write-rank-%d.json' % rank, identity)
    comm.Barrier()
    return {'ranks': identity['size']}


def mpi_reduce(config):
    import h5py
    import numpy as np
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    identity = mpi_identity(comm, h5py)
    rank = identity['rank']
    out = {}
    with h5py.File(config['file']['name'], 'r', driver='mpio', comm=comm) as f:
        for o in config['objects']:
            if o['kind'] != 'dataset':
                continue
            lo, hi = config['partitions'][o['path']][rank]
            ds = f[o['path']]
            with ds.collective:
                local = np.asarray(ds[lo:hi])
            flat = local.reshape(-1)
            is_float = flat.dtype.kind == 'f'
            values = [float(x) for x in flat] if is_float else [int(x) for x in flat]
            finite = [x for x in values if not is_float or math.isfinite(x)]
            count = comm.allreduce(len(values), op=MPI.SUM)
            total = comm.allreduce(math.fsum(finite) if is_float else sum(finite), op=MPI.SUM)
            low = comm.allreduce(min(finite) if finite else None, op=MPI.MIN) if all(comm.allgather(bool(finite))) else None
            high = comm.allreduce(max(finite) if finite else None, op=MPI.MAX) if low is not None else None
            out[o['path']] = {'count': count, 'sum': total.hex() if is_float else total,
                              'minimum': (low.hex() if is_float else low) if low is not None else None,
                              'maximum': (high.hex() if is_float else high) if high is not None else None,
                              'localRows': [lo, hi]}
    write_json('mpi-reduce-rank-%d.json' % rank, {**identity, 'reduced': out})
    comm.Barrier()
    return {'reduced': out}


# ---------------------------------------------------------------- main
def main():
    stage = sys.argv[1]
    try:
        runtime = runtime_identity()
        config = read_json('native-config.json')
        ACCESS.update(config.get('access') or {})
        if stage == 'build':
            result = build(config)
        elif stage == 'edit':
            result = edit(config)
        elif stage.startswith('preflight-'):
            result = preflight(config['preflights'][stage])
        elif stage.startswith('readback') or stage.startswith('inspect'):
            target = config['manifests'][stage]
            result = manifest(target['file'], {**config, **target})
        elif stage == 'extract':
            result = {'extracts': extract(config)}
        elif stage.startswith('chunk-list-'):
            result = chunk_list(config['chunkLists'][stage])
        elif stage == 'swmr-writer':
            result = swmr_writer(config)
        elif stage.startswith('swmr-reader-'):
            result = swmr_reader(config, int(stage.rsplit('-', 1)[1]))
        elif stage == 'compare':
            result = compare(config)
        elif stage in ('mpi-write', 'mpi-reduce', 'mpi-extract'):
            result = {'mpi-write': mpi_write, 'mpi-reduce': mpi_reduce, 'mpi-extract': mpi_extract}[stage](config)
            from mpi4py import MPI
            if MPI.COMM_WORLD.Get_rank() != 0:
                return
        else:
            raise Fault('HDF5_UNKNOWN_STAGE', 'unknown stage ' + stage)
        write_json(stage + '-result.json', {'runtime': runtime, 'result': result, 'access': OBSERVED_ACCESS or None})
    except Fault as fault:
        name = stage + '-fault.json'
        if stage.startswith('mpi-'):
            try:
                from mpi4py import MPI
                name = '%s-fault-%d.json' % (stage, MPI.COMM_WORLD.Get_rank())
            except ImportError:
                pass
        write_json(name, fault.payload)
        sys.exit(3)


if __name__ == '__main__':
    main()
