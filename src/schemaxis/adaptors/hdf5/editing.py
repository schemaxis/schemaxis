"""editFile: ordered typed edits on a captured copy, with host simulation over the independent source reading.

The base state is the captured source as observed by a fresh h5py readback (metadata, scale attachments,
fill definitions) and h5dump XML (literal values). Each edit is resolved against the simulated state
(types, selections, shapes, appended blocks) before any native work, so authoring faults are located at
the edit that causes them. The output must then agree with the simulated state through both consumers.
"""
import copy
import json
import shutil

from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from . import expect, model, operations, state


def resolve(p, base, dependency_states, captured):
    """Return (resolved native edits, expected state, payload values) for an edit plan."""
    current = copy.deepcopy(base)
    values, native = {}, []
    parsed = {}
    inputs = {i['id']: i for i in p['inputs']}
    for i, e in enumerate(p['edits']):
        at = f'$.edits[{i}]'
        e = copy.deepcopy(e)
        e['key'] = 'e%d' % i
        action = e['action']
        if action == 'create':
            o = e['object']
            if o['kind'] == 'dataset':
                v = operations.data_values(o['data'], o['type'], o['shape'], at + '.object.data', captured, parsed, inputs)
                if v is not None:
                    values[o['path']] = v
                    e['object']['payload'] = e['key']
                    values[e['key']] = v
            for anc in state.ancestors(o['path']):
                rec = current['objects'].get(anc)
                if rec is not None and rec['kind'] != 'group':
                    fail('INVALID_HDF5_EDIT', 'a parent of the created path is not a group', at + '.object.path', parent=anc)
        elif action in ('write', 'append', 'relayout', 'resize'):
            obj = current['objects'].get(e['path'])
            if obj is None or obj['kind'] != 'dataset':
                fail('INVALID_HDF5_EDIT', 'the path is not a dataset in the edited file', at + '.path', path=e['path'])
            if obj.get('null'):
                fail('INVALID_HDF5_EDIT', 'the dataset has a null dataspace: no elements or extent to %s; delete it and create a dataset with a shape' % action,
                     at + '.path')
            t = obj['type']
            if t['class'] in ('reference',) and action in ('write', 'append'):
                fail('INVALID_HDF5_EDIT', 'reference datasets are rebuilt with createFile, not written element by element', at + '.path')
            e['type'] = t
            if action == 'write' and obj.get('values') is None:
                fail('HDF5_RESOURCE_LIMIT', 'writes into datasets beyond the independently verified value budget are not offered; append instead', at + '.path')
            if action == 'append' and obj.get('values') is None and (obj['type']['class'] not in ('int', 'uint', 'float') or not (obj.get('digest') or obj.get('regions'))):
                fail('HDF5_RESOURCE_LIMIT', 'appends to large datasets need integer or float elements with a preserved-content digest', at + '.path')
            if action == 'write' and 'fields' in e:
                names = [f['name'] for f in model.resolved(t)['fields']] if model.resolved(t)['class'] == 'compound' else []
                for j, name in enumerate(e['fields']):
                    if name not in names:
                        fail('INVALID_HDF5_EDIT', 'fields name members of a compound dataset', f'{at}.fields[{j}]', fields=names)
                members = [model.resolved(t)['fields'][names.index(n)] for n in e['fields']]
                e['fieldType'] = members[0]['type'] if len(members) == 1 else {'class': 'compound', 'fields': members}
            if action == 'write':
                rec = e.pop('selectionRecord')
                if rec['kind'] == 'slices' and rec.get('slices'):
                    pass
                sel, shape, count = model.selection(rec, obj['shape'], at + '.selection', writable=True)
                e['selection'], e['selectedShape'] = sel, shape
                v = operations.data_values(e.pop('dataRecord'), e.get('fieldType', t), shape, at + '.data', captured, parsed, inputs)
                values[(e['key'], 'write')] = v
                e['payload'] = e['key']
                values[e['key']] = v
            elif action == 'append':
                if obj['layout'] != 'chunked':
                    fail('INVALID_HDF5_EDIT', 'only chunked resizable datasets can grow', at + '.path', layout=obj['layout'])
                axis, block = e['axis'], e['appendShape']
                if axis >= len(obj['shape']) or len(block) != len(obj['shape']) or any(b != s for j, (b, s) in enumerate(zip(block, obj['shape'])) if j != axis):
                    fail('INVALID_HDF5_EDIT', 'the appended block matches the dataset shape on every other axis', at + '.shape', shape=obj['shape'], axis=axis)
                limit = obj['maxshape'][axis]
                if limit != 'unlimited' and obj['shape'][axis] + block[axis] > limit:
                    fail('INVALID_HDF5_EDIT', 'appending would exceed maxshape', at + '.shape', maxshape=obj['maxshape'])
                v = operations.data_values(e.pop('dataRecord'), t, block, at + '.data', captured, parsed, inputs)
                values[(e['key'], 'append')] = v
                e['payload'] = e['key']
                values[e['key']] = v
            elif action == 'resize':
                if obj['layout'] != 'chunked':
                    fail('INVALID_HDF5_EDIT', 'only chunked datasets can be resized', at + '.path', layout=obj['layout'])
                if len(e['shape']) != len(obj['shape']) or any(m != 'unlimited' and n > m for n, m in zip(e['shape'], obj['maxshape'])):
                    fail('INVALID_HDF5_EDIT', 'the new shape keeps the rank and stays within maxshape', at + '.shape', maxshape=obj['maxshape'])
            else:
                ctx = model.context({'inputs': [], 'dependencies': []})
                storage = model.plan_storage(e.pop('storageRecord'), t, obj['shape'], obj['maxshape'], at + '.storage', ctx, False)
                if storage['layout'] in ('external', 'virtual'):
                    fail('INVALID_HDF5_EDIT', 'relayout chooses contiguous, chunked or compact storage', at + '.storage.layout')
                e['storage'], e['maxshape'] = storage, obj['maxshape']
        elif action in ('makeScale', 'attachScale', 'detachScale', 'copyChunks') and any(
                (current['objects'].get(e.get(key)) or {}).get('null') for key in ('path', 'scale', 'to')):
            key = next(k for k in ('path', 'scale', 'to') if (current['objects'].get(e.get(k)) or {}).get('null'))
            fail('INVALID_HDF5_EDIT', 'a dataset with a null dataspace has no axes, scales or stored chunks', at + '.' + key)
        elif action == 'copyChunks':
            touched = [x for x in p['edits'][:i] for y in (x.get('path'), x.get('to'), x.get('object', {}).get('path'), x.get('link', {}).get('path'))
                       if y and (e['path'] == y or e['path'].startswith(y.rstrip('/') + '/'))]
            if touched or e['path'] not in base['objects']:
                fail('INVALID_HDF5_EDIT', 'copyChunks copies from a dataset as captured; earlier edits may not create, move or change it', at + '.path')
        elif action == 'copy' and 'from' in e:
            dep = next(d for d in p['dependencies'] if d['id'] == e['from'])
            e['fromName'] = dep['name']
        step = state.simulate(current, [e], {(i, 'write'): values.get((e['key'], 'write')), (i, 'append'): values.get((e['key'], 'append')),
                                             **{k: v for k, v in values.items() if isinstance(k, str) and k.startswith('/')}},
                              dependency_states, start=i)
        current = step
        native.append(e)
    if p['repack']:
        for rec in current['objects'].values():
            if rec.get('references'):
                rec['references'] = [None if ref is not None and ref.get('unresolved') else ref for ref in rec['references']]
    return native, current, values


def run(p, directory, paths, deadline, captured):
    from . import adaptor
    readback, xml, base = adaptor.source_state(directory, paths, deadline)
    adaptor.agreement(base, xml)
    deps = {}
    for d in p['dependencies']:
        if d['role'] == 'copySource':
            _, dxml, dstate = adaptor.source_state(directory, paths, deadline, d['name'], d['id'])
            adaptor.agreement(dstate, dxml)
            deps[d['id']] = dstate
    native, expected, values = resolve(p, base, deps, captured)
    for e in native:
        name = e.get('payload') or e.get('object', {}).get('payload')
        if name:
            atomic_json(directory / ('payload-%s.json' % name),
                        [operations.payload_value(v, e.get('fieldType', e['type']) if e['action'] != 'create' else e['object']['type']) for v in values[e['key']]])
    shutil.copyfile(directory / 'source.h5', directory / 'working.h5')
    config = adaptor.read(directory, 'native-config.json')
    config.update(file=p['file'], working='working.h5', edits=native, repack=p['repack'],
                  dependencies={d['id']: {'name': d['name']} for d in p['dependencies']})
    config['manifests']['readback'] = {'file': p['file']['name'], 'fileSettings': p['file'],
                                       'regions': {path: [r['selection'] for r in rec['regions']] for path, rec in expected['objects'].items() if rec.get('regions')}}
    atomic_json(directory / 'native-config.json', config)
    adaptor.stage(paths, directory, 'edit', deadline)
    atomic_json(directory / 'expected-state.json', expected)
    out_rb = adaptor.stage(paths, directory, 'readback', deadline)
    state.compare_readback(expected, out_rb)
    total = sum(len(o.get('values') or []) for o in expected['objects'].values() if o['kind'] == 'dataset')
    out_xml = adaptor.dump(paths, directory, 'h5dump-output', p['file']['name'], deadline, values=total <= adaptor.XML_ELEMENT_BUDGET)
    state.compare_xml(expected, out_xml)
    written_regions(paths, directory, p['file']['name'], expected, deadline)
    if p['repack']:
        adaptor.check_file_settings(p['file'], out_rb['file'])
    report = edit_report(p, directory, native, expected)
    check_copied_chunks(paths, directory, p, native, deadline)
    if p['extracts']:
        report['extracts'] = adaptor.run_extracts(p, directory, paths, deadline, expected, p['file']['name'])
    return report


def check_copied_chunks(paths, directory, p, native, deadline):
    """Fresh HDF5 chunk listings: each copyChunks target stores exactly the captured source's chunk bytes and masks."""
    from . import adaptor
    for e in native:
        if e['action'] != 'copyChunks':
            continue
        at = '$.edits[%d]' % e['index']
        source = adaptor.chunk_listing(paths, directory, 'source.h5', e['path'], 'chunk-list-source-%d' % e['index'], deadline)
        target = adaptor.chunk_listing(paths, directory, p['file']['name'], e['to'], 'chunk-list-target-%d' % e['index'], deadline)
        strip = [{k: v for k, v in c.items() if k != 'byteOffset'} for c in source['chunks']]
        if [{k: v for k, v in c.items() if k != 'byteOffset'} for c in target['chunks']] != strip or source['filters'] != target['filters']:
            fail('VERIFICATION_FAILED', 'the copied dataset does not store exactly the source chunks', at + '.to')


def fresh_check(directory, scratch, p, paths, deadline):
    from . import adaptor
    shutil.copyfile(directory / p['file']['name'], scratch / p['file']['name'])
    _, _, base = adaptor.fresh_source(paths, directory, scratch, 'source.h5', 'source', deadline)
    deps = {}
    for d in p['dependencies']:
        if d['role'] == 'copySource':
            deps[d['id']] = adaptor.fresh_source(paths, directory, scratch, d['name'], d['id'], deadline)[2]
    native, expected, _ = resolve(p, base, deps, adaptor.captured_bytes(directory, p))
    if json.loads(json.dumps(expected)) != adaptor.read(directory, 'expected-state.json'):
        fail('VERIFICATION_FAILED', 'the retained expected state differs from a fresh simulation')
    total = sum(len(o.get('values') or []) for o in expected['objects'].values() if o['kind'] == 'dataset')
    xml = adaptor.dump(paths, scratch, 'h5dump-fresh', p['file']['name'], deadline, values=total <= adaptor.XML_ELEMENT_BUDGET)
    state.compare_xml(expected, xml)
    written_regions(paths, scratch, p['file']['name'], expected, deadline)
    regions = {path: [r['selection'] for r in rec['regions']] for path, rec in expected['objects'].items() if rec.get('regions')}
    state.compare_readback(expected, adaptor.fresh_manifest(paths, scratch, 'readback', p['file']['name'], deadline, p['file'], regions))
    report = edit_report(p, directory, native, expected)
    if not (scratch / 'source.h5').exists():
        shutil.copyfile(directory / 'source.h5', scratch / 'source.h5')
    check_copied_chunks(paths, scratch, p, native, deadline)
    if p['extracts']:
        selections = adaptor.recheck_extracts(paths, directory, scratch, p['file']['name'], p['extracts'], expected, deadline)
        report['extracts'] = adaptor.extracts_report(directory, p['extracts'], expected, p, selections)
    adaptor.same_report(directory, report)
    return ['h5dump-source', 'h5dump-output', 'readback-output', *[e['id'] for e in p['extracts']]]


def edit_report(p, directory, native, expected):
    return {'operation': 'editFile', 'file': p['file']['name'], 'edits': [e['action'] for e in native], 'repack': p['repack'],
            'objects': len(expected['objects']), 'links': len(expected['links']),
            'sourceBytes': (directory / 'source.h5').stat().st_size, 'outputBytes': (directory / p['file']['name']).stat().st_size,
            'warnings': scale_warnings(expected)}


def scale_warnings(expected):
    out = []
    for path, rec in sorted(expected['objects'].items()):
        if rec['kind'] != 'dataset':
            continue
        for axis, d in enumerate(rec.get('dims') or []):
            for scale in d['scales']:
                target = expected['objects'].get(scale)
                if target is not None and target.get('shape') != [rec['shape'][axis]]:
                    out.append('axis %d of %s has %d elements but its dimension scale %s has %s' % (axis, path, rec['shape'][axis], scale, target.get('shape')))
    return out


def written_regions(paths, directory, target, expected, deadline):
    """Blocks appended to large datasets are read back independently by h5dump hyperslab reads."""
    from . import adaptor
    for path, rec in sorted(expected['objects'].items()):
        for region in rec.get('regions') or []:
            if 'values' not in region:
                continue
            got = adaptor.selected_values(paths, directory, target, path, {'type': rec['type'], 'shape': rec['shape'], 'values': None},
                                          region['selection'], deadline, path)
            if got != region['values']:
                fail('VERIFICATION_FAILED', 'h5dump: appended values differ from the authored block', path)
