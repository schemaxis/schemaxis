"""Curated discovery for verified geodesic route chainage."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {'label': 'pyproj',
            'purpose': 'Station an ordered WGS84 longitude/latitude route at true ellipsoidal (geodesic) distances, with labelled '
                       'station and leg tables, GeoJSON for GIS and an independently verified total length.',
            'keywords': ['pyproj', 'PROJ', 'geodesic', 'ellipsoidal distance', 'chainage', 'WGS84']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': ['Isolated Python with exactly pyproj 3.8.0 and PROJ 9.9.0 on POSIX, network disabled; the host never imports pyproj.',
                         'Strict ASCII waypoint CSV with lon_deg,lat_deg (optionally name) columns in WGS84 decimal degrees.'],
        'references': ['docs/pyproj.md', 'src/schemaxis/adaptors/pyproj/readiness.json'],
        'operations': {'routeStations': {
            'purpose': 'Place stations every N metres of WGS84 geodesic distance along an ordered route, continuously across '
                       'turning points; publish labelled station and leg tables, station and route GeoJSON and a verified length summary.',
            'keywords': ['chainage', 'stationing', 'stations along a route', 'geodesic distance', 'ellipsoidal distance',
                         'route length', 'great circle', 'linear referencing', 'kilometre posts', 'azimuth', 'bearing',
                         'deflection angle', 'waypoints', 'pipeline route', 'transect', 'WGS84', 'Geod'],
            'semantics': ['Explicit WGS84 ellipsoid and longitude-first decimal degrees; no datum, CRS, height or survey-accuracy claim.',
                          'Chainage is the correctly rounded sum of geodesic leg lengths; stations at k x spacing merge with waypoints only when bitwise equal.',
                          'Every published distance, station and step is re-evaluated by an independent standard-library verifier; '
                          'requirements are decided by the host and only met requirements give an accepted deliverable.'],
            'examples': [{'reference': 'examples/schemaxis/pyproj-winnipeg-route.json', 'purpose': 'Winnipeg regional two-leg route at 1 km stations with a length limit.'},
                         {'reference': 'examples/schemaxis/pyproj-winnipeg-loop.json', 'purpose': 'Closed triangle with closure deflection.'},
                         {'reference': 'examples/schemaxis/pyproj-equator.json', 'purpose': 'Exact equatorial arcs a x delta-longitude.'}]}}
    }
