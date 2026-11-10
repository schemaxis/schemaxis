"""Operation planning, payload materialisation and independent expected HDF5 state (host only)."""
import copy
import itertools
import math
from pathlib import PurePosixPath

from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail, keys
from . import expect, model
from .model import (FILE, OPTIONS, OPERATIONS, ROOT_KEYS, VERSION, element_count, object_path, resolved, selection)

RESERVED = set(model.RESERVED_ATTRIBUTES)
LITERAL_LIMIT = 1024 * 1024


# ------------------------------------------------------------------ dispatch
def plan(document):
    keys(document, ROOT_KEYS, '$')
    if document.get('version') != VERSION:
        fail('UNSUPPORTED_VERSION', 'select ' + VERSION, '$.version')
    op = document.get('operation')
    if op not in OPERATIONS:
        fail('UNKNOWN_OPERATION', 'select one of ' + ', '.join(OPERATIONS), '$.operation')
    options = OPTIONS[op]
    stray = sorted(set(document) - {'version', 'operation'} - set(options))
    if stray:
        fail('UNKNOWN_ARGUMENT', 'these fields do not apply to ' + op, '$.' + stray[0], keys=stray)
    p = validate_arguments(options, {k: v for k, v in document.items() if k in options}, location='$')
    p = {'version': 'schemaxis.hdf5.plan/1', 'operation': op, **p}
    p = PLANNERS[op](p)
    plan_access(p)
    return p


CREATING = ('createFile', 'writeMeshFields', 'parallelWrite', 'appendSeries')


def plan_access(p):
    """Access tuning: chunk cache and sieve buffer for every open; creation-time alignment/metadata blocks; memory-bounded extracts."""
    access = p.get('access')
    if not access:
        p.pop('access', None)
        return
    op = p['operation']
    writes_new = op in CREATING or op == 'editFile' and p['repack']
    for key in ('alignment', 'metaBlockBytes'):
        if key in access and not writes_new:
            fail('INVALID_HDF5_ACCESS', key + ' shapes the layout of a newly written file; use it with createFile, writeMeshFields, '
                 'parallelWrite, appendSeries or editFile with repack', '$.access.' + key)
    f = p.get('file') or {}
    if access.get('alignment') and f.get('userblock') and f['userblock'] < access['alignment']['interval']:
        fail('INVALID_HDF5_ACCESS', 'HDF5 needs the user block to be at least the allocation alignment interval', '$.access.alignment.interval',
             userblock=f['userblock'])
    if 'pageBufferBytes' in access:
        f = p.get('file') or {}
        if op not in CREATING or f.get('spaceStrategy') != 'page':
            fail('INVALID_HDF5_ACCESS', 'a page buffer needs a newly written file with spaceStrategy page', '$.access.pageBufferBytes')
        if access['pageBufferBytes'] < f['pageBytes'] or access['pageBufferBytes'] % f['pageBytes']:
            fail('INVALID_HDF5_ACCESS', 'the page buffer is a whole multiple of the file page size', '$.access.pageBufferBytes', pageBytes=f['pageBytes'])
    if 'memoryBytes' in access:
        if not p.get('extracts'):
            fail('INVALID_HDF5_ACCESS', 'memoryBytes bounds extraction blocks; declare extracts', '$.access.memoryBytes')
        if p.get('parallel'):
            fail('INVALID_HDF5_ACCESS', 'parallel extraction reads one block per rank; omit memoryBytes', '$.access.memoryBytes')


def split_blocks(sel, shape, rows_per_block=None, parts=None, at='$'):
    """Ordered axis-0 sub-selections whose concatenation is exactly the selection (by row budget or into equal parts)."""
    if not shape:
        fail('INVALID_HDF5_ACCESS', 'scalar datasets cannot be split into blocks', at)
    if sel['kind'] == 'all':
        sel = {'kind': 'slices', 'slices': [[0, n, 1] for n in shape]}
    if sel['kind'] in ('points', 'rows'):
        units, unit_rows = len(sel[sel['kind']]), 1
    elif sel['kind'] == 'slices':
        a, b, c = sel['slices'][0]
        units, unit_rows = (b - a + c - 1) // c, 1
    else:
        units, unit_rows = sel['count'][0], sel['block'][0]
    if parts is not None:
        if units < parts:
            fail('INVALID_HDF5_PARALLEL', 'the selection has fewer axis-0 units than ranks', at, units=units, ranks=parts)
        bounds = [units * r // parts for r in range(parts + 1)]
    else:
        per = max(1, rows_per_block // unit_rows)
        bounds = list(range(0, units, per)) + [units]
    out = []
    for lo, hi in zip(bounds, bounds[1:]):
        if sel['kind'] in ('points', 'rows'):
            out.append({'kind': sel['kind'], sel['kind']: sel[sel['kind']][lo:hi]})
        elif sel['kind'] == 'slices':
            a, b, c = sel['slices'][0]
            out.append({'kind': 'slices', 'slices': [[a + lo * c, a + (hi - 1) * c + 1, c]] + [list(x) for x in sel['slices'][1:]]})
        else:
            out.append({'kind': 'hyperslab', 'start': [sel['start'][0] + lo * sel['stride'][0]] + sel['start'][1:],
                        'count': [hi - lo] + sel['count'][1:], 'stride': list(sel['stride']), 'block': list(sel['block'])})
    if not out and sel['kind'] in ('points', 'rows'):
        out.append({'kind': sel['kind'], sel['kind']: []})
    return out


def file_settings(p, default_name='data.h5'):
    f = validate_arguments(FILE['properties'], p.get('file', {'name': default_name}), location='$.file')
    return f


def source(p):
    model.absolute_file(p['source'], '$.source', 'INVALID_HDF5_SOURCE')
    if 'sha256' in p and not model.HEX.fullmatch(p['sha256']):
        fail('INVALID_SHA256', 'use 64 lower-case hexadecimal digits', '$.sha256')


def plan_create(p):
    ctx = model.context(p)
    p['file'] = model.plan_file(file_settings(p), '$.file', ctx['dependencies'])
    objects = [model.plan_object(o, f'$.objects[{i}]', ctx) for i, o in enumerate(p['objects'])]
    links = [model.plan_link(link, f'$.links[{i}]', ctx) for i, link in enumerate(p['links'])]
    model.finish_tree(objects, links, ctx)
    p['objects'], p['links'] = objects, links
    dense = model.LIBVER.index(p['file']['libver']) >= model.LIBVER.index('v108')
    model.check_attribute_sizes(p['file']['attributes'], dense or p['file']['trackOrder'], '$.file.attributes')
    for i, o in enumerate(objects):
        model.check_attribute_sizes(o['attributes'], dense or o.get('trackOrder', False), f'$.objects[{i}].attributes')
    p['extracts'] = plan_extracts(p['extracts'], {o['path']: o for o in objects if o['kind'] == 'dataset'})
    single_file_chunks(p)
    external_files(p, objects, ctx)
    p['inputs'] = list(ctx['inputs'].values())
    p['dependencies'] = list(ctx['dependencies'].values())
    p['losses'] = LOSSES['createFile']
    return p


def external_files(p, objects, ctx):
    produced = []
    for o in objects:
        for seg in o.get('storage', {}).get('external', []):
            dep = ctx['dependencies'].get(seg['file'])
            seg['path'] = dep['name'] if dep else seg['file']
            if not dep and seg['path'] not in produced:
                produced.append(seg['path'])
    if set(produced) & {d['name'] for d in ctx['dependencies'].values()}:
        fail('INVALID_HDF5_STORAGE', 'a new external raw file name collides with a dependency', '$.objects')
    p['rawFiles'] = produced


def plan_extracts(items, shapes, known=True):
    out, ids = [], set()
    for i, item in enumerate(items):
        at = f'$.extracts[{i}]'
        model.identifier(item['id'], at + '.id')
        if item['id'] in ids:
            fail('DUPLICATE_HDF5_EXTRACT', 'extract ids are unique', at + '.id')
        ids.add(item['id'])
        path = object_path(item['dataset'], at + '.dataset')
        if item['header'] != 'units' and item['format'] != 'csv':
            fail('INVALID_HDF5_EXTRACT', 'header applies only to CSV extracts', at + '.header')
        rec = {'id': item['id'], 'dataset': path, 'format': item['format'], 'coordinates': item['coordinates'], 'header': item['header'],
               'output': item['id'] + {'csv': '.csv', 'npy': '.npy', 'json': '.json', 'chunks': '.chunks.json'}[item['format']]}
        if item['format'] == 'chunks':
            for key in ('fields', 'columns', 'where'):
                if key in item:
                    fail('INVALID_HDF5_EXTRACT', 'a chunk index lists whole stored chunks; ' + key + ' does not apply', at + '.' + key)
            if item.get('selection', {'kind': 'all'})['kind'] != 'all':
                fail('INVALID_HDF5_EXTRACT', 'a chunk index lists every allocated chunk; omit selection', at + '.selection')
            rec['coordinates'] = False
        if 'fields' in item:
            if len(set(item['fields'])) != len(item['fields']):
                fail('INVALID_HDF5_EXTRACT', 'field names are unique', at + '.fields')
            rec['fields'] = list(item['fields'])
        if 'columns' in item:
            if item['format'] != 'csv':
                fail('INVALID_HDF5_EXTRACT', 'columns names CSV header cells only', at + '.columns')
            rec['columns'] = list(item['columns'])
        if 'where' in item:
            if known:
                fail('INVALID_HDF5_EXTRACT', 'where filters rows of an existing file; for a file written in this run select the rows directly', at + '.where')
            if item.get('selection', {'kind': 'all'})['kind'] != 'all':
                fail('INVALID_HDF5_EXTRACT', 'where chooses the axis-0 rows; combine it with fields or columns, not with a selection', at + '.selection')
            rec['where'] = [plan_condition(c, path, f'{at}.where[{j}]') for j, c in enumerate(item['where'])]
        if known:
            o = shapes.get(path)
            if o is None:
                fail('INVALID_HDF5_EXTRACT', 'extract a declared dataset', at + '.dataset')
            if o.get('empty'):
                fail('INVALID_HDF5_EXTRACT', 'the dataset has a null dataspace: it holds no elements to select or extract', at + '.dataset')
            sel, shape, count = selection(item.get('selection'), o['shape'], at + '.selection')
            rec.update(selection=sel, selectedShape=shape, count=count)
            check_extract_type(rec, resolved(o['type']), at)
        else:
            rec['selection'] = model.selection_unknown_shape(item.get('selection'), at + '.selection')
        out.append(rec)
    return out


def single_file_chunks(p):
    """Chunk byte offsets refer to one ordinary file, so chunk indexes need an output written with sec2, stdio or core."""
    for i, e in enumerate(p['extracts']):
        if e['format'] == 'chunks' and p['file']['driver'] in ('family', 'split'):
            fail('INVALID_HDF5_EXTRACT', 'chunk byte offsets need a single-file output; use the sec2, stdio or core driver', f'$.extracts[{i}].format')


def plan_condition(c, dataset, at):
    """Normalise one typed row condition: which values it reads and how they are compared."""
    out = {'dataset': object_path(c.get('dataset', dataset), at + '.dataset'), 'op': c['op']}
    if 'field' in c:
        out['field'] = c['field']
    op = c['op']
    needs = {'between': {'value', 'upper'}, 'in': {'values'}, 'finite': set(), 'nan': set()}.get(op, {'value'})
    for key in ('value', 'upper', 'values'):
        if (key in c) != (key in needs):
            fail('INVALID_HDF5_EXTRACT', '%s %s %s' % (op, 'needs' if key in needs else 'does not take', key), at + '.' + key)
    for key in needs:
        out[key] = c[key]
    numeric = {'lt', 'le', 'gt', 'ge', 'between'}
    if op in numeric and any(isinstance(c.get(k), (str, bool)) for k in ('value', 'upper')):
        fail('INVALID_HDF5_EXTRACT', op + ' compares numbers', at + '.value')
    if op == 'between' and c['value'] > c['upper']:
        fail('INVALID_HDF5_EXTRACT', 'between needs value <= upper', at + '.upper')
    return out


def check_extract_type(rec, t, at):
    if 'fields' in rec:
        if t['class'] != 'compound':
            fail('INVALID_HDF5_EXTRACT', 'fields select members of a compound dataset', at + '.fields')
        names = [f['name'] for f in t['fields']]
        for j, name in enumerate(rec['fields']):
            if name not in names:
                fail('INVALID_HDF5_EXTRACT', 'unknown compound field', f'{at}.fields[{j}]', fields=names)
    if rec['format'] == 'csv':
        leaf = [f['type'] for f in t['fields'] if f['name'] in rec.get('fields', names_of(t))] if t['class'] == 'compound' else [t]
        for item in leaf:
            if item['class'] not in ('int', 'uint', 'float', 'bool', 'enum', 'string') or item.get('dims'):
                fail('INVALID_HDF5_EXTRACT', 'CSV extracts hold numeric, bool, enum or string cells; use npy or json', at + '.format')
        width = 1
        for n in rec['selectedShape'][1:]:
            width *= n
        if width > 4096 or t['class'] == 'compound' and len(rec['selectedShape']) > 1:
            fail('INVALID_HDF5_EXTRACT', 'CSV rows follow axis 0 with at most 4096 columns (compound selections are one-dimensional); use npy or json', at + '.format')
    if rec['format'] == 'chunks' and (t['class'] not in ('int', 'uint', 'float') or t.get('dims')):
        fail('INVALID_HDF5_EXTRACT', 'chunk indexes are offered for integer and float datasets', at + '.format')
    if rec['format'] == 'npy' and (t['class'] not in ('int', 'uint', 'float', 'bool', 'complex') or t.get('dims') or 'fields' in rec):
        fail('INVALID_HDF5_EXTRACT', 'npy extracts hold bool, integer, float or complex elements', at + '.format')


def names_of(t):
    return [f['name'] for f in t['fields']]


def plan_inspect(p):
    source(p)
    p['dependencies'] = list(model.plan_dependencies(p).values())
    ids = set()
    for i, e in enumerate(p['expectations']):
        at = f'$.expectations[{i}]'
        model.identifier(e['id'], at + '.id')
        if e['id'] in ids:
            fail('DUPLICATE_HDF5_EXPECTATION', 'expectation ids are unique', at + '.id')
        ids.add(e['id'])
        object_path(e['path'], at + '.path', root=True)
        if not e['present'] and set(e) - {'id', 'path', 'present'}:
            fail('INVALID_HDF5_EXPECTATION', 'an absence expectation states only id, path and present false', at)
        if ('attribute' in e) != ('value' in e) and 'value' in e:
            fail('INVALID_HDF5_EXPECTATION', 'value compares an attribute; name it with attribute', at + '.value')
        if 'minimum' in e and 'maximum' in e and e['minimum'] > e['maximum']:
            fail('INVALID_HDF5_EXPECTATION', 'minimum exceeds maximum', at + '.minimum')
    p['losses'] = LOSSES['inspectFile']
    return p


def plan_extract(p):
    source(p)
    if p.get('parallel') is not None:
        p['parallel'] = validate_arguments(model.PARALLEL_READ['properties'], p['parallel'], location='$.parallel')
    p['dependencies'] = list(model.plan_dependencies(p).values())
    p['extracts'] = plan_extracts(p['extracts'], {}, known=False)
    if p.get('parallel') and any('where' in e or e['format'] == 'chunks' for e in p['extracts']):
        fail('INVALID_HDF5_PARALLEL', 'where and chunk-index extracts run serially; omit parallel or those extracts', '$.parallel')
    p['losses'] = LOSSES['extractData']
    return p


def plan_edit(p):
    source(p)
    ctx = model.context(p)
    p['file'] = model.plan_file(file_settings(p, 'edited.h5'), '$.file', ctx['dependencies'])
    if p['file']['driver'] != 'sec2' and not p['repack']:
        fail('INVALID_HDF5_FILE', 'an edited copy keeps the source layout; choose repack true to rewrite with another driver', '$.file.driver')
    edits = []
    for i, e in enumerate(p['edits']):
        edits.append(plan_edit_item(e, f'$.edits[{i}]', ctx))
    p['edits'] = edits
    p['extracts'] = plan_extracts(p['extracts'], {}, known=False)
    single_file_chunks(p)
    p['inputs'] = list(ctx['inputs'].values())
    p['dependencies'] = list(ctx['dependencies'].values())
    p['losses'] = LOSSES['editFile']
    return p


EDIT_FIELDS = {'create': {'object'}, 'delete': {'path'}, 'move': {'path', 'to'},
               'copy': {'path', 'to', 'from', 'shallow', 'withoutAttributes', 'expandSoft', 'expandExternal', 'expandReferences'},
               'link': {'link'}, 'setAttribute': {'path', 'attribute'}, 'deleteAttribute': {'path', 'name'},
               'renameAttribute': {'path', 'name', 'newName'},
               'write': {'path', 'selection', 'data', 'fields'}, 'resize': {'path', 'shape'}, 'append': {'path', 'axis', 'data', 'shape'},
               'makeScale': {'path', 'name'}, 'attachScale': {'path', 'axis', 'scale'}, 'detachScale': {'path', 'axis', 'scale'},
               'relayout': {'path', 'storage'}, 'copyChunks': {'path', 'to'}}
COPY_DEFAULTS = ('shallow', 'withoutAttributes', 'expandSoft', 'expandExternal', 'expandReferences')


def plan_edit_item(e, at, ctx):
    action = e['action']
    allowed = EDIT_FIELDS[action] | {'action'}
    for key in set(e) - allowed:
        if key in COPY_DEFAULTS and not e[key]:
            continue
        fail('INVALID_HDF5_EDIT', key + ' does not apply to ' + action, at + '.' + key)
    for key in allowed - {'action', 'from', 'name', 'selection', 'shape', 'fields'} - set(COPY_DEFAULTS):
        if key not in e and not (action == 'makeScale' and key == 'name'):
            fail('INVALID_HDF5_EDIT', action + ' needs ' + key, at + '.' + key)
    out = {'action': action}
    if 'path' in e:
        out['path'] = object_path(e['path'], at + '.path', root=action in ('setAttribute', 'deleteAttribute', 'renameAttribute'))
    if 'to' in e:
        out['to'] = object_path(e['to'], at + '.to')
        if out['to'] == out['path'] or out['to'].startswith(out['path'] + '/'):
            fail('INVALID_HDF5_EDIT', 'move or copy into itself is refused', at + '.to')
    if action == 'copyChunks':
        out['index'] = int(at[len('$.edits['):-1])
    if action == 'create':
        if e['object']['kind'] == 'dataset' and e['object'].get('data', {}).get('source') in ('copy', 'references'):
            fail('INVALID_HDF5_EDIT', 'in-file copies use action copy; references are authored in createFile', at + '.object.data.source')
        if 'virtual' in e['object'] or e['object'].get('dimensions'):
            fail('INVALID_HDF5_EDIT', 'create virtual datasets in createFile; attach scales with attachScale', at + '.object')
        out['object'] = model.plan_object(e['object'], at + '.object', ctx)
    elif action == 'copy':
        for key in COPY_DEFAULTS:
            out[key] = e.get(key, False)
        if 'from' in e:
            dep = ctx['dependencies'].get(e['from'])
            if dep is None or dep['role'] != 'copySource':
                fail('INVALID_HDF5_EDIT', 'from names a copySource dependency', at + '.from')
            out['from'] = e['from']
        if out['expandExternal'] or out['expandReferences']:
            fail('INVALID_HDF5_EDIT', 'expandExternal and expandReferences are not offered: their result depends on files and objects outside the verified copy', at)
    elif action == 'link':
        out['link'] = model.plan_link(e['link'], at + '.link', ctx)
    elif action == 'setAttribute':
        out['attribute'] = model.plan_attributes([e['attribute']], at + '.attribute', ctx['named'])[0]
    elif action == 'renameAttribute':
        new = e['newName']
        if '\x00' in new or '/' in new or new.strip() != new or new in RESERVED or e['name'] in RESERVED or new == e['name']:
            fail('INVALID_HDF5_EDIT', 'rename to a different nonblank name without / or NUL; scale bookkeeping attributes cannot be renamed', at + '.newName')
        out['name'], out['newName'] = e['name'], new
    elif action == 'deleteAttribute':
        if e['name'] in RESERVED:
            fail('INVALID_HDF5_EDIT', 'dimension-scale bookkeeping attributes change through scale edits', at + '.name')
        out['name'] = e['name']
    elif action in ('write', 'append'):
        out['dataRecord'] = e['data']
        if e['data']['source'] not in ('values', 'input', 'range', 'linspace'):
            fail('INVALID_HDF5_EDIT', action + ' takes values, input, range or linspace data', at + '.data.source')
        if action == 'write':
            out['selectionRecord'] = e.get('selection', {'kind': 'all'})
            if 'fields' in e:
                if len(set(e['fields'])) != len(e['fields']):
                    fail('INVALID_HDF5_EDIT', 'field names are unique', at + '.fields')
                out['fields'] = list(e['fields'])
        else:
            out['axis'] = e['axis']
            if 'shape' not in e:
                fail('INVALID_HDF5_EDIT', 'append declares the appended block shape', at + '.shape')
            out['appendShape'] = list(e['shape'])
    elif action == 'resize':
        out['shape'] = list(e['shape'])
    elif action == 'makeScale':
        out['name'] = e.get('name', '')
    elif action in ('attachScale', 'detachScale'):
        out['axis'] = e['axis']
        out['scale'] = object_path(e['scale'], at + '.scale')
    elif action == 'relayout':
        out['storageRecord'] = e['storage']
    return out


def plan_mesh(p):
    from . import meshes
    return meshes.plan(p)


def plan_series(p):
    ctx = model.context(p)
    p['file'] = model.plan_file(file_settings(p, 'series.h5'), '$.file', ctx['dependencies'])
    if p['file']['driver'] != 'sec2' or p['file']['userblock']:
        fail('INVALID_HDF5_FILE', 'SWMR series use the default sec2 driver without a user block', '$.file.driver')
    if p['file']['libver'] not in ('earliest', 'latest') or p['file']['libverHigh'] != 'latest':
        fail('INVALID_HDF5_FILE', 'SWMR files are always written with libver latest; omit the bounds', '$.file.libver')
    p['file']['libver'] = 'latest'
    s = dict(p['series'])
    object_path(s['dataset'], '$.series.dataset')
    s['type'] = model.scalar_type(s.get('type', {'class': 'float', 'bits': 64, 'order': 'little'}), '$.series.type')
    if s['type']['class'] not in ('int', 'uint', 'float'):
        fail('INVALID_HDF5_TYPE', 'SWMR series hold integer or float samples', '$.series.type.class')
    width = s['width']
    batches = []
    rows = 0
    for i, b in enumerate(p['batches']):
        at = f'$.batches[{i}]'
        if b['source'] not in ('values', 'range', 'linspace', 'input'):
            fail('INVALID_HDF5_DATA', 'series batches take values, range, linspace or input data', at + '.source')
        if b['source'] == 'values':
            if len(b.get('values', [])) % width or not b.get('values'):
                fail('INVALID_HDF5_DATA', 'a batch holds whole rows of width samples', at + '.values', width=width)
            n = len(b['values']) // width
        else:
            n = None
        batches.append({'record': b, 'rows': n})
        rows += n or 0
    if p['readers'] and not p['swmr']:
        fail('INVALID_HDF5_SWMR', 'concurrent readers require swmr true', '$.readers')
    p['series'], p['batches'] = s, batches
    p['inputs'] = list(ctx['inputs'].values())
    p['dependencies'] = list(ctx['dependencies'].values())
    p['losses'] = LOSSES['appendSeries']
    return p


def plan_compare(p):
    source(p)
    model.absolute_file(p['reference'], '$.reference', 'INVALID_HDF5_SOURCE')
    if 'referenceSha256' in p and not model.HEX.fullmatch(p['referenceSha256']):
        fail('INVALID_SHA256', 'use 64 lower-case hexadecimal digits', '$.referenceSha256')
    p['dependencies'] = list(model.plan_dependencies(p).values())
    tol = validate_arguments(model.COMPARE['properties'], p.get('tolerance', {}), location='$.tolerance')
    for i, path in enumerate(tol.get('paths', [])):
        object_path(path, f'$.tolerance.paths[{i}]', root=True)
    p['tolerance'] = tol
    p['losses'] = LOSSES['compareFiles']
    return p


def plan_parallel(p):
    ctx = model.context({'inputs': [], 'dependencies': []})
    p['file'] = model.plan_file(file_settings(p, 'parallel.h5'), '$.file', ctx['dependencies'])
    if p['file']['driver'] != 'sec2' or p['file']['userblock'] or p['file']['spaceStrategy'] == 'page':
        fail('INVALID_HDF5_FILE', 'parallel files use the mpio driver chosen by the operation; leave driver, userblock and spaceStrategy at their defaults', '$.file.driver')
    objects = []
    for i, o in enumerate(p['objects']):
        at = f'$.objects[{i}]'
        if o.get('kind', 'dataset') != 'dataset':
            objects.append(model.plan_object(o, at, ctx))
            continue
        for key in ('virtual', 'dimensions', 'scale'):
            if o.get(key):
                fail('INVALID_HDF5_PARALLEL', key + ' is created serially; use createFile or editFile', at + '.' + key)
        planned = model.plan_object(o, at, ctx)
        t = resolved(planned['type'])
        if t['class'] not in ('int', 'uint', 'float') or not planned['shape'] or planned['shape'][0] < p['ranks']:
            fail('INVALID_HDF5_PARALLEL', 'parallel datasets hold integer or float elements with at least one axis-0 row per rank', at)
        if planned['data']['source'] not in ('values', 'range', 'linspace', 'fill'):
            fail('INVALID_HDF5_PARALLEL', 'parallel data comes from values, range, linspace or fill', at + '.data.source')
        if planned['storage']['layout'] not in ('contiguous', 'chunked'):
            fail('INVALID_HDF5_PARALLEL', 'parallel datasets are contiguous or chunked', at + '.storage.layout')
        if planned['storage']['compression'] != 'none' or planned['storage'].get('shuffle') or planned['storage'].get('fletcher32') \
                or 'scaleOffset' in planned['storage'] or planned['storage'].get('nbit'):
            if p['io'] != 'collective':
                fail('INVALID_HDF5_PARALLEL', 'filtered parallel writes require collective I/O', '$.io')
            if planned['storage']['compression'] in ('lzf', 'szip'):
                fail('INVALID_HDF5_PARALLEL', 'parallel filters are limited to gzip, shuffle, fletcher32, nbit and scaleOffset', at + '.storage.compression')
        objects.append(planned)
    model.finish_tree(objects, [], ctx)
    p['objects'], p['links'], p['extracts'], p['inputs'], p['dependencies'], p['rawFiles'] = objects, [], [], [], [], []
    p['partitions'] = {o['path']: partition(o['shape'][0], p['ranks']) for o in objects if o['kind'] == 'dataset'}
    p['losses'] = LOSSES['parallelWrite']
    return p


def partition(rows, ranks):
    return [[r * rows // ranks, (r + 1) * rows // ranks] for r in range(ranks)]


PLANNERS = {'createFile': plan_create, 'editFile': plan_edit, 'inspectFile': plan_inspect, 'extractData': plan_extract,
            'writeMeshFields': plan_mesh, 'appendSeries': plan_series, 'compareFiles': plan_compare, 'parallelWrite': plan_parallel}

LOSSES = {
    'createFile': ['Creates one new HDF5 file (plus declared family/split members, external raw files and captured dependent files); nothing outside the run directory is written.',
                   'Values are authored literals, documented generators (range: start+i*step; linspace: start+i*(stop-start)/(n-1), last element exactly stop), captured CSV/NPY/raw inputs or in-file copies; no random data.',
                   'Floats are rounded once to the declared precision (IEEE round-to-nearest-even); integers outside the declared type are refused, never wrapped.',
                   'Object, attribute and link names use a portable ASCII subset; compound fields, vlen and array bases are one level deep.',
                   'Dimension scales are one-dimensional; third-party filter plugins, MPI-IO and remote drivers are not offered.'],
    'editFile': ['The source file is captured; the original is never modified. Edits apply in order to a copy, which is published under a new name.',
                 'Space freed by deletions is reclaimed only with repack true (a full copy into a fresh file).',
                 'expandExternal/expandReferences copies are refused because their result depends on objects outside the verified copy.'],
    'inspectFile': ['Read-only inventory of a captured copy; external links and virtual sources are reported, and resolved only against declared dependencies.',
                    'Values are summarised by count, SHA-256 and a bounded preview, not reproduced in full.'],
    'extractData': ['Reads selections from a captured copy into new CSV, NPY or JSON files; CSV keeps no HDF5 type metadata beyond the header and documented cell spelling.'],
    'writeMeshFields': ['Writes unstructured mesh geometry, connectivity and per-time-step fields to HDF5 with an XDMF 3 description; no mesh generation, interpolation or solver output.'],
    'appendSeries': ['Appends integer/float sample rows to one chunked unlimited dataset in SWMR mode; concurrent readers observe flushed batches only, and structural changes after SWMR start are not possible.'],
    'parallelWrite': ['MPI ranks write contiguous axis-0 row blocks of integer/float datasets with the mpio driver; groups, attributes and dataset creation are collective.',
                      'Requires a separately built parallel h5py (MPI) runtime and mpiexec; the serial wheel and h5dump verify the closed file.',
                      'No virtual, external, compound, string or reference datasets, scales or lzf/szip filters in parallel.'],
    'compareFiles': ['Compares captured copies of two files: presence, kinds, types, shapes, attributes and numeric values within |a-b| <= absolute + relative*|reference|; NaN equals NaN.'],
}


# ------------------------------------------------------------------ payload values
def payload_value(v, t):
    """JSON-safe host value for the worker (non-finite floats as text)."""
    t = resolved(t)
    if t.get('dims'):
        inner = {k: x for k, x in t.items() if k != 'dims'}
        return [payload_value(x, inner) for x in v]
    cls = t['class']
    if cls == 'float':
        return v if isinstance(v, str) or math.isfinite(v) else repr(v)
    if cls == 'complex':
        return [x if isinstance(x, str) or math.isfinite(x) else repr(x) for x in v]
    if cls == 'compound':
        return [payload_value(x, f['type']) for x, f in zip(v, t['fields'])]
    if cls in ('vlen',):
        return [payload_value(x, t['base']) for x in v]
    if cls == 'array':
        return payload_value(v, t['base'])
    return v


def input_values(item, data, t, shape, record, at, parsed):
    """Host-checked values of a captured input for a dataset of resolved type t and shape."""
    rt = resolved(t)
    n = element_count(shape)
    fmt = item['format']
    if fmt == 'csv':
        header, rows = parsed.setdefault(item['id'], expect.parse_csv(data, item['delimiter'], '$.inputs.' + item['id']))
        if 'column' in record:
            if record['column'] not in header:
                fail('INVALID_HDF5_DATA', 'the CSV input has no such column', at + '.column', columns=header)
            j = header.index(record['column'])
            if rt['class'] == 'compound':
                fail('INVALID_HDF5_DATA', 'compound datasets map one CSV column per field with columns', at + '.column')
            cells = [r[j] for r in rows]
            if len(cells) != n:
                fail('INVALID_HDF5_DATA', 'the CSV column length does not equal the declared shape', at, rows=len(cells), elements=n)
            return [model.check_element(expect.csv_cell(c, rt, f'{at}[{i}]'), t, f'{at}.row[{i + 2}]') for i, c in enumerate(cells)]
        cols = record['columns']
        missing = [c for c in cols if c not in header]
        if missing:
            fail('INVALID_HDF5_DATA', 'the CSV input has no such column', at + '.columns', missing=missing, columns=header)
        idx = [header.index(c) for c in cols]
        if rt['class'] == 'compound':
            if len(cols) != len(rt['fields']) or len(rows) != n:
                fail('INVALID_HDF5_DATA', 'compound CSV rows give one column per field and one row per element', at, rows=len(rows), elements=n)
            return [model.check_element([expect.csv_cell(r[j], f['type'], at) for j, f in zip(idx, rt['fields'])], t, f'{at}.row[{i + 2}]')
                    for i, r in enumerate(rows)]
        if len(shape) != 2 or shape != [len(rows), len(cols)]:
            fail('INVALID_HDF5_DATA', 'columns fill a two-dimensional dataset of shape [rows, columns]', at, rows=len(rows), columns=len(cols), shape=shape)
        return [model.check_element(expect.csv_cell(r[j], rt, at), t, f'{at}.row[{i + 2}]') for i, r in enumerate(rows) for j in idx]
    if fmt == 'npy':
        nt, nshape, values = parsed.setdefault(item['id'], expect.parse_npy(data, '$.inputs.' + item['id']))
        if nshape != list(shape):
            fail('INVALID_HDF5_DATA', 'the NPY array shape differs from the declared dataset shape', at, npy=nshape, shape=shape)
    else:
        if list(item['shape']) != list(shape):
            fail('INVALID_HDF5_DATA', 'the raw input shape differs from the declared dataset shape', at, raw=item['shape'], shape=shape)
        values = parsed.setdefault(item['id'], expect.parse_raw(data, item, '$.inputs.' + item['id']))
    if rt['class'] not in ('int', 'uint', 'float', 'bool', 'enum'):
        fail('INVALID_HDF5_DATA', 'NPY and raw inputs fill numeric, bool or enum datasets', at)
    out = []
    for i, v in enumerate(values):
        if rt['class'] == 'float' and isinstance(v, bool):
            v = float(v)
        if rt['class'] in ('int', 'uint', 'enum') and isinstance(v, float):
            if not v.is_integer():
                fail('INVALID_HDF5_DATA', 'a non-integral input value cannot fill an integer dataset', f'{at}[{i}]', value=v)
            v = int(v)
        if rt['class'] == 'bool' and not isinstance(v, bool):
            fail('INVALID_HDF5_DATA', 'bool datasets need bool input elements', f'{at}[{i}]')
        out.append(model.check_element(v, t, f'{at}[{i}]'))
    return out


def data_values(data, t, shape, at, captured, parsed, inputs):
    """Iterate host-checked element values for a planned data record, or None for fill/copy/references."""
    src = data['source']
    if src == 'none':
        return None
    n = element_count(shape)
    if src == 'values':
        values = data.get('values')
        if values is None or len(values) != n:
            fail('INVALID_HDF5_DATA', 'value count must equal the product of the selected or declared shape', at + '.values',
                 values=None if values is None else len(values), elements=n)
        return [model.check_element(v, t, f'{at}.values[{i}]') for i, v in enumerate(values)]
    if src in ('range', 'linspace'):
        checked = model.plan_data(data, t, shape, at, {'inputs': inputs, 'referenceChecks': []})
        return list(expect.generated(checked, resolved(t), n))
    if src == 'input':
        item = inputs[data['input']]
        return input_values(item, captured[data['input']], t, shape, data, at, parsed)
    return None
