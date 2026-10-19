"""Detect drift between parser-owned envelopes and exported schema keywords."""
import ast
from functools import partial
import inspect
import textwrap
import unittest

from schemaxis.schema import export_schema
from schemaxis.schema_authoring import VERSIONS
from schemaxis.errors import keys, keys as _closed

PARITY_FIELDS = {'payload': {}}


def guarded_parser_fixture(document):
    if not isinstance(document, dict):
        keys(document, (), '$')
    keys(document.get('nested', {}), ('nestedOnly',), '$.nested')
    keys(document, ('version', *PARITY_FIELDS), '$')


def closed_parser_fixture(document):
    _closed(document, ('version', *PARITY_FIELDS), '$')


def delegated_parser_fixture(document, *, fields):
    keys(document, ('version', *fields), '$')


PARITY_BRANCHES = {'left': {'leftField': {}}, 'right': {'rightField': {}}}


def selected_parser_fixture(document):
    operation = document.get('operation')
    fields = PARITY_BRANCHES[operation]
    keys(document, ('version', 'operation', *fields), '$')


def key_contract(function, *, root=True):
    """Read declared envelope keys, without executing the parser or using schema.

    Empty checks only reject non-objects. Root checks can use literal sequences
    or starred module declarations; wrapped planners retain their own globals.
    Alternative root envelopes contribute their union to the exported envelope.
    Scheduler sections use the first nonempty check instead of location '$'.
    """
    bindings = function.keywords if isinstance(function, partial) else {}
    function = inspect.unwrap(function.func if isinstance(function, partial) else function)
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    assignments = {target.id: node.value for node in tree.body[0].body
                   if isinstance(node, ast.Assign) for target in node.targets
                   if isinstance(target, ast.Name)}
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id in ('keys', '_closed')
             and len(node.args) >= 2]
    if root:
        calls = [call for call in calls if len(call.args) >= 3
                 and isinstance(call.args[2], ast.Constant) and call.args[2].value == '$']

    def declaration(node):
        if isinstance(node, ast.Name):
            if node.id in assignments and node.id not in bindings:
                return declaration(assignments[node.id])
            value = bindings[node.id] if node.id in bindings else function.__globals__[node.id]
            if type(value) not in (dict, list, tuple, set, frozenset):
                raise AssertionError('Key declaration must be a plain collection')
            return value
        if isinstance(node, ast.Subscript):
            choices = declaration(node.value)
            if type(choices) is not dict:
                raise AssertionError('Selected key declarations must use a plain mapping')
            try:
                selected = ast.literal_eval(node.slice)
            except (ValueError, TypeError):
                # A runtime operation selects one closed declaration. The
                # exported root envelope must include every declared branch.
                if any(type(value) not in (dict, list, tuple, set, frozenset)
                       for value in choices.values()):
                    raise AssertionError('Every declaration branch must be a plain collection')
                return set().union(*choices.values())
            return choices[selected]
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            result = []
            for member in node.elts:
                if isinstance(member, ast.Starred): result.extend(declaration(member.value))
                else: result.append(ast.literal_eval(member))
            return result
        return ast.literal_eval(node)

    contracts = []
    for call in sorted(calls, key=lambda node: (node.lineno, node.col_offset)):
        fields = declaration(call.args[1])
        if type(fields) not in (dict, list, tuple, set, frozenset) or any(not isinstance(field, str) for field in fields):
            raise AssertionError('Closed-key declaration must contain string field names')
        if fields:
            if not root: return set(fields)
            contracts.append(set(fields))
    if not contracts:
        raise AssertionError('Parser no longer exposes a nonempty closed-key contract; update the parity test')
    return set.union(*contracts)


class ParserSchemaParityTests(unittest.TestCase):
    def test_every_routed_document_has_exact_parser_root_keywords(self):
        from schemaxis.pipeline import DefinitionGraph
        from schemaxis.adaptors.blender.adaptor import plan as blender
        from schemaxis.adaptors.blender.render_job import plan as render
        from schemaxis.adaptors.freecad.adaptor import plan as freecad
        from schemaxis.adaptors.freecad.assembly import plan as assembly
        from schemaxis.adaptors.godot.adaptor import plan as godot
        from schemaxis.adaptors.aseprite.adaptor import plan as aseprite
        from schemaxis.adaptors.premiere.adaptor import plan as premiere, LAYOUT_OPTIONS
        from schemaxis.adaptors.premiere.layout import plan as premiere_layout
        from schemaxis.adaptors.pyproj.contract import validate as pyproj
        from schemaxis.workflow import validate as workflow

        parsers = {
            'schemaxis/1': DefinitionGraph.__init__, 'schemaxis.blender/1': blender,
            'schemaxis.blender.render/1': render, 'schemaxis.freecad/1': freecad,
            'schemaxis.freecad.assembly/1': assembly, 'schemaxis.godot/1': godot,
            'schemaxis.aseprite/1': aseprite, 'schemaxis.workflow/1': workflow,
            'schemaxis.premiere/1': (
                premiere, partial(premiere_layout, definitions=LAYOUT_OPTIONS)),
            'schemaxis.pyproj/1': pyproj,
        }
        from schemaxis.adaptors.registry import routes
        from importlib import import_module
        for version, (_, route) in routes().items():
            parsers.setdefault(version, import_module(route['module']).plan)
        self.assertEqual(set(parsers), set(VERSIONS))
        for version, parser in parsers.items():
            for authored in (False, True):
                with self.subTest(version=version, authored=authored):
                    schema = export_schema(version=version, authored=authored)
                    branches = parser if isinstance(parser, tuple) else (parser,)
                    expected = set.union(*(key_contract(branch) for branch in branches))
                    common = {'dimensions', 'definitions', 'settings', 'axes', 'maxStates'}
                    if authored:
                        expected |= common
                    elif version == 'schemaxis.workflow/1':
                        expected -= common
                    self.assertEqual(set(schema['properties']), expected)
                    self.assertFalse(schema['additionalProperties'])
                    self.assertEqual(schema['properties']['version'].get('const'), version)

    def test_contract_reader_ignores_type_guards_and_nested_keys(self):
        expected = {'version', 'payload'}
        for parser in (guarded_parser_fixture, closed_parser_fixture):
            self.assertEqual(key_contract(parser), expected)
        self.assertEqual(key_contract(partial(delegated_parser_fixture,
                                             fields={'tracks': {}})), {'version', 'tracks'})
        self.assertEqual(key_contract(selected_parser_fixture),
                         {'version', 'operation', 'leftField', 'rightField'})
        # The reader owns an independent parser-derived set. Either schema
        # drift direction must remain visible, even with descriptive metadata.
        schema = {'properties': {'version': {'const': 'fixture/1', 'description': 'An annotation'}, 'payload': {}}}
        self.assertEqual(set(schema['properties']), key_contract(guarded_parser_fixture))
        for altered in (expected | {'extra'}, expected - {'payload'}):
            with self.assertRaises(AssertionError):
                self.assertEqual(altered, key_contract(guarded_parser_fixture))

    def test_execution_keyword_sets_match_the_scheduler(self):
        from schemaxis.parallel import configuration, requests
        for section, parser in [('execution', configuration), ('operation-execution', requests)]:
            with self.subTest(section=section):
                schema = export_schema(section=section)
                self.assertEqual(set(schema['properties']), key_contract(parser, root=False))
                self.assertFalse(schema['additionalProperties'])

    def test_discovered_versions_are_covered_without_native_applications(self):
        from schemaxis.adaptors.registry import discover
        discovered = {'schemaxis.workflow/1'}
        for provider in discover()['providers']:
            discovered.add(provider['documentVersion'])
            discovered.update(provider['additionalDocumentVersions'])
        self.assertEqual(discovered, set(VERSIONS))


if __name__ == '__main__':
    unittest.main()
