"""String $expr in pipeline documents: names, phases, legacy markers and faults."""
import copy
import unittest

from schemaxis.core.faults import SchemaxisError
from schemaxis.filters import catalogue
from schemaxis.pipeline import DefinitionGraph, RuntimeClosure


class Backend:
    def __init__(self):
        self.events = []

    def create(self, node, declaration, inputs, constructor):
        return {'node': node, 'values': dict(constructor)}

    def configure(self, handle, declaration, values):
        handle['values'].update(copy.deepcopy(values))
        self.events.append(('set', handle['node'], copy.deepcopy(values)))

    def update(self, handle, time):
        self.events.append(('update', handle['node'], time))

    def observe(self, handle):
        return {'bounds': [0, 4.5, -0.9, 0.9, 0.2, 1.4], 'points': 12}

    def delete(self, handle):
        pass


def document(origin, **sections):
    value = {'version': 'schemaxis/1', 'nodes': [
        {'id': 'source', 'filter': 'wavelet'},
        {'id': 'slice', 'filter': 'slice', 'inputs': {'input': 'source'}, 'options': {'origin': origin}}],
        'dimensions': {'wheelbase': 2.7}, 'settings': {'zoom': 0.52, 'options': {'gap': 0.25}},
        'definitions': {'body': {'min': [0, -0.9, 0.2], 'max': [4.5, 0.9, 1.4]},
                        'wheels': [0.5, 3.6, -1, 1, 0, 0.7],
                        'model': {'$expr': 'union(body, wheels)'},
                        'obs': {'$observe': 'source'},
                        'car': {'$expr': 'box(obs.bounds)'},
                        'v': {'$calc': 'multiply', 'args': [[1, 2, 3], 2]}},
        'sweeps': [{'name': 't', 'values': [0, 0.5, 1]}]}
    for section, entries in sections.items():
        value.setdefault(section, {}).update(entries)
    return value


def expression(text):
    return {'$expr': text}


class DocumentExpressions(unittest.TestCase):
    def graph(self, origin, **sections):
        return DefinitionGraph(document(origin, **sections), catalogue())

    def origins(self, origin, **sections):
        backend = Backend()
        active = RuntimeClosure(self.graph(origin, **sections), backend)
        results = [active.apply(visit) for visit in active.activate(['slice']).visits()]
        return [result['effective']['slice']['origin'] for result in results]

    def fault(self, code, origin, **sections):
        with self.assertRaises(SchemaxisError) as caught:
            self.origins(origin, **sections)
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def close(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            self.assertAlmostEqual(a, e, places=12)

    def test_constant_expression_is_resolved_before_planning(self):
        graph = self.graph(expression('model.mid'))
        self.close(graph.nodes['slice']['options']['origin'], [2.25, 0, 0.7])
        self.assertEqual(graph.document['definitions']['model'], {'min': [0, -1, 0], 'max': [4.5, 1, 1.4]})
        self.assertEqual(graph.select(['slice']).axes, ())

    def test_visit_expression_follows_the_axis(self):
        graph = self.graph(expression('lerp(model.min, model.max, t)'))
        self.assertEqual(graph.select(['slice']).axes, ('t',))
        values = self.origins(expression('lerp(model.min, model.max, t)'))
        for actual, expected in zip(values, ([0, -1, 0], [2.25, 0, 0.7], [4.5, 1, 1.4])):
            self.close(actual, expected)
        self.assertEqual(self.origins(expression('vector(time, sweeps.t, 0)'))[2], [0.0, 1, 0])

    def test_observed_expression_waits_for_its_node(self):
        graph = self.graph(expression('car.mid + vector(1, 0, 0)'))
        self.assertEqual(graph.nodes['slice']['dependencies'], ['source'])
        self.assertTrue(graph.profiles['slice']['origin'].observed)
        self.close(self.origins(expression('car.mid + vector(1, 0, 0)'))[0], [3.25, 0, 0.8])
        self.close(self.origins(expression('vector(scalar(obs.points), t, car.deltaZ)'))[1], [12, 0.5, 1.2])

    def test_entries_written_with_other_markers_are_read_by_name(self):
        self.assertEqual(self.origins(expression('v'))[0], [2, 4, 6])
        self.assertEqual(self.origins(expression('vector(v.x, settings.options.gap + 1, wheelbase)'))[0],
                         [2, 1.25, 2.7])
        entries = {'x': {'$sweep': 't'}, 'c': {'$call': 'boundsCentre3D', 'args': {'bounds': {'$expr': 'car'}}}}
        self.assertEqual(self.origins(expression('vector(x + 1, 0, 0)'), definitions=entries)[1], [1.5, 0, 0])
        self.close(self.origins(expression('c * 2'), definitions=entries)[0], [4.5, 0, 1.6])

    def test_catalogue_functions_take_named_arguments(self):
        self.assertEqual(self.origins(expression("directionVector(direction = 'x+', length = 2)"))[0], [2, 0, 0])
        self.close(self.origins(expression('fitCamera(bounds = model).focalPoint'))[0], [2.25, 0, 0.7])
        self.close(self.origins(expression('fitCamera(bounds = car).focalPoint'))[0], [2.25, 0, 0.8])
        self.fault('EXPR_ARGUMENTS', expression("directionVector('x+')"))
        self.fault('EXPR_ARGUMENTS', expression("directionVector(length = 2)"))
        self.fault('EXPR_TYPE', expression("directionVector(direction = 'x+', length = model)"))
        self.fault('EXPR_UNKNOWN_PROPERTY', expression('fitCamera(bounds = model).nothing'))
        self.fault('EXPR_UNKNOWN_PROPERTY', expression("model.directionVector(direction = 'x+')"))

    def test_legacy_markers_take_expressions_and_late_arguments(self):
        late = {'$value': 'boundsCentre3D', 'args': {'bounds': expression('car')}}
        self.close(self.origins(late)[0], [2.25, 0, 0.8])
        self.assertEqual(self.origins({'$calc': 'midpoint', 'args': [expression('box(0, 2, 0, 4, 0, 6)')]})[0],
                         [1, 2, 3])
        constant = {'$call': 'directionVector', 'args': {'direction': 'y+'}}
        self.assertEqual(self.graph(constant).nodes['slice']['options']['origin'], [0, 1, 0])
        sum_ = {'$expr': {'op': 'add', 'args': [expression('wheelbase'), {'$sweep': 't'}]}}
        self.assertEqual(self.origins([sum_, 0, 0])[2], [3.7, 0, 0])

    def test_faults_are_reported_at_the_marker_before_any_native_work(self):
        fault = self.fault('EXPR_UNKNOWN_NAME', expression('model.mid + missing'))
        self.assertEqual(fault.location, '$/nodes/1/options/origin')
        self.assertEqual((fault.phase, fault.observed['position'], fault.observed['length']), ('input', 12, 7))
        self.assertIn('model', fault.observed['available']['definitions'])
        self.assertEqual(self.fault('EXPR_SYNTAX', expression('model.mid +')).observed['position'], 11)
        self.fault('EXPR_TYPE', expression('settings'))
        self.fault('EXPR_AMBIGUOUS_NAME', expression('vector(zoom, 0, 0)'), definitions={'zoom': 1})
        self.assertEqual(self.origins(expression('vector(settings.zoom, 0, 0)'), definitions={'zoom': 1})[0],
                         [0.52, 0, 0])
        cycle = {'a': expression('b + 1'), 'b': expression('a + 1')}
        self.assertIn('definitions.a', self.fault('EXPR_CYCLE', expression('vector(a, 0, 0)'),
                                                  definitions=cycle).observed['chain'])
        self.fault('EXPR_INVALID_BOX', expression('intersect(body, box()).mid'))
        self.fault('INVALID_EXPRESSION', {'$expr': 'model.mid', 'extra': 1})

    def test_late_expression_in_a_constructor_option_is_rejected(self):
        value = document([0, 0, 0])
        value['nodes'][0] = {'id': 'source', 'filter': 'foam', 'options': {'file': expression('t > 0 ? "a" : "b"')}}
        with self.assertRaises(SchemaxisError) as caught:
            DefinitionGraph(value, catalogue())
        fault = caught.exception.fault
        self.assertEqual((fault.code, fault.observed['phase'], fault.observed['chain']),
                         ('DYNAMIC_CONSTRUCTOR', 'visit', ['t']))

    def test_constant_expressions_set_the_ends_of_an_analytic(self):
        value = document([0, 0, 0])
        value['nodes'].append({'id': 'ball', 'filter': 'sphere', 'options': {'radius': {'$analytic': {
            'type': 'linear', 'start': expression('model.deltaY / 2'), 'end': expression('model.deltaX'),
            'count': 3}}}})
        graph = DefinitionGraph(value, catalogue())
        self.assertEqual([item['member0'] for item in graph.axes['analytic0']], [1.0, 2.75, 4.5])

    def test_documents_without_string_expressions_are_unchanged(self):
        value = document({'$sweep': 't', 'path': []})
        del value['definitions'], value['sweeps'][0]
        value['sweeps'] = [{'name': 't', 'values': [[0, 0, 0], [1, 0, 0]]}]
        graph = DefinitionGraph(value, catalogue())
        self.assertEqual(graph.nodes['slice']['options']['origin'], {'$sweep': 't', 'path': []})


class OtherDocuments(unittest.TestCase):
    def test_constant_expressions_resolve_in_any_adaptor_document(self):
        from schemaxis.documents import resolve_document
        authored = {'dimensions': {'width': 4}, 'definitions': {'plate': {'$expr': 'boxAt(vector(0, 0, 0), '
                    'vector(width, 2, 0))'}}, 'parts': [{'size': {'$expr': 'plate.size'}, 'area': {'$value':
                    'vectorLength', 'args': {'vector': {'$expr': 'plate.size'}}}, 'late': {'$expr': 'time * 2'}}]}
        resolved, evidence = resolve_document(authored)
        self.assertEqual(resolved['parts'][0]['size'], [4, 2, 0])
        self.assertAlmostEqual(resolved['parts'][0]['area'], 20 ** 0.5)
        self.assertEqual(resolved['parts'][0]['late'], {'$expr': 'time * 2'})
        self.assertIn({'location': '$/parts/0/size', 'expression': 'plate.size', 'effectiveValue': [4, 2, 0]},
                      evidence)
        with self.assertRaises(SchemaxisError) as caught:
            resolve_document({'parts': [{'$expr': 'missing + 1'}]})
        self.assertEqual((caught.exception.fault.code, caught.exception.fault.location),
                         ('EXPR_UNKNOWN_NAME', '$/parts/0'))


def workflow(radius):
    return {'version': 'schemaxis.workflow/1', 'settings': {'gap': 7}, 'operations': [{'id': 'one', 'document': {
        'version': 'schemaxis/1', 'settings': {'gap': 2},
        'nodes': [{'id': 'ball', 'filter': 'sphere', 'options': {'radius': radius}}]}}]}


def outline(bounds, **sections):
    return {'version': 'schemaxis/1', **sections,
            'nodes': [{'id': 'outline', 'filter': 'pvOutlineSource', 'options': {'Bounds': bounds}}]}


class Boundaries(unittest.TestCase):
    def radius(self, value):
        from schemaxis.workflow import validate
        return validate(workflow(value))[0]['document']['nodes'][0]['options']['radius']

    def code(self, action, *arguments):
        with self.assertRaises(SchemaxisError) as caught:
            action(*arguments)
        return caught.exception.fault

    def test_an_operation_resolves_names_in_its_own_document(self):
        self.assertEqual(self.radius(expression('gap + 1')), 3)
        self.assertEqual(self.radius(expression('workflow.settings.gap + gap')), 9)
        self.assertEqual(self.radius(expression('workflow.settings.gap')), 7)
        fault = self.code(self.radius, expression('workflow.settings.missing'))
        self.assertEqual((fault.code, fault.location), ('EXPR_UNKNOWN_NAME', '$/operations/0/document/nodes/0/options/radius'))

    def test_functions_and_expressions_mix_in_either_order(self):
        from schemaxis.documents import resolve_document
        authored = {'definitions': {'v': {'$value': 'directionVector', 'args': {
            'direction': 'x+', 'length': expression('2')}}}, 'out': expression('v.x')}
        self.assertEqual(resolve_document(authored)[0]['out'], 2)
        self.assertEqual(self.radius({'$value': 'vectorLength', 'args': {'vector': expression('vector(1, 2, 2)')}}), 3)

    def test_an_invalid_box_from_an_expression_is_not_an_option_value(self):
        fault = self.code(DefinitionGraph, outline(expression('box()')), catalogue())
        self.assertEqual((fault.code, fault.location, fault.observed['source']),
                         ('EXPR_INVALID_BOX', '$/nodes/0/options/Bounds', 'box()'))
        held = outline(expression('union(empty, box(0, 1, 0, 1, 0, 1))'), definitions={'empty': expression('box()')})
        graph = DefinitionGraph(held, catalogue())
        self.assertEqual(graph.nodes['outline']['options']['Bounds'], [0, 1, 0, 1, 0, 1])
        self.assertEqual(graph.document['definitions']['empty'], {'min': [1, 1, 1], 'max': [-1, -1, -1]})
        late = outline(expression('t > 0 ? box() : box(0, 1, 0, 1, 0, 1)'), sweeps=[{'name': 't', 'values': [0, 1]}])
        fault = self.code(DefinitionGraph, late, catalogue())
        self.assertEqual((fault.code, fault.observed['source']), ('EXPR_INVALID_BOX', 't > 0 ? box() : box(0, 1, 0, 1, 0, 1)'))

    def test_a_series_axis_is_a_scalar_name(self):
        authored = {'version': 'schemaxis/1', 'sweeps': [{'name': 't', 'series': {'start': 1, 'end': 3, 'count': 3}}],
                    'nodes': [{'id': 'ball', 'filter': 'sphere', 'options': {'radius': expression('t + 1')}}]}
        self.assertEqual(DefinitionGraph(authored, catalogue()).select(['ball']).count, 3)

    def test_an_axis_declared_with_constant_expressions_keeps_its_type(self):
        cases = [({'series': {'start': expression('1'), 'end': 3, 'count': 3}}, 3),
                 ({'series': {'start': expression('first'), 'end': expression('first + 2'), 'count': 3}}, 3),
                 ({'values': [expression('first'), 2]}, 2)]
        for declared, count in cases:
            authored = {'version': 'schemaxis/1', 'definitions': {'first': 1}, 'sweeps': [{'name': 't', **declared}],
                        'nodes': [{'id': 'ball', 'filter': 'sphere', 'options': {'radius': expression('t + 1')}}]}
            self.assertEqual(DefinitionGraph(authored, catalogue()).select(['ball']).count, count, declared)
        authored['sweeps'] = [{'name': 't', 'values': [expression('t'), 2]}]
        self.assertEqual(self.code(DefinitionGraph, authored, catalogue()).code, 'EXPR_CYCLE')

    def test_legacy_bounds_functions_take_either_box_form(self):
        from schemaxis.documents import resolve_document
        box = {'min': [0, 0, 0], 'max': [2, 4, 6]}
        for name, key, expected in [('boundsCentre', 'bounds', [1, 2, 3]), ('boundsFromExtents', 'extents', box)]:
            for given in (box, [0, 2, 0, 4, 0, 6]):
                authored = {'out': {'$value': name, 'args': {key: given}}}
                self.assertEqual(resolve_document(authored)[0]['out'], expected, (name, given))
        flat = {'out': {'$value': 'boundsCentre', 'args': {'bounds': [0, 2, 0, 4, 1, 1]}}}
        self.assertEqual(resolve_document(flat)[0]['out'], [1, 2, 1])
        reversed_box = {'out': {'$value': 'boundsCentre', 'args': {'bounds': [2, 0, 0, 4, 0, 6]}}}
        self.assertEqual(self.code(resolve_document, reversed_box).code, 'FUNCTION_FAILED')

    def test_the_catalogue_cannot_take_a_language_name(self):
        from schemaxis.functions import FUNCTIONS, FunctionRegistry
        for name in ('vector', 'if', 'min', 'grad', 'lookup'):
            fault = self.code(FunctionRegistry().register, name, {}, {'type': 'number'}, float)
            self.assertEqual(fault.code, 'RESERVED_FUNCTION', name)
        FunctionRegistry().register('boundsVolume', {}, {'type': 'number'}, float)
        self.assertNotIn('grad', FUNCTIONS.entries)


if __name__ == '__main__':
    unittest.main()


class Provider(Backend):
    """A backend with an extents provider: port 0 has bounds, port 1 is empty and port 2 is a table."""

    def extents(self, handle):
        return [{'status': 'ok', 'bounds': [0, 4.5, -0.9, 0.9, 0.2, 1.4]}, {'status': 'empty'},
                {'status': 'notSpatial'}]


class Scheduled(unittest.TestCase):
    """Sweeps, extents and analytics whose ends are only known at the visit (specification 6.6, 6.9, 13.2)."""

    def run_origin(self, origin, backend=None, **definitions):
        graph = DefinitionGraph(document(origin, definitions=definitions), catalogue())
        active = RuntimeClosure(graph, backend or Provider())
        selection = active.activate(['slice'])
        return selection, [active.apply(visit)['effective']['slice']['origin'] for visit in selection.visits()]

    def fault(self, code, origin, **definitions):
        with self.assertRaises(SchemaxisError) as caught:
            self.run_origin(origin, **definitions)
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def close(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for a, e in zip(actual, expected):
            self.assertAlmostEqual(a, e, places=12)

    def test_two_sweeps_are_two_axes_and_the_first_written_is_fastest(self):
        selection, origins = self.run_origin(expression('vector(sweep(0, 1, 2), sweep(10, 20, 2), 0)'))
        self.assertEqual(selection.axes, ('sweep:/nodes/1/options/origin/$expr#0',
                                          'sweep:/nodes/1/options/origin/$expr#1'))
        self.assertEqual(origins, [[0, 10, 0], [1, 10, 0], [0, 20, 0], [1, 20, 0]])
        self.assertEqual(selection.count, 4)

    def test_sweeps_with_one_sync_name_advance_together(self):
        selection, origins = self.run_origin(expression("vector(sweep(0, 1, 3, 's'), sweep(10, 30, 3, 's'), 0)"))
        self.assertEqual(selection.axes, ('sync:s',))
        self.assertEqual(origins, [[0, 10, 0], [0.5, 20, 0], [1, 30, 0]])
        fault = self.fault('ANALYTIC_LENGTH_MISMATCH',
                           expression("vector(sweep(0, 1, 3, 's'), sweep(10, 30, 4, 's'), 0)"))
        self.assertEqual((fault.observed['expected'], fault.observed['actual']), (3, 4))

    def test_a_sweep_in_an_entry_is_one_axis_for_every_reader(self):
        selection, origins = self.run_origin(expression('vector(y, 2 * y, 0)'), y=expression('sweep(-1, 1, 3)'))
        self.assertEqual(selection.axes, ('sweep:/definitions/y/$expr#0',))
        self.assertEqual(origins, [[-1, -2, 0], [0, 0, 0], [1, 2, 0]])

    def test_one_position_is_the_midpoint_and_an_unread_sweep_adds_no_visits(self):
        self.assertEqual(self.run_origin(expression('vector(sweep(0, 10, 1), 0, 0)'))[1], [[5, 0, 0]])
        selection, origins = self.run_origin([0, 0, 0], y=expression('sweep(-1, 1, 3)'))
        self.assertEqual((selection.axes, selection.count, origins), ((), 1, [[0, 0, 0]]))

    def test_the_ends_of_a_sweep_may_be_observed(self):
        selection, origins = self.run_origin(
            expression('vector(car.mid.x, sweep(car.min.y, car.max.y, 5), car.max.z)'),
            car=expression('extents(source)'))
        self.assertEqual(selection.count, 5)
        for origin, y in zip(origins, [-0.9, -0.45, 0, 0.45, 0.9]):
            for actual, expected in zip(origin, [2.25, y, 1.4]):
                self.assertAlmostEqual(actual, expected, places=12)
        graph = selection.master
        self.assertEqual(graph.nodes['slice']['dependencies'], ['source'])

    def test_the_count_of_a_sweep_is_a_constant_whole_number(self):
        self.assertEqual(self.run_origin(expression('vector(sweep(0, 1, wheelbase > 2 ? 2 : 3), 0, 0)'))[0].count, 2)
        for text in ('sweep(0, 1, t)', 'sweep(0, 1, 0)', 'sweep(0, 1, 2.5)', 'sweep(0, 1, 10001)',
                     'sweep(0, 1, extents(source).min.x)'):
            fault = self.fault('SWEEP_COUNT', expression(f'vector({text}, 0, 0)'))
            self.assertEqual((fault.observed['limit'], fault.phase), (10000, 'input'))
        self.fault('EXPR_TYPE', expression('vector(sweep(0, vector(1, 1, 1), 2), 0, 0)'))
        self.fault('EXPR_ARGUMENTS', expression('vector(sweep(0, 1), 0, 0)'))
        self.fault('EXPR_ARGUMENTS', expression('vector(sweep(0, 1, 2, zoom), 0, 0)'))
        self.fault('EXPR_UNKNOWN_PROPERTY', expression('vector(wheelbase.sweep(1, 2), 0, 0)'))

    def test_generated_axes_follow_the_order_of_first_use(self):
        linear = {'$analytic': {'type': 'linear', 'start': 0, 'end': 1, 'count': 2}}
        selection, origins = self.run_origin([linear, expression('sweep(0, 5, 3)'), copy.deepcopy(linear)])
        self.assertEqual(selection.axes, ('analytic0', 'sweep:/nodes/1/options/origin/1/$expr#0', 'analytic1'))
        self.assertEqual(origins[:4], [[0, 0, 0], [1, 0, 0], [0, 2.5, 0], [1, 2.5, 0]])
        selection, _ = self.run_origin([expression('sweep(0, 5, 3)'), linear, 0])
        self.assertEqual(selection.axes, ('sweep:/nodes/1/options/origin/0/$expr#0', 'analytic0'))
        selection, _ = self.run_origin([expression('t'), expression('sweep(0, 5, 3)'), 0])
        self.assertEqual(selection.axes, ('t', 'sweep:/nodes/1/options/origin/1/$expr#0'))

    def test_a_planned_document_plans_again_to_the_same_schedule(self):
        linear = {'$analytic': {'type': 'linear', 'start': 0, 'end': 1, 'count': 2}}
        first = DefinitionGraph(document([expression('sweep(0, 5, 3)'), linear, expression('y')],
                                         definitions={'y': expression('sweep(extents(source).min.x, 1, 2)')}),
                                catalogue())
        again = DefinitionGraph(first.document, catalogue())
        self.assertEqual(first.to_dict()['digest'], again.to_dict()['digest'])
        self.assertEqual(first.select(['slice']).axes, again.select(['slice']).axes)
        self.assertEqual(first.select(['slice']).axes, ('sweep:/nodes/1/options/origin/0/$expr#0', 'analytic0',
                                                       'sweep:/definitions/y/$expr#0'))

    def test_an_analytic_with_late_ends_behaves_as_a_sweep(self):
        late = {'$analytic': {'type': 'linear', 'start': expression('extents(source).min'),
                              'end': expression('extents(source).max'), 'count': 3}}
        selection, origins = self.run_origin(late)
        self.assertEqual(selection.axes, ('sweep:/nodes/1/options/origin/$analytic#0',))
        self.assertEqual(origins[0], [0, -0.9, 0.2])
        self.assertEqual(origins[2], [4.5, 0.9, 1.4])
        synced = [{'$analytic': {'type': 'linear', 'start': 0, 'end': 1, 'count': 3, 'sync': 's'}},
                  expression("sweep(extents(source).min.y, 5, 3, 's')"), 0]
        selection, origins = self.run_origin(synced)
        self.assertEqual(selection.axes, ('sync:s',))
        self.assertEqual([origin[0] for origin in origins], [0, 0.5, 1])
        single = {'$analytic': {'type': 'linear', 'start': expression('vector(t, 0, 0)'),
                                'end': [1, 0, 0], 'count': 1}}
        self.fault('INVALID_ANALYTIC', single)

    def test_extents_reads_each_output_port(self):
        self.close(self.run_origin(expression('extents(source).mid'))[1][0], [2.25, 0, 0.8])
        self.assertEqual(self.run_origin(expression('extents(source, 1).valid ? model.max : model.min'))[1],
                         [[0, -1, 0]])
        fault = self.fault('EXPR_INVALID_BOX', expression('extents(source, 1).mid'))
        self.assertEqual(fault.observed['source'], 'extents(source, 1)')
        fault = self.fault('EXTENTS_UNAVAILABLE', expression('extents(source, 2).mid'))
        self.assertEqual((fault.observed['node'], fault.observed['port']), ('source', 2))
        fault = self.fault('INVALID_OUTPUT_PORT', expression('extents(source, 3).mid'))
        self.assertEqual(fault.observed['available'], 3)
        fault = self.fault('UNKNOWN_NODE', expression('extents(nothing).mid'))
        self.assertEqual((fault.phase, fault.observed['position'], fault.observed['length']), ('input', 8, 7))
        self.fault('PIPELINE_CYCLE', expression('extents(slice).mid'))
        self.fault('EXPR_ARGUMENTS', expression('extents(model.mid).mid'))
        self.fault('EXPR_ARGUMENTS', expression('extents(source, t).mid'))
        self.fault('EXPR_UNKNOWN_PROPERTY', expression('source.extents().mid'), source=1)

    def test_extents_equals_the_observed_bounds_when_no_provider_answers(self):
        self.assertEqual(self.run_origin(expression('extents(source).mid'), backend=Backend())[1],
                         self.run_origin(expression('box(obs.bounds).mid'), backend=Backend())[1])

    def test_data_extents_is_the_union_of_what_the_readers_load(self):
        value = document(expression('dataExtents.valid ? dataExtents.mid : vector(9, 9, 9)'))
        self.assertEqual(self.run_origin(value['nodes'][1]['options']['origin'])[1], [[9, 9, 9]])
        value['nodes'].insert(0, {'id': 'reader', 'filter': 'foam', 'options': {'file': 'case.foam'}})
        graph = DefinitionGraph(value, catalogue())
        self.assertEqual(graph.nodes['slice']['dependencies'], ['reader', 'source'])
        active = RuntimeClosure(graph, Provider())
        applied = active.apply(next(active.activate(['slice']).visits()))
        self.close(applied['effective']['slice']['origin'], [2.25, 0, 0.8])
        self.assertEqual(applied['observations']['reader']['extents'],
                         [[0, 4.5, -0.9, 0.9, 0.2, 1.4], [1, -1, 1, -1, 1, -1], None])

    def test_an_adaptor_without_the_capability_refuses_extents_at_validation(self):
        for text in ('extents(source).mid', 'dataExtents.mid'):
            with self.assertRaises(SchemaxisError) as caught:
                DefinitionGraph(document(expression(text)), catalogue(), adaptor='gmsh')
            self.assertEqual((caught.exception.fault.code, caught.exception.fault.phase,
                              caught.exception.fault.observed['adaptor']), ('EXTENTS_UNSUPPORTED', 'input', 'gmsh'))


class Misuse(unittest.TestCase):
    """A value that is known too late for its destination names the variable and the reason (8.2)."""

    def refused(self, value):
        with self.assertRaises(SchemaxisError) as caught:
            DefinitionGraph(value, catalogue())
        return caught.exception.fault

    def reader(self, file, **definitions):
        value = document([0, 0, 0], definitions=definitions)
        value['nodes'].insert(0, {'id': 'reader', 'filter': 'foam', 'options': {'file': file}})
        return value

    def test_a_constructor_option_names_the_entry_and_the_chain_that_makes_it_late(self):
        fault = self.refused(self.reader(expression('cells > 1 ? "a" : "b"'), cells=expression('seen.span'),
                                         seen=expression('extents(source)')))
        self.assertEqual((fault.code, fault.location, fault.phase), ('DYNAMIC_CONSTRUCTOR', 'reader.file', 'input'))
        self.assertEqual(fault.observed, {'variable': 'cells', 'phase': 'observed', 'accepted': ['constant'],
                                          'chain': ['cells', 'seen', 'extents(source)'],
                                          'destination': 'constructor option reader.file'})
        self.assertEqual(fault.message, '`cells` cannot be used in constructor option reader.file: it is only '
                         'known after node `source` has been updated (cells → seen → extents(source))')

    def test_each_kind_of_late_value_gives_its_own_reason(self):
        cases = [('sweep(0, 1, 2) > 0 ? "a" : "b"', 'sweep(0, 1, 2)', 'it changes at each visit'),
                 ('time > 0 ? "a" : "b"', 'time', 'it changes with time'),
                 ('box(obs.bounds).valid ? "a" : "b"', 'obs', 'node `source` has been updated')]
        for text, variable, reason in cases:
            fault = self.refused(self.reader(expression(text)))
            self.assertEqual((fault.code, fault.observed['variable']), ('DYNAMIC_CONSTRUCTOR', variable))
            self.assertIn(reason, fault.message)

    def test_axes_times_and_limits_are_fixed_at_planning(self):
        for key, value, pointer in (('sweeps', [{'name': 't', 'values': [0, expression('time')]}], '/sweeps/0/values/1'),
                                    ('times', [0, expression('t')], '/times/1'),
                                    ('maxStates', expression('t > 0 ? 10 : 20'), '/maxStates')):
            draft = document([0, 0, 0])
            draft[key] = value
            fault = self.refused(draft)
            self.assertEqual((fault.code, fault.location, fault.observed['accepted']),
                             ('EXPR_PHASE', '$' + pointer, ['constant']))
            self.assertIn('fixed when the document is planned', fault.message)
        fault = self.refused(document({'$analytic': {'type': 'linear', 'start': [0, 0, 0], 'end': [1, 1, 1],
                                                     'count': expression('t > 0 ? 2 : 3')}}))
        self.assertEqual((fault.code, fault.location), ('EXPR_PHASE', '$/nodes/1/options/origin/$analytic/count'))

    def test_a_port_beyond_those_a_declaration_fixes_is_refused_at_validation(self):
        value = document(expression('extents(counts, 2).valid ? model.min : model.max'))
        value['nodes'].insert(0, {'id': 'counts', 'filter': 'pvDescriptiveStatistics', 'inputs': {'Input': 'late'}})
        value['nodes'].insert(0, {'id': 'late', 'filter': 'wavelet'})
        fault = self.refused(value)
        self.assertEqual((fault.code, fault.phase, fault.observed['available']), ('INVALID_OUTPUT_PORT', 'input', 2))


class Envelope(unittest.TestCase):
    """An operation is planned on its own, so the envelope entries its late values read travel with it."""

    def radii(self, radius, definitions=None, times=None):
        from schemaxis.workflow import validate
        operation = {'version': 'schemaxis/1', 'sweeps': [{'name': 't', 'values': [0, 1]}],
                     'nodes': [{'id': 'ball', 'filter': 'sphere', 'options': {'radius': radius}}]}
        if definitions:
            operation['definitions'] = definitions
        if times:
            operation['times'] = times
        workflow = {'version': 'schemaxis.workflow/1', 'settings': {'gap': 7}, 'dimensions': {'depth': 3},
                    'definitions': {'base': expression('gap + depth')},
                    'operations': [{'id': 'one', 'document': operation}]}
        planned = validate(workflow)[0]['document']
        graph = DefinitionGraph(planned, catalogue())
        self.assertEqual(DefinitionGraph(graph.document, catalogue()).to_dict()['digest'], graph.to_dict()['digest'])
        active = RuntimeClosure(graph, Backend())
        visits = active.activate(['ball']).visits()
        return planned.get('%%workflowScope%%'), [active.apply(visit)['effective']['ball']['radius'] for visit in visits]

    def test_a_late_value_reads_each_section_of_the_envelope_at_the_visit(self):
        self.assertEqual(self.radii(expression('workflow.settings.gap + t')), ({'settings': {'gap': 7}}, [7, 8]))
        self.assertEqual(self.radii(expression('workflow.dimensions.depth + t')),
                         ({'dimensions': {'depth': 3}}, [3, 4]))
        carried, radii = self.radii(expression('workflow.definitions.base + t'))
        self.assertEqual((carried['definitions'], radii), ({'base': 10}, [10, 11]))

    def test_a_value_made_late_by_time_reads_the_envelope(self):
        self.assertEqual(self.radii(expression('workflow.settings.gap + time'), times=[1.5, 2.5])[1], [8.5, 9.5])

    def test_a_late_local_definition_reads_the_envelope_whether_or_not_it_is_used(self):
        wide = {'wide': expression('workflow.settings.gap + t')}
        self.assertEqual(self.radii(expression('wide'), definitions=wide), ({'settings': {'gap': 7}}, [7, 8]))
        self.assertEqual(self.radii(2, definitions=wide), ({'settings': {'gap': 7}}, [2]))

    def test_a_late_read_in_a_branch_that_is_not_chosen_still_plans(self):
        self.assertEqual(self.radii(expression('if(false, workflow.settings.gap + t, 1)')),
                         ({'settings': {'gap': 7}}, [1, 1]))

    def test_a_constant_read_needs_nothing_carried(self):
        self.assertEqual(self.radii(expression('workflow.settings.gap + 1')), (None, [8]))


class Studies(unittest.TestCase):
    """Adaptors without a scheduled graph: the common study evaluates what waits only for axes."""

    def visits(self, document):
        from schemaxis.adaptor_runtime import InputProgram
        program = InputProgram({'version': 'schemaxis.gmsh/1', **document}, {})
        return program, [{key: value for key, value in visit['document'].items() if key != 'version'}
                         for visit in program.visits()]

    def refused(self, document):
        with self.assertRaises(SchemaxisError) as caught:
            self.visits(document)
        return caught.exception.fault

    def test_an_expression_over_an_axis_is_a_value_at_each_visit(self):
        _, visits = self.visits({'sweeps': [{'name': 't', 'values': [1, 2]}], 'settings': {'k': 3},
                                 'x': expression('t + k'), 'y': {'$sweep': 't'}, 'z': expression('k * 2')})
        self.assertEqual(visits, [{'x': 4, 'y': 1, 'z': 6}, {'x': 5, 'y': 2, 'z': 6}])

    def test_a_sweep_schedules_visits_and_shares_a_sync_name_with_an_analytic(self):
        program, visits = self.visits({
            'settings': {'k': 3},
            'definitions': {'s': expression('sweep(0, k, 3)'), 'unread': expression('sweep(0, 1, 7)')},
            'x': expression('s * 2'),
            'y': [expression("sweep(0, 1, 2, 'p')"),
                  {'$analytic': {'type': 'linear', 'start': 5, 'end': 6, 'count': 2, 'sync': 'p'}}]})
        self.assertEqual(program.groups, {'/sweep:/definitions/s/$expr#0': 3, 'sync:p': 2})
        self.assertEqual([visit['x'] for visit in visits], [0, 3, 6, 0, 3, 6])
        self.assertEqual([visit['y'] for visit in visits], [[0, 5]] * 3 + [[1, 6]] * 3)

    def test_what_is_still_late_is_refused_with_its_reason(self):
        fault = self.refused({'x': expression('time + 1')})
        self.assertEqual((fault.code, fault.location, fault.observed['chain']), ('EXPR_PHASE', '$/x', ['time']))
        self.assertIn('fixed before it runs', fault.message)
        for text in ('dataExtents.span', 'extents(a).span'):
            fault = self.refused({'x': expression(text)})
            self.assertEqual((fault.code, fault.phase), ('EXTENTS_UNSUPPORTED', 'input'))

    def test_a_carried_envelope_entry_is_read_and_then_removed(self):
        _, visits = self.visits({'%%workflowScope%%': {'settings': {'gap': 7}},
                                 'sweeps': [{'name': 't', 'values': [1, 2]}],
                                 'x': expression('workflow.settings.gap + t')})
        self.assertEqual(visits, [{'x': 8}, {'x': 9}])


def sphere(options=None, definitions=None):
    return {'version': 'schemaxis/1', 'nodes': [{'id': 'ball', 'filter': 'sphere', 'options': options or {}}],
            'definitions': definitions or {}, 'scenes': [{'id': 'view', 'geometry': ['ball']}]}


def linear(start=1, end=2, count=3, sync=None):
    specification = {'type': 'linear', 'start': start, 'end': end, 'count': count}
    if sync is not None:
        specification['sync'] = sync
    return {'$analytic': specification}


class StudyRoute(unittest.TestCase):
    """A document that a named analytic sends through the common study keeps the rules of its graph.

    The study owns every step: a graph is given its position on each sweep and steps only time.
    """

    def refused(self, value):
        from schemaxis.adaptors import registry
        with self.assertRaises(SchemaxisError) as caught:
            registry.plan(value)
        return caught.exception.fault

    def test_a_study_does_not_admit_an_axis_into_a_constructor_or_the_times(self):
        from schemaxis.adaptors import registry
        value = sphere(definitions={'unused': {'$analytic': {'type': 'values', 'values': [1, 2]}}})
        value['sweeps'] = [{'name': 't', 'values': [0, 1]}]
        value['nodes'] = [{'id': 'ball', 'filter': 'foam',
                           'options': {'file': expression("t > 0 ? 'a.foam' : 'b.foam'")}}]
        fault = self.refused(value)
        self.assertEqual((fault.code, fault.location, fault.observed['chain']),
                         ('DYNAMIC_CONSTRUCTOR', 'ball.file', ['t']))
        value['nodes'] = sphere()['nodes']
        value['times'] = [expression('t')]
        fault = self.refused(value)
        self.assertEqual((fault.code, fault.location, fault.observed['chain']), ('EXPR_PHASE', '$/times/0', ['t']))
        value['times'] = [0.0]
        value['nodes'][0]['options'] = {'radius': expression('t + 1')}
        registry.plan(value)

    def test_a_named_analytic_with_observed_ends_is_stepped_by_the_study_and_evaluated_by_the_graph(self):
        from schemaxis.adaptor_runtime import InputProgram
        from schemaxis.adaptors import registry
        value = sphere({'radius': expression('r')}, {'r': linear(expression('extents(source).deltaX'), 2)})
        value['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
        program = InputProgram(value, registry.resolve(value)[1])
        self.assertEqual((program.groups, program.bindings),
                         ({'member:/definitions/r': 3}, {'/definitions/r': 'member:/definitions/r'}))
        radii = []
        for position, visit in enumerate(program.visits()):
            self.assertEqual((visit['document']['%%studyPositions%%'], visit['document']['%%studyVisits%%']),
                             ({'sweep:/definitions/r/$analytic#0': position}, 3))
            graph = DefinitionGraph(visit['document'], catalogue())
            selected = graph.select(['ball'])
            self.assertEqual((selected.axes, selected.count), (('sweep:/definitions/r/$analytic#0',), 1))
            backend = Backend()
            active = RuntimeClosure(graph, backend)
            for state in active.activate(['ball']).visits():
                active.apply(state)
            radii.extend(values['radius'] for kind, node, values in backend.events
                         if kind == 'set' and node == 'ball' and 'radius' in values)
        self.assertEqual(radii, [4.5, 3.25, 2])
        registry.plan(value)

    def test_the_graph_reads_the_axis_value_the_study_chose(self):
        from schemaxis.adaptor_runtime import InputProgram
        from schemaxis.adaptors import registry
        value = sphere({'radius': expression('t + extents(source).deltaX')},
                       {'unused': {'$analytic': {'type': 'values', 'values': [1, 2]}},
                        'aside': expression('t * extents(source).deltaX')})
        value['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
        value['sweeps'] = [{'name': 't', 'values': [10, 20]}]
        radii = []
        for visit in InputProgram(value, registry.resolve(value)[1]).visits():
            graph = DefinitionGraph(visit['document'], catalogue())
            backend = Backend()
            active = RuntimeClosure(graph, backend)
            states = [active.apply(state) for state in active.activate(['ball']).visits()]
            self.assertEqual(len(states), 1)
            radii.extend(values['radius'] for kind, node, values in backend.events
                         if kind == 'set' and node == 'ball' and 'radius' in values)
        self.assertEqual(radii, [14.5, 24.5, 14.5, 24.5])

    def test_a_constant_analytic_keeps_the_axis_of_a_late_one_with_its_sync_name(self):
        value = sphere({'centre': linear(expression('vector(time, 0, 0)'), [2, 0, 0], 3, 's'),
                        'radius': linear(1, 2, 3, 's')})
        graph = DefinitionGraph(value, catalogue())
        selected = graph.select(['ball'])
        self.assertEqual((selected.axes, selected.count), (('sync:s',), 3))
        backend = Backend()
        active = RuntimeClosure(graph, backend)
        for visit in active.activate(['ball']).visits():
            active.apply(visit)
        self.assertEqual([(values['centre'], values['radius']) for kind, node, values in backend.events
                          if kind == 'set' and 'radius' in values],
                         [([0, 0, 0], 1), ([1, 0, 0], 1.5), ([2, 0, 0], 2)])

    def stepped(self, value, declared=None):
        from schemaxis.adaptor_runtime import InputProgram
        from schemaxis.adaptors import registry
        value['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
        if declared:
            value['sweeps'] = declared
        registry.plan(value)
        program = InputProgram(value, registry.resolve(value)[1])
        self.assertTrue(program.common)
        pairs = []
        for visit in program.visits():
            backend = Backend()
            active = RuntimeClosure(DefinitionGraph(visit['document'], catalogue()), backend)
            for state in active.activate(['ball']).visits():
                active.apply(state)
                last = {}
                for kind, node, values in backend.events:
                    if kind == 'set' and node == 'ball':
                        last.update(values)
                pairs.append((last['centre'][0], last['radius']))
        return program, pairs

    def test_everything_with_one_sync_name_steps_together_when_one_member_waits_for_data(self):
        late = linear(expression('extents(source).deltaX'), 2, 3, 's')
        together = [(10, 4.5), (20, 3.25), (30, 2)]
        cases = {
            'a named constant analytic': sphere({'centre': expression('vector(c, 0, 0)'), 'radius': expression('l')},
                                                {'c': linear(10, 30, 3, 's'), 'l': late}),
            'a sweep in an option': sphere({'centre': expression("vector(sweep(10, 30, 3, 's'), 0, 0)"),
                                            'radius': expression('l')}, {'l': late}),
            'a constant analytic in an option': sphere({'centre': [linear(10, 30, 3, 's'), 0, 0],
                                                        'radius': expression('l')}, {'l': late}),
            'a named sweep': sphere({'centre': expression('vector(c, 0, 0)'), 'radius': expression('l')},
                                    {'c': expression("sweep(10, 30, 3, 's')"), 'l': late}),
            'a sweep with observed ends': sphere(
                {'centre': expression('vector(c, 0, 0)'),
                 'radius': expression("sweep(extents(source).deltaX, 2, 3, 's')")}, {'c': linear(10, 30, 3, 's')})}
        for label, value in cases.items():
            with self.subTest(label):
                program, pairs = self.stepped(value)
                self.assertEqual((program.groups, pairs), ({'sync:s': 3}, together))

    def test_a_declared_sweep_steps_fastest_beside_a_sync_name_with_a_member_that_waits_for_data(self):
        value = sphere({'centre': expression('vector(c + t, 0, 0)'), 'radius': expression('l')},
                       {'c': linear(10, 30, 3, 's'),
                        'l': linear(expression('extents(source).deltaX'), 2, 3, 's')})
        program, pairs = self.stepped(value, [{'name': 't', 'values': [0, 100]}])
        self.assertEqual(program.groups, {'/declared:t': 2, 'sync:s': 3})
        self.assertEqual(pairs, [(10, 4.5), (110, 4.5), (20, 3.25), (120, 3.25), (30, 2), (130, 2)])
        first = next(program.visits())['document']
        self.assertEqual((first['sweeps'], first['%%studyPositions%%'], first['%%studyVisits%%']),
                         ([{'name': 't', 'values': [0]}], {'sync:s': 0}, 6))

    def test_two_sync_names_step_in_the_order_of_first_use_whichever_waits_for_data(self):
        late = linear(expression('extents(source).deltaX'), 2, 2, 'late')
        for label, options, expected in (
                ('the late name first', {'radius': late, 'centre': [linear(10, 30, 3, 'early'), 0, 0]},
                 [(10, 4.5), (10, 2), (20, 4.5), (20, 2), (30, 4.5), (30, 2)]),
                ('the late name second', {'centre': expression("vector(sweep(10, 30, 3, 'early'), 0, 0)"),
                                          'radius': expression("sweep(extents(source).deltaX, 2, 2, 'late')")},
                 [(10, 4.5), (20, 4.5), (30, 4.5), (10, 2), (20, 2), (30, 2)])):
            with self.subTest(label):
                program, pairs = self.stepped(sphere(options, {'unused': linear(1, 1, 1)}))
                self.assertEqual((program.count, pairs), (6, expected))

    def test_a_visit_of_a_study_is_not_planned_again(self):
        from schemaxis.adaptor_runtime import InputProgram
        from schemaxis.adaptors import registry
        value = sphere({'radius': expression('l')}, {'l': linear(expression('extents(source).deltaX'), 2, 3)})
        value['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
        route = registry.resolve(value)[1]
        for visit in InputProgram(value, route).visits():
            again = InputProgram(visit['document'], route)
            self.assertEqual((again.common, again.count, again.first), (False, 1, visit['document']))
            self.assertEqual(registry.plan(visit['document'])['pipeline']['sweeps'],
                             {'sweep:/definitions/l/$analytic#0': [visit['index']]})
        settled = sphere({'radius': expression('t + extents(source).deltaX')}, {'unused': linear(1, 1, 1)})
        settled['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
        settled['sweeps'] = [{'name': 't', 'values': [1]}]
        only = next(InputProgram(settled, route).visits())['document']
        self.assertEqual((only['%%studyPositions%%'], '%%studyVisits%%' in only, InputProgram(only, route).common),
                         ({}, False, False))

    def test_a_named_analytic_read_by_name_and_by_reference_is_one_group_when_it_waits_for_data(self):
        value = sphere({'centre': expression('vector(r, 0, 0)'), 'radius': {'$document': '/definitions/r'}},
                       {'r': linear(expression('extents(source).deltaX'), 2)})
        program, pairs = self.stepped(value)
        self.assertEqual((program.groups, pairs), ({'member:/definitions/r': 3}, [(4.5, 4.5), (3.25, 3.25), (2, 2)]))
        self.assertEqual(next(program.visits())['document']['%%studyPositions%%'],
                         {'sweep:/definitions/r/$analytic#0': 0, 'sweep:/nodes/1/options/radius/$analytic#0': 0})

    def test_ends_the_study_can_compute_leave_a_value_and_a_count_may_be_a_constant_expression(self):
        from schemaxis.adaptor_runtime import InputProgram
        from schemaxis.adaptors import registry
        value = sphere({'radius': linear(expression('k'), 4, 3)}, {'k': 1, 'unused': linear(1, 1, 1)})
        program = InputProgram(value, registry.resolve(value)[1])
        self.assertEqual(program.groups, {'member:/nodes/0/options/radius': 3, 'member:/definitions/unused': 1})
        self.assertEqual([visit['document']['nodes'][0]['options']['radius'] for visit in program.visits()],
                         [1, 2.5, 4])
        counted = sphere({'centre': [1, 0, 0], 'radius': linear(expression('extents(source).deltaX'), 2,
                                                              expression('n'))},
                         {'n': 3, 'unused': linear(1, 1, 1)})
        program, pairs = self.stepped(counted)
        self.assertEqual((program.groups['member:/nodes/1/options/radius'], pairs),
                         (3, [(1, 4.5), (1, 3.25), (1, 2)]))

    def test_a_position_outside_its_sweep_is_refused_by_the_graph(self):
        value = sphere({'radius': expression('sweep(1, 2, 3)')})
        axis = 'sweep:/nodes/0/options/radius/$expr#0'
        chosen = DefinitionGraph({**value, '%%studyPositions%%': {axis: 2}}, catalogue())
        self.assertEqual((chosen.select(['ball']).count, chosen.document['%%studyPositions%%']), (1, {axis: 2}))
        for positions in ({axis: 3}, {axis: -1}, {axis: 1.0}, {axis: True}, [0]):
            with self.subTest(positions=positions):
                with self.assertRaises(SchemaxisError) as caught:
                    DefinitionGraph({**value, '%%studyPositions%%': positions}, catalogue())
                self.assertEqual(caught.exception.fault.code, 'INVALID_SELECTION')

    def test_a_sync_name_with_no_member_waiting_for_data_stays_with_the_study(self):
        value = sphere({'centre': expression("vector(sweep(10, 30, 3, 's'), 0, 0)"), 'radius': expression('c')},
                       {'c': linear(1, 2, 3, 's')})
        program, pairs = self.stepped(value)
        self.assertEqual((program.groups, pairs), ({'sync:s': 3}, [(10, 1), (20, 1.5), (30, 2)]))

    def test_synchronised_members_of_unequal_count_are_refused_when_one_waits_for_data(self):
        value = sphere({'centre': expression('vector(c, 0, 0)'), 'radius': expression('l')},
                       {'c': linear(10, 30, 4, 's'), 'l': linear(expression('extents(source).deltaX'), 2, 3, 's')})
        value['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
        self.assertEqual(self.refused(value).code, 'ANALYTIC_LENGTH_MISMATCH')

    def test_a_named_analytic_read_by_an_expression_is_one_group_of_the_study(self):
        from schemaxis.adaptor_runtime import InputProgram
        from schemaxis.adaptors import registry
        value = sphere({'centre': expression('vector(a, b, 0)'), 'radius': expression('a')},
                       {'a': linear(1, 3, 3), 'b': linear(10, 30, 3)})
        program = InputProgram(value, registry.resolve(value)[1])
        self.assertEqual(program.groups, {'member:/definitions/a': 3, 'member:/definitions/b': 3})
        options = [visit['document']['nodes'][0]['options'] for visit in program.visits()]
        self.assertEqual([(item['centre'][0], item['centre'][1], item['radius']) for item in options],
                         [(a, b, a) for b in (10, 20, 30) for a in (1, 2, 3)])
        late = sphere({'centre': expression('vector(c, 0, 0)'), 'radius': expression('l')},
                      {'c': linear(10, 30, 3), 'l': linear(expression('extents(source).deltaX'), 2, 3)})
        program, pairs = self.stepped(late)
        self.assertEqual(program.groups, {'member:/definitions/c': 3, 'member:/definitions/l': 3})
        self.assertEqual(pairs, [(centre, radius) for radius in (4.5, 3.25, 2) for centre in (10, 20, 30)])

    def test_a_sweep_written_inside_an_end_of_a_named_analytic_is_scheduled_from_that_end(self):
        options = {'centre': expression('vector(c, 0, 0)'), 'radius': expression('l')}
        late = linear(expression('extents(source).deltaX'), 2, 3, 's')
        named = sphere(dict(options), {'k': expression("sweep(10, 30, 3, 's')"),
                                       'c': linear(expression('k'), 40, 3, 's'), 'l': late})
        inline = sphere(dict(options), {'c': linear(expression("sweep(10, 30, 3, 's')"), 40, 3, 's'), 'l': late})
        for label, value in (('named', named), ('inline', inline)):
            with self.subTest(label):
                self.assertEqual(self.stepped(value)[1], [(10, 4.5), (30, 3.25), (40, 2)])
        alone = sphere({'radius': expression('c')}, {'c': linear(expression('sweep(1, 3, 3)'), 5, 2)})
        self.assertEqual(set(DefinitionGraph(alone, catalogue()).select(['ball']).axes),
                         {'sweep:/definitions/c/$analytic#0', 'sweep:/definitions/c/$analytic/start/$expr#0'})

    def mixed(self, limit):
        value = sphere({'centre': expression('vector(c + t, 0, 0)'), 'radius': expression('l')},
                       {'c': linear(10, 30, 3, 's'), 'l': linear(expression('extents(source).deltaX'), 2, 3, 's')})
        value['maxStates'] = limit
        return value

    def test_the_state_limit_covers_the_visits_of_the_study_and_the_states_of_each_graph(self):
        declared = [{'name': 't', 'values': [0, 100]}]
        value = self.mixed(5)
        value['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
        value['sweeps'] = declared
        fault = self.refused(value)
        self.assertEqual((fault.code, fault.observed['states'], fault.observed['limit']),
                         ('EXPANSION_TOO_LARGE', 6, 5))
        program, pairs = self.stepped(self.mixed(6), declared)
        self.assertEqual((program.count, len(pairs)), (6, 6))
        self.assertEqual([visit['document']['%%studyVisits%%'] for visit in program.visits()], [6] * 6)
        timed = self.mixed(11)
        timed['times'] = [1.0, 2.0]
        timed['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
        timed['sweeps'] = declared
        fault = self.refused(timed)
        self.assertEqual((fault.code, fault.observed['states'], fault.observed['limit']),
                         ('EXPANSION_TOO_LARGE', 12, 11))
        timed['maxStates'] = 12
        self.assertEqual(self.stepped_states(timed), 12)
        single = sphere({'radius': expression('t + extents(source).deltaX')}, {'unused': linear(1, 1, 1)})
        program, pairs = self.stepped(dict(single, nodes=[dict(single['nodes'][0], options={
            'centre': [0, 0, 0], 'radius': expression('t + extents(source).deltaX')})]),
            [{'name': 't', 'values': [1]}])
        self.assertEqual(('%%studyVisits%%' in next(program.visits())['document'], len(pairs)), (False, 1))

    def stepped_states(self, value):
        from schemaxis.adaptor_runtime import InputProgram
        from schemaxis.adaptors import registry
        registry.plan(value)
        return sum(DefinitionGraph(visit['document'], catalogue()).select(['ball']).count
                   for visit in InputProgram(value, registry.resolve(value)[1]).visits())

    def test_a_blender_document_plans_with_the_visit_count_of_its_study(self):
        from schemaxis.adaptors import registry
        value = {'version': 'schemaxis.blender/1', 'nodes': [
            {'id': 'paint', 'filter': 'material'},
            {'id': 'box', 'filter': 'cube', 'inputs': {'material': {'$object': 'paint'}}},
            {'id': 'crate', 'filter': 'cube', 'inputs': {'material': {'$object': 'paint'}},
             'options': {'size': expression('extents(box).deltaX * k + t')}}],
            'definitions': {'k': linear(1, 2, 2)}, 'sweeps': [{'name': 't', 'values': [0, 1]}],
            'scenes': [{'id': 'main', 'visible': ['box', 'crate'], 'prepareOnly': True, 'images': [
                {'id': 'view', 'size': [32, 32], 'cameras': [{'direction': [0, 0, 1], 'up': [0, 1, 0]}]}]}]}
        planned = registry.plan(value)
        self.assertEqual((planned['states'], [visit['document']['%%studyVisits%%'] for visit in planned['visits']]),
                         (4, [4, 4, 4, 4]))
        value['maxStates'] = 3
        self.assertEqual(self.refused(value).code, 'EXPANSION_TOO_LARGE')

    def test_generated_axes_are_reported_and_stepped_in_the_order_of_first_use(self):
        from schemaxis.adaptor_runtime import InputProgram
        value = sphere({'centre': expression('vector(sweep(0, 1, 3), 0, 0)'), 'radius': linear(1, 2, 2)})
        graph = DefinitionGraph(value, catalogue())
        expected = ['sweep:/nodes/0/options/centre/$expr#0', 'analytic0']
        self.assertEqual(list(graph.select(['ball']).axes), expected)
        self.assertEqual((graph.to_dict()['sweepsFastestFirst'], list(graph.to_dict()['sweeps'])), (expected, expected))
        program = InputProgram({'version': 'schemaxis.gmsh/1', 'first': linear(1, 2, 2),
                                'second': expression('sweep(10, 30, 3)')}, {})
        self.assertEqual([(visit['document']['first'], visit['document']['second']) for visit in program.visits()],
                         [(1, 10), (2, 10), (1, 20), (2, 20), (1, 30), (2, 30)])
        swapped = InputProgram({'version': 'schemaxis.gmsh/1', 'first': expression('sweep(10, 30, 3)'),
                                'second': linear(1, 2, 2)}, {})
        self.assertEqual([(visit['document']['first'], visit['document']['second']) for visit in swapped.visits()],
                         [(10, 1), (20, 1), (30, 1), (10, 2), (20, 2), (30, 2)])


def waiting(sync='s', count=3, **options):
    """A sphere whose radius waits for the extents of another node of its own document."""
    value = sphere({'radius': linear(expression('extents(source).deltaX'), 2, count, sync), **options})
    value['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
    return value


def workflow_of(*operations, **envelope):
    return {'version': 'schemaxis.workflow/1', **envelope,
            'operations': [{'id': identity, 'document': value} for identity, value in operations]}


def measured(document, target, **options):
    """Stand-in for an application: it keeps the document it was given and publishes one file."""
    import json
    from pathlib import Path
    from schemaxis.artifacts import atomic_json, file_digest
    target = Path(target)
    target.mkdir()
    atomic_json(target / 'authored.json', document)
    atomic_json(target / 'measurement.json', {'radius': json.dumps(document['nodes'][-1]['options']['radius'])})
    atomic_json(target / 'verification.json', {'artifacts': [
        {'file': str(target / 'measurement.json'), 'kind': 'text',
         'sha256': file_digest(target / 'measurement.json')}]})
    atomic_json(target / 'result.json', {'status': 'succeeded', 'verified': True})
    return {'verified': True}


def accepted(target, expected=None):
    return {'verified': True}


def receipt(target, effective, outcome, identity):
    import json
    from pathlib import Path
    return json.loads((Path(target) / 'verification.json').read_text())


class SyncAcrossOperations(unittest.TestCase):
    """One sync name steps every operation of a workflow together, also where a member waits for its own data."""

    def program(self, value):
        from schemaxis.adaptor_runtime import InputProgram
        from schemaxis.workflow import study_required
        self.assertTrue(study_required(value))
        return InputProgram(value, workflow=True)

    def states(self, value):
        """Effective options of the ball at every state the graph of one operation steps."""
        active = RuntimeClosure(DefinitionGraph(value, catalogue()), Backend())
        return [active.apply(state)['effective']['ball'] for state in active.activate(['ball']).visits()]

    def operations(self, visit):
        return [operation['document'] for operation in visit['document']['operations']]

    def test_a_member_that_waits_for_data_steps_with_the_other_operation(self):
        from schemaxis.workflow import inspect_plan, study_required, validate
        value = workflow_of(('a', sphere({'radius': linear(10, 30, 3, 's')})), ('b', waiting()))
        program = self.program(value)
        self.assertEqual((program.groups, program.count), ({'sync:s': 3}, 3))
        pairs = []
        for position, visit in enumerate(program.visits()):
            first, second = self.operations(visit)
            self.assertEqual((second['%%studyPositions%%'], second['%%studyVisits%%']), ({'sync:s': position}, 3))
            self.assertFalse(any(key in first for key in ('%%studyPositions%%', '%%studyVisits%%', 'definitions')))
            radii = [state['radius'] for state in self.states(second)]
            self.assertEqual(len(radii), 1)
            pairs.append((first['nodes'][0]['options']['radius'], radii[0]))
            self.assertFalse(study_required(visit['document']))
            self.assertEqual(validate(visit['document'])[1]['document'], second)
        self.assertEqual(pairs, [(10, 4.5), (20, 3.25), (30, 2)])
        self.assertEqual(inspect_plan(value)['states'], 3)

    def test_two_members_that_wait_for_data_in_two_operations_step_together(self):
        value = workflow_of(('a', waiting()), ('b', waiting(centre=expression("vector(sweep(10, 30, 3, 's'), 0, 0)"))))
        program = self.program(value)
        self.assertEqual(program.groups, {'sync:s': 3})
        found = []
        for visit in program.visits():
            first, second = (self.states(operation) for operation in self.operations(visit))
            self.assertEqual((len(first), len(second)), (1, 1))
            found.append((first[0]['radius'], second[0]['centre'][0], second[0]['radius']))
        self.assertEqual(found, [(4.5, 10, 4.5), (3.25, 20, 3.25), (2, 30, 2)])

    def test_a_member_that_waits_for_time_steps_with_the_other_operation(self):
        timed = sphere({'radius': linear(expression('time'), 2, 3, 's')})
        timed['times'] = [1.0, 3.0]
        program = self.program(workflow_of(('a', sphere({'radius': linear(10, 30, 3, 's')})), ('b', timed)))
        found = [(self.operations(visit)[0]['nodes'][0]['options']['radius'],
                  [state['radius'] for state in self.states(self.operations(visit)[1])])
                 for visit in program.visits()]
        self.assertEqual(found, [(10, [1, 3]), (20, [1.5, 2.5]), (30, [2, 2])])

    def test_an_operation_keeps_the_named_sections_its_late_values_read(self):
        from schemaxis.workflow import inspect_plan
        named = sphere({'radius': expression('r')}, {'r': linear(expression('extents(source).deltaX'), 2)})
        named['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
        named['sweeps'] = [{'name': 't', 'values': [0, 1]}]
        named['nodes'][1]['options']['centre'] = expression('vector(t + extents(source).deltaX, 0, 0)')
        value = workflow_of(('only', named))
        program = self.program(value)
        self.assertEqual(program.groups, {'/operations/0/document/declared:t': 2,
                                          'member:/operations/0/document/definitions/r': 3})
        found = []
        for visit in program.visits():
            operation = self.operations(visit)[0]
            self.assertEqual(operation['sweeps'], [{'name': 't', 'values': [visit['index'] % 2]}])
            self.assertEqual(operation['%%studyPositions%%'], {'sweep:/definitions/r/$analytic#0': visit['index'] // 2})
            found.extend((state['centre'][0], state['radius']) for state in self.states(operation))
        self.assertEqual(found, [(4.5, 4.5), (5.5, 4.5), (4.5, 3.25), (5.5, 3.25), (4.5, 2), (5.5, 2)])
        self.assertEqual(inspect_plan(value)['states'], 6)

    def test_an_operation_reads_an_envelope_entry_at_its_value_for_the_visit(self):
        from schemaxis.workflow import study_required, validate
        reader = sphere({'radius': expression('workflow.definitions.w + extents(source).deltaX')})
        reader['nodes'].insert(0, {'id': 'source', 'filter': 'sphere'})
        value = workflow_of(('b', reader), sweeps=[{'name': 't', 'values': [0, 100]}],
                            definitions={'w': expression('t * 2'), 'unread': linear(1, 1, 1)})
        found = []
        for visit in self.program(value).visits():
            self.assertFalse(study_required(visit['document']))
            self.assertEqual(visit['document']['definitions'], {'w': 200 * visit['index'], 'unread': 1})
            operation = validate(visit['document'])[0]['document']
            self.assertEqual(operation, self.operations(visit)[0])
            found.append((operation['%%workflowScope%%'], self.states(operation)[0]['radius']))
        self.assertEqual(found, [({'definitions': {'w': 0}}, 4.5), ({'definitions': {'w': 200}}, 204.5)])

    def test_unequal_counts_under_one_sync_name_are_refused_across_operations(self):
        from schemaxis.adaptor_runtime import InputProgram
        value = workflow_of(('a', sphere({'radius': linear(10, 30, 4, 's')})), ('b', waiting()))
        with self.assertRaises(SchemaxisError) as caught:
            InputProgram(value, workflow=True)
        self.assertEqual(caught.exception.fault.code, 'ANALYTIC_LENGTH_MISMATCH')

    def test_the_state_limit_of_a_workflow_covers_the_times_of_an_operation_that_waits_for_data(self):
        from schemaxis.workflow import inspect_plan
        timed = waiting()
        timed['times'] = [0.0, 1.0]
        value = workflow_of(('a', sphere({'radius': linear(10, 30, 3, 's')})), ('b', timed), maxStates=5)
        with self.assertRaises(SchemaxisError) as caught:
            inspect_plan(value)
        fault = caught.exception.fault
        self.assertEqual((fault.code, fault.observed['states'], fault.observed['limit'],
                          fault.observed['workflowOperation']), ('EXPANSION_TOO_LARGE', 6, 5, 'b'))
        value['maxStates'] = 6
        self.assertEqual(inspect_plan(value)['states'], 3)

    def test_sync_names_kept_apart_leave_the_operations_to_plan_on_their_own(self):
        from schemaxis.workflow import study_required
        self.assertFalse(study_required(workflow_of(('a', sphere({'radius': linear(10, 30, 3, 'one')})),
                                                    ('b', waiting('two')))))

    def test_a_sync_name_on_a_sweep_that_waits_for_another_operation_is_refused_when_shared(self):
        from schemaxis.workflow import inspect_plan, study_required
        produced = {'$value': 'a', 'path': '/radius'}

        def consumer(sync, **options):
            return sphere({'radius': linear(produced, 2, 3, sync), **options})

        shared = [workflow_of(('a', sphere({'radius': linear(10, 30, 3, 's')})), ('b', consumer('s'))),
                  workflow_of(('a', sphere()), ('b', consumer('s')), ('c', consumer('s'))),
                  workflow_of(('a', sphere()), ('b', consumer('s', centre=expression("vector(sweep(1, 3, 3, 's'), 0, 0)")))),
                  workflow_of(('a', sphere()), ('b', consumer('s')), definitions={'gap': linear(1, 3, 3, 's')})]
        for value in shared:
            for check in (study_required, inspect_plan):
                with self.assertRaises(SchemaxisError) as raised:
                    check(value)
                fault = raised.exception.fault
                self.assertEqual((fault.code, fault.to_dict()['observed']['sync']), ('UNSCHEDULABLE_SYNC', 's'))
                self.assertTrue(fault.location.startswith('$/operations/1/document/nodes/0/options/radius'))
                self.assertIn('result of an earlier operation', fault.message)
        alone = workflow_of(('a', sphere()), ('b', consumer('s', height=linear(produced, 4, 3, 's'))),
                            ('c', sphere({'radius': linear(10, 30, 3, 'other')})))
        self.assertFalse(study_required(alone))

    def test_a_result_reached_through_a_document_reference_is_still_a_result(self):
        from schemaxis.workflow import inspect_plan, study_required
        produced = {'$value': 'a', 'path': '/radius'}
        indirect = linear({'$document': '/definitions/start'}, 2, 3, 's')
        hidden = workflow_of(('a', sphere({'radius': linear(10, 30, 3, 's')})),
                             ('b', sphere({'radius': indirect}, {'start': produced})))
        with self.assertRaises(SchemaxisError) as raised:
            inspect_plan(hidden)
        self.assertEqual(raised.exception.fault.code, 'UNSCHEDULABLE_SYNC')
        together = workflow_of(('a', sphere()), ('b', sphere(
            {'radius': indirect, 'centre': [linear(produced, 4, 3, 's'), 0, 0]}, {'start': produced})))
        self.assertFalse(study_required(together))
        inspect_plan(together)

    def test_an_operation_that_waits_for_a_result_elsewhere_still_steps_its_other_sweeps_with_the_run(self):
        from schemaxis.adaptor_runtime import InputProgram
        produced = {'$value': 'a', 'path': '/radius'}

        def value(count):
            return workflow_of(('a', sphere({'radius': linear(10, 30, 3, 's')})),
                               ('b', sphere({'radius': linear(1, 3, count, 's'), 'centre': [produced, 0, 0]})))

        program = self.program(value(3))
        self.assertEqual(program.groups, {'sync:s': 3})
        pairs = [[operation['nodes'][0]['options']['radius'] for operation in self.operations(visit)]
                 for visit in program.visits()]
        self.assertEqual(pairs, [[10, 1], [20, 2], [30, 3]])
        self.assertEqual(next(program.visits())['document']['operations'][1]['document']['nodes'][0]['options']['centre'][0],
                         produced)
        with self.assertRaises(SchemaxisError) as raised:
            InputProgram(value(4), workflow=True)
        self.assertEqual(raised.exception.fault.code, 'ANALYTIC_LENGTH_MISMATCH')

    def test_a_workflow_study_runs_each_operation_once_at_its_position(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from schemaxis import workflow
        value = workflow_of(('a', sphere({'radius': linear(10, 30, 3, 's')})), ('b', waiting()))
        ran = []

        def run(document, target, **options):
            ran.append((Path(target).parent.name, Path(target).name, document.get('%%studyPositions%%'),
                        document['nodes'][-1]['options']['radius']))
            return measured(document, target, **options)

        late = waiting()['nodes'][1]['options']['radius']
        with tempfile.TemporaryDirectory() as temporary, \
                patch('schemaxis.adaptors.paraview.job._native_run', side_effect=run), \
                patch('schemaxis.adaptors.paraview.integration.verifyAttempt', side_effect=accepted), \
                patch('schemaxis.adaptors.paraview.integration.verifyLegacy', side_effect=receipt):
            target = Path(temporary) / 'run'
            self.assertEqual(len(workflow.execute(value, target)['states']), 3)
            self.assertEqual(workflow.verify(target), {'verified': True, 'states': 3, 'artifacts': 6})
        self.assertEqual(ran, [(f'state-0000{position}', identity, positions, radius)
                               for position, start in enumerate((10, 20, 30))
                               for identity, positions, radius in (('a', None, start),
                                                                   ('b', {'sync:s': position}, late))])


class References(unittest.TestCase):
    """A $document reference to an entry that holds an expression reads the entry; it does not copy its text."""

    def test_an_operation_reads_an_envelope_expression_among_the_envelope_names(self):
        from schemaxis.workflow import validate
        workflow = {'version': 'schemaxis.workflow/1', 'settings': {'gap': 7, 'wide': expression('gap * 2')},
                    'operations': [{'id': 'one', 'document': {
                        'version': 'schemaxis/1', 'settings': {'gap': 1},
                        'nodes': [{'id': 'ball', 'filter': 'sphere', 'options': {
                            'radius': {'$document': '/settings/wide', 'scope': 'workflow'}}}]}}]}
        planned = validate(workflow)[0]['document']
        self.assertEqual(planned['nodes'][0]['options']['radius'], 14)

    def test_a_referenced_sweep_stays_one_axis(self):
        value = document({'$document': '/definitions/swept'},
                         definitions={'y': expression('sweep(0, 1, 3)'), 'swept': expression('vector(y, y, 0)'),
                                      'again': {'$document': '/definitions/y'}})
        graph = DefinitionGraph(value, catalogue())
        self.assertEqual(graph.select(['slice']).axes, ('sweep:/definitions/y/$expr#0',))
        self.assertEqual(graph.document['definitions']['again'], expression('definitions.`y`'))
        active = RuntimeClosure(graph, Backend())
        origins = [active.apply(visit)['effective']['slice']['origin']
                   for visit in active.activate(['slice']).visits()]
        self.assertEqual(origins, [[0, 0, 0], [0.5, 0.5, 0], [1, 1, 0]])
