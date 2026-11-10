"""Trusted xarray worker; copied into the owned run directory and never host-imported.

Run as: python -I -B native-worker.py compute|readback   (working directory = run directory)
Reads native-config.json and source.nc. compute opens the captured file with xarray engine='scipy', selects
by coordinate label, reduces and writes profile.nc (xarray to_netcdf) and profile.csv; readback is a separate
process that freshly reopens profile.nc. Structured refusals are written to <stage>-fault.json with exit
status 3; readback failures exit 4. The host verifier owns every acceptance decision.
"""
import hashlib
import json
import math
import os
import sys

REQUIRED = {'xarray': '2026.9.0', 'scipy': '1.18.1', 'numpy': '2.5.4'}
MAX_BYTES = 4 * 1024 * 1024


class Fault(Exception):
    def __init__(self, code, message, location='$', **details):
        super().__init__(message)
        self.payload = {'code': code, 'message': message, 'location': location, 'details': details}


def bounded(name, limit=MAX_BYTES):
    import stat
    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise Fault('XR_RESOURCE_LIMIT', 'native input is not a bounded regular file', name)
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise Fault('XR_RESOURCE_LIMIT', 'native input exceeds its byte budget', name)
    return data


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(text):
    def bad(token):
        raise ValueError('non-finite JSON constant ' + token)
    return json.loads(text, parse_constant=bad)


def write_json(name, value):
    with open(name + '.tmp', 'w') as stream:
        stream.write(json.dumps(value, indent=1, allow_nan=False, sort_keys=True) + '\n')
    os.replace(name + '.tmp', name)


def runtime_identity():
    """Observed in-process identity: versions, loader file locations and the engine actually used."""
    import numpy
    import scipy
    import xarray
    observed = {'xarray': xarray.__version__, 'scipy': scipy.__version__, 'numpy': numpy.__version__}
    for name, version in REQUIRED.items():
        if observed[name] != version:
            raise Fault('XR_UNSUPPORTED_RUNTIME', 'qualified for %s %s only' % (name, version), '$.runtime', observed=observed[name])
    from xarray.backends import scipy_
    import scipy.io
    return {**observed, 'python': sys.version.split()[0], 'pid': os.getpid(),
            'loaders': {'xarray': os.path.dirname(xarray.__file__), 'xarrayScipyBackend': os.path.basename(scipy_.__file__),
                        'scipyNetcdf': os.path.basename(scipy.io.netcdf_file.__module__)}}


def text(attrs, name):
    value = attrs.get(name)
    if value is not None and not isinstance(value, str):
        raise Fault('XR_TYPE_UNSUPPORTED', name + ' is not a text attribute', '$.source.' + name)
    return value


def open_source(config):
    import xarray as xr
    ds = xr.open_dataset('source.nc', engine='scipy', decode_cf=False, mask_and_scale=False, decode_times=False,
                         decode_timedelta=False, decode_coords=False)
    names = [d['name'] for d in config['coordinates']]
    name = config['variable']['name']
    if tuple(ds[name].dims) != tuple(names):
        raise Fault('XR_DIMENSION_ORDER', 'native dimension order differs from the declaration', '$.coordinates', storage=list(ds[name].dims))
    for d in config['coordinates']:
        if text(ds[d['name']].attrs, 'units') != d['unit']:
            raise Fault('XR_UNITS_MISMATCH', 'native coordinate units differ', '$.coordinates.' + d['name'])
    if text(ds[name].attrs, 'units') != config['variable']['unit'] or ds[name].attrs.get('_FillValue') != config['missing']['value']:
        raise Fault('XR_UNITS_MISMATCH', 'native variable units or _FillValue differ', '$.variable')
    return ds


def digest(array):
    import numpy as np
    return sha(np.ascontiguousarray(array, dtype='>f8').tobytes())


def compute():
    import numpy as np
    import xarray as xr
    config_bytes = bounded('native-config.json', 1024 * 1024)
    config = strict_json(config_bytes.decode('utf-8'))
    source = bounded('source.nc')
    write_json('compute-inputs.json', {'source.nc': sha(source), 'native-config.json': sha(config_bytes),
                                       'native-worker.py': sha(bounded('native-worker.py'))})
    if sha(source) != config['sourceSha256']:
        raise Fault('XR_SOURCE_CHANGED', 'captured source differs from the planned digest', 'source.nc')
    identity = runtime_identity()
    ds = open_source(config)
    name, retain = config['variable']['name'], config['retain']
    miss = config['missing']
    sentinel = miss['value']
    da = ds[name]
    for d in config['coordinates']:
        if 'range' in d:
            da = da.sel({d['name']: slice(d['range']['minimum'], d['range']['maximum'])})
    others = [d['name'] for d in config['coordinates'] if d['name'] != retain]
    valid = da != sentinel
    masked = da.where(valid)
    cells = int(np.prod([da.sizes[o] for o in others]))
    validCount = valid.sum(dim=others)
    missingCount = cells - validCount
    mean = masked.mean(dim=others, skipna=miss['policy'] == 'skip')
    if miss['policy'] == 'refuse' and int(missingCount.values.sum()):
        raise Fault('XR_MISSING_VALUES', 'a selected cell equals the missing sentinel and the policy is refuse', '$.missing')
    if miss['policy'] == 'skip' and int(validCount.values.min()) < miss['minimumValid']:
        raise Fault('XR_INSUFFICIENT_VALID', 'fewer valid cells than minimumValid', '$.missing')
    coord = da[retain]
    means = np.where(np.isnan(mean.values), sentinel, mean.values).astype('float64')
    if miss['policy'] == 'propagate':
        means = np.where(missingCount.values > 0, sentinel, means)
    elif not np.isfinite(mean.values).all():
        raise Fault('XR_NONFINITE_VALUE', 'a reduced mean is not finite', '$.retain')
    unit_attrs = {'units': config['variable']['unit'], '_FillValue': float(sentinel)}
    if text(ds[name].attrs, 'long_name') is not None:
        unit_attrs['long_name'] = text(ds[name].attrs, 'long_name')
    coord_attrs = {'units': text(ds[retain].attrs, 'units')}
    if text(ds[retain].attrs, 'long_name') is not None:
        coord_attrs['long_name'] = text(ds[retain].attrs, 'long_name')
    attrs = dict(config['outputAttributes'])
    if text(ds.attrs, 'title') is not None:
        attrs['title'] = text(ds.attrs, 'title')
    out = xr.Dataset({name: ((retain,), means, unit_attrs),
                      'validCount': ((retain,), validCount.values.astype('int32'), {'units': 'count'}),
                      'missingCount': ((retain,), np.asarray(missingCount.values).astype('int32'), {'units': 'count'})},
                     coords={retain: (retain, np.asarray(coord.values, dtype='float64'), coord_attrs)}, attrs=attrs)
    encoding = {v: {'_FillValue': None} for v in (name, 'validCount', 'missingCount', retain)}
    out.to_netcdf('profile.nc', engine='scipy', format='NETCDF3_CLASSIC', encoding=encoding)
    lines = [','.join([retain, name, 'validCount', 'missingCount'])]
    for c, v, nv, nm, bad in zip(coord.values, means, validCount.values, missingCount.values,
                                 (missingCount.values > 0) if miss['policy'] == 'propagate' else [False] * len(means)):
        lines.append(','.join([repr(float(c)), '' if bad else repr(float(v)), str(int(nv)), str(int(nm))]))
    with open('profile.csv', 'w', newline='') as stream:
        stream.write('\n'.join(lines) + '\n')
    write_json('native-result.json', {
        'runtime': identity, 'engine': 'scipy', 'source': sha(source), 'dims': list(da.dims), 'sizes': {k: int(v) for k, v in da.sizes.items()},
        'coordinateDigest': digest(coord.values), 'meanDigest': digest(means), 'validCounts': [int(x) for x in validCount.values],
        'missingCounts': [int(x) for x in missingCount.values], 'files': {f: sha(bounded(f)) for f in ('profile.nc', 'profile.csv')}})


def readback():
    """Separate process: freshly reopen the published profile with xarray and compare it with the compute record."""
    result = {'pid': os.getpid()}
    try:
        import xarray as xr
        config_bytes = bounded('native-config.json', 1024 * 1024)
        config = strict_json(config_bytes.decode('utf-8'))
        record_bytes = bounded('native-result.json', 1024 * 1024)
        record = strict_json(record_bytes.decode('utf-8'))
        result['runtime'] = runtime_identity()
        write_json('readback-inputs.json', {'source.nc': sha(bounded('source.nc')), 'native-config.json': sha(config_bytes),
                                            'native-worker.py': sha(bounded('native-worker.py')),
                                            'native-result.json': sha(record_bytes),
                                            'profile.nc': sha(bounded('profile.nc')), 'profile.csv': sha(bounded('profile.csv'))})
        name, retain = config['variable']['name'], config['retain']
        ds = xr.open_dataset('profile.nc', engine='scipy', decode_cf=False, mask_and_scale=False, decode_times=False)
        checks = {'dims': list(ds[name].dims) == [retain] and int(ds[retain].size) >= 2,
                  'coordinateDigest': digest(ds[retain].values) == record['coordinateDigest'],
                  'meanDigest': digest(ds[name].values) == record['meanDigest'],
                  'validCounts': [int(x) for x in ds['validCount'].values] == record['validCounts'],
                  'missingCounts': [int(x) for x in ds['missingCount'].values] == record['missingCounts'],
                  'units': ds[name].attrs.get('units') == config['variable']['unit'] and ds[retain].attrs.get('units') is not None,
                  'filesEqual': {f: sha(bounded(f)) == h for f, h in sorted(record['files'].items())}}
        rows = bounded('profile.csv').decode('ascii').splitlines()[1:]
        values = [[float(c) if c else None for c in row.split(',')[:2]] for row in rows]
        checks['csvEqualsNetCDF'] = len(values) == int(ds[retain].size) and all(
            a[0] == float(c) and (a[1] is None or a[1] == float(m))
            for a, c, m in zip(values, ds[retain].values, ds[name].values))
        ok = all(v if isinstance(v, bool) else all(v.values()) for v in checks.values())
        result.update({'ok': ok, **checks})
    except (OSError, ValueError, KeyError, IndexError, TypeError, Fault) as error:
        result.update({'ok': False, 'reason': '%s: %s' % (type(error).__name__, error)})
    write_json('readback.json', result)
    return result['ok']


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    stage = sys.argv[1] if len(sys.argv) == 2 else None
    if stage == 'compute':
        try:
            compute()
        except Fault as fault:
            write_json('compute-fault.json', {**fault.payload, 'pid': os.getpid()})
            sys.exit(3)
    elif stage == 'readback':
        sys.exit(0 if readback() else 4)
    else:
        sys.exit(2)


if __name__ == '__main__':
    main()
