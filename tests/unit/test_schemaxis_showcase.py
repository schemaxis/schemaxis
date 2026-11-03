# Copyright (C) 2026 David L F Gaden
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.context import InputContext, ObjectRegistry
from schemaxis.job import plan
from schemaxis.pipeline import RuntimeClosure
from test_schemaxis_pipeline import Backend


class ShowcaseTests(unittest.TestCase):
    def fault(self, code, callback):
        with self.assertRaises(SchemaxisError) as caught:
            callback()
        self.assertEqual(caught.exception.fault.code, code)

    def test_typed_objects_and_lifecycle(self):
        registry = ObjectRegistry()
        registry.declare('mesh', ['data', 'reader'])
        ctx = InputContext({'input': {'$object': 'mesh'}, 'n': 'bad'}, owner='test', objects=registry)
        self.fault('NOT_YET_PRODUCED', lambda: ctx.get(['input'], object_kind='reader'))
        native = object()
        registry.publish('mesh', native)
        self.assertIs(ctx.get(['input'], object_kind='reader'), native)
        self.assertIs(ctx.get(['input'], object_kind='data'), native)
        self.assertEqual(ctx.dependencies, {'mesh'})
        self.fault('TYPE_MISMATCH', lambda: ctx.get(['input'], object_kind='filter'))
        self.assertEqual(ctx.get(['missing'], default=12), 12)
        self.fault('INVALID_ARGUMENT', lambda: ctx.get(['n'], {'type': 'number'}, default=12))
        self.assertEqual(ctx.get(['input'], raw=True), {'$object': 'mesh'})
        registry.retire('mesh')
        self.fault('CLOSED_HANDLE', lambda: ctx.get(['input'], object_kind='data'))
        replacement = object()
        registry.publish('mesh', replacement)
        self.assertIs(ctx.get(['input'], object_kind='data'), replacement)
        registry.close()
        self.fault('CLOSED_REGISTRY', lambda: registry.resolve('mesh'))

    def document(self):
        def linear(a, b, sync=None, count=3):
            spec = {'type': 'linear', 'start': a, 'end': b, 'count': count}
            if sync:
                spec['sync'] = sync
            return {'$analytic': spec}
        return {'version': 'schemaxis/1', 'nodes': [
            {'id': 'sphere', 'filter': 'sphere', 'options': {
                'radius': linear(1, 3, 'shape'),
                'centre': linear([0, 0, 0], [2, 0, 0], 'shape')}},
            {'id': 'other', 'filter': 'sphere', 'options': {'radius': linear(2, 4, 'shape')}},
            {'id': 'cut', 'filter': 'slice', 'inputs': {'input': 'sphere'}, 'options': {
                'origin': linear([0, 0, 0], [0, 0, .5], count=2), 'normal': 'z+'}},
            {'id': 'unused', 'filter': 'sphere', 'options': {'radius': linear(1, 10, count=10)}}],
            'scenes': [{'id': 'test', 'geometry': ['cut'], 'visible': {'cut': {}, 'other': {}},
                        'images': [{'id': 'orbit', 'cameras': {'$analytic': {
                            'type': 'orbit', 'start': 0, 'end': 270, 'count': 4, 'elevation': 30}}}]}]}

    def test_bindings_product_pruning_and_camera_scope(self):
        master, scenes, result = plan(self.document())
        selection = master.select(scenes[0]['selection']['roots'])
        self.assertEqual(selection.count, 6)
        self.assertNotIn('unused', selection.order)
        self.assertEqual(result['expectedPublications'], 30)
        self.assertEqual(len(master.analytic_bindings), 5)
        active = RuntimeClosure(master, Backend())
        active.activate(selection.roots)
        states = [active.apply(v) for v in selection.visits()]
        self.assertEqual([s['effective']['sphere']['radius'] for s in states], [1, 2, 3, 1, 2, 3])
        self.assertEqual([s['effective']['other']['radius'] for s in states], [2, 3, 4, 2, 3, 4])
        self.assertIs(active.objects.resolve('sphere', 'source'), active.handles['sphere'])
        self.fault('NOT_YET_PRODUCED', lambda: active.objects.resolve('unused'))
        active.close()

    def test_mismatched_sync_rejected(self):
        doc = self.document()
        doc['nodes'][1]['options']['radius']['$analytic']['count'] = 2
        self.fault('ANALYTIC_LENGTH_MISMATCH', lambda: plan(doc))

    def test_vector_shape_and_empty_values_rejected(self):
        doc = self.document()
        doc['nodes'][0]['options']['centre']['$analytic']['end'] = [1, 2]
        self.fault('INVALID_ANALYTIC', lambda: plan(doc))
        doc = self.document()
        doc['nodes'][0]['options']['radius'] = {'$analytic': {'type': 'values', 'values': []}}
        self.fault('EMPTY_ANALYTIC', lambda: plan(doc))

    def test_composition_has_explicit_text_and_list_concatenation(self):
        from schemaxis.core.documents import resolve_document
        document = {'directory': '/data/', 'path': {'$expr': {'op': 'concat', 'args': [
            {'$document': '/directory'}, 'case.foam']}},
            'combined': {'$expr': {'op': 'concat', 'args': [[1, 2], [3]]}}}
        resolved, _ = resolve_document(document)
        self.assertEqual(resolved['path'], '/data/case.foam')
        self.assertEqual(resolved['combined'], [1, 2, 3])

    def test_registered_call_returns_full_object(self):
        from schemaxis.functions import FunctionRegistry
        objects = ObjectRegistry()
        objects.declare('reader', ['reader', 'data'])
        native = object()
        objects.publish('reader', native)
        functions = FunctionRegistry()
        functions.register('select', {'source': {'objectKind': 'reader', 'required': True}},
                           {'objectKind': 'data'}, lambda source: source)
        self.assertIs(functions.invoke('select', {'source': native}, 'test', objects), native)
        context = InputContext({'input': {'$call': 'select', 'args': {'source': {'$object': 'reader'}}}},
                               owner='test', objects=objects, functions=functions)
        self.assertIs(context.get(['input'], object_kind='data'), native)
        self.assertEqual(context.dependencies, {'reader'})
        self.fault('UNKNOWN_REFERENCE', lambda: functions.invoke('select', {'source': object()}, 'test', objects))
        objects.retire('reader')
        self.fault('UNKNOWN_REFERENCE', lambda: functions.invoke('select', {'source': native}, 'test', objects))

    def test_lookup_registers_analytic_and_returns_current_value(self):
        from schemaxis.analytics import AnalyticBindings
        bindings = AnalyticBindings()
        context = InputContext({'radius': {'$analytic': {'type': 'linear', 'start': 1, 'end': 3, 'count': 3}}},
                               owner='sphere', analytics=bindings)
        self.assertEqual(context.get(['radius'], {'type': 'number'}), 1)
        self.assertEqual(context.get(['radius'], {'type': 'number'}), 1)
        self.assertEqual(len(bindings.bindings), 1)
        self.assertEqual(bindings.bindings[0]['owner'], 'sphere')
        self.assertEqual(bindings.bindings[0]['memberPath'], ['radius'])
        bindings.indices['analytic0'] = 2
        self.assertEqual(context.get(['radius'], {'type': 'number'}), 3)
        bindings.indices['analytic0'] = 3
        self.fault('ANALYTIC_EXHAUSTED', lambda: context.get(['radius'], {'type': 'number'}))
        bindings.indices.clear()
        self.assertEqual(context.get(['radius'], {'type': 'number'}), 1)

    def test_inline_input_and_nested_calls(self):
        doc = {'version': 'schemaxis/1', 'nodes': [
            {'id': 'cut', 'filter': 'slice', 'inputs': {'input': {'$create': {
                'id': 'source', 'filter': 'wavelet'}}}, 'options': {
                    'origin': {'$call': 'boundsCentre', 'args': {'bounds': {
                        '$observe': 'source', 'path': ['bounds']}}}}}],
            'scenes': [{'id': 'one', 'geometry': ['cut']}]}
        master, scenes, _ = plan(doc)
        active = RuntimeClosure(master, Backend())
        active.activate(scenes[0]['selection']['roots'])
        state = active.apply(next(active.selection.visits()))
        self.assertEqual(state['effective']['cut']['origin'], [0, 0, 0])
        self.assertIs(active.handles['cut']['inputs']['input'], active.objects.resolve('source'))
        from schemaxis.pipeline import evaluate
        value = {'$call': 'sinDegrees', 'args': {'angle': {'$call': 'vectorLength',
                 'args': {'vector': [0, 0, 90]}}}}
        self.assertEqual(evaluate(value, {}, {}, 0, 'test'), 1)
        self.fault('UNKNOWN_FUNCTION', lambda: evaluate({'$call': 'missing'}, {}, {}, 0, 'test'))
        active.close()

    def test_inline_identity_conflict(self):
        doc = self.document()
        doc['nodes'][2]['inputs']['input'] = {'$create': {'id': 'sphere', 'filter': 'wavelet'}}
        self.fault('CONFLICTING_OBJECT', lambda: plan(doc))


if __name__ == '__main__':
    unittest.main()
