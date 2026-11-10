"""Curated discovery for named-coordinate profile reduction of one classic NetCDF measurement cube."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {'label': 'xarray',
            'purpose': 'Reduce named dimensions of one captured classic NetCDF measurement cube to a coordinate-labelled depth, time or station profile, '
                       'with explicit numeric range selection, declared units and missing-value policy, and independently verified counts.',
            'keywords': ['xarray', 'NetCDF', 'named coordinates', 'measurement cube', 'profile', 'dimension reduction']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': ['Isolated Python with exactly xarray 2026.9.0, SciPy 1.18.1 and NumPy 2.5.4; the host never imports them.',
                         'One local classic NetCDF (CDF-1) file with fixed dimensions, one double variable, double coordinate variables '
                         'and declared units; the host decodes it with its own bounded reader before any native launch.'],
        'references': ['docs/xarray.md', 'src/schemaxis/adaptors/xarray/readiness.json'],
        'operations': {'reduceProfile': {
            'purpose': 'Select inclusive numeric coordinate ranges from a captured NetCDF measurement cube, average the other named '
                       'dimensions with an explicit missing-value policy and publish a depth, time or station profile with valid and '
                       'missing counts.',
            'keywords': ['NetCDF', 'classic NetCDF', 'named coordinates', 'coordinate range', 'measurement cube', 'profile',
                         'depth profile', 'dimension reduction', 'mean over dimensions', 'missing values', 'fill value',
                         'valid count', 'xarray', 'sel', 'labelled array', 'units assertion'],
            'semantics': ['Dimensions are declared in the exact storage order of the variable as a deliberate layout assertion; a permuted order is refused, never reinterpreted.',
                          'Means are unweighted arithmetic means of the selected cells, not area, volume or time weighted.',
                          'Missing policy is explicit: skip with a valid-count threshold, propagate as an empty value, or refuse.',
                          'Strongly cancelling means are refused as ill-conditioned rather than published with a hidden error.'],
            'examples': [{'reference': 'examples/schemaxis/xarray-profile.json', 'purpose': 'Depth profile from an analytic time, depth and station cube.'},
                         {'reference': 'examples/schemaxis/xarray-profile-variant.json', 'purpose': 'Range selection with a skip policy and valid-count threshold.'}]}}
    }
