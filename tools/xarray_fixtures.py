"""Original tiny classic NetCDF cubes for the xarray adaptor, written with the adaptor's own bounded CDF-1 writer.

Analytic values: v = 280 + 5*depthIndex + 0.5*timeIndex + 0.25*stationIndex (all dyadic, so every mean is exact).
"""
import argparse
from pathlib import Path

from schemaxis.adaptors.xarray import cdf

TIME, DEPTH, STATION = [0.0, 1.0, 2.0], [0.0, 10.0, 20.0, 30.0], [1.0, 2.0]
AXES = {'time': (TIME, 'h'), 'depth': (DEPTH, 'm'), 'station': (STATION, 'km')}


def value(t, d, s):
    return 280.0 + 5 * d + 0.5 * t + 0.25 * s


def build(order=('time', 'depth', 'station'), missing=(), sentinel=-999.0, units=None, axes=None, extra_attrs=(), extra_vars=(),
          fill=True, data=None, title='Analytic measurement cube', name='temperature', variable_unit='K'):
    """Return CDF-1 bytes. missing is a set of (t, d, s) index triples stored as the sentinel."""
    axes = {k: list(v[0]) for k, v in AXES.items()} | (axes or {})
    units = {k: v[1] for k, v in AXES.items()} | (units or {})
    index = {'time': 0, 'depth': 1, 'station': 2}
    lengths = {k: len(axes[k]) for k in order}
    cells = []
    from itertools import product
    for combo in product(*[range(lengths[k]) for k in order]):
        pos = [None] * 3
        for k, i in zip(order, combo):
            pos[index[k]] = i
        cells.append(sentinel if tuple(pos) in missing else value(*pos))
    if data is not None:
        cells = data
    variables = []
    for k in order:
        attrs = [] if units[k] is None else [('units', 'char', units[k])]
        variables.append({'name': k, 'dims': [k], 'type': 'double', 'attrs': attrs, 'values': axes[k]})
    vattrs = [('units', 'char', variable_unit)] + ([('_FillValue', 'double', sentinel)] if fill else []) + list(extra_attrs)
    variables.append({'name': name, 'dims': list(order), 'type': 'double', 'attrs': vattrs, 'values': cells})
    variables.extend(extra_vars)
    return cdf.write([(k, lengths[k]) for k in order], [('title', 'char', title)] if title else [], variables)


def write_all(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'xarray-cube.nc').write_bytes(build())
    (directory / 'xarray-cube-missing.nc').write_bytes(build(missing={(1, 1, 0)} | {(t, 3, s) for t in range(3) for s in range(2)}
                                                             | {(0, 2, 1), (2, 2, 0)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory')
    write_all(parser.parse_args().directory)
