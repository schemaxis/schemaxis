"""Expected HDF5 state from authored intent, comparison with both consumers, and edit simulation.

Expected records use the same vocabulary as the worker readback and the h5dump XML reader:
{kind, type, shape, maxshape, layout, chunks, filters, fill, scale, dims, attributes, values}.
``values`` is the full canonical element list (bounded) so that the independent XML consumer can be
compared element by element; readback agreement is checked through its SHA-256 summary.
"""
import copy
import itertools

from schemaxis.errors import fail
from . import expect, h5xml
from .model import element_count, resolved, selection

RESERVED = {'CLASS', 'NAME', 'REFERENCE_LIST', 'DIMENSION_LIST', 'DIMENSION_LABELS'}
FILTER_ORDER = ('scaleoffset', 'nbit', 'shuffle', 'gzip', 'lzf', 'szip', 'fletcher32')


def descriptor(t):
    """Comparable type descriptor (named types resolved, enum members by code, no field units)."""
    t = resolved(t)
    cls = t['class']
    if cls == 'compound':
        return {'class': 'compound', 'fields': [{'name': f['name'], 'type': descriptor(f['type'])} for f in t['fields']]}
    if cls == 'vlen':
        return {'class': 'vlen', 'base': descriptor(t['base'])}
    out = {k: v for k, v in t.items() if k in ('class', 'bits', 'order', 'encoding', 'length', 'signed', 'reference', 'size', 'dims')}
    if cls == 'enum':
        out['members'] = sorted(({'name': m['name'], 'value': m['value']} for m in t['members']), key=lambda m: m['value'])
    if cls == 'bool':
        out = {'class': 'bool'}
    return out


def canonical_list(values, t):
    rt = resolved(t)
    return [expect.canonical(v, rt) for v in values]


def indices(sel, shape):
    """Flat C-order indices selected by a normalised selection, in read order."""
    strides = []
    acc = 1
    for d in reversed(shape):
        strides.insert(0, acc)
        acc *= d
    kind = sel['kind']
    if kind == 'all':
        return list(range(element_count(shape)))
    if kind == 'points':
        return [sum(c * s for c, s in zip(p, strides)) for p in sel['points']]
    if kind == 'rows':
        width = strides[0] if strides else 1
        return [r * width + j for r in sel['rows'] for j in range(width)]
    if kind == 'slices':
        axes = [range(a, b, c) for a, b, c in sel['slices']]
    else:
        axes = [[s + k * st + b for k in range(c) for b in range(bl)]
                for s, c, st, bl in zip(sel['start'], sel['count'], sel['stride'], sel['block'])]
    return [sum(c * s for c, s in zip(p, strides)) for p in itertools.product(*axes)]


def attribute_expectation(a):
    if a.get('empty'):
        return {'type': descriptor(a['type']), 'empty': True}
    return {'type': descriptor(a['type']), 'shape': a['shape'], 'values': canonical_list(a['values'], a['type'])}


def fill_element(o):
    rt = resolved(o['type'])
    if 'fillValue' in o['storage']:
        return expect.canonical(o['storage']['fillValue'], rt)
    return expect.canonical(expect.default_fill(rt), rt)


def expected_create(p, values, dependencies=None):
    """Expected objects/links of a createFile plan; ``values`` maps dataset path to host element values."""
    objects = {'/': {'kind': 'group', 'attributes': {a['name']: attribute_expectation(a) for a in p['file']['attributes']}}}
    if p['file'].get('trackOrder'):
        objects['/']['attributeOrder'] = [a['name'] for a in p['file']['attributes']]
    for o in p['objects']:
        for anc in ancestors(o['path']):
            objects.setdefault(anc, {'kind': 'group', 'attributes': {}})
    for o in p['objects']:
        rec = {'kind': o['kind'], 'attributes': {a['name']: attribute_expectation(a) for a in o['attributes']}}
        if o['kind'] == 'datatype':
            rec['type'] = descriptor(o['type'])
        if o['kind'] == 'dataset':
            rec.update(dataset_expectation(o, values, objects))
        if o['kind'] == 'group' and 'trackOrder' in o:
            rec['trackOrder'] = o['trackOrder']
        if o['kind'] == 'dataset':
            rec['trackOrder'] = o.get('trackOrder', False)
        if o['kind'] != 'datatype' and o.get('trackOrder'):
            rec['attributeOrder'] = [a['name'] for a in o['attributes']]
        objects[o['path']] = rec
    for o in p['objects']:
        if o['kind'] == 'dataset' and 'virtual' in o:
            objects[o['path']]['values'] = virtual_values(o, objects, dependencies or {})
    links = {}
    for link in p['links']:
        for anc in ancestors(link['path']):
            objects.setdefault(anc, {'kind': 'group', 'attributes': {}})
        if link['kind'] == 'hard':
            links[link['path']] = {'kind': 'hard', 'target': link['target']}
        elif link['kind'] == 'soft':
            links[link['path']] = {'kind': 'soft', 'target': link['target']}
        else:
            links[link['path']] = {'kind': 'external', 'file': link['file'], 'target': link['target']}
    return {'objects': objects, 'links': links}


def ancestors(path):
    out, parts = [], path.strip('/').split('/')
    for i in range(1, len(parts)):
        out.append('/' + '/'.join(parts[:i]))
    return out


def dataset_expectation(o, values, objects):
    if o.get('empty'):
        rec = {'type': descriptor(o['type']), 'shape': None, 'maxshape': None, 'null': True, 'layout': 'contiguous', 'chunks': None,
               'filters': [], 'scale': None, 'dims': [], 'values': []}
        if o['type']['class'] == 'named':
            rec['committedType'] = o['type']['path']
        return rec
    s = o['storage']
    rt = resolved(o['type'])
    filters = [name for name in FILTER_ORDER if name == 'scaleoffset' and 'scaleOffset' in s or name == 'nbit' and s.get('nbit') or name == 'shuffle' and s.get('shuffle')
               or name == s.get('compression') or name == 'fletcher32' and s.get('fletcher32')]
    rec = {'type': descriptor(o['type']), 'shape': o['shape'], 'maxshape': o['maxshape'], 'layout': s['layout'],
           'chunks': s['chunks'] if s['layout'] == 'chunked' and s['chunks'] != 'auto' else None, 'filters': sorted(filters),
           'scale': o.get('scale'), 'dims': [{'label': d.get('label', ''), 'scales': d['scales']} for d in sorted(o['dimensions'], key=lambda d: d['axis'])]}
    rec['dims'] = [next(({'label': d.get('label', ''), 'scales': d['scales']} for d in o['dimensions'] if d['axis'] == axis), {'label': '', 'scales': []})
                   for axis in range(len(o['shape']))]
    if o['type']['class'] == 'named':
        rec['committedType'] = o['type']['path']
    if 'fillValue' in s:
        rec['fill'] = expect.canonical(s['fillValue'], rt)
    if s['layout'] == 'external':
        rec['external'] = [[seg['path'], seg['offset'], seg['size']] for seg in s['external']]
    n = element_count(o['shape'])
    data = o.get('data', {})
    src = data.get('source')
    if src in ('values', 'input', 'range', 'linspace'):
        rec['values'] = canonical_list(values[o['path']], o['type'])
    elif src == 'external':
        rec['values'] = canonical_list(values[o['path']], o['type'])
    elif src == 'fill':
        rec['values'] = [fill_element(o)] * n if rt['class'] != 'reference' else [None] * n
    elif src == 'copy':
        rec['values'] = list(objects[data['dataset']]['values'])
    elif src == 'references':
        rec['values'] = None
        rec['references'] = [{'path': t['path'], **({'points': sorted(point_list(t['selection'], objects[t['path']]['shape']))} if 'selection' in t else {})}
                             for t in data['targets']]
    return rec


def point_list(sel, shape):
    strides, acc = [], 1
    for d in reversed(shape):
        strides.insert(0, acc)
        acc *= d
    out = set()
    for flat in indices(sel, shape):
        p = []
        for s in strides:
            p.append(flat // s)
            flat %= s
        out.add(tuple(p))
    return [list(p) for p in out]


def virtual_values(o, objects, dependencies):
    n = element_count(o['shape'])
    rt = resolved(o['type'])
    fill = expect.canonical(o['virtual'].get('fill', expect.default_fill(rt)), rt)
    out = [fill] * n
    for s in o['virtual']['sources']:
        if s['file'] == '.':
            src = objects[s['dataset']]
        else:
            src = dependencies.get(s['file'], {'objects': {}})['objects'].get(s['dataset'])
            if src is None or src['kind'] != 'dataset':
                fail('INVALID_HDF5_VIRTUAL', 'the virtual source dataset does not exist in its dependency', s['dataset'], file=s['file'])
            if not h5xml.same_type(src['type'], descriptor(o['type'])):
                fail('INVALID_HDF5_VIRTUAL', 'the virtual source element type differs from the virtual dataset type', s['dataset'], source=src['type'])
            sel = s['select']
            if sel['kind'] == 'slices':
                raw = {'kind': 'slices', 'slices': [{k: v for k, v in zip(('start', 'stop', 'step'), item) if v is not None} for item in sel['slices']]}
                sel = selection(raw, src['shape'], s['dataset'])[0]
            elif sel['kind'] == 'hyperslab':
                sel = selection(sel, src['shape'], s['dataset'])[0]
            count = len(indices(sel, src['shape']))
            if count != s['count']:
                fail('INVALID_HDF5_VIRTUAL', 'source and target selections select the same number of elements', s['dataset'], source=count, target=s['count'])
            s = {**s, 'select': sel}
        if src.get('values') is None:
            return None
        picked = [src['values'][i] for i in indices(s['select'], src['shape'])]
        for target, value in zip(indices(s['at'], o['shape']), picked):
            out[target] = value
    return out


# ------------------------------------------------------------------ comparison
def mismatch(where, what, **observed):
    fail('VERIFICATION_FAILED', what, where, **observed)


def check_attribute_order(path, want, observed, consumer):
    """Authored attributes of an object that tracks creation order appear in that order (HDF5-maintained ones excluded)."""
    if 'attributeOrder' not in want:
        return
    order = [name for name in observed or [] if name in want['attributes']]
    if observed is None or order != want['attributeOrder']:
        mismatch(path, consumer + ': attribute creation order differs', expected=want['attributeOrder'], observed=observed)


def compare_readback(expected, manifest, *, exact=True, consumer='readback'):
    objects = manifest['objects']
    addresses = {path: rec.get('address') for path, rec in objects.items()}
    for path, want in expected['objects'].items():
        got = objects.get(path)
        if got is None:
            mismatch(path, consumer + ': declared object is missing')
        if got['kind'] != want['kind']:
            mismatch(path, consumer + ': object kind differs', expected=want['kind'], observed=got['kind'])
        compare_attributes(path, want['attributes'], got['attributes'], consumer)
        if want['kind'] == 'datatype' and got.get('type') != want['type']:
            mismatch(path, consumer + ': committed datatype differs', expected=want['type'], observed=got.get('type'))
        if 'trackOrder' in want and got.get('trackOrder') != want['trackOrder']:
            mismatch(path, consumer + ': creation order tracking differs', expected=want['trackOrder'], observed=got.get('trackOrder'))
        check_attribute_order(path, want, got.get('attributeOrder'), consumer)
        if want['kind'] != 'dataset':
            continue
        for key in ('type', 'shape', 'maxshape', 'layout'):
            if got.get(key) != want[key]:
                mismatch(path, consumer + ': dataset ' + key + ' differs', expected=want[key], observed=got.get(key))
        if bool(got.get('null')) != bool(want.get('null')):
            mismatch(path, consumer + ': null dataspace differs', expected=bool(want.get('null')), observed=bool(got.get('null')))
        if want['chunks'] is not None and got.get('chunks') != want['chunks']:
            mismatch(path, consumer + ': chunk shape differs', expected=want['chunks'], observed=got.get('chunks'))
        if sorted(f['name'] for f in got.get('filters', [])) != want['filters']:
            mismatch(path, consumer + ': filter pipeline differs', expected=want['filters'], observed=[f['name'] for f in got.get('filters', [])])
        if 'fill' in want and got.get('fill') != want['fill']:
            mismatch(path, consumer + ': fill value differs', expected=want['fill'], observed=got.get('fill'))
        if got.get('scale') != want['scale']:
            mismatch(path, consumer + ': dimension-scale status differs', expected=want['scale'], observed=got.get('scale'))
        want_dims = [{'label': d['label'], 'scales': [addresses.get(x) for x in d['scales']]} for d in want['dims']]
        if got.get('dims') != want_dims:
            mismatch(path, consumer + ': dimension labels or attached scales differ', expected=want['dims'], observed=got.get('dims'))
        if 'committedType' in want and (not got.get('committedType') or got.get('typeAddress') != addresses.get(want['committedType'])):
            mismatch(path, consumer + ': dataset no longer uses the declared committed datatype', expected=want['committedType'])
        if 'external' in want and got.get('external') != want['external']:
            mismatch(path, consumer + ': external raw storage segments differ', expected=want['external'], observed=got.get('external'))
        if 'references' in want:
            got_targets = got.get('targets') or []
            if len(got_targets) != len(want['references']):
                mismatch(path, consumer + ': reference count differs')
            for i, (w, g) in enumerate(zip(want['references'], got_targets)):
                if w is None or w.get('unresolved'):
                    if (g is None) != (w is None) or w is not None and not (g or {}).get('unresolved'):
                        mismatch(f'{path}[{i}]', consumer + ': null or dangling reference state differs')
                    continue
                if g is None or g.get('unresolved') or g.get('address') != addresses.get(w['path']):
                    mismatch(f'{path}[{i}]', consumer + ': reference does not resolve to the declared object', expected=w['path'], observed=g and g.get('path'))
                if 'points' in w and sorted(g.get('points') or []) != w['points']:
                    mismatch(f'{path}[{i}]', consumer + ': region reference selects different elements')
            continue
        if want.get('regions'):
            got_regions = (got.get('regions') or [])
            if len(got_regions) != len(want['regions']):
                mismatch(path, consumer + ': region digests were not read back')
            for w, g in zip(want['regions'], got_regions):
                if 'digest' in w:
                    target = (w['digest'].get('count'), w['digest'].get('sha256'))
                else:
                    d = expect.Digest()
                    for v in w['values']:
                        d.add(v)
                    target = (d.result()['count'], d.result()['sha256'])
                if (g.get('count'), g.get('sha256')) != target:
                    mismatch(path, consumer + (': preserved rows changed' if 'digest' in w else ': appended rows differ from the authored block'))
        if want.get('values') is None and want.get('digest'):
            summary = got.get('values') or {}
            if (summary.get('count'), summary.get('sha256')) != (want['digest'].get('count'), want['digest'].get('sha256')):
                mismatch(path, consumer + ': preserved values beyond the literal budget changed', expected=want['digest'], observed={k: summary.get(k) for k in ('count', 'sha256')})
        if want.get('values') is not None:
            summary = got.get('values')
            if summary is None:
                mismatch(path, consumer + ': values were not read back')
            d = expect.Digest()
            for e in want['values']:
                d.add(e)
            mine = d.result()
            if summary['count'] != mine['count'] or summary['sha256'] != mine['sha256']:
                first = next((i for i, (a, b) in enumerate(zip(summary.get('head', []), want['values'])) if a != b), None)
                mismatch(path, consumer + ': stored values differ from the independently computed values', expected=mine, observed={k: summary.get(k) for k in ('count', 'sha256')},
                         firstDifference=first)
    if exact:
        declared = set(expected['objects']) | set(expected['links'])
        extra = sorted(set(objects) - declared - {p for p, w in expected['links'].items() if w['kind'] == 'hard'})
        extra += sorted(set(manifest['links']) - declared)
        if extra:
            mismatch(extra[0], consumer + ': undeclared objects or links are present', paths=extra[:16])
    for path, want in expected['links'].items():
        if want['kind'] == 'hard':
            got = objects.get(path)
            if got is None or got.get('address') != addresses.get(want['target']):
                mismatch(path, consumer + ': hard link does not share the target object', target=want['target'])
            continue
        got = manifest['links'].get(path)
        if got is None or got.get('kind') != want['kind'] or got.get('target') != want['target'] or want['kind'] == 'external' and got.get('file') != want['file']:
            mismatch(path, consumer + ': link differs', expected=want, observed=got)


def compare_attributes(path, want, got, consumer):
    got = {k: v for k, v in got.items() if k not in RESERVED}
    if set(want) != set(got):
        mismatch(path, consumer + ': attribute names differ', expected=sorted(want), observed=sorted(got))
    for name, w in want.items():
        g = got[name]
        if g.get('type') != w['type'] or bool(g.get('empty')) != bool(w.get('empty')):
            mismatch(path + '@' + name, consumer + ': attribute type or emptiness differs', expected=w, observed={k: g.get(k) for k in ('type', 'empty')})
        if not w.get('empty') and (g.get('shape') != w['shape'] or g.get('values') is not None and g.get('values') != w['values']):
            mismatch(path + '@' + name, consumer + ': attribute value differs', expected=w.get('values')[:16], observed=(g.get('values') or [])[:16])


def compare_xml(expected, xml):
    """Independent h5dump agreement: structure, types, shapes, layouts, filters, attributes, scales, links and values."""
    objects = xml['objects']
    declared = set(expected['objects']) | set(expected['links'])
    observed = set(objects) | set(xml['links'])
    if declared != observed:
        extra, missing = sorted(observed - declared), sorted(declared - observed)
        mismatch((extra or missing)[0], 'h5dump: object and link names differ from the expected file', undeclared=extra[:16], missing=missing[:16])

    def identity(path):
        rec = objects.get(path)
        if rec is None:
            return path
        if rec.get('kind') == 'alias':
            return (rec.get('xid') or '').split('-')[0] or rec.get('of')
        return (rec.get('xid') or '').split('-')[0] or path
    for path, want in expected['objects'].items():
        got = objects.get(path)
        if got is None:
            mismatch(path, 'h5dump: declared object is missing')
        if got['kind'] == 'alias':
            got = objects.get(got['of'])
        if want['kind'] == 'datatype':
            continue
        if got['kind'] != want['kind']:
            mismatch(path, 'h5dump: object kind differs', expected=want['kind'], observed=got['kind'])
        xml_attributes = {k: v for k, v in got['attributes'].items() if k not in RESERVED}
        check_attribute_order(path, want, list(got['attributes']), 'h5dump')
        if set(xml_attributes) != set(want['attributes']):
            mismatch(path, 'h5dump: attribute names differ', expected=sorted(want['attributes']), observed=sorted(xml_attributes))
        for name, w in want['attributes'].items():
            g = xml_attributes[name]
            gt = g['type'] if g['type'].get('class') != 'compound' else _complex(g['type'])
            if not h5xml.same_type(gt, w['type']):
                mismatch(path + '@' + name, 'h5dump: attribute type differs', expected=w['type'], observed=g['type'])
            if not w.get('empty') and g.get('values') is not None and _norm(g['values'], w['type']) != w['values']:
                mismatch(path + '@' + name, 'h5dump: attribute value differs', expected=w['values'][:16], observed=g['values'][:16])
        if want['kind'] != 'dataset':
            continue
        if not h5xml.same_type(got['type'], want['type']):
            mismatch(path, 'h5dump: dataset type differs', expected=want['type'], observed=got['type'])
        if got['shape'] != want['shape'] or got['maxshape'] != want['maxshape'] or bool(got.get('null')) != bool(want.get('null')):
            mismatch(path, 'h5dump: dataspace differs', expected=[want['shape'], want['maxshape']], observed=[got['shape'], got['maxshape']])
        layout = want['layout'] if want['layout'] not in ('external', 'virtual') else got['layout']
        if got['layout'] != layout and not (want['layout'] == 'external' and got['layout'] in ('external', 'contiguous')):
            mismatch(path, 'h5dump: storage layout differs', expected=want['layout'], observed=got['layout'])
        if 'committedType' in want and identity(got.get('committedType') or '') != identity(want['committedType']):
            mismatch(path, 'h5dump: dataset no longer uses the declared committed datatype', expected=want['committedType'], observed=got.get('committedType'))
        if want['chunks'] is not None and got.get('chunks') != want['chunks']:
            mismatch(path, 'h5dump: chunk shape differs', expected=want['chunks'], observed=got.get('chunks'))
        if want['layout'] == 'chunked' and sorted(got.get('filters', [])) != [f for f in want['filters'] if f not in h5xml.UNNAMED_FILTERS]:
            mismatch(path, 'h5dump: filter pipeline differs', expected=want['filters'], observed=got.get('filters'))
        scale = got['attributes'].get('NAME') if got['attributes'].get('CLASS', {}).get('values') == ['DIMENSION_SCALE'] else None
        if (want['scale'] is not None) != (got['attributes'].get('CLASS', {}).get('values') == ['DIMENSION_SCALE']):
            mismatch(path, 'h5dump: dimension-scale status differs', expected=want['scale'])
        if want['scale'] and scale is not None and scale.get('values') not in ([want['scale']], None):
            mismatch(path, 'h5dump: dimension-scale name differs', expected=want['scale'], observed=scale.get('values'))
        attached = got['attributes'].get('DIMENSION_LIST', {}).get('scales')
        want_attached = [[identity(x) for x in d['scales']] for d in want['dims']]
        if any(d['scales'] for d in want['dims']) or attached is not None:
            if attached is None or len(attached) != len(want_attached) or [sorted(identity(x) for x in a) for a in attached] != [sorted(a) for a in want_attached]:
                mismatch(path, 'h5dump: attached dimension scales differ', expected=[d['scales'] for d in want['dims']], observed=attached)
        labels = got['attributes'].get('DIMENSION_LABELS', {}).get('values')
        if labels is not None and [x or '' for x in labels] != [d['label'] for d in want['dims']]:
            mismatch(path, 'h5dump: dimension labels differ', expected=[d['label'] for d in want['dims']], observed=labels)
        if want.get('values') is not None and got.get('values') is not None:
            observed = _norm(got['values'], want['type'])
            if observed != want['values']:
                first = next((i for i, (a, b) in enumerate(zip(observed, want['values'])) if a != b), None)
                mismatch(path, 'h5dump: stored values differ from the independently computed values', firstDifference=first,
                         expected=want['values'][first] if first is not None and first < len(want['values']) else None,
                         observed=observed[first] if first is not None and first < len(observed) else len(observed))
    for path, want in expected['links'].items():
        if want['kind'] == 'hard':
            got = objects.get(path)
            target = objects.get(want['target'])
            if got is None or target is None:
                mismatch(path, 'h5dump: hard link is missing')
            ids = {got.get('xid', '').split('-')[0], (got.get('of') and objects.get(got['of'], {}).get('xid', '').split('-')[0]) or None}
            tids = {target.get('xid', '').split('-')[0], (target.get('of') and objects.get(target['of'], {}).get('xid', '').split('-')[0]) or None}
            if not (ids - {None, ''}) & (tids - {None, ''}):
                mismatch(path, 'h5dump: hard link does not share the target object', target=want['target'])
            continue
        got = xml['links'].get(path)
        if got is None or got['kind'] != want['kind'] or got['target'] != want['target'] or want['kind'] == 'external' and got['file'] != want['file']:
            mismatch(path, 'h5dump: link differs', expected=want, observed=got)


def _complex(t):
    from .h5xml import complex_as_compound
    return complex_as_compound(t)


def _norm(values, t):
    """XML canonical values -> expected canonical shape (complex pairs and bool already handled by the reader)."""
    return values


# ------------------------------------------------------------------ editing simulation
def subtree(paths, root):
    return [p for p in paths if p == root or p.startswith(root.rstrip('/') + '/')]


def simulate(state, edits, values, dependency_states, keys=None, start=0):
    """Apply planned edits to an expected state (from the independent source manifest)."""
    s = copy.deepcopy(state)
    for i, e in enumerate(edits, start):
        at = f'$.edits[{i}]'
        action = e['action']
        objects, links = s['objects'], s['links']
        if action == 'create':
            o = e['object']
            exp = expected_create({'file': {'attributes': []}, 'objects': [o], 'links': []}, values)
            for path, rec in exp['objects'].items():
                if path == '/':
                    continue
                if path in objects and path != o['path']:
                    continue
                if path in objects or path in links:
                    fail('INVALID_HDF5_EDIT', 'the created path already exists in the source', at + '.object.path', path=path)
                objects[path] = rec
        elif action == 'delete':
            path = e['path']
            if path not in objects and path not in links:
                fail('INVALID_HDF5_EDIT', 'the deleted path does not exist', at + '.path', path=path)
            deleted = set(subtree(list(objects), path)) | set(subtree(list(links), path))
            for rec in objects.values():
                for j, ref in enumerate(rec.get('references') or []):
                    if ref and ref.get('path') in deleted:
                        aliases = sorted(q for q, r in links.items() if r['kind'] == 'hard' and q not in deleted
                                         and (r['target'] == ref['path'] or links.get(ref['path'], {}).get('target') in (q, r['target'])))
                        if not aliases:
                            holder = next(q for q, r in objects.items() if r is rec)
                            if holder not in deleted:
                                fail('INVALID_HDF5_EDIT', 'deleting this object would leave a dangling object or region reference; delete or rewrite the referencing dataset first',
                                     at + '.path', reference=f'{holder}[{j}]', target=ref['path'])
                            continue
                        rec['references'][j] = {**ref, 'path': aliases[0]}
            for p in subtree(list(objects), path):
                del objects[p]
            for p in subtree(list(links), path):
                del links[p]
            for rec in objects.values():
                for d in rec.get('dims') or []:
                    d['scales'] = [x for x in d['scales'] if x not in deleted]
            for p, rec in list(links.items()):
                if rec['kind'] == 'hard' and (rec['target'] == path or rec['target'].startswith(path.rstrip('/') + '/')):
                    survivors = [q for q, r in links.items() if r['kind'] == 'hard' and r['target'] == rec['target'] and q in objects]
                    promoted = sorted(survivors)[0] if survivors else None
                    for q in survivors:
                        links[q] = {'kind': 'hard', 'target': promoted}
                    if promoted is not None:
                        del links[promoted]
        elif action in ('move', 'copy'):
            source_state = dependency_states[e['from']] if e.get('from') else s
            path, to = e['path'], e['to']
            if path not in source_state['objects'] and path not in source_state['links']:
                fail('INVALID_HDF5_EDIT', 'the source path does not exist', at + '.path', path=path)
            if action == 'copy' and source_state['links'].get(path, {}).get('kind') in ('soft', 'external'):
                fail('INVALID_HDF5_EDIT', 'copy would follow a soft or external link; copy the linked object by its own path', at + '.path', path=path)
            for anc in ancestors(path):
                if source_state['links'].get(anc, {}).get('kind') in ('soft', 'external'):
                    fail('INVALID_HDF5_EDIT', 'the path passes through a soft or external link; use the object path itself', at + '.path', link=anc)
            if to in objects or to in links:
                fail('INVALID_HDF5_EDIT', 'the destination path already exists', at + '.to', path=to)
            for anc in ancestors(to):
                if anc in objects and objects[anc]['kind'] != 'group':
                    fail('INVALID_HDF5_EDIT', 'the destination parent is not a group', at + '.to', parent=anc)
                objects.setdefault(anc, {'kind': 'group', 'attributes': {}})
            moved_objects = {p: source_state['objects'][p] for p in subtree(list(source_state['objects']), path)}
            moved_links = {p: source_state['links'][p] for p in subtree(list(source_state['links']), path)}
            if action == 'copy' and e['shallow']:
                depth = path.rstrip('/').count('/') + 1
                moved_objects = {p: r for p, r in moved_objects.items() if p.count('/') <= depth}
                moved_links = {p: r for p, r in moved_links.items() if p.count('/') <= depth}
            inside = lambda x: x == path or x.startswith(path.rstrip('/') + '/')
            for p, rec in moved_objects.items():
                rec = copy.deepcopy(rec)
                if action == 'copy' and e['withoutAttributes']:
                    rec['attributes'] = {}
                    if 'attributeOrder' in rec:
                        rec['attributeOrder'] = []
                    rec['dims'] = [{'label': '', 'scales': []} for _ in rec.get('dims') or []] if rec['kind'] == 'dataset' else rec.get('dims')
                    if rec['kind'] == 'dataset':
                        rec['scale'] = None
                elif action == 'copy' and rec.get('dims'):
                    rec['dims'] = [{'label': d['label'], 'scales': [to + x[len(path):] if inside(x) else x for x in d['scales']
                                                                    if inside(x) or not e.get('from')]} for d in rec['dims']]
                objects[to + p[len(path):]] = rec
            for p, rec in moved_links.items():
                rec = copy.deepcopy(rec)
                if action == 'copy' and e['expandSoft'] and rec['kind'] == 'soft':
                    target = source_state['objects'].get(rec['target'])
                    if target is None:
                        fail('INVALID_HDF5_EDIT', 'expandSoft needs every soft link in the copied tree to resolve', at, link=p)
                    objects[to + p[len(path):]] = copy.deepcopy(target)
                    continue
                if rec['kind'] == 'hard' and inside(rec['target']):
                    rec['target'] = to + rec['target'][len(path):]
                links[to + p[len(path):]] = rec
            if action == 'copy' and e.get('from') and any(r.get('references') for r in moved_objects.values()):
                fail('INVALID_HDF5_EDIT', 'references cannot be copied between files; their targets would not exist in the edited file', at + '.path')
            if action == 'move':
                for rec in list(objects.values()) + list(moved_objects.values()):
                    for ref in rec.get('references') or []:
                        if ref and ref.get('path') and (ref['path'] == path or ref['path'].startswith(path.rstrip('/') + '/')):
                            ref['path'] = to + ref['path'][len(path):]
                for p in moved_objects:
                    del objects[p]
                for p in moved_links:
                    del links[p]
                for rec in objects.values():
                    for d in rec.get('dims') or []:
                        d['scales'] = [to + x[len(path):] if x == path or x.startswith(path + '/') else x for x in d['scales']]
                for rec in links.values():
                    if rec['kind'] == 'hard' and (rec['target'] == path or rec['target'].startswith(path + '/')):
                        rec['target'] = to + rec['target'][len(path):]
        elif action == 'link':
            link = e['link']
            if link['path'] in objects or link['path'] in links:
                fail('INVALID_HDF5_EDIT', 'the link path already exists', at + '.link.path')
            for anc in ancestors(link['path']):
                objects.setdefault(anc, {'kind': 'group', 'attributes': {}})
            if link['kind'] == 'hard':
                if link['target'] not in objects:
                    fail('INVALID_HDF5_EDIT', 'hard links target an existing object', at + '.link.target')
                links[link['path']] = {'kind': 'hard', 'target': link['target']}
                objects[link['path']] = objects[link['target']]
            else:
                links[link['path']] = {k: link[k] for k in ('kind', 'target', 'file') if k in link and link[k] is not None}
        elif action == 'setAttribute':
            obj = need(objects, e['path'], at + '.path')
            obj['attributes'][e['attribute']['name']] = attribute_expectation(e['attribute'])
            reorder(obj, e['attribute']['name'], e['attribute']['name'])
        elif action == 'renameAttribute':
            obj = need(objects, e['path'], at + '.path')
            if e['name'] not in obj['attributes']:
                fail('INVALID_HDF5_EDIT', 'the attribute does not exist', at + '.name', name=e['name'])
            if e['newName'] in obj['attributes']:
                fail('INVALID_HDF5_EDIT', 'an attribute with the new name already exists', at + '.newName', name=e['newName'])
            obj['attributes'][e['newName']] = obj['attributes'].pop(e['name'])
            reorder(obj, e['name'], e['newName'])
        elif action == 'deleteAttribute':
            obj = need(objects, e['path'], at + '.path')
            if e['name'] not in obj['attributes']:
                fail('INVALID_HDF5_EDIT', 'the attribute does not exist', at + '.name', name=e['name'])
            del obj['attributes'][e['name']]
            reorder(obj, e['name'], None)
        elif action == 'write':
            obj = dataset(objects, e['path'], at)
            sel = e['selection']
            positions = indices(sel, obj['shape'])
            new = canonical_list(values[(i, 'write')], e.get('fieldType', e['type']))
            if obj.get('values') is None:
                obj['valuesUnknown'] = True
            elif 'fields' in e:
                names = [f['name'] for f in resolved(e['type'])['fields']]
                picks = [names.index(n) for n in e['fields']]
                for pos, v in zip(positions, new):
                    record = list(obj['values'][pos])
                    for k, value in zip(picks, v if len(picks) > 1 else [v]):
                        record[k] = value
                    obj['values'][pos] = record
            else:
                for pos, v in zip(positions, new):
                    obj['values'][pos] = v
        elif action == 'resize':
            obj = dataset(objects, e['path'], at)
            obj['values'] = reshape(obj, e['shape'])
            obj['shape'] = list(e['shape'])
        elif action == 'append':
            obj = dataset(objects, e['path'], at)
            axis = e['axis']
            new_shape = list(obj['shape'])
            new_shape[axis] += e['appendShape'][axis]
            grown = reshape(obj, new_shape)
            block = canonical_list(values[(i, 'append')], e['type'])
            start = [0] * len(new_shape)
            start[axis] = obj['shape'][axis]
            sel = {'kind': 'hyperslab', 'start': start, 'count': e['appendShape'], 'stride': [1] * len(new_shape), 'block': [1] * len(new_shape)}
            if grown is not None:
                for pos, v in zip(indices(sel, new_shape), block):
                    grown[pos] = v
            elif obj.get('digest') or obj.get('regions'):
                regions = obj.get('regions') or [{'selection': {'kind': 'slices', 'slices': [[0, n, 1] for n in obj['shape']]}, 'digest': obj['digest']}]
                obj['regions'] = regions + [{'selection': sel, 'values': block}]
                obj['digest'] = None
            obj['values'], obj['shape'] = grown, new_shape
        elif action == 'copyChunks':
            src = dataset(objects, e['path'], at + '.path')
            dst = dataset(objects, e['to'], at + '.to')
            for key in ('layout', 'shape', 'chunks', 'type', 'filters'):
                if src.get(key) != dst.get(key):
                    fail('INVALID_HDF5_EDIT', 'copyChunks needs two chunked datasets with the same shape, chunk shape, type and filters',
                         at + '.to', differs=key, source=src.get(key), target=dst.get(key))
            if src['layout'] != 'chunked':
                fail('INVALID_HDF5_EDIT', 'copyChunks copies stored chunks; the datasets are not chunked', at + '.path')
            if src.get('values') is not None:
                dst['values'] = list(src['values'])
            elif src.get('digest') and not src.get('regions'):
                dst['values'], dst['digest'] = None, dict(src['digest'])
                dst.pop('regions', None)
            else:
                fail('HDF5_RESOURCE_LIMIT', 'copyChunks needs the source values or a whole-content digest', at + '.path')
        elif action == 'makeScale':
            obj = dataset(objects, e['path'], at)
            obj['scale'] = e['name']
        elif action in ('attachScale', 'detachScale'):
            obj = dataset(objects, e['path'], at)
            scale = dataset(objects, e['scale'], at + '.scale')
            if scale.get('scale') is None:
                fail('INVALID_HDF5_EDIT', 'attach a dataset that is a dimension scale (makeScale first)', at + '.scale')
            if e['axis'] >= len(obj['shape']):
                fail('INVALID_HDF5_EDIT', 'the axis does not exist', at + '.axis')
            scales = obj['dims'][e['axis']]['scales']
            if action == 'attachScale':
                if scale['shape'] != [obj['shape'][e['axis']]]:
                    fail('INVALID_HDF5_EDIT', 'a scale has exactly the length of the axis it describes', at + '.scale')
                if e['scale'] not in scales:
                    scales.append(e['scale'])
            else:
                if e['scale'] not in scales:
                    fail('INVALID_HDF5_EDIT', 'the scale is not attached to this axis', at + '.scale')
                scales.remove(e['scale'])
        elif action == 'relayout':
            obj = dataset(objects, e['path'], at)
            if obj.get('scale') is not None:
                fail('INVALID_HDF5_EDIT', 'relayout of a dimension scale would detach its datasets; relayout the datasets instead', at + '.path')
            st = e['storage']
            obj['layout'] = st['layout']
            obj['chunks'] = st['chunks'] if st['layout'] == 'chunked' and st['chunks'] != 'auto' else None
            obj['filters'] = sorted(name for name in FILTER_ORDER if name == 'scaleoffset' and 'scaleOffset' in st or name == 'nbit' and st.get('nbit') or name == 'shuffle' and st.get('shuffle')
                                    or name == st.get('compression') or name == 'fletcher32' and st.get('fletcher32'))
            if 'fillValue' in st:
                obj['fill'] = expect.canonical(st['fillValue'], resolved(e['type']))
    return s


def need(objects, path, at):
    if path not in objects:
        fail('INVALID_HDF5_EDIT', 'the path does not exist in the edited file', at, path=path)
    return objects[path]


def reorder(obj, old, new):
    """Creation order after an attribute is (re)written, renamed or deleted: HDF5 creates the new attribute last."""
    if 'attributeOrder' in obj:
        obj['attributeOrder'] = [n for n in obj['attributeOrder'] if n not in (old, new)] + ([new] if new else [])


def dataset(objects, path, at):
    obj = need(objects, path, at)
    if obj['kind'] != 'dataset':
        fail('INVALID_HDF5_EDIT', 'the path is not a dataset', at, path=path)
    return obj


def reshape(obj, new_shape):
    """Values after resize: retained overlap in place, new elements are the fill value."""
    old_shape = obj['shape']
    if any(m != 'unlimited' and n > m for n, m in zip(new_shape, obj['maxshape'])) or len(new_shape) != len(old_shape):
        fail('INVALID_HDF5_EDIT', 'the new shape exceeds maxshape or changes the rank', '$.edits', shape=new_shape, maxshape=obj['maxshape'])
    if obj.get('values') is None:
        return None
    fill = obj.get('fill', obj.get('defaultFill'))
    out = [fill] * element_count(new_shape)
    keep = [min(a, b) for a, b in zip(old_shape, new_shape)]
    if element_count(keep):
        sel = {'kind': 'slices', 'slices': [[0, k, 1] for k in keep]}
        for src, dst in zip(indices(sel, old_shape), indices(sel, new_shape)):
            out[dst] = obj['values'][src]
    return out
