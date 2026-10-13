"""ParaView selection queries never pass authored or runtime text to Python eval."""
import copy
import json
import sys
import types
import unittest
from unittest.mock import patch

from schemaxis.authoring import source_diagnostic
from schemaxis.bindings import COMPILERS, native_value, validate_options
from schemaxis.core.faults import SchemaxisError
from schemaxis.pipeline import DefinitionGraph, RuntimeClosure
from schemaxis.schema import export_schema
from schemaxis.adaptors.paraview import selection_query as sq
from schemaxis.adaptors.paraview.catalogue import generated_declarations
from schemaxis.adaptors.paraview.catalogue_import import compile_catalogue
from schemaxis.adaptors.paraview.filters import catalogue
from schemaxis.adaptors.paraview.job import plan


def query(*clauses, groups=None):
    return {'any': groups if groups is not None else [{'all': list(clauses)}]}


def document(value, extra=None, axes=None):
    result = {'version': 'schemaxis/1', 'nodes': [
        {'id': 'grid', 'filter': 'wavelet'},
        {'id': 'find', 'filter': 'pvSelectionQuerySource', 'options': {'QueryString': value, **(extra or {})}},
        {'id': 'cut', 'filter': 'pvExtractSelection', 'inputs': {'Input': 'grid', 'Selection': 'find'}}],
        'scenes': [{'id': 'view', 'geometry': ['cut']}]}
    if axes:
        result['axes'] = axes
    return result


ACCEPTED = [
    (query({'array': 'RTData', 'test': '>', 'value': 150}), '(RTData > 150)'),
    (query({'array': 'RTData', 'test': '>=', 'value': -2.5}), '(RTData >= -2.5)'),
    (query({'array': 'Temperature (K)', 'test': '!=', 'value': 0}), '(TemperatureK != 0)'),
    (query({'array': '2D', 'test': '<', 'value': 1e-05}), '(a2D < 1e-05)'),
    (query({'ids': True, 'test': 'oneOf', 'values': [1, 2, 3]}), '(in1d(id, [1, 2, 3]))'),
    (query({'array': 'V', 'component': 2, 'test': 'between', 'minimum': 0, 'maximum': 1}),
     '((V[:, 2] > 0) & (V[:, 2] < 1))'),
    (query({'array': 'V', 'magnitude': True, 'test': 'isMaximum'}), '(mag(V) == max(mag(V)))'),
    (query({'array': 'p', 'test': 'isMinimumPerBlock'}), '(p == min_per_block(p))'),
    (query({'array': 'p', 'test': 'isNaN', 'negate': True}), '(logical_not(isnan(p)))'),
    (query({'array': 'p', 'test': 'atLeastMean'}), '(p >= mean(p))'),
    (query({'array': 'p', 'test': 'nearMean', 'tolerance': 0.5}), '(abs(p - mean(p)) <= 0.5)'),
    (query({'test': 'pointNear', 'point': [0, 0, 1.5], 'tolerance': 0.1}),
     '(pointIsNear([(0, 0, 1.5)], 0.1, inputs))'),
    (query({'test': 'cellContaining', 'point': [1, 2, 3]}), '(cellContainsPoint(inputs, [(1, 2, 3)]))'),
    (query(groups=[{'all': [{'array': 'RTData', 'test': '>', 'value': 150},
                            {'array': 'RTData', 'test': '<', 'value': 200}]},
                   {'all': [{'ids': True, 'test': '==', 'value': 0}]}]),
     '((RTData > 150) & (RTData < 200)) | ((id == 0))'),
]

UNSAFE_TEXT = {
    'import call': "__import__('os').system('id')",
    'bare import name': '__import__ > 1',
    'class bases chain': '().__class__.__bases__[0].__subclasses__()',
    'attribute on array': 'RTData.__class__ > 1',
    'method on array': 'RTData.mean() > 1',
    'attribute on module': 'np.where(RTData) > 1',
    'lambda': '(lambda: RTData)() > 1',
    'f-string': "f'{RTData}' == 1",
    'string literal': "RTData == 'x'",
    'byte literal': "RTData == b'x'",
    'eval call': "eval('1') > 0",
    'open call': "open('x') > 0",
    'getattr call': 'getattr(RTData, mag) > 0',
    'non-allow-listed numpy call': 'sum(RTData) > 1',
    'non-allow-listed algorithm': 'gradient(RTData) > 1',
    'keyword argument': 'in1d(RTData, [1], invert=1)',
    'starred argument': 'in1d(RTData, *[1])',
    'wrong arity': 'isnan(RTData, RTData)',
    'python and': 'RTData > 1 and RTData < 2',
    'python or': 'RTData > 1 or RTData < 2',
    'chained comparison': '1 < RTData < 2',
    'comprehension': '[x for x in RTData] == 1',
    'conditional': '(RTData if RTData else RTData) > 1',
    'walrus': '(x := RTData) > 1',
    'bitwise invert': '~(RTData > 1)',
    'power': 'RTData ** 2 > 1',
    'integer index': 'RTData[0] > 1',
    'range slice': 'RTData[:, 0:2] > 1',
    'reserved builtin name': 'exec > 1',
    'reserved compute local': 'points > 1',
    'inputs as array': 'inputs > 1',
    'location with module': 'pointIsNear([(0, 0, 0)], 1, sys)',
    'constant only': 'True',
    'none literal': 'None == RTData',
    'newline': 'RTData > 1\n',
    'empty': '',
    'very long': '(RTData > 1)' + ' | (RTData > 1)' * 2000,
    'deeply nested': '(' * 100 + 'RTData > 1' + ')' * 100,
    'nested calls': 'logical_not(' * 40 + 'RTData > 1' + ')' * 40,
}


class SelectionQueryLanguageTests(unittest.TestCase):
    def test_accepted_corpus_compiles_to_canonical_find_data_text(self):
        for value, expected in ACCEPTED:
            with self.subTest(expected=expected):
                text = sq.compile_query(value, 'q')
                self.assertEqual(text, expected)
                self.assertEqual(sq.check_text(text, 'q'), text)
                self.assertNotIn(' and ', text)

    def test_allow_list_rejects_unsafe_text_without_evaluating_it(self):
        for label, text in UNSAFE_TEXT.items():
            with self.subTest(label), self.assertRaises(SchemaxisError) as caught:
                sq.check_text(text, 'q')
            self.assertEqual(caught.exception.fault.code, 'UNSAFE_NATIVE_QUERY')
        for value in (None, 5, b'RTData > 1', ['RTData > 1']):
            with self.subTest(value=value), self.assertRaises(SchemaxisError):
                sq.check_text(value, 'q')

    def test_structured_rejections_have_specific_codes_and_locations(self):
        clause = {'array': 'RTData', 'test': '>', 'value': 1}
        cases = [
            ("__import__('os').system('id')", 'INVALID_ARGUMENT', 'q'),
            (query({**clause, 'array': "__import__('os')"}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].array'),
            (query({**clause, 'array': '().__class__.__bases__'}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].array'),
            (query({**clause, 'array': 'eval'}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].array'),
            (query({**clause, 'array': 'max'}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].array'),
            (query({**clause, 'array': 'inputs'}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].array'),
            (query({**clause, 'array': 'id'}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].array'),
            (query({**clause, 'array': '°'}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].array'),
            (query({**clause, 'array': 'x' * 257}), 'INVALID_ARGUMENT', 'q.any[0].all[0].array'),
            (query({**clause, 'expression': 'RTData > 1'}), 'UNKNOWN_ARGUMENT', 'q.any[0].all[0]'),
            (query({**clause, 'test': 'eval'}), 'INVALID_ARGUMENT', 'q.any[0].all[0].test'),
            (query({**clause, 'value': "1); __import__('os')"}), 'INVALID_ARGUMENT', 'q.any[0].all[0].value'),
            (query({**clause, 'value': float('nan')}), 'INVALID_ARGUMENT', 'q.any[0].all[0].value'),
            (query({**clause, 'value': 10 ** 30}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].value'),
            (query({'array': 'RTData', 'test': '>'}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].value'),
            (query({**clause, 'test': 'isNaN'}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].value'),
            (query({'test': 'between', 'array': 'p', 'minimum': 2, 'maximum': 1}), 'INVALID_SELECTION_QUERY',
             'q.any[0].all[0].maximum'),
            (query({'test': 'pointNear', 'array': 'p', 'point': [0, 0, 0], 'tolerance': 1}),
             'INVALID_SELECTION_QUERY', 'q.any[0].all[0].array'),
            (query({**clause, 'ids': True}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].ids'),
            (query({**clause, 'component': 0, 'magnitude': True}), 'INVALID_SELECTION_QUERY',
             'q.any[0].all[0].magnitude'),
            (query({'ids': True, 'component': 0, 'test': '>', 'value': 1}), 'INVALID_SELECTION_QUERY',
             'q.any[0].all[0].component'),
            (query({'test': '>', 'value': 1}), 'INVALID_SELECTION_QUERY', 'q.any[0].all[0].array'),
            (query({'test': 'oneOf', 'array': 'p', 'values': list(range(257))}), 'INVALID_ARGUMENT',
             'q.any[0].all[0].values'),
            (query(groups=[{'all': [clause]}] * 17), 'INVALID_ARGUMENT', 'q.any'),
            (query(groups=[{'all': [clause] * 17}]), 'INVALID_ARGUMENT', 'q.any[0].all'),
            (query(groups=[]), 'INVALID_ARGUMENT', 'q.any'),
            ({'any': [{'all': [[[[[clause]]]]]}]}, 'INVALID_ARGUMENT', 'q.any[0].all[0]'),
        ]
        for value, code, location in cases:
            with self.subTest(value=json.dumps(value)[:80]), self.assertRaises(SchemaxisError) as caught:
                sq.compile_query(value, 'q')
            self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), (code, location))

    def test_sanitised_names_follow_paraview(self):
        for name, expected in [('RTData', 'RTData'), ('Temperature (K)', 'TemperatureK'), ('2D', 'a2D'),
                               ('_x', 'a_x'), ('°', ''), ('vtkGhostType', 'vtkGhostType')]:
            self.assertEqual(sq.sanitise(name), expected)


class SelectionQueryEnforcementTests(unittest.TestCase):
    def test_catalogue_offers_only_the_compiled_form(self):
        binding = generated_declarations()['pvSelectionQuerySource']['options']['QueryString']
        self.assertEqual(binding['compiler'], sq.COMPILER)
        self.assertEqual(binding['value'], sq.QUERY)
        self.assertIs(COMPILERS[sq.COMPILER], sq.compile_query)

    def test_studio_schema_has_no_free_text_query(self):
        operation = export_schema('paraview', operation='pvSelectionQuerySource')['properties']['QueryString']
        route = export_schema('paraview')['$defs']['options-pvSelectionQuerySource']['properties']['QueryString']
        for schema in (operation, route):
            literal = schema['anyOf'][0] if 'anyOf' in schema else schema
            self.assertEqual(literal['type'], 'object')
            self.assertEqual(literal['required'], ['any'])
            self.assertFalse(literal['additionalProperties'])
            strings = []

            def visit(node, path):
                if isinstance(node, dict):
                    if node.get('type') == 'string':
                        strings.append(path)
                    for key, child in node.items():
                        visit(child, path + '/' + key)
                elif isinstance(node, list):
                    for index, child in enumerate(node):
                        visit(child, path + '/' + str(index))
            visit(literal, '')
            self.assertTrue(strings)
            self.assertTrue(all(path.endswith('/properties/array') or path.endswith('/properties/array/anyOf/0')
                                for path in strings), strings)
        self.assertEqual(operation['x-schemaxis-compiler'], sq.COMPILER)

    def test_planning_rejects_with_rfc6901_pointer(self):
        value = document(query({'array': 'RTData', 'test': 'between', 'minimum': 3, 'maximum': 1}))
        with self.assertRaises(SchemaxisError) as caught:
            plan(value)
        self.assertEqual(caught.exception.fault.code, 'INVALID_SELECTION_QUERY')
        diagnostic = source_diagnostic(json.dumps(value, indent=2), value, caught.exception.fault.to_dict())
        self.assertEqual(diagnostic['pointer'], '/nodes/1/options/QueryString/any/0/all/0/maximum')
        self.assertIn('line', diagnostic)
        plan(document(query({'array': 'RTData', 'test': '>', 'value': 150})))

    def test_planning_checks_static_query_beside_dynamic_options(self):
        axes = [{'name': 'flip', 'values': [False, True]}]
        bad = document(query({'array': 'exec', 'test': '>', 'value': 1}), {'InsideOut': {'$axis': 'flip'}}, axes)
        with self.assertRaises(SchemaxisError) as caught:
            plan(bad)
        self.assertEqual(caught.exception.fault.code, 'INVALID_SELECTION_QUERY')

    def test_axis_values_are_checked_at_planning(self):
        good = query({'array': 'RTData', 'test': '>', 'value': 150})
        for values, code in [([good, "__import__('os').system('id')"], 'INVALID_ARGUMENT'),
                             ([good, query({'array': 'eval', 'test': '>', 'value': 1})], 'INVALID_SELECTION_QUERY')]:
            with self.subTest(code=code), self.assertRaises(SchemaxisError) as caught:
                plan(document({'$axis': 'q'}, axes=[{'name': 'q', 'values': values}]))
            self.assertEqual(caught.exception.fault.code, code)

    def test_runtime_values_are_checked_before_the_backend_sees_them(self):
        class Backend:
            def __init__(self, observed):
                self.observed, self.configured = observed, []
            def create(self, node, declaration, inputs, constructor): return node
            def configure(self, handle, declaration, changes):
                for key, value in changes.items():
                    binding = declaration['options'][key]
                    self.configured.append((handle, key, native_value(binding, value, handle + '.' + key)))
            def update(self, handle, time): pass
            def observe(self, handle): return {'array': self.observed} if handle == 'grid' else {}
            def delete(self, handle): pass
        clause = {'array': {'$observe': 'grid', 'path': ['array']}, 'test': '>', 'value': 150}
        value = document(query(clause))
        for observed, expected in [('RTData', '(RTData > 150)'), ('eval', 'INVALID_SELECTION_QUERY'),
                                   ("__import__('os')", 'INVALID_SELECTION_QUERY'), (5, 'INVALID_ARGUMENT')]:
            with self.subTest(observed=observed):
                backend = Backend(observed)
                closure = RuntimeClosure(DefinitionGraph(copy.deepcopy(value), catalogue()), backend)
                closure.activate(['find'])
                visit = next(closure.selection.visits())
                if expected.startswith('('):
                    closure.apply(visit)
                    self.assertIn(('find', 'QueryString', expected), backend.configured)
                    continue
                with self.assertRaises(SchemaxisError) as caught:
                    closure.apply(visit)
                self.assertEqual(caught.exception.fault.code, expected)
                self.assertFalse([item for item in backend.configured if item[1] == 'QueryString'])

    def test_whole_query_from_runtime_text_is_rejected(self):
        declaration = catalogue()['pvSelectionQuerySource']
        with self.assertRaises(SchemaxisError) as caught:
            validate_options(declaration, {'QueryString': "__import__('os').system('id')"}, 'find')
        self.assertEqual(caught.exception.fault.code, 'INVALID_ARGUMENT')

    def test_unregistered_compiler_fails_closed(self):
        binding = {'path': ['QueryString'], 'value': {'type': 'string'}, 'compiler': 'missing.compiler'}
        with self.assertRaises(SchemaxisError) as caught:
            native_value(binding, 'RTData > 1', 'find.QueryString')
        self.assertEqual(caught.exception.fault.code, 'UNAVAILABLE_COMPILER')


class NativeBoundaryTests(unittest.TestCase):
    """Fake proxies stand in for ParaView; the guard reads only property commands."""

    def proxy(self, commands, vtk_class='vtkSelectionSource'):
        class Property:
            def __init__(self, command): self.SMProperty = types.SimpleNamespace(GetCommand=lambda: command)
        class SMProxy:
            def GetVTKClassName(self): return vtk_class
        class Proxy:
            def __init__(self):
                object.__setattr__(self, 'assigned', {})
                object.__setattr__(self, 'SMProxy', SMProxy())
            def ListProperties(self): return list(commands)
            def GetProperty(self, name): return Property(commands[name])
            def GetXMLGroup(self): return 'sources'
            def GetXMLName(self): return 'SelectionQuerySource'
            def __setattr__(self, name, value): self.assigned[name] = value
            def __getattr__(self, name):
                if name in self.assigned: return self.assigned[name]
                raise AttributeError(name)
        return Proxy()

    def output_window(self):
        window = types.SimpleNamespace(AddObserver=lambda *args: 1, RemoveObserver=lambda *args: None)
        core = types.ModuleType('vtkmodules.vtkCommonCore')
        core.vtkOutputWindow = types.SimpleNamespace(GetInstance=lambda: window)
        return patch.dict(sys.modules, {'vtkmodules': types.ModuleType('vtkmodules'), 'vtkmodules.vtkCommonCore': core})

    def test_assignment_rechecks_text_immediately_before_native_property(self):
        from schemaxis.adaptors.paraview.native import assign
        proxy = self.proxy({'QueryString': 'SetQueryString', 'Script': 'SetScript', 'Radius': 'SetRadius'})
        for text in ["__import__('os').system('id')", 'RTData.__class__ > 1', '', 'RTData > 1 and id < 2']:
            with self.subTest(text=text), self.assertRaises(SchemaxisError) as caught:
                assign(proxy, ['QueryString'], text)
            self.assertEqual(caught.exception.fault.code, 'UNSAFE_NATIVE_QUERY')
        with self.assertRaises(SchemaxisError) as caught:
            assign(proxy, ['Script'], 'print(1)')
        self.assertEqual(caught.exception.fault.code, 'UNSAFE_NATIVE_PROPERTY')
        self.assertEqual(proxy.assigned, {})
        assign(proxy, ['QueryString'], '(RTData > 150)')
        assign(proxy, ['Radius'], 2)
        self.assertEqual(proxy.assigned, {'QueryString': '(RTData > 150)', 'Radius': 2})

    def test_backend_configure_assigns_compiled_text_and_reads_it_back(self):
        from schemaxis.adaptors.paraview.native import ParaViewBackend
        declaration = catalogue()['pvSelectionQuerySource']
        backend = ParaViewBackend.__new__(ParaViewBackend)
        proxy = self.proxy({'QueryString': 'SetQueryString'})
        backend.records = {id(proxy): {'node': 'find', 'options': {}}}
        value = query({'array': 'RTData', 'test': '>', 'value': 150})
        with self.output_window():
            backend.configure(proxy, declaration, {'QueryString': value})
            self.assertEqual(proxy.assigned, {'QueryString': '(RTData > 150)'})
            self.assertEqual(backend.records[id(proxy)]['options']['QueryString'], value)
            for bad in ["__import__('os').system('id')", query({'array': 'eval', 'test': '>', 'value': 1})]:
                target = self.proxy({'QueryString': 'SetQueryString'})
                backend.records[id(target)] = {'node': 'find', 'options': {}}
                with self.subTest(bad=bad), self.assertRaises(SchemaxisError):
                    backend.configure(target, declaration, {'QueryString': bad})
                self.assertEqual(target.assigned, {})
            # A tampered declaration that drops the compiler still meets the final guard.
            tampered = copy.deepcopy(declaration)
            tampered['options']['QueryString'] = {'path': ['QueryString'], 'nativeDomains': [], 'value': {'type': 'string'}}
            target = self.proxy({'QueryString': 'SetQueryString'})
            backend.records[id(target)] = {'node': 'find', 'options': {}}
            with self.assertRaises(SchemaxisError) as caught:
                backend.configure(target, tampered, {'QueryString': "__import__('os').system('id')"})
            self.assertEqual(caught.exception.fault.code, 'UNSAFE_NATIVE_QUERY')
            self.assertEqual(target.assigned, {})

    def test_create_refuses_python_classes_and_unsafe_constructor_values(self):
        from schemaxis.adaptors.paraview.native import ParaViewBackend
        deleted = []
        for vtk_class, constructor, code in [('vtkPythonCalculator', {}, 'UNSAFE_NATIVE_PROXY'),
                                             ('vtkSelectionSource', {'QueryString': "__import__('os')"}, 'UNSAFE_NATIVE_QUERY')]:
            proxy = self.proxy({'QueryString': 'SetQueryString'}, vtk_class)
            backend = ParaViewBackend.__new__(ParaViewBackend)
            backend.records, backend.loaded_dependencies = {}, set()
            backend.pv = types.SimpleNamespace(SelectionQuerySource=lambda registrationName, **kwargs: proxy,
                                               Delete=deleted.append)
            declaration = {'id': 'pvSelectionQuerySource', 'native': 'SelectionQuerySource', 'inputs': {},
                           'nativeIdentity': 'sources/SelectionQuerySource',
                           'options': {'QueryString': {'path': ['QueryString'], 'value': {'type': 'string'}}}}
            with self.subTest(vtk_class=vtk_class), self.assertRaises(SchemaxisError) as caught:
                backend.create('find', declaration, {}, constructor)
            self.assertEqual(caught.exception.fault.code, code)
            self.assertIs(deleted[-1], proxy)


class CatalogueRegenerationTests(unittest.TestCase):
    """A future catalogue import must not reintroduce Python-evaluated properties."""

    # Reviewed text-valued options whose names suggest evaluation, with the reason they are safe.
    REVIEWED = {
        ('pvAppendSelections', 'Expression'): 'vtkSelection::Evaluate C++ boolean parser over selection names',
        ('pvCalculator', 'Function'): 'vtkArrayCalculator expression parser (ExprTk or vtkFunctionParser), not Python',
        ('pvCalculator', 'FunctionParserType'): 'chooses one of the two native C++ parsers',
        ('pvHyperTreeGrid', 'Descriptor'): 'vtkHyperTreeGridSource refinement descriptor parsed in C++',
        ('pvPLOT3DReader', 'FunctionFileName'): 'vtkMultiBlockPLOT3DReader function file path',
    }
    PYTHON_IDENTITIES = {'filters/PythonCalculator', 'filters/PythonAnnotation', 'filters/ProgrammableFilter',
                         'filters/ProgrammableAnnotation', 'sources/ProgrammableSource',
                         'sources/LiveProgrammableSource', 'filters/ExplicitStructuredGridPythonExtractor'}

    def snapshot(self, properties, name='Probe', implementation='vtkSelectionSource'):
        return {'version': 'test', 'source': 'test', 'roots': ['sources/' + name], 'groups': {'sources': [name]},
                'proxies': {'sources/' + name: {'group': 'sources', 'name': name, 'native': name, 'label': name,
                                               'constructorAvailable': True, 'implementationClass': implementation,
                                               'properties': properties}}}

    def string_property(self, command, default=''):
        return {'nativeName': command[3:], 'class': 'vtkSMStringVectorProperty', 'informationOnly': False,
                'domains': [], 'numberOfElements': 1, 'repeatCommand': False, 'observedDefault': default,
                'definition': {'tag': 'StringVectorProperty', 'attributes': {'command': command,
                                                                              'number_of_elements': '1'}}}

    def test_python_evaluated_commands_are_compiled_or_excluded(self):
        result = compile_catalogue(self.snapshot({'Filter': self.string_property('SetQueryString')}))
        binding = result['declarations']['pvProbe']['options']['Filter']
        self.assertEqual((binding['compiler'], binding['value']), (sq.COMPILER, sq.QUERY))
        for command in [key for key, compiler in sq.PYTHON_EVALUATED.items() if compiler is None]:
            with self.subTest(command=command):
                result = compile_catalogue(self.snapshot({'Formula': self.string_property(command)}))
                self.assertEqual(result['declarations'], {})
                self.assertEqual(result['inventory']['sources/Probe']['reason'], 'requires arbitrary code execution')
        result = compile_catalogue(self.snapshot({'Formula': self.string_property('SetFormula')},
                                                 implementation='vtkPythonSomething'))
        self.assertEqual(result['declarations'], {})

    def test_committed_catalogue_has_no_unreviewed_python_text(self):
        declarations = generated_declarations()
        self.assertFalse(self.PYTHON_IDENTITIES & {d.get('nativeIdentity') for d in declarations.values()})
        found = {}

        def visit(operation, options):
            for key, binding in options.items():
                if binding.get('compiler'):
                    self.assertIn(binding['compiler'], COMPILERS)
                    continue
                text = 'string' in json.dumps(binding['value'])
                if text and any(token in key.lower() for token in ('query', 'script', 'python', 'expression', 'function')):
                    found[(operation, key)] = binding['value']
                for choice in binding.get('proxyChoices', {}).values():
                    visit(operation, choice['options'])
        for operation, declaration in declarations.items():
            visit(operation, declaration['options'])
        self.assertEqual(set(found) - set(self.REVIEWED), set())
        compiled = [(name, key) for name, d in declarations.items() for key, b in d['options'].items() if b.get('compiler')]
        self.assertEqual(compiled, [('pvSelectionQuerySource', 'QueryString')])


if __name__ == '__main__':
    unittest.main()
