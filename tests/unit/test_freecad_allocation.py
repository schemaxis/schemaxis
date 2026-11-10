"""Degenerated native edges are valid topology, not malformed edge inventories.

Spheres carry degenerated pole edges whose curve is undefined; a pointed cone has a
zero-length apex edge. Selection and measurement must keep edge numbering, ignore
them in geometric predicates and still reject forged or genuinely malformed records.
"""
import copy
import math
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad import measurements as m, selections as s
from schemaxis.adaptors.freecad.adaptor import plan
from test_freecad_selections import selector


class Point:
    def __init__(self, *xyz):
        self.x, self.y, self.z = xyz

    def __iter__(self):
        return iter((self.x, self.y, self.z))


class Box:
    def __init__(self, bounds):
        self.XMin, self.XMax, self.YMin, self.YMax, self.ZMin, self.ZMax = bounds


class Circle: pass
class Line: pass


class FakeEdge:
    """Stands in for a native edge; `curve=None` reproduces `undefined curve type`."""
    def __init__(self, curve, length, bounds, centre, vertices):
        self._curve, self.Length, self._bounds = curve, length, bounds
        self.CenterOfMass, self.Vertexes = Point(*centre), [type('V', (), {'Point': Point(*v)}) for v in vertices]

    @property
    def Curve(self):
        if self._curve is None:
            raise TypeError('undefined curve type')
        return self._curve()

    def optimalBoundingBox(self, *_):
        return Box(self._bounds)


class FakeShape:
    def __init__(self, edges):
        self.Edges = edges


def pole(z):
    return FakeEdge(None, 1.9e-15, [-1e-7, 1e-7, -1e-7, 1e-7, z-1e-7, z+1e-7], (0, 0, z), [(0, 0, z)])


def circle(radius, z, length=None):
    return FakeEdge(Circle, 2*math.pi*radius if length is None else length,
                    [-radius, radius, -radius, radius, z, z], (0, 0, z), [(radius, 0, z)])


def sphere():
    seam = FakeEdge(Circle, 5*math.pi, [0, 5, 0, 0, -5, 5], (3.18, 0, 0), [(0, 0, 5), (0, 0, -5)])
    return FakeShape([pole(5), seam, pole(-5)])


def cone():
    line = FakeEdge(Line, math.hypot(5, 10), [0, 5, 0, 0, 0, 10], (2.5, 0, 5), [(0, 0, 10), (5, 0, 0)])
    return FakeShape([circle(0, 10, length=0.0), line, circle(5, 0)])


class DegenerateEdgeTests(unittest.TestCase):
    def test_native_inventory_survives_undefined_curves_and_zero_length_apexes(self):
        inventory = s.native_edges(sphere())
        self.assertEqual([e['index'] for e in inventory], [1, 2, 3])
        self.assertEqual([e['curve'] for e in inventory], ['Degenerate', 'Circle', 'Degenerate'])
        apex = s.native_edges(cone())
        self.assertEqual([e['curve'] for e in apex], ['Degenerate', 'Line', 'Circle'])
        self.assertEqual(s.resolve([1, 2, 3], inventory), [1, 2, 3])
        self.assertEqual(s.resolve([1, 2, 3], apex), [1, 2, 3])

    def test_undefined_curve_with_real_length_is_a_structured_fault_not_a_raw_type_error(self):
        edge = FakeEdge(None, 12.0, [0, 1, 0, 1, 0, 1], (0, 0, 0), [(0, 0, 0), (1, 0, 0)])
        with self.assertRaises(SchemaxisError) as error:
            s.native_edges(FakeShape([circle(1, 0), edge]))
        self.assertEqual(error.exception.fault.code, 'UNSUPPORTED_EDGE')
        self.assertEqual(error.exception.fault.observed['index'], 2)

    def test_semantic_selection_ignores_degenerate_edges_but_keeps_numbering(self):
        edges = s.native_edges(cone())
        self.assertEqual(s.resolve(selector({'curve': 'circle'}, 1), edges), [3])
        truncated = s.native_edges(FakeShape(cone().Edges + [circle(2, 10)]))
        self.assertEqual(s.resolve(selector({'onPlane': {'axis': 'z', 'coordinate': 10}}, 1), truncated), [4])
        # A zero-length interval and the apex plane must not match the degenerate apex.
        for where in ({'length': {'minimum': 0, 'maximum': 1}}, {'onPlane': {'axis': 'z', 'coordinate': 10}}):
            with self.subTest(where=where), self.assertRaises(SchemaxisError) as error:
                s.resolve(selector(where, 1), edges)
            self.assertEqual(error.exception.fault.code, 'EMPTY_SELECTION')
        # Explicit indices still address the native topology, apex included.
        self.assertEqual(s.resolve([1, 3], edges), [1, 3])

    def test_degenerate_label_cannot_hide_a_real_edge_or_negative_length(self):
        edges = s.native_edges(cone())
        for index, length in ((1, 5.0), (1, -1e-9), (1, float('nan'))):
            bad = copy.deepcopy(edges); bad[index-1]['lengthMM'] = length
            with self.subTest(length=length), self.assertRaises(SchemaxisError) as error:
                s.resolve(selector({'curve': 'circle'}, 1), bad)
            self.assertEqual(error.exception.fault.code, 'VERIFICATION_FAILED')
        bad = copy.deepcopy(edges); bad[2]['lengthMM'] = 0.0   # a non-degenerate record keeps the old rule
        with self.assertRaises(SchemaxisError):
            s.resolve(selector({'curve': 'circle'}, 1), bad)

    def test_measurements_count_and_sum_selected_edges_of_a_pointed_solid(self):
        document = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'tip', 'filter': 'cone',
                    'options': {'radius1': 5, 'radius2': 0, 'height': 10}}], 'output': 'tip',
                    'measurements': [{'id': 'rim', 'node': 'tip', 'quantity': 'totalEdgeLength',
                                      'edges': {'where': {'curve': 'circle'}, 'expect': 1}},
                                     {'id': 'n', 'node': 'tip', 'quantity': 'edgeCount', 'edges': [1, 2, 3]}]}
        prepared = plan(document)
        observed = {'tip': {'shape': {'valid': True, 'solids': 1, 'volume': 261.8, 'area': 259.8,
                                      'bounds': [-5, 5, -5, 5, 0, 10]}, 'centreMM': [0, 0, 2.5],
                            'edges': s.native_edges(cone())}}
        result = m.evaluate(prepared, observed)['measurements']
        self.assertEqual(result['rim']['selectedEdges'], [3])
        self.assertTrue(math.isclose(result['rim']['value'], 10*math.pi))
        self.assertEqual(result['n']['value'], 3)
        m.verify(prepared, observed, copy.deepcopy(observed), m.evaluate(prepared, observed))

    def test_legacy_inventories_without_degenerate_edges_are_unchanged(self):
        from test_freecad_selections import box_edges
        edges = box_edges()
        self.assertEqual(s.resolve(selector(), edges), [1, 6, 9, 12])
        self.assertTrue(all(e['curve'] == 'Line' for e in s.native_edges(FakeShape(
            [FakeEdge(Line, 10.0, [0, 10, 0, 0, 0, 0], (5, 0, 0), [(0, 0, 0), (10, 0, 0)])]))))
