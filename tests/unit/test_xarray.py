"""Host semantics of the xarray named-coordinate profile reduction; never imports xarray, NumPy or SciPy."""
import ast
import copy
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from schemaxis import workflow
from schemaxis.adaptors import registry
from schemaxis.adaptors.gnuplot import adaptor as gnuplot
from schemaxis.adaptors.xarray import adaptor as a, cdf, oracle as o
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import xarray_fixtures as fx  # noqa: E402

EXAMPLES = ROOT / 'examples/schemaxis'
MISSING = {(1, 1, 0)} | {(t, 3, s) for t in range(3) for s in range(2)} | {(0, 2, 1), (2, 2, 0)}


def code(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault.code, error.fault.location
    except cdf.CdfError as error:
        return error.code, error.location
    return 'accepted', None


def document(**changes):
    doc = json.loads((EXAMPLES / 'xarray-profile.json').read_text())
    doc['source'] = str(EXAMPLES / 'xarray-cube.nc')
    doc.update(changes)
    return doc


def reduce(doc, data):
    p = a.plan(doc)
    cube, points = a.load_cube(p, data)
    return p, cube, points


def means(doc, data):
    return [r['mean'] for r in reduce(doc, data)[2]]


def with_missing(policy, **extra):
    doc = document(missing={'value': -999.0, 'policy': policy, **extra})
    return doc


def storage_order(order):
    """The same logical cube stored with permuted axes, declared in the new order."""
    doc = document()
    names = {c['name']: c for c in doc['coordinates']}
    doc['coordinates'] = [names[k] for k in order]
    return doc, fx.build(order=order)


class AnalyticTests(unittest.TestCase):
    def test_literal_profile_over_time_and_station(self):
        p, cube, points = reduce(document(), fx.build())
        self.assertEqual([r['mean'] for r in points], [280.625, 285.625, 290.625, 295.625])
        self.assertEqual([r['valid'] for r in points], [6] * 4)

    def test_wrong_retained_dimension_gives_different_literal_means(self):
        # mean over depth and station: 280 + 7.5 + 0.125 + 0.5 * time
        self.assertEqual(means(document(retain='time'), fx.build()), [287.625, 288.125, 288.625])
        self.assertEqual(means(document(retain='station'), fx.build()), [288.0, 288.25])

    def test_skip_policy_literal_values_and_counts(self):
        doc = with_missing('skip', minimumValid=1)
        doc['coordinates'][1]['range'] = {'minimum': 0, 'maximum': 20}
        _, _, points = reduce(doc, fx.build(missing=MISSING))
        self.assertEqual([r['valid'] for r in points], [6, 5, 4])
        self.assertEqual([r['missing'] for r in points], [0, 1, 2])
        self.assertEqual(points[0]['mean'], 280.625)
        self.assertEqual(points[1]['mean'], 285.65)      # 1428.25 / 5, exact rational rounded to nearest
        self.assertEqual(points[2]['mean'], 290.625)     # 290, 290.5, 290.75, 291.25 are the four valid cells

    def test_propagate_publishes_empty_not_zero(self):
        _, _, points = reduce(with_missing('propagate'), fx.build(missing={(1, 3, 0)}))
        self.assertEqual([r['mean'] for r in points], [280.625, 285.625, 290.625, None])
        self.assertEqual([r['missing'] for r in points], [0, 0, 0, 1])

    def test_permuted_storage_axes_are_refused_unless_declared_and_give_identical_named_results(self):
        data = fx.build(order=('depth', 'time', 'station'))
        self.assertEqual(code(lambda: reduce(document(), data)), ('XR_DIMENSION_ORDER', '$.coordinates'))
        doc, data = storage_order(('depth', 'time', 'station'))
        self.assertEqual(means(doc, data), [280.625, 285.625, 290.625, 295.625])
        doc, data = storage_order(('station', 'depth', 'time'))
        self.assertEqual(means(doc, data), [280.625, 285.625, 290.625, 295.625])

    def test_changed_range_changes_selection_hash_and_values(self):
        data = fx.build()
        doc = document()
        doc['coordinates'][0]['range'] = {'minimum': 1, 'maximum': 2}
        changed = means(doc, data)
        self.assertEqual(changed, [280.875, 285.875, 290.875, 295.875])
        self.assertNotEqual(o.canonical(o.selection_record(a.plan(doc))), o.canonical(o.selection_record(a.plan(document()))))
        doc['coordinates'][0]['range'] = {'minimum': 0, 'maximum': 0}
        self.assertEqual(means(doc, data), [280.125, 285.125, 290.125, 295.125])


class FaultTests(unittest.TestCase):
    def check(self, doc, data, expected, location=None):
        got = code(lambda: reduce(doc, data))
        self.assertEqual(got[0], expected)
        if location:
            self.assertEqual(got[1], location)

    def test_units_absent_different_and_calendar(self):
        self.check(document(), fx.build(units={'depth': None}), 'XR_UNITS_MISSING', '$.coordinates[1].unit')
        self.check(document(), fx.build(units={'depth': 'cm'}), 'XR_UNITS_MISMATCH', '$.coordinates[1].unit')
        self.check(document(), fx.build(variable_unit='degC'), 'XR_UNITS_MISMATCH', '$.variable.unit')
        self.check(document(), fx.build(units={'time': 'hours since 2000-01-01'}), 'XR_UNITS_CALENDAR')

    def test_coordinate_order_duplicates_and_nonfinite(self):
        for axis, expected in (([0.0, 10.0, 10.0, 30.0], 'XR_COORDINATE_ORDER'), ([30.0, 20.0, 10.0, 0.0], 'XR_COORDINATE_ORDER'),
                               ([0.0, 20.0, 10.0, 30.0], 'XR_COORDINATE_ORDER'), ([0.0, math.nan, 20.0, 30.0], 'XR_COORDINATE_RANGE'),
                               ([0.0, 10.0, 20.0, math.inf], 'XR_COORDINATE_RANGE')):
            with self.subTest(axis=axis):
                self.check(document(), fx.build(axes={'depth': axis}), expected)

    def test_selection_empty_out_of_bounds_and_short(self):
        for rng, expected in (({'minimum': 11, 'maximum': 19}, 'XR_SELECTION_EMPTY'), ({'minimum': -1, 'maximum': 20}, 'XR_RANGE_OUT_OF_BOUNDS'),
                              ({'minimum': 0, 'maximum': 31}, 'XR_RANGE_OUT_OF_BOUNDS'), ({'minimum': 10, 'maximum': 10}, 'XR_PROFILE_TOO_SHORT')):
            doc = document()
            doc['coordinates'][1]['range'] = rng
            with self.subTest(rng=rng):
                self.check(doc, fx.build(), expected)

    def test_missing_policies(self):
        data = fx.build(missing=MISSING)
        self.check(with_missing('refuse'), data, 'XR_MISSING_VALUES')
        self.check(with_missing('skip', minimumValid=1), data, 'XR_INSUFFICIENT_VALID')      # depth 30 is all missing
        doc = with_missing('skip', minimumValid=5)
        doc['coordinates'][1]['range'] = {'minimum': 0, 'maximum': 20}
        self.check(doc, data, 'XR_INSUFFICIENT_VALID')
        every = fx.build(missing={(t, d, s) for t in range(3) for d in range(4) for s in range(2)})
        self.check(with_missing('propagate'), every, 'XR_PROFILE_ALL_MISSING')
        self.check(with_missing('propagate'), data, 'XR_PROFILE_TOO_SHORT')
        self.check(with_missing('skip'), every, 'XR_INSUFFICIENT_VALID')

    def test_fill_value_must_match_and_exist(self):
        self.check(document(missing={'value': -998.0, 'policy': 'refuse'}), fx.build(), 'XR_FILL_MISMATCH')
        self.check(document(), fx.build(fill=False), 'XR_FILL_MISMATCH')

    def test_nonfinite_and_huge_data_are_refused_not_treated_as_missing(self):
        data = [fx.value(t, d, s) for t in range(3) for d in range(4) for s in range(2)]
        for bad, expected in ((math.nan, 'XR_NONFINITE_VALUE'), (math.inf, 'XR_NONFINITE_VALUE'), (1e101, 'XR_VALUE_RANGE')):
            changed = list(data)
            changed[5] = bad
            with self.subTest(bad=bad):
                self.check(document(), fx.build(data=changed), expected)

    def test_unsupported_information_is_refused_not_dropped(self):
        self.check(document(), fx.build(extra_attrs=[('scale_factor', 'double', 0.5)]), 'XR_ATTRIBUTE_UNSUPPORTED')
        self.check(document(), fx.build(extra_attrs=[('add_offset', 'double', 1.0)]), 'XR_ATTRIBUTE_UNSUPPORTED')
        extra = {'name': 'mask', 'dims': ['depth'], 'type': 'double', 'attrs': [], 'values': [0.0] * 4}
        self.check(document(), fx.build(extra_vars=[extra]), 'XR_EXTRA_VARIABLE')
        self.check(document(coordinates=document()['coordinates'][:2]), fx.build(), 'XR_DIMENSION_MISMATCH')
        self.check(document(variable={'name': 'salinity', 'unit': 'K'}), fx.build(), 'XR_VARIABLE_MISSING')

    def test_ill_conditioned_cancellation_is_refused(self):
        doc = document()
        doc['coordinates'] = [{'name': 'time', 'unit': 'h'}, {'name': 'depth', 'unit': 'm'}, {'name': 'station', 'unit': 'km'}]
        cube = fx.build(axes={'time': [0.0, 1.0, 2.0, 3.0], 'depth': [0.0, 10.0], 'station': [1.0]},
                        data=[1e16, 5.0, 1.0, 5.0, -1e16, 5.0, 1.0, 5.0])
        self.check(doc, cube, 'XR_ILL_CONDITIONED')
        # the same magnitudes without cancellation are accepted and the tolerance is far below the mean
        benign = fx.build(axes={'time': [0.0, 1.0, 2.0, 3.0], 'depth': [0.0, 10.0], 'station': [1.0]},
                          data=[1e16, 5.0, 3e16, 5.0, 2e16, 5.0, 4e16, 5.0])
        _, _, points = reduce(doc, benign)
        self.assertEqual(points[0]['mean'], 2.5e16)
        self.assertLess(points[0]['tolerance'], 1e-9 * points[0]['mean'])

    def test_plan_contract_faults(self):
        base = document()
        cases = [({'retain': 'latitude'}, 'XR_INVALID_CONTRACT', '$.retain'),
                 ({'missing': {'value': -999.0, 'policy': 'propagate', 'minimumValid': 2}}, 'XR_INVALID_CONTRACT', '$.missing.minimumValid'),
                 ({'source': 'cube.nc'}, 'XR_INVALID_SOURCE', '$.source'),
                 ({'source': '/tmp/cube.csv'}, 'XR_INVALID_SOURCE', '$.source'),
                 ({'variable': {'name': 'validCount', 'unit': 'K'}}, 'XR_INVALID_CONTRACT', '$.variable.name')]
        for changes, expected, where in cases:
            with self.subTest(changes=changes):
                self.assertEqual(code(lambda: a.plan({**base, **changes})), (expected, where))
        dup = copy.deepcopy(base)
        dup['coordinates'][1]['name'] = 'time'
        self.assertEqual(code(lambda: a.plan(dup))[0], 'XR_INVALID_CONTRACT')
        rev = copy.deepcopy(base)
        rev['coordinates'][1]['range'] = {'minimum': 20, 'maximum': 0}
        self.assertEqual(code(lambda: a.plan(rev)), ('XR_INVALID_CONTRACT', '$.coordinates[1].range'))
        short = copy.deepcopy(base)
        short['coordinates'] = short['coordinates'][:1]
        self.assertNotEqual(code(lambda: a.plan(short))[0], 'accepted')

    def test_missing_runtime_is_a_structured_unavailable_fault(self):
        with tempfile.TemporaryDirectory() as tmp:
            error = code(lambda: a.run(document(), Path(tmp) / 'run', executable='/nonexistent/python'))
        self.assertEqual(error[0], 'INTERPRETER_NOT_FOUND')


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.data = fx.build()
        self.parsed = cdf.parse(self.data)

    def begin_offset(self, name):
        begin = next(v['begin'] for v in self.parsed['vars'] if v['name'] == name)
        return self.data.find(struct.pack('>I', begin), 0, self.parsed['vars'][0]['begin'])

    def test_roundtrip_values_and_attributes(self):
        names = [v['name'] for v in self.parsed['vars']]
        self.assertEqual(names, ['time', 'depth', 'station', 'temperature'])
        self.assertEqual(self.parsed['vars'][3]['attrs']['_FillValue'], ('double', -999.0))
        self.assertEqual(self.parsed['attrs'], {'title': ('char', 'Analytic measurement cube')})

    def test_malformed_structures_have_stable_faults(self):
        data = self.data
        i = self.begin_offset('depth')
        j = self.begin_offset('station')
        cases = {
            'wrong version (CDF-2)': (b'CDF\x02' + data[4:], 'XR_UNSUPPORTED_FORMAT'),
            'CDF-5': (b'CDF\x05' + data[4:], 'XR_UNSUPPORTED_FORMAT'),
            'HDF5 magic': (b'\x89HDF\r\n\x1a\n' + data[8:], 'XR_UNSUPPORTED_FORMAT'),
            'trailing bytes': (data + b'\0' * 8, 'XR_CDF_LAYOUT'),
            'truncated header': (data[:40], 'XR_CDF_MALFORMED'),
            'truncated data': (data[:-8], 'XR_CDF_MALFORMED'),
            'record count': (data[:4] + struct.pack('>I', 3) + data[8:], 'XR_UNLIMITED_DIMENSION'),
            'streaming record count': (data[:4] + b'\xff\xff\xff\xff' + data[8:], 'XR_UNLIMITED_DIMENSION'),
            'overlap': (data[:j] + data[i:i + 4] + data[j + 4:], 'XR_CDF_LAYOUT'),
            'gap': (data[:j] + struct.pack('>I', struct.unpack('>I', data[j:j + 4])[0] + 8) + data[j + 4:], 'XR_CDF_LAYOUT'),
            'offset beyond file': (data[:j] + struct.pack('>I', 10**9) + data[j + 4:], 'XR_CDF_LAYOUT'),
            'oversize': (data + b'\0' * cdf.LIMITS['maxBytes'], 'XR_RESOURCE_LIMIT'),
        }
        for label, (blob, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(code(lambda: cdf.parse(blob))[0], expected)

    def test_unlimited_dimension_zero_length_is_refused(self):
        blob = bytearray(cdf.write([('time', 3)], [], [{'name': 'time', 'dims': ['time'], 'type': 'double', 'attrs': [], 'values': [0, 1, 2.0]}]))
        position = bytes(blob).find(struct.pack('>I', 3), 16)
        blob[position:position + 4] = struct.pack('>I', 0)
        self.assertEqual(code(lambda: cdf.parse(bytes(blob)))[0], 'XR_UNLIMITED_DIMENSION')

    def test_duplicates_types_and_counts(self):
        dup = cdf.write([('a', 1), ('b', 1)], [], [{'name': 'v', 'dims': ['a'], 'type': 'double', 'attrs': [], 'values': [1.0]},
                                                    {'name': 'v', 'dims': ['b'], 'type': 'double', 'attrs': [], 'values': [1.0]}])
        self.assertEqual(code(lambda: cdf.parse(dup))[0], 'XR_CDF_DUPLICATE')
        dims = cdf.write([('a', 1), ('a', 2)], [], [])
        self.assertEqual(code(lambda: cdf.parse(dims))[0], 'XR_CDF_DUPLICATE')
        attrs = cdf.write([('a', 1)], [('title', 'char', 'x'), ('title', 'char', 'y')], [])
        self.assertEqual(code(lambda: cdf.parse(attrs))[0], 'XR_CDF_DUPLICATE')
        many = cdf.write([('d%d' % i, 1) for i in range(5)], [], [])
        self.assertEqual(code(lambda: cdf.parse(many))[0], 'XR_RESOURCE_LIMIT')
        wide = cdf.write([('a', 5000)], [], [])
        self.assertEqual(code(lambda: cdf.parse(wide))[0], 'XR_RESOURCE_LIMIT')
        ints = cdf.write([('a', 2)], [], [{'name': 'n', 'dims': ['a'], 'type': 'int', 'attrs': [], 'values': [1, 2]}])
        self.assertEqual(cdf.parse(ints)['vars'][0]['values'], [1, 2])
        self.assertEqual(code(lambda: reduce(document(), fx.build(data=None, extra_vars=[{'name': 'n', 'dims': ['depth'], 'type': 'int',
                                                                                          'attrs': [], 'values': [1, 2, 3, 4]}]))),
                         ('XR_EXTRA_VARIABLE', '$.source'))
        nonzero = bytearray(self.data)
        nonzero[nonzero.find(b'depth') + 5] = 1
        self.assertEqual(code(lambda: cdf.parse(bytes(nonzero)))[0], 'XR_CDF_MALFORMED')

    def test_data_variable_must_be_double(self):
        data = cdf.write([('time', 2), ('depth', 2)], [], [
            {'name': 'time', 'dims': ['time'], 'type': 'double', 'attrs': [('units', 'char', 'h')], 'values': [0.0, 1.0]},
            {'name': 'depth', 'dims': ['depth'], 'type': 'double', 'attrs': [('units', 'char', 'm')], 'values': [0.0, 1.0]},
            {'name': 'temperature', 'dims': ['time', 'depth'], 'type': 'int', 'attrs': [('units', 'char', 'K'), ('_FillValue', 'double', -999.0)],
             'values': [1, 2, 3, 4]}])
        doc = document(coordinates=document()['coordinates'][:2])
        self.assertEqual(code(lambda: reduce(doc, data))[0], 'XR_TYPE_UNSUPPORTED')


def native_shaped(doc, data, tamper=None):
    """A profile.nc/profile.csv pair built by the independent writer from the exact oracle (host-only verifier input)."""
    p, cube, points = reduce(doc, data)
    expect = o.expectations(p, cube, points)
    retain, variable = p['retain'], p['variable']['name']
    sentinel = p['missing']['value']
    attrs = [(k, 'char', v) for k, v in expect['attrs'].items()] + ([('title', 'char', cube['title'])] if cube['title'] is not None else [])
    vals = [sentinel if r['mean'] is None else r['mean'] for r in points]
    pv = [{'name': variable, 'dims': [retain], 'type': 'double', 'attrs': [('units', 'char', p['variable']['unit']), ('_FillValue', 'double', sentinel)], 'values': vals},
          {'name': 'validCount', 'dims': [retain], 'type': 'int', 'attrs': [('units', 'char', 'count')], 'values': [r['valid'] for r in points]},
          {'name': 'missingCount', 'dims': [retain], 'type': 'int', 'attrs': [('units', 'char', 'count')], 'values': [r['missing'] for r in points]},
          {'name': retain, 'dims': [retain], 'type': 'double', 'attrs': [('units', 'char', expect['retained']['unit'])], 'values': [r['coordinate'] for r in points]}]
    if tamper:
        tamper(pv, attrs)
    return p, cube, points, cdf.write([(retain, len(points))], attrs, pv), o.render_csv(p, points)


class VerifierTests(unittest.TestCase):
    def test_exact_publication_verifies_and_summary_is_complete(self):
        data = fx.build()
        p, cube, points, nc, csv_bytes = native_shaped(document(), data)
        verified = o.verify_profile(p, cube, points, nc, csv_bytes)
        self.assertEqual(verified['maxAbsoluteError'], 0.0)
        summary = o.summary(p, cube, points, verified, nc, csv_bytes, data, {})
        self.assertEqual(summary['csv']['header'], 'depth,temperature,validCount,missingCount')
        self.assertEqual(summary['totals'], {'selectedCells': 24, 'validCells': 24, 'missingCells': 0})
        self.assertEqual([x['coordinateSha256'] for x in summary['axes']][1], o.digest_doubles([0.0, 10.0, 20.0, 30.0]))
        self.assertEqual(summary['source']['sha256'], cube['sourceSha256'])
        self.assertEqual(csv_bytes.decode().splitlines()[1], '0.0,280.625,6,0')

    def test_tampered_publications_are_rejected(self):
        data = fx.build()

        def failing(tamper=None, csv_edit=None):
            p, cube, points, nc, csv_bytes = native_shaped(document(), data, tamper)
            if csv_edit:
                csv_bytes = csv_edit(csv_bytes)
            return code(lambda: o.verify_profile(p, cube, points, nc, csv_bytes))[0]

        def mean(pv, attrs):
            pv[0]['values'][1] += 1e-9

        def unit(pv, attrs):
            pv[0]['attrs'][0] = ('units', 'char', 'degC')

        def coordinate(pv, attrs):
            pv[3]['values'][2] = 21.0

        def count(pv, attrs):
            pv[1]['values'][0] = 5

        def dropped(pv, attrs):
            del attrs[0]

        def zero(pv, attrs):
            pv[0]['values'][3] = 0.0

        for label, tamper in (('mean', mean), ('unit', unit), ('coordinate', coordinate), ('count', count), ('attribute', dropped), ('fake zero', zero)):
            with self.subTest(label):
                self.assertEqual(failing(tamper), 'VERIFICATION_FAILED')
        self.assertEqual(failing(csv_edit=lambda b: b.replace(b'280.625', b'280.626')), 'VERIFICATION_FAILED')
        self.assertEqual(failing(csv_edit=lambda b: b + b'\n'), 'VERIFICATION_FAILED')

    def test_tolerance_is_scale_aware_and_never_hides_one_ulp_scale_errors(self):
        data = fx.build()
        p, cube, points, _, _ = native_shaped(document(), data)
        tol = points[0]['tolerance']
        self.assertLess(tol / points[0]['mean'], 1e-9)
        self.assertGreater(tol, 0)
        slightly = math.nextafter(points[0]['mean'], math.inf)
        self.assertLess(abs(slightly - points[0]['mean']), tol * 2)           # ulp-scale native differences are allowed
        self.assertGreater(abs(points[0]['mean'] * 1e-6), tol * 1e3)           # a 1e-6 relative error is far outside it

    def test_propagate_publication_round_trips_with_sentinel_and_empty_cell(self):
        data = fx.build(missing={(1, 3, 0)})
        p, cube, points, nc, csv_bytes = native_shaped(with_missing('propagate'), data)
        o.verify_profile(p, cube, points, nc, csv_bytes)
        self.assertEqual(csv_bytes.decode().splitlines()[4], '30.0,,5,1')


class BoundaryTests(unittest.TestCase):
    """Published attribute budget, the selected-retained-point cap and the stated rounding behaviour."""

    def long_name_cube(self):
        names = ['A' + 'a' * 39, 'B' + 'b' * 39, 'depth']
        lengths = [2, 2, 3]
        variables = [{'name': n, 'dims': [n], 'type': 'double', 'attrs': [('units', 'char', 'm')], 'values': [float(10 * i) for i in range(k)]}
                     for n, k in zip(names, lengths)]
        variables.append({'name': 'temperature', 'dims': names, 'type': 'double',
                          'attrs': [('units', 'char', 'K'), ('_FillValue', 'double', -999.0)], 'values': [280.0 + i for i in range(12)]})
        doc = document(source='/data/long.nc', coordinates=[{'name': n, 'unit': 'm'} for n in names], retain='depth',
                       missing={'value': -999.0, 'policy': 'refuse'})
        return doc, cdf.write(list(zip(names, lengths)), [], variables)

    def test_two_forty_character_reduced_names_keep_published_attributes_within_budget(self):
        doc, data = self.long_name_cube()
        p, cube, points, nc, csv_bytes = native_shaped(doc, data)
        text = o.expectations(p, cube, points)['attrs']['schemaxis_reduction']
        self.assertEqual(text, o.reduction_text(p))
        self.assertNotIn('A' + 'a' * 39, text)
        self.assertLessEqual(len(text), cdf.LIMITS['maxText'])
        self.assertEqual(a.native_config(p, 'f' * 64)['outputAttributes']['schemaxis_reduction'], text)
        self.assertEqual(o.expectations(p, cube, points)['reduced'], ['A' + 'a' * 39, 'B' + 'b' * 39])
        o.verify_profile(p, cube, points, nc, csv_bytes)                 # the independent reader accepts its own published budget
        for policy in o.POLICIES:                                        # the longest fixed text of any policy fits
            self.assertLessEqual(len(o.reduction_text({'missing': {'policy': policy}})), cdf.LIMITS['maxText'])

    def cap_cube(self, length, minimum=None, maximum=None):
        values = [float(i) for i in range(length)]
        variables = [{'name': 'depth', 'dims': ['depth'], 'type': 'double', 'attrs': [('units', 'char', 'm')], 'values': values},
                     {'name': 'station', 'dims': ['station'], 'type': 'double', 'attrs': [('units', 'char', 'index')], 'values': [1.0, 2.0]},
                     {'name': 'temperature', 'dims': ['depth', 'station'], 'type': 'double',
                      'attrs': [('units', 'char', 'K'), ('_FillValue', 'double', -999.0)],
                      'values': [300.0 + i % 7 for i in range(2 * length)]}]
        depth = {'name': 'depth', 'unit': 'm'}
        if minimum is not None:
            depth['range'] = {'minimum': minimum, 'maximum': maximum}
        doc = document(source='/data/cap.nc', coordinates=[depth, {'name': 'station', 'unit': 'index'}], retain='depth',
                       missing={'value': -999.0, 'policy': 'refuse'})
        return doc, cdf.write([('depth', length), ('station', 2)], [], variables)

    def test_selected_retained_points_are_capped_at_2048_before_launch(self):
        self.assertEqual(o.LIMITS['maxProfile'], 2048)
        accepted = reduce(*self.cap_cube(2048))
        self.assertEqual(len(accepted[2]), 2048)
        for label, args, expected in (('whole axis 2049', (2049,), 2049), ('whole axis 3000', (3000,), 3000),
                                      ('selected 2049 of 3000', (3000, 0.0, 2048.0), 2049)):
            with self.subTest(label):
                doc, data = self.cap_cube(*args)
                got = code(lambda: reduce(doc, data))
                self.assertEqual(got, ('XR_RESOURCE_LIMIT', '$.retain'))
                with self.assertRaises(SchemaxisError) as caught:
                    reduce(doc, data)
                self.assertEqual(caught.exception.fault.observed['selected'], expected)

    def test_source_axis_may_exceed_the_cap_when_the_selection_fits(self):
        doc, data = self.cap_cube(3000, 100.0, 2147.0)                  # 2048 selected points of a 3000-point axis
        points = reduce(doc, data)[2]
        self.assertEqual(len(points), 2048)
        self.assertEqual([points[0]['coordinate'], points[-1]['coordinate']], [100.0, 2147.0])

    def test_the_cap_names_the_retained_dimension_not_a_reduced_one(self):
        doc, data = self.cap_cube(3000)
        doc['retain'] = 'station'                                       # 2 points retained; the long axis is only reduced
        self.assertEqual(len(reduce(doc, data)[2]), 2)

    def test_subnormal_means_must_equal_the_nearest_rounded_exact_mean_with_no_floor(self):
        cells = [fx.value(t, d, s) for t in range(3) for d in range(4) for s in range(2)]
        for t in range(3):
            for s in range(2):
                cells[t * 8 + s] = 5e-324 if (t, s) == (0, 0) else 0.0
        data = fx.build(data=cells)
        p, cube, points, nc, csv_bytes = native_shaped(document(), data)
        self.assertEqual((points[0]['mean'], points[0]['tolerance']), (0.0, 0.0))     # 5e-324 / 6 rounds to zero: correct, not invented
        o.verify_profile(p, cube, points, nc, csv_bytes)
        wrong = native_shaped(document(), data, lambda pv, attrs: pv[0]['values'].__setitem__(0, 5e-324))
        self.assertEqual(code(lambda: o.verify_profile(*wrong[:3], wrong[3], o.render_csv(wrong[0], [{**r, 'mean': 5e-324 if i == 0 else r['mean']} for i, r in enumerate(points)])))[0],
                         'VERIFICATION_FAILED')

    def test_reader_names_follow_the_identifier_patterns(self):
        for kind, name in (('dimension', 'bad-name'), ('attribute', 'bad name')):
            with self.subTest(kind):
                if kind == 'dimension':
                    data = cdf.write([(name, 1)], [], [{'name': 'v', 'dims': [name], 'type': 'double', 'attrs': [], 'values': [1.0]}])
                else:
                    data = cdf.write([('x', 1)], [(name, 'char', 'v')], [{'name': 'v', 'dims': ['x'], 'type': 'double', 'attrs': [], 'values': [1.0]}])
                self.assertEqual(code(lambda: cdf.parse(data))[0], 'XR_CDF_NAME')


class WorkflowBindingTests(unittest.TestCase):
    """Host binding of the xarray profile.csv -> Gnuplot workflow edge (the native edge is run by tools/qualify_xarray.py)."""
    EXAMPLE = EXAMPLES / 'xarray-profile-plot-workflow.json'

    def example(self):
        return json.loads(self.EXAMPLE.read_text())

    def test_artifact_index_names_the_csv_table_and_gnuplot_accepts_tables(self):
        p = a.plan(document())
        index = [name for name, _ in a.publications(p)].index('profile.csv')
        self.assertEqual((index, a.publications(p)[index][1]), (1, 'table'))
        edge = self.example()['operations'][1]['document']['source']
        self.assertEqual(edge, {'$artifact': 'profile', 'index': index})
        route = registry.resolve({'version': 'schemaxis.gnuplot/1'}, legacy=True)[1]
        self.assertIn('table', route['acceptedArtifacts'])
        self.assertEqual(registry.resolve({'version': 'schemaxis.xarray/1'}, legacy=True)[1]['acceptedArtifacts'], ['file'])

    def test_example_plot_columns_equal_the_published_csv_header_and_units(self):
        p, cube, points, nc, csv_bytes = native_shaped(document(), fx.build())
        header = csv_bytes.decode().splitlines()[0]
        consumer = self.example()['operations'][1]['document']
        self.assertEqual(','.join(c['name'] for c in consumer['columns']), header)
        self.assertEqual([c['unit'] for c in consumer['columns']], ['m', 'K', 'count', 'count'])
        self.assertEqual(self.example()['operations'][0]['document']['source'], '/replace/with/xarray-cube.nc')

    def test_example_workflow_plans_on_the_host_with_a_deferred_artifact_edge(self):
        planned = workflow.inspect_plan(self.example())
        entry = {item['id']: item for item in planned['operations']}['plot']['provisionalPlan']
        self.assertEqual((entry['status'], entry['references']), ('deferred', [{'$artifact': 'profile', 'index': 1}]))
        self.assertEqual({job['id']: job for job in planned['jobs']}['plot/0']['dependencies'], ['profile'])

    def test_consumer_route_refuses_a_propagated_empty_cell_and_accepts_the_complete_profile(self):
        complete = native_shaped(document(), fx.build())[4]
        holes = native_shaped(with_missing('propagate'), fx.build(missing={(1, 3, 0)}))[4]
        with tempfile.TemporaryDirectory() as tmp:
            for name, data, expected in (('complete.csv', complete, 'accepted'), ('holes.csv', holes, 'INVALID_PLOT_DATA')):
                path = Path(tmp) / name
                path.write_bytes(data)
                doc = self.example()['operations'][1]['document'] | {'source': str(path)}
                self.assertEqual(code(lambda: gnuplot.reusableInputs(doc))[0], expected, name)

    def test_xarray_production_code_imports_no_other_adaptor(self):
        for path in sorted((ROOT / 'src/schemaxis/adaptors/xarray').glob('*.py')):
            for node in ast.walk(ast.parse(path.read_text())):
                names = [node.module or ''] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names] if isinstance(node, ast.Import) else []
                for name in names:
                    if name.startswith('schemaxis.adaptors.') or (isinstance(node, ast.ImportFrom) and node.level and name.startswith('..adaptors')):
                        self.assertTrue(name.startswith('schemaxis.adaptors.xarray'), (path.name, name))

    def test_readiness_and_guidance_name_the_workflow_example(self):
        readiness = json.loads((ROOT / 'src/schemaxis/adaptors/xarray/readiness.json').read_text())['routes']['schemaxis.xarray/1']
        self.assertIn('examples/schemaxis/xarray-profile-plot-workflow.json', readiness['profiles']['workflow']['references'])
        self.assertNotIn('xarray-profile-plot-workflow', json.dumps(readiness['examples']))   # a workflow, not a standalone operation example
        guidance = json.loads((ROOT / 'src/schemaxis/adaptors/xarray/guidance.json').read_text())
        self.assertIn('examples/schemaxis/xarray-profile-plot-workflow.json',
                      [e['reference'] for e in guidance['operations']['reduceProfile']['examples']])

    def test_absorbed_version_requires_a_registered_native_receipt(self):
        folder = ROOT / 'src/schemaxis/adaptors/xarray'
        upstream = json.loads((folder / 'upstream.json').read_text())
        self.assertIn('2026.9.0', upstream['scope'])
        # A new provider starts unqualified. Later acceptance may promote its
        # version; subsequent source edits may stale that historical receipt.
        if upstream['absorbedVersion'] is not None:
            self.assertEqual(upstream['absorbedVersion'], '2026.9.0')
            bundle = json.loads((folder / 'qualification.json').read_text())
            self.assertEqual(bundle['protocol'], 'schemaxis.adaptor-qualification/1')
            receipt = bundle['routes']['schemaxis.xarray/1']
            self.assertEqual(receipt['mode'], 'native')
            self.assertIs(receipt['verified'], True)
            self.assertTrue(receipt['cases'])
            for case in receipt['cases']:
                self.assertIs(case['verified'], True)
                self.assertIn('xarray 2026.9.0 /', case['runtime'])


if __name__ == '__main__':
    unittest.main()
