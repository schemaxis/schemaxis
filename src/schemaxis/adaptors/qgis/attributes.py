# Copyright (C) 2026 David L F Gaden
"""Closed attribute intentions shared with the isolated QGIS worker (stdlib only)."""
import csv
import io
import json
import math
import re

FIELD = {'type': 'string', 'minLength': 1, 'maxLength': 128, 'required': True}
PREDICATE = {'type': 'object', 'properties': {
    'field': FIELD,
    'type': {'type': 'enum', 'values': ['number', 'string', 'boolean'], 'required': True},
    'comparison': {'type': 'enum', 'values': ['eq', 'ne', 'gt', 'ge', 'lt', 'le', 'isNull', 'isNotNull'], 'required': True},
    'value': {'type': 'union', 'options': [{'type': 'number'}, {'type': 'string', 'maxLength': 4096}, {'type': 'boolean'}]}}}
AGGREGATE = {'type': 'object', 'properties': {
    'name': FIELD,
    'statistic': {'type': 'enum', 'values': ['count', 'nonNullCount', 'sum', 'mean'], 'required': True},
    'field': {'type': 'string', 'minLength': 1, 'maxLength': 128},
    'units': {'type': 'string', 'minLength': 1, 'maxLength': 128, 'required': True}}}
OPTIONS = {
    'selectAttributes': {'idField': FIELD,
        'predicates': {'type': 'array', 'items': PREDICATE, 'minItems': 1, 'maxItems': 16, 'required': True},
        'minFeatures': {'type': 'integer', 'minimum': 1, 'maximum': 10000, 'default': 1},
        'maxFeatures': {'type': 'integer', 'minimum': 1, 'maximum': 10000, 'default': 10000}},
    'summariseAttributes': {'idField': FIELD, 'groupBy': FIELD,
        'aggregates': {'type': 'array', 'items': AGGREGATE, 'minItems': 1, 'maxItems': 16, 'required': True}}}


class ContractError(ValueError):
    def __init__(self, code, message, location):
        self.code, self.location = code, location
        super().__init__(message)


def require(condition, message, location, code='INVALID_ATTRIBUTE'):
    if not condition:
        raise ContractError(code, message, location)


def matches_type(value, kind):
    return ((kind == 'number' and type(value) in (int, float) and math.isfinite(value))
            or (kind == 'string' and type(value) is str)
            or (kind == 'boolean' and type(value) is bool))


def validate_options(operation, options, location):
    """Cross-field validation after normal closed declaration validation."""
    if operation == 'selectAttributes':
        require(options['minFeatures'] <= options['maxFeatures'],
                'minFeatures must not exceed maxFeatures', location + '.minFeatures', 'INVALID_ARGUMENT')
        for i, predicate in enumerate(options['predicates']):
            address = f'{location}.predicates[{i}]'
            null_test = predicate['comparison'] in ('isNull', 'isNotNull')
            require(('value' in predicate) != null_test, 'null tests omit value; comparisons require a typed value', address, 'INVALID_ARGUMENT')
            if not null_test:
                require(matches_type(predicate['value'], predicate['type']), 'value must match the declared type without coercion', address + '.value', 'INVALID_ARGUMENT')
            require(predicate['comparison'] not in ('gt', 'ge', 'lt', 'le') or predicate['type'] == 'number',
                    'ordered comparisons require number type', address + '.comparison', 'INVALID_ARGUMENT')
    else:
        names = set()
        for i, aggregate in enumerate(options['aggregates']):
            address = f'{location}.aggregates[{i}]'
            require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,62}', aggregate['name']) is not None
                    and aggregate['name'].casefold() not in names
                    and aggregate['name'].casefold() not in ('fid', 'group', 'groupisnull', 'memberids'),
                    'aggregate names must be unique and not group, groupIsNull or memberIds', address + '.name', 'INVALID_ARGUMENT')
            names.add(aggregate['name'].casefold())
            count = aggregate['statistic'] == 'count'
            require(('field' in aggregate) != count, 'count omits field; sum and mean require a numeric field', address + '.field', 'INVALID_ARGUMENT')
            require(aggregate['statistic'] not in ('count', 'nonNullCount') or aggregate['units'] == 'features', 'count units must be features', address + '.units', 'INVALID_ARGUMENT')


def validate_rows(rows, fields, options, location):
    identity = options['idField']
    require(identity in fields and identity != 'fid', 'idField must name a semantic field, not storage fid', location + '.idField')
    ids = [row[identity] for row in rows]
    require(all(type(value) is str and value for value in ids) and len(set(ids)) == len(ids),
            'idField must contain unique nonempty nonnull strings', location + '.idField')
    return ids


def select(rows, fields, options, location):
    validate_rows(rows, fields, options, location)
    predicates = options['predicates']
    for i, predicate in enumerate(predicates):
        address = f'{location}.predicates[{i}].field'
        field = predicate['field']
        require(field in fields and field != 'fid', 'predicate field does not exist or is storage fid', address)
        require(all(row[field] is None or matches_type(row[field], predicate['type']) for row in rows),
                'non-null field values must match the declared type without coercion', address)
    def accepts(row):
        for predicate in predicates:
            value = row[predicate['field']]; comparison = predicate['comparison']
            if comparison == 'isNull': result = value is None
            elif comparison == 'isNotNull': result = value is not None
            elif value is None: result = False
            else:
                target = predicate['value']
                if comparison == 'eq': result = value == target
                elif comparison == 'ne': result = value != target
                elif comparison == 'gt': result = value > target
                elif comparison == 'ge': result = value >= target
                elif comparison == 'lt': result = value < target
                else: result = value <= target
            if not result: return False
        return True
    selected = [row for row in rows if accepts(row)]
    require(options['minFeatures'] <= len(selected) <= options['maxFeatures'],
            f'selected {len(selected)} features outside required [{options["minFeatures"]},{options["maxFeatures"]}]',
            location + '.minFeatures', 'FEATURE_REQUIREMENT_FAILED')
    return sorted(row[options['idField']] for row in selected)


def summarise(rows, fields, options, location):
    validate_rows(rows, fields, options, location)
    group_field = options['groupBy']
    require(group_field in fields and group_field != 'fid', 'groupBy must name an existing string field', location + '.groupBy')
    require(all(row[group_field] is None or type(row[group_field]) is str for row in rows),
            'groupBy must contain strings or null; no coercion', location + '.groupBy')
    for i, aggregate in enumerate(options['aggregates']):
        if aggregate['statistic'] == 'count': continue
        field = aggregate['field']; address = f'{location}.aggregates[{i}].field'
        require(field in fields and field != 'fid', 'aggregate field does not exist or is storage fid', address)
        require(all(row[field] is None or matches_type(row[field], 'number') for row in rows),
                'sum and mean require finite numeric or null values; Boolean is not numeric', address)
    groups = {}
    for row in rows: groups.setdefault(row[group_field], []).append(row)
    result = []
    for group in sorted(groups, key=lambda value: (value is not None, value or '')):
        members = sorted(groups[group], key=lambda row: row[options['idField']])
        record = {'group': group, 'groupIsNull': group is None,
                  'memberIds': [row[options['idField']] for row in members]}
        for i, aggregate in enumerate(options['aggregates']):
            statistic = aggregate['statistic']
            if statistic == 'count': value = len(members)
            else:
                values = [row[aggregate['field']] for row in members if row[aggregate['field']] is not None]
                try: value = len(values) if statistic == 'nonNullCount' else math.fsum(values) if values else None
                except (OverflowError, ValueError): value = math.inf
                if statistic == 'nonNullCount': value = len(values)
                elif value is not None and statistic == 'mean': value /= len(values)
                require(value is None or math.isfinite(value), 'aggregate overflowed finite numeric range',
                        f'{location}.aggregates[{i}]')
            record[aggregate['name']] = value
        result.append(record)
    columns = [{'name': 'group', 'type': 'string', 'nullable': True, 'units': 'unitless'},
               {'name': 'groupIsNull', 'type': 'boolean', 'nullable': False, 'units': 'unitless'},
               {'name': 'memberIds', 'type': 'string[]', 'nullable': False, 'units': 'unitless'}]
    columns += [{'name': a['name'], 'type': 'integer' if a['statistic'] in ('count', 'nonNullCount') else 'number',
                 'nullable': a['statistic'] not in ('count', 'nonNullCount'), 'units': a['units']} for a in options['aggregates']]
    return {'version': 'schemaxis.qgis.summary/1', 'groupBy': group_field, 'idField': options['idField'],
            'columns': columns, 'rows': result,
            'semantics': 'count includes nulls; nonNullCount counts non-null numeric values; sum/mean ignore nulls and return null for all-null groups; no unit conversion'}


def csv_text(table):
    stream = io.StringIO(newline=''); writer = csv.writer(stream, lineterminator='\n')
    names = [column['name'] for column in table['columns']]; writer.writerow(names)
    for row in table['rows']:
        writer.writerow([json.dumps(row[name], ensure_ascii=False, separators=(',', ':')) if name == 'memberIds'
                         else '' if row[name] is None else 'true' if row[name] is True
                         else 'false' if row[name] is False else row[name] for name in names])
    return stream.getvalue()
