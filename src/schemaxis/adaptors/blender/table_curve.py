# Copyright (C) 2026 David L F Gaden
"""Bounded 1D/3D numeric-table interpretation, safe on the host as well as Blender."""
from schemaxis.tabular import read_csv
from schemaxis.errors import fail


def points_from_csv(options):
    table=read_csv(options['file'],minimum=2)
    if len(table['rows'])>1024:fail('RESOURCE_LIMIT','CSV curve is limited to 1024 points')
    names=[options['xColumn'],options['yColumn']]
    if options['zColumn']:names.append(options['zColumn'])
    try:indices=[table['columns'].index(name) for name in names]
    except ValueError:fail('INVALID_TABLE','requested curve column is absent')
    points=[[row[index] for index in indices] for row in table['rows']]
    if len(indices)==2:points=[[*point,0] for point in points]
    if any(abs(value)>100000 for point in points for value in point):fail('INVALID_GEOMETRY','curve coordinates exceed +/-100000')
    return points
