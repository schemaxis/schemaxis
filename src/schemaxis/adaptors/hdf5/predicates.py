"""Typed row conditions for extracts (``where``): checked against the observed file and evaluated on the host.

The host decides which axis-0 rows satisfy every condition from the independent h5dump reading; the native
worker evaluates the same conditions with h5py and NumPy, and the two row lists must agree before any
extracted value is accepted. Conditions compare numbers, booleans, enum member names and strings; there is
no expression language.
"""
import hashlib
import json
import math

from schemaxis.errors import fail
from . import model

COMPARABLE = ('int', 'uint', 'float', 'bool', 'enum', 'string')
ORDERED = ('lt', 'le', 'gt', 'ge', 'between')


def condition_type(c, obj, rows, at):
    """Element type compared by one condition, refusing shapes and classes the condition cannot compare."""
    if obj is None or obj.get('kind') != 'dataset':
        fail('INVALID_HDF5_EXTRACT', 'a where dataset must be a dataset in the file', at + '.dataset', path=c['dataset'])
    if obj.get('null'):
        fail('INVALID_HDF5_EXTRACT', 'a where dataset with a null dataspace holds no values to compare', at + '.dataset')
    if len(obj['shape']) != 1 or obj['shape'][0] != rows:
        fail('INVALID_HDF5_EXTRACT', 'a where dataset is one-dimensional with one value per axis-0 row of the extracted dataset', at + '.dataset',
             shape=obj['shape'], rows=rows)
    t = model.resolved(obj['type'])
    if 'field' in c:
        names = [f['name'] for f in t['fields']] if t['class'] == 'compound' else []
        if c['field'] not in names:
            fail('INVALID_HDF5_EXTRACT', 'field names a member of a compound where dataset', at + '.field', fields=names)
        t = t['fields'][names.index(c['field'])]['type']
    elif t['class'] == 'compound':
        fail('INVALID_HDF5_EXTRACT', 'a compound where dataset needs field', at + '.field')
    if t['class'] not in COMPARABLE or t.get('dims'):
        fail('INVALID_HDF5_EXTRACT', 'where compares integer, float, bool, enum or string elements', at, type=t)
    op = c['op']
    if op in ORDERED and t['class'] not in ('int', 'uint', 'float'):
        fail('INVALID_HDF5_EXTRACT', op + ' needs a numeric dataset', at + '.op', type=t['class'])
    if op in ('finite', 'nan') and t['class'] != 'float':
        fail('INVALID_HDF5_EXTRACT', op + ' needs a float dataset', at + '.op', type=t['class'])
    operands = [('value', c['value'])] if 'value' in c else []
    operands += [('upper', c['upper'])] if 'upper' in c else []
    operands += [('values[%d]' % i, v) for i, v in enumerate(c.get('values', []))]
    for key, v in operands:
        check_operand(v, t, at + '.' + key)
    return t


def check_operand(v, t, at):
    cls = t['class']
    if cls in ('int', 'uint'):
        if isinstance(v, bool) or not isinstance(v, int):
            fail('INVALID_HDF5_EXTRACT', 'compare an integer dataset with integers', at)
        low, high = (-(2 ** (t['bits'] - 1)), 2 ** (t['bits'] - 1) - 1) if cls == 'int' else (0, 2 ** t['bits'] - 1)
        if not low <= v <= high:
            fail('INVALID_HDF5_EXTRACT', 'the operand does not fit the dataset integer type', at, low=low, high=high)
    elif cls == 'float':
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            fail('INVALID_HDF5_EXTRACT', 'compare a float dataset with numbers', at)
    elif cls == 'bool':
        if not isinstance(v, bool):
            fail('INVALID_HDF5_EXTRACT', 'compare a bool dataset with true or false', at)
    elif cls == 'enum':
        names = [m['name'] for m in t['members']]
        if v not in names:
            fail('INVALID_HDF5_EXTRACT', 'compare an enum dataset with one of its member names', at, members=names)
    elif not isinstance(v, str):
        fail('INVALID_HDF5_EXTRACT', 'compare a string dataset with text', at)


def decode(v, t):
    if t['class'] == 'float':
        return float.fromhex(v) if isinstance(v, str) else float(v)
    return v


def holds(c, x):
    op = c['op']
    if op == 'eq':
        return x == c['value']
    if op == 'ne':
        return x != c['value']
    if op == 'lt':
        return x < c['value']
    if op == 'le':
        return x <= c['value']
    if op == 'gt':
        return x > c['value']
    if op == 'ge':
        return x >= c['value']
    if op == 'between':
        return c['value'] <= x <= c['upper']
    if op == 'in':
        return x in c['values']
    if op == 'finite':
        return math.isfinite(x)
    return math.isnan(x)


def rows(conditions, columns, n):
    """Ascending axis-0 rows where every condition holds; columns[i] are the decoded values of condition i."""
    keep = [True] * n
    for c, column in zip(conditions, columns):
        for r, x in enumerate(column):
            if keep[r] and not holds(c, x):
                keep[r] = False
    return [r for r in range(n) if keep[r]]


def digest(row_list):
    return {'count': len(row_list), 'sha256': hashlib.sha256(json.dumps(row_list, separators=(',', ':')).encode()).hexdigest()}
