# Copyright (C) 2026 David L F Gaden
"""Host-side retained attribute verification, using captured files and stdlib SQLite."""
import json
import sqlite3
from fractions import Fraction
from pathlib import Path
from . import attributes as contract
from schemaxis.errors import fail


def canonical(rows):
    def normalise(value):
        if type(value) in (int,float): return {'$numeric': str(Fraction(value))}
        if isinstance(value,dict): return {key:normalise(item) for key,item in value.items()}
        if isinstance(value,list): return [normalise(item) for item in value]
        return value
    return sorted(json.dumps(normalise(row), sort_keys=True, ensure_ascii=False, allow_nan=False) for row in rows)


def database_rows(path, table, geometry=False):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        quoted = '"' + table.replace('"', '""') + '"'
        columns = connection.execute('PRAGMA table_info(' + quoted + ')').fetchall()
        geometries = {row[0] for row in connection.execute('SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?', (table,))}
        names = [row[1] for row in columns if row[1] not in geometries and row[1] != 'fid']
        types = {row[1]: row[2].upper() for row in columns}
        rows = connection.execute('SELECT ' + ','.join('"' + name.replace('"','""') + '"' for name in names) + ' FROM ' + quoted).fetchall()
        return [{name: bool(value) if types[name] == 'BOOLEAN' and value is not None else value
                 for name, value in zip(names, row)} for row in rows]


def source_rows(path):
    if path.suffix.lower() == '.geojson':
        source = json.loads(path.read_text())
        fields = set().union(*(feature['properties'] for feature in source['features'])) - {'fid'}
        return [{name: feature['properties'].get(name) for name in fields} for feature in source['features']]
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        tables = connection.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()
    if len(tables) != 1: raise ValueError('captured GeoPackage must contain one vector table')
    return database_rows(path, tables[0][0])


def verify(directory, prepared, sources, built, reopened):
    def check(condition, message):
        if not condition: fail('VERIFICATION_FAILED', message)
    nodes = prepared['nodes']; snapshots = built['nodeSnapshots']; analytical = built['attributes']
    check(set(snapshots) == {node['id'] for node in nodes}, 'attribute graph node snapshot membership differs')
    check(set(analytical) == {node['id'] for node in nodes if node['filter'] in contract.OPTIONS}, 'attribute receipt membership differs')
    expected_tables = {}
    for node in nodes:
        identity, op, options = node['id'], node['filter'], node['options']
        snap = snapshots[identity]; rows = [feature['attributes'] for feature in snap['features']]
        if op == 'readVector':
            check(canonical(rows) == canonical(source_rows(directory / sources[identity]['retained'])), 'captured source attributes differ: ' + identity)
            continue
        parent = snapshots[node['inputs']['input']]
        parent_rows = [feature['attributes'] for feature in parent['features']]
        if op not in contract.OPTIONS:
            # Geometry operations can discard clipped features, but never author attributes.
            check(all(canonical([row])[0] in canonical(parent_rows) for row in rows), 'geometry operation changed attributes: ' + identity)
            continue
        try:
            if op == 'selectAttributes':
                selected = contract.select(parent_rows, parent['fields'], options, identity + '.options')
                expected = [row for row in parent['features'] if row['attributes'][options['idField']] in selected]
                check(snap == {**parent, 'count': len(expected), 'features': expected, 'bounds': snap['bounds']}, 'selection changed geometry, attributes, fields or CRS')
                # Bounds are recomputed independently from unchanged selected WKB in native reopen;
                # require the selected identities and full rows here rather than only counts.
                check(analytical[identity] == {'memberIds': selected}, 'selection member identities differ')
            else:
                table = contract.summarise(parent_rows, parent['fields'], options, identity + '.options')
                check(snap == parent, 'summary side product changed input vector')
                check(analytical[identity] == table, 'summary arithmetic or group membership differs')
                stem = 'summary-' + identity
                check(json.loads((directory / (stem + '.json')).read_text()) == table, 'published typed summary differs')
                check((directory / (stem + '.csv')).read_text() == contract.csv_text(table), 'published summary CSV differs')
                expected = [{column['name']: json.dumps(row[column['name']], ensure_ascii=False, separators=(',', ':'))
                             if column['name'] == 'memberIds' else row[column['name']] for column in table['columns']} for row in table['rows']]
                actual = database_rows(directory / (stem + '.gpkg'), 'summary')
                check(canonical(actual) == canonical(expected), 'native summary GeoPackage data differs')
                expected_tables[identity] = {'columns': [c['name'] for c in table['columns']],
                    'rows': sorted([list(row.values()) for row in expected], key=lambda row:json.dumps(row, sort_keys=True, ensure_ascii=False)), 'spatial': False}
        except contract.ContractError as error:
            fail('VERIFICATION_FAILED', str(error), error.location)
    check(reopened['summaryTables'] == expected_tables, 'fresh project summary table readback differs')
    check(canonical(database_rows(directory/'result.gpkg', 'result')) == canonical([f['attributes'] for f in reopened['snapshot']['features']]), 'published vector database attributes differ')
    check(snapshots[prepared['output']] == built['snapshot'], 'output vector differs from selected graph node')
