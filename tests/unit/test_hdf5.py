"""Host tests for the HDF5 adaptor: contracts, semantics and independent expectations (no h5py needed)."""
import copy
import json
import struct
import unittest
from pathlib import Path

from schemaxis.adaptors.hdf5 import adaptor, expect, h5xml, model, operations, state
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'examples' / 'schemaxis'
FIXTURES = EXAMPLES / 'hdf5-fixtures'


def example(name):
    return json.loads((EXAMPLES / ('hdf5-%s.json' % name)).read_text())


def bound(name):
    text = (EXAMPLES / ('hdf5-%s.json' % name)).read_text().replace('/replace/with/hdf5-fixtures', str(FIXTURES))
    return json.loads(text)


def fault(test, document, code, location=None):
    with test.assertRaises(SchemaxisError) as caught:
        adaptor.plan(document)
    test.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
    if location is not None:
        test.assertEqual(caught.exception.fault.location, location)
    return caught.exception.fault


def create(*objects, **extra):
    return {'version': 'schemaxis.hdf5/1', 'operation': 'createFile', 'objects': list(objects), **extra}


class Planning(unittest.TestCase):
    def test_every_example_plans_deterministically_without_mutation(self):
        for name in ('sensor-run', 'campaign', 'inspect', 'extract', 'edit', 'compare', 'mesh-fields', 'swmr-monitor', 'parallel-write',
                     'raw-export', 'import-group', 'streamed-grid', 'parallel-extract', 'human-names', 'filter-rows', 'chunk-index', 'copy-chunks', 'sieve-columns', 'large-attributes', 'edit-fields'):
            document = example(name)
            before = copy.deepcopy(document)
            self.assertEqual(adaptor.plan(document), adaptor.plan(document), name)
            self.assertEqual(document, before, name)
            json.dumps(adaptor.plan(document), allow_nan=False)

    def test_examples_satisfy_the_published_schema(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('jsonschema is a developer dependency')
        validator = Draft202012Validator(adaptor.schema())
        for name in ('sensor-run', 'campaign', 'inspect', 'extract', 'edit', 'compare', 'mesh-fields', 'swmr-monitor',
                     'invalid-scale-length', 'invalid-int-range', 'human-names', 'filter-rows', 'chunk-index', 'copy-chunks', 'sieve-columns', 'large-attributes', 'edit-fields'):
            self.assertEqual(list(validator.iter_errors(example(name))), [], name)

    def test_invalid_examples_fail_at_the_offending_value(self):
        fault(self, example('invalid-scale-length'), 'INVALID_HDF5_DIMENSION', '$.objects[1].dimensions[0].scales[0]')
        fault(self, example('invalid-int-range'), 'INVALID_HDF5_VALUE', '$.objects[0].data.values[2]')

    def test_unknown_fields_and_operations_are_refused(self):
        fault(self, {'version': 'schemaxis.hdf5/1', 'operation': 'shred'}, 'UNKNOWN_OPERATION')
        fault(self, create({'path': '/a', 'kind': 'group'}, edits=[]), 'UNKNOWN_ARGUMENT', '$.edits')

    def test_paths_are_absolute_and_portable(self):
        for path in ('a/b', '/a//b', '/a/', '/../x', '/a/./b', '/tab\there', '/nul\x00', '/' + 'é' * 128,
                     '/' + '/'.join('g' * 17)):
            fault(self, create({'path': path, 'kind': 'group'}), 'INVALID_HDF5_PATH')

    def test_internal_names_are_unicode_text(self):
        for path in ('/Experiment 1/Temperature (°C)', '/μm', '/.calibration', '/Run #2, "warm" & <dry>', '/ lead', '/Kanal[2] = Druck', '/' + 'é' * 127):
            self.assertEqual(adaptor.plan(create({'path': path, 'kind': 'group'}))['objects'][0]['path'], path)
        doc = {'version': 'schemaxis.hdf5/1', 'operation': 'extractData', 'source': str(FIXTURES / 'run-a.h5'),
               'extracts': [{'id': 'x', 'dataset': '/Experiment 1/Temperature (°C)'}]}
        self.assertEqual(adaptor.plan(doc)['extracts'][0]['dataset'], '/Experiment 1/Temperature (°C)')
        self.assertEqual(adaptor.h5ls_name('/Experiment\\ 1/Temperature\\ (\\302\\260C)'), '/Experiment 1/Temperature (°C)')
        self.assertEqual(adaptor.h5ls_name('/q\\"uote/back\\\\slash'), '/q"uote/back\\slash')
        ddl = 'HDF5 "f.h5" {\nDATASET "/x DATA { y" {\n   DATA {\n   1, 2\n   }\n}\n}\n'
        self.assertEqual(h5xml.ddl_values(ddl, {'class': 'int', 'bits': 32, 'signed': True, 'order': 'little'}, '/x'), [1, 2])

    def test_parent_must_be_a_group(self):
        f = fault(self, create({'path': '/d', 'type': {'class': 'int'}, 'shape': [1], 'data': {'source': 'values', 'values': [1]}},
                               {'path': '/d/x', 'kind': 'group'}), 'INVALID_HDF5_PATH')
        self.assertEqual(f.observed['parent'], '/d')

    def test_type_fields_must_apply_to_the_class(self):
        fault(self, create({'path': '/d', 'type': {'class': 'float', 'members': [{'name': 'A', 'value': 0}]}, 'shape': [1]}),
              'INVALID_HDF5_TYPE', '$.objects[0].type.members')
        fault(self, create({'path': '/d', 'type': {'class': 'float', 'bits': 8}, 'shape': [1]}), 'INVALID_HDF5_TYPE', '$.objects[0].type.bits')

    def test_value_checks(self):
        fault(self, create({'path': '/s', 'type': {'class': 'string', 'length': 2}, 'shape': [1], 'data': {'source': 'values', 'values': ['ééé']}}),
              'INVALID_HDF5_VALUE')
        fault(self, create({'path': '/s', 'type': {'class': 'string', 'encoding': 'ascii'}, 'shape': [1], 'data': {'source': 'values', 'values': ['é']}}),
              'INVALID_HDF5_VALUE')
        fault(self, create({'path': '/f', 'type': {'class': 'float', 'bits': 16}, 'shape': [1], 'data': {'source': 'values', 'values': [1e6]}}),
              'INVALID_HDF5_VALUE')
        fault(self, create({'path': '/v', 'type': {'class': 'int'}, 'shape': [2, 2], 'data': {'source': 'values', 'values': [1, 2, 3]}}),
              'INVALID_HDF5_DATA', '$.objects[0].data.values')

    def test_storage_semantics(self):
        base = {'path': '/d', 'type': {'class': 'float'}, 'shape': [4]}
        fault(self, create({**base, 'storage': {'layout': 'contiguous', 'compression': 'gzip'}}), 'INVALID_HDF5_STORAGE')
        fault(self, create({**base, 'maxshape': ['unlimited'], 'storage': {'layout': 'contiguous'}}), 'INVALID_HDF5_STORAGE')
        fault(self, create({**base, 'storage': {'chunks': [8]}}), 'INVALID_HDF5_STORAGE', '$.objects[0].storage.chunks[0]')
        fault(self, create({**base, 'storage': {'compression': 'lzf', 'level': 3}}), 'INVALID_HDF5_STORAGE', '$.objects[0].storage.level')
        p = adaptor.plan(create({**base, 'maxshape': ['unlimited'], 'storage': {'compression': 'gzip'}}))
        self.assertEqual(p['objects'][0]['storage']['layout'], 'chunked')
        self.assertEqual(p['objects'][0]['storage']['level'], 4)

    def test_virtual_counts_and_dependency_roles(self):
        doc = create({'path': '/src', 'type': {'class': 'float'}, 'shape': [4], 'data': {'source': 'range', 'start': 0, 'step': 1}},
                     {'path': '/v', 'type': {'class': 'float'}, 'shape': [3], 'virtual': {'sources': [{'dataset': '/src'}]}})
        fault(self, doc, 'INVALID_HDF5_VIRTUAL')
        doc = create({'path': '/v', 'type': {'class': 'float'}, 'shape': [3], 'virtual': {'sources': [{'file': 'raw', 'dataset': '/x'}]}},
                     dependencies=[{'id': 'raw', 'path': '/tmp/x.bin', 'role': 'rawStorage'}])
        fault(self, doc, 'INVALID_HDF5_VIRTUAL', '$.objects[0].virtual.sources[0].file')

    def test_references_need_declared_targets(self):
        fault(self, create({'path': '/r', 'type': {'class': 'reference'}, 'shape': [1], 'data': {'source': 'references', 'targets': [{'path': '/nope'}]}}),
              'INVALID_HDF5_REFERENCE')

    def test_edit_records(self):
        doc = example('edit')
        doc['edits'] = [{'action': 'move', 'path': '/a', 'to': '/a/b'}]
        fault(self, doc, 'INVALID_HDF5_EDIT', '$.edits[0].to')
        doc['edits'] = [{'action': 'copy', 'path': '/a', 'to': '/b', 'expandReferences': True}]
        fault(self, doc, 'INVALID_HDF5_EDIT')
        doc['edits'] = [{'action': 'deleteAttribute', 'path': '/a', 'name': 'DIMENSION_LIST'}]
        fault(self, doc, 'INVALID_HDF5_EDIT', '$.edits[0].name')
        doc['edits'] = [{'action': 'renameAttribute', 'path': '/', 'name': 'a', 'newName': 'a'}]
        fault(self, doc, 'INVALID_HDF5_EDIT', '$.edits[0].newName')

    def test_mesh_and_series_semantics(self):
        doc = example('mesh-fields')
        doc['times'] = [0, 0, 1]
        fault(self, doc, 'INVALID_HDF5_MESH', '$.times')
        doc = example('swmr-monitor')
        doc['batches'][0]['values'] = [1.0, 2.0]
        fault(self, doc, 'INVALID_HDF5_DATA', '$.batches[0].values')
        doc = example('swmr-monitor')
        doc['swmr'] = False
        fault(self, doc, 'INVALID_HDF5_SWMR', '$.readers')


    def test_parallel_write_semantics(self):
        doc = example('parallel-write')
        p = adaptor.plan(doc)
        self.assertEqual(p['partitions']['/field/cell_id'], [[0, 3], [3, 7]])
        bad = copy.deepcopy(doc)
        bad['objects'][2]['type'] = {'class': 'string'}
        bad['objects'][2]['data'] = {'source': 'values', 'values': ['a'] * 7}
        fault(self, bad, 'INVALID_HDF5_PARALLEL', '$.objects[2]')
        bad = copy.deepcopy(doc)
        bad['io'] = 'independent'
        fault(self, bad, 'INVALID_HDF5_PARALLEL', '$.io')
        bad = copy.deepcopy(doc)
        bad['ranks'] = 4
        bad['objects'][1]['shape'] = [3, 3]
        bad['objects'][1]['storage'] = {}
        fault(self, bad, 'INVALID_HDF5_PARALLEL', '$.objects[1]')
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.resources(doc, {'ranks': 2}, 'op')
        self.assertEqual(caught.exception.fault.code, 'INVALID_EXECUTION')
        self.assertEqual(adaptor.resources(doc, {}, 'op'), {'threads': 2})


    def test_access_rules(self):
        doc = example('inspect')
        doc['access'] = {'alignment': {'interval': 4096}}
        fault(self, doc, 'INVALID_HDF5_ACCESS', '$.access.alignment')
        doc = example('inspect')
        doc['access'] = {'memoryBytes': 65536}
        fault(self, doc, 'INVALID_HDF5_ACCESS', '$.access.memoryBytes')
        doc = example('sensor-run')
        doc['access'] = {'alignment': {'interval': 4096}}
        fault(self, doc, 'INVALID_HDF5_ACCESS', '$.access.alignment.interval')
        doc = example('parallel-extract')
        doc['access'] = {'memoryBytes': 65536}
        fault(self, doc, 'INVALID_HDF5_ACCESS', '$.access.memoryBytes')
        self.assertEqual(adaptor.plan(example('sieve-columns'))['access'], {'sieveBufferBytes': 1048576})
        doc = example('inspect')
        doc['access'] = {'sieveBufferBytes': 100}
        fault(self, doc, 'INVALID_ARGUMENT', '$.access.sieveBufferBytes')
        p = adaptor.plan(example('streamed-grid'))
        self.assertEqual(p['access']['chunkCache'], {'bytes': 4194304, 'slots': 1009, 'preemption': 0.25})

    def test_where_conditions(self):
        from schemaxis.adaptors.hdf5 import predicates
        doc = bound('filter-rows')
        p = adaptor.plan(doc)
        self.assertEqual(p['extracts'][1]['where'], [{'dataset': '/run/calibrated/pressure', 'op': 'gt', 'value': 101.305}])
        for where, location in (([{'op': 'between', 'value': 2}], '$.extracts[0].where[0].upper'),
                                ([{'op': 'lt', 'value': 'high'}], '$.extracts[0].where[0].value'),
                                ([{'op': 'nan', 'values': [1]}], '$.extracts[0].where[0].values')):
            bad = bound('filter-rows')
            bad['extracts'] = [{'id': 'x', 'dataset': '/a', 'where': where}]
            fault(self, bad, 'INVALID_HDF5_EXTRACT', location)
        bad = bound('filter-rows')
        bad['extracts'][0]['selection'] = {'kind': 'points', 'points': [[0, 0]]}
        fault(self, bad, 'INVALID_HDF5_EXTRACT', '$.extracts[0].selection')
        bad = bound('filter-rows')
        bad['parallel'] = {'ranks': 2}
        fault(self, bad, 'INVALID_HDF5_PARALLEL', '$.parallel')
        f32 = {'kind': 'dataset', 'shape': [6], 'type': {'class': 'float', 'bits': 32, 'order': 'little'}}
        stored = [float.fromhex(v) for v in (float(101.31).hex(), 'nan')]
        self.assertEqual(predicates.rows([{'op': 'gt', 'value': 1.0}], [[0.5, 2.0, float('nan')]], 3), [1])
        self.assertEqual(predicates.rows([{'op': 'ne', 'value': 1.0}], [[1.0, float('nan')]], 2), [1])
        self.assertEqual(predicates.rows([{'op': 'finite'}, {'op': 'in', 'values': [2, 3]}], [[1.0, float('inf'), 2.0], [2, 3, 4]], 3), [0])
        self.assertTrue(stored[0] > 101.305)
        with self.assertRaises(SchemaxisError) as caught:
            predicates.condition_type({'op': 'gt', 'value': 1}, {**f32, 'shape': [5]}, 6, '$.extracts.x.where[0]')
        self.assertEqual(caught.exception.fault.location, '$.extracts.x.where[0].dataset')
        u8 = {'kind': 'dataset', 'shape': [6], 'type': {'class': 'uint', 'bits': 8, 'order': 'little'}}
        for value in (256, 1.5, True):
            with self.assertRaises(SchemaxisError):
                predicates.condition_type({'op': 'eq', 'value': value}, u8, 6, '$')
        self.assertEqual(state.indices({'kind': 'rows', 'rows': [1, 3]}, [4, 2]), [2, 3, 6, 7])
        self.assertEqual(operations.split_blocks({'kind': 'rows', 'rows': [1, 3, 4]}, [6, 2], rows_per_block=2),
                         [{'kind': 'rows', 'rows': [1, 3]}, {'kind': 'rows', 'rows': [4]}])
        self.assertEqual(operations.split_blocks({'kind': 'rows', 'rows': []}, [6, 2], rows_per_block=2), [{'kind': 'rows', 'rows': []}])
        self.assertEqual(adaptor.row_runs([0, 1, 2, 5, 7, 8]), [[0, 3], [5, 1], [7, 2]])

    def test_chunk_decoding_is_independent_of_h5py(self):
        from schemaxis.adaptors.hdf5 import chunks
        data = (FIXTURES / 'sensor-run.h5').read_bytes()
        t = {'class': 'int', 'bits': 16, 'order': 'big'}
        pipeline = ['shuffle', 'gzip', 'fletcher32']
        first = chunks.elements(chunks.decode(data[6706:6729], pipeline, 0, 2, 12, '$'), t)
        second = chunks.elements(chunks.decode(data[6729:6750], pipeline, 0, 2, 12, '$'), t)
        self.assertEqual(first + second, list(range(-5, 31, 3)))
        corrupt = bytearray(data[6729:6750])
        corrupt[2] ^= 0x40
        for raw, order in ((bytes(corrupt), pipeline), (data[6729:6750], ['gzip', 'shuffle', 'fletcher32'])):
            with self.assertRaises(SchemaxisError) as caught:
                self.assertEqual(chunks.elements(chunks.decode(raw, order, 0, 2, 12, '$'), t), list(range(13, 31, 3)))
            self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        obj = {'kind': 'dataset', 'layout': 'chunked', 'type': {'class': 'float', 'bits': 32, 'order': 'little'}, 'filters': ['lzf']}
        with self.assertRaises(SchemaxisError) as caught:
            chunks.check_indexable(obj, '$.extracts.p')
        self.assertEqual(caught.exception.fault.location, '$.extracts.p.format')
        listing = {'chunkShape': [4], 'filters': ['gzip'], 'chunks': [{'offset': [0], 'byteOffset': 10, 'size': 5, 'filterMask': 0, 'sha256': 'a'},
                                                                     {'offset': [4], 'byteOffset': 15, 'size': 5, 'filterMask': 0, 'sha256': 'a'}]}
        chunks.check_listing(copy.deepcopy(listing), listing, 'x')
        swapped = copy.deepcopy(listing)
        swapped['chunks'][1]['byteOffset'] = 10
        with self.assertRaises(SchemaxisError) as caught:
            chunks.check_listing(swapped, listing, 'x')
        self.assertEqual(caught.exception.fault.location, 'x.chunks[1]')
        bad = bound('chunk-index')
        bad['extracts'][0]['where'] = [{'op': 'gt', 'value': 1}]
        fault(self, bad, 'INVALID_HDF5_EXTRACT', '$.extracts[0].where')

    def test_copy_chunks_simulation(self):
        t = {'class': 'float', 'bits': 32, 'order': 'little'}
        rec = {'kind': 'dataset', 'type': t, 'shape': [4], 'maxshape': [4], 'layout': 'chunked', 'chunks': [2], 'filters': ['gzip', 'shuffle'],
               'attributes': {}, 'dims': [{'label': '', 'scales': []}], 'scale': None}
        base = {'objects': {'/': {'kind': 'group', 'attributes': {}}, '/a': {**rec, 'values': ['0x1.0p+0'] * 4},
                            '/b': {**rec, 'values': ['0x0.0p+0'] * 4}, '/c': {**rec, 'filters': ['gzip'], 'values': ['0x0.0p+0'] * 4}}, 'links': {}}
        out = state.simulate(base, [{'action': 'copyChunks', 'path': '/a', 'to': '/b', 'index': 0}], {}, {})
        self.assertEqual(out['objects']['/b']['values'], ['0x1.0p+0'] * 4)
        with self.assertRaises(SchemaxisError) as caught:
            state.simulate(base, [{'action': 'copyChunks', 'path': '/a', 'to': '/c', 'index': 0}], {}, {})
        self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('INVALID_HDF5_EDIT', '$.edits[0].to'))
        fault(self, bound('copy-chunks') | {'edits': [{'action': 'copyChunks', 'path': '/a'}]}, 'INVALID_HDF5_EDIT', '$.edits[0].to')

    def test_large_attributes_and_creation_order(self):
        doc = example('large-attributes')
        p = adaptor.plan(doc)
        self.assertEqual(len(p['objects'][1]['attributes'][1]['values']), 9000)
        self.assertEqual(state.expected_create(p, adaptor.host_values(p, {}))['objects']['/detector/counts']['attributeOrder'], ['zeta', 'lookup table', 'alpha', 'units'])
        doc['objects'][1]['trackOrder'] = False
        fault(self, doc, 'INVALID_HDF5_ATTRIBUTE', '$.objects[1].attributes[1]')
        doc['file']['libver'] = 'v110'
        adaptor.plan(doc)
        rec = {'kind': 'dataset', 'attributes': {'a': {}, 'b': {}}, 'attributeOrder': ['a', 'b']}
        state.reorder(rec, 'a', 'a')
        self.assertEqual(rec['attributeOrder'], ['b', 'a'])
        with self.assertRaises(SchemaxisError):
            state.check_attribute_order('/x', rec, ['a', 'b'], 'h5dump')

    def test_null_datasets_and_field_writes(self):
        p = adaptor.plan(create({'path': '/n', 'type': {'class': 'float', 'bits': 64}, 'empty': True, 'units': 'K'}))
        self.assertEqual((p['objects'][0]['shape'], p['objects'][0]['empty']), (None, True))
        rec = state.expected_create(p, {})['objects']['/n']
        self.assertEqual((rec['shape'], rec['null'], rec['values']), (None, True, []))
        fault(self, create({'path': '/n', 'type': {'class': 'float', 'bits': 64}, 'empty': True, 'shape': []}), 'INVALID_HDF5_OBJECT', '$.objects[0].shape')
        fault(self, create({'path': '/n', 'type': {'class': 'float', 'bits': 64}, 'empty': True},
                           extracts=[{'id': 'n', 'dataset': '/n'}]), 'INVALID_HDF5_EXTRACT', '$.extracts[0].dataset')
        t = {'class': 'compound', 'fields': [{'name': 'id', 'type': {'class': 'uint', 'bits': 64, 'order': 'little'}},
                                             {'name': 't', 'type': {'class': 'float', 'bits': 32, 'order': 'little'}}]}
        base = {'objects': {'/': {'kind': 'group', 'attributes': {}}, '/r': {'kind': 'dataset', 'type': t, 'shape': [2], 'attributes': {},
                                                                            'values': [[2 ** 63, '0x0.0p+0'], [2 ** 64 - 1, '0x0.0p+0']]}}, 'links': {}}
        e = {'action': 'write', 'path': '/r', 'fields': ['t'], 'type': t, 'fieldType': t['fields'][1]['type'], 'selection': {'kind': 'points', 'points': [[1]]}}
        out = state.simulate(base, [e], {(0, 'write'): [1.5]}, {})
        self.assertEqual(out['objects']['/r']['values'], [[2 ** 63, '0x0.0p+0'], [2 ** 64 - 1, '0x1.8000000000000p+0']])
        fault(self, bound('edit-fields') | {'edits': [{'action': 'write', 'path': '/r', 'fields': ['t', 't'], 'data': {'source': 'values', 'values': [1]}}]},
              'INVALID_HDF5_EDIT', '$.edits[0].fields')

    def test_memory_blocks_use_fixed_selected_sizes(self):
        f64 = {'class': 'float', 'bits': 64, 'order': 'little'}
        record = {'class': 'compound', 'fields': [{'name': 'f%d' % k, 'type': f64} for k in range(64)] +
                  [{'name': 'note', 'type': {'class': 'string', 'encoding': 'utf-8'}}]}
        obj = {'type': record, 'shape': [8000]}
        p = {'access': {'memoryBytes': 32768}}
        item = {'selection': {'kind': 'all'}, 'selectedShape': [8000], 'fields': ['f0', 'f63']}
        adaptor.plan_blocks(p, item, obj, '$.extracts.pair')
        self.assertEqual([b['slices'][0][1] - b['slices'][0][0] if b['kind'] == 'slices' else None for b in item['blocks']][:1], [2048])
        self.assertEqual(len(item['blocks']), 4)
        for fields in (['note'], None):
            item = {'selection': {'kind': 'all'}, 'selectedShape': [8000], **({'fields': fields} if fields else {})}
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.plan_blocks(p, item, obj, '$.extracts.x')
            self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('INVALID_HDF5_ACCESS', '$.extracts.x'))
        self.assertFalse(model.variable_size({'class': 'string', 'length': 8}))
        self.assertTrue(model.variable_size({'class': 'vlen', 'base': f64}))
        self.assertTrue(model.variable_size({'class': 'reference', 'reference': 'object'}))

    def test_blocks_reproduce_selection_order(self):
        shape = [12, 3]
        for record in ({'kind': 'all'}, {'kind': 'slices', 'slices': [{'start': 1, 'stop': 11, 'step': 3}]},
                       {'kind': 'hyperslab', 'start': [1, 0], 'count': [5, 2], 'stride': [2, 1], 'block': [1, 1]},
                       {'kind': 'points', 'points': [[5, 1], [0, 0], [11, 2]]}):
            sel = model.selection(record, shape, '$')[0]
            full = state.indices(sel, shape)
            for kwargs in ({'rows_per_block': 1}, {'rows_per_block': 4}, {'parts': 2}, {'parts': 3}):
                blocks = operations.split_blocks(sel, shape, **kwargs)
                self.assertEqual([i for b in blocks for i in state.indices(b, shape)], full, (record, kwargs))
        with self.assertRaises(SchemaxisError):
            operations.split_blocks(model.selection({'kind': 'points', 'points': [[1, 1]]}, shape, '$')[0], shape, parts=2)


class Expectations(unittest.TestCase):
    def test_documented_generators(self):
        t = {'class': 'float', 'bits': 64, 'order': 'little'}
        self.assertEqual(list(expect.generated({'source': 'linspace', 'start': 0, 'stop': 2.5}, t, 6)), [0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
        self.assertEqual(list(expect.generated({'source': 'range', 'start': -5, 'step': 3}, {'class': 'int', 'bits': 16, 'order': 'big'}, 4)), [-5, -2, 1, 4])
        self.assertEqual(expect.round_float(0.1, 32), struct.unpack('<f', struct.pack('<f', 0.1))[0])
        self.assertEqual(expect.round_float(1e6, 16), float('inf'))

    def test_selection_indices_follow_c_order(self):
        shape = [4, 2, 3]
        sel = model.selection({'kind': 'hyperslab', 'start': [1, 0, 1], 'count': [2, 2, 2], 'stride': [2, 1, 1], 'block': [1, 1, 1]}, shape, '$')[0]
        frames = [10 * i for i in range(24)]
        self.assertEqual([frames[i] for i in state.indices(sel, shape)], [70, 80, 100, 110, 190, 200, 220, 230])
        sel = model.selection({'kind': 'slices', 'slices': [{'start': -2}]}, [6, 2], '$')[0]
        self.assertEqual(state.indices(sel, [6, 2]), [8, 9, 10, 11])
        sel = model.selection({'kind': 'points', 'points': [[5, 1], [0, 0]]}, [6, 2], '$')[0]
        self.assertEqual(state.indices(sel, [6, 2]), [11, 0])

    def test_csv_npy_raw_readers(self):
        header, rows = expect.parse_csv((FIXTURES / 'temperatures.csv').read_bytes(), ',', '$')
        self.assertEqual(header, ['time', 'temperature', 'valid'])
        self.assertEqual(len(rows), 4)
        t, shape, values = expect.parse_npy((FIXTURES / 'matrix.npy').read_bytes(), '$')
        self.assertEqual((t['class'], t['bits'], shape, values), ('float', 32, [2, 3], [1.5, -2.0, 3.25, 4.0, 5.5, -6.75]))
        raw = (FIXTURES / 'probe-counts.bin').read_bytes()
        item = {'type': {'class': 'int', 'bits': 16, 'order': 'big'}, 'shape': [8], 'offset': 4}
        self.assertEqual(expect.parse_raw(raw, item, '$'), [10, -20, 30, -40, 500, -600, 7000, -8000])

    def test_expected_create_values_and_layout(self):
        p = adaptor.plan(example('sensor-run'))
        values = adaptor.host_values(p, {})
        expected = state.expected_create(p, values)
        counts = expected['objects']['/run/raw/counts']
        self.assertEqual(counts['values'][:4], [-5, -2, 1, 4])
        self.assertEqual(counts['filters'], ['fletcher32', 'gzip', 'shuffle'])
        self.assertEqual(counts['dims'][0], {'label': 'time', 'scales': ['/run/raw/time']})
        self.assertEqual(expected['links']['/run/time_alias'], {'kind': 'hard', 'target': '/run/raw/time'})
        pressure = expected['objects']['/run/calibrated/pressure']['values']
        self.assertEqual(pressure[4], 'nan')
        self.assertEqual(float.fromhex(pressure[0]), struct.unpack('<f', struct.pack('<f', 101.325))[0])

    def test_campaign_virtual_values_from_dependency_states(self):
        p = adaptor.plan(bound('campaign'))
        deps = {}
        for dep, start in (('runA', 0.5), ('runB', 4.5)):
            deps[dep] = {'objects': {'/signal': {'kind': 'dataset', 'type': {'class': 'float', 'bits': 64, 'order': 'little'}, 'shape': [4],
                                                 'values': [(start + i).hex() for i in range(4)]}}, 'links': {}}
        captured = {i['id']: Path(i['path']).read_bytes() for i in p['inputs']}
        captured.update({'dep:' + d['id']: Path(d['path']).read_bytes() for d in p['dependencies']})
        expected = state.expected_create(p, adaptor.host_values(p, captured), deps)
        got = [float.fromhex(v) for v in expected['objects']['/campaign/signal']['values']]
        self.assertEqual(got, [0.5, 1.5, 2.5, 3.5, -999.0, 5.5, 6.5, 7.5, -999.0, -999.0])
        self.assertEqual(expected['objects']['/campaign/probe_counts']['values'], [10, -20, 30, -40, 500, -600, 7000, -8000])

    def test_edit_simulation(self):
        base = {'objects': {'/': {'kind': 'group', 'attributes': {}},
                            '/t': {'kind': 'dataset', 'type': {'class': 'float', 'bits': 64, 'order': 'little'}, 'shape': [3], 'maxshape': [3],
                                   'layout': 'contiguous', 'chunks': None, 'filters': [], 'scale': 'time', 'dims': [{'label': '', 'scales': []}],
                                   'attributes': {}, 'values': [x.hex() for x in (0.0, 1.0, 2.0)]},
                            '/d': {'kind': 'dataset', 'type': {'class': 'int', 'bits': 32, 'order': 'little'}, 'shape': [3], 'maxshape': ['unlimited'],
                                   'layout': 'chunked', 'chunks': [2], 'filters': [], 'scale': None, 'dims': [{'label': 't', 'scales': ['/t']}],
                                   'attributes': {}, 'values': [1, 2, 3], 'defaultFill': 0}}, 'links': {}}
        doc = {'version': 'schemaxis.hdf5/1', 'operation': 'editFile', 'source': '/tmp/x.h5', 'edits': [
            {'action': 'append', 'path': '/d', 'axis': 0, 'shape': [2], 'data': {'source': 'values', 'values': [4, 5]}},
            {'action': 'resize', 'path': '/d', 'shape': [6]},
            {'action': 'write', 'path': '/d', 'selection': {'kind': 'points', 'points': [[0]]}, 'data': {'source': 'values', 'values': [9]}},
            {'action': 'copy', 'path': '/d', 'to': '/g/d2'},
            {'action': 'move', 'path': '/t', 'to': '/axes/t'}]}
        from schemaxis.adaptors.hdf5 import editing
        _, final, _ = editing.resolve(adaptor.plan(doc), base, {}, {})
        self.assertEqual(final['objects']['/d']['values'], [9, 2, 3, 4, 5, 0])
        self.assertEqual(final['objects']['/g/d2']['values'], [9, 2, 3, 4, 5, 0])
        self.assertEqual(final['objects']['/d']['dims'][0]['scales'], ['/axes/t'])
        self.assertEqual(final['objects']['/g/d2']['dims'][0]['scales'], ['/axes/t'])
        self.assertEqual(editing.scale_warnings(final)[0], 'axis 0 of /d has 6 elements but its dimension scale /axes/t has [3]')
        linked = copy.deepcopy(base)
        linked['links']['/far'] = {'kind': 'external', 'file': 'x.h5', 'target': '/secret'}
        for edit in ({'action': 'copy', 'path': '/far', 'to': '/near'}, {'action': 'copy', 'path': '/far/deep', 'to': '/near'}):
            probe = copy.deepcopy(doc)
            probe['edits'] = [edit]
            with self.assertRaises(SchemaxisError) as caught:
                editing.resolve(adaptor.plan(probe), linked, {}, {})
            self.assertEqual(caught.exception.fault.code, 'INVALID_HDF5_EDIT')
        bad = copy.deepcopy(doc)
        bad['edits'] = [{'action': 'append', 'path': '/t', 'axis': 0, 'shape': [1], 'data': {'source': 'values', 'values': [1.0]}}]
        with self.assertRaises(SchemaxisError) as caught:
            editing.resolve(adaptor.plan(bad), base, {}, {})
        self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('INVALID_HDF5_EDIT', '$.edits[0].path'))
        late = copy.deepcopy(doc)
        late['edits'] = [{'action': 'makeScale', 'path': '/d', 'name': 'd'}, {'action': 'delete', 'path': '/missing'}]
        with self.assertRaises(SchemaxisError) as caught:
            editing.resolve(adaptor.plan(late), base, {}, {})
        self.assertEqual(caught.exception.fault.location, '$.edits[1].path')

    def test_xml_reader_tokens_and_types(self):
        self.assertEqual(h5xml.tokens('1 "a \\"q\\"" "b\\000" x'), [('w', '1'), ('s', 'a "q"'), ('s', 'b\x00'), ('w', 'x')])
        self.assertTrue(h5xml.same_type({'class': 'string', 'encoding': '*'}, {'class': 'string', 'encoding': 'utf-8'}))
        self.assertFalse(h5xml.same_type({'class': 'string', 'encoding': 'ascii'}, {'class': 'string', 'encoding': 'utf-8'}))
        with self.assertRaises(SchemaxisError):
            h5xml.parse(b'<!DOCTYPE x [<!ENTITY a "b">]><x/>')

    def test_host_comparison_tolerances(self):
        f = lambda *v: {'objects': {'/s': {'kind': 'dataset', 'type': {'class': 'float', 'bits': 64, 'order': 'little'}, 'shape': [len(v)],
                                           'attributes': {}, 'layout': 'contiguous', 'chunks': None, 'filters': [], 'values': [x.hex() for x in v]}}, 'links': {}}
        tol = {'absolute': 0.5, 'relative': 0.0, 'attributes': True, 'storage': False}
        self.assertEqual(adaptor.host_compare(f(1.0, 2.0), f(1.4, 2.6), tol), [{'path': '/s', 'kind': 'values', 'count': 1}])
        self.assertEqual(adaptor.host_compare(f(float('nan')), f(float('nan')), tol), [])

    def test_expectation_decisions(self):
        readback = {'objects': {'/d': {'kind': 'dataset', 'type': {'class': 'float', 'bits': 32, 'order': 'little'}, 'shape': [3], 'filters': [],
                                       'attributes': {'units': {'type': {'class': 'string', 'encoding': 'utf-8'}, 'shape': [], 'values': ['K']}},
                                       'stats': {'finite': 2, 'nan': 1, 'minimum': (1.0).hex(), 'maximum': (5.0).hex()}, 'values': {'count': 3}}},
                    'links': {}}
        independent = {'/d': [(1.0).hex(), (5.0).hex(), float('nan').hex()]}
        decide = lambda e: adaptor.decide({'present': True, **e}, readback, None, independent)
        self.assertEqual(decide({'id': 'a', 'path': '/d', 'units': 'K', 'maximum': 5})['decision'], 'met')
        self.assertEqual(decide({'id': 'b', 'path': '/d', 'finite': True})['reasons'], ['finite elements 2 of 3'])
        self.assertEqual(adaptor.decide({'id': 'c', 'path': '/x', 'present': False}, readback, None)['decision'], 'met')
        self.assertEqual(adaptor.decide({'id': 'e', 'path': '/d', 'present': True, 'maximum': 9}, readback, None, {})['decision'], 'indeterminate')


class Discovery(unittest.TestCase):
    def test_search_cases_match_capability_search(self):
        from schemaxis.capabilities import CapabilityCatalogue
        catalogue = CapabilityCatalogue()
        cases = json.loads((ROOT / 'src/schemaxis/adaptors/hdf5/search-cases.json').read_text())
        for case in cases:
            found = {item['id'] for item in catalogue.search(case['query'], scope='app/hdf5', limit=50)['items']}
            for want in case['expected'].get('capabilities', []):
                self.assertIn(want, found, case['id'])
            for bad in case.get('excluded', {}).get('capabilities', []):
                self.assertNotIn(bad, found, case['id'])

    def test_runtime_is_required_before_any_native_work(self):
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.runtime('/nonexistent/python', '/nonexistent/h5dump')
        self.assertEqual(caught.exception.fault.code, 'INTERPRETER_NOT_FOUND')


if __name__ == '__main__':
    unittest.main()
