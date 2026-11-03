# Copyright (C) 2026 David L F Gaden
"""Bounded discovery, authoritative details and recovery through the shared service."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.capabilities import CapabilityCatalogue, SECTIONS, digest, operation_id, response_bytes
from schemaxis.core.faults import SchemaxisError
from schemaxis.schema import export_schema

ROOT = Path(__file__).resolve().parents[2]


class ProgressiveCapabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue = CapabilityCatalogue()

    def assertFault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)
        self.assertEqual(caught.exception.fault.phase, 'discovery')
        self.assertTrue(caught.exception.fault.recovery)
        return caught.exception.fault.to_dict()

    def browse_all(self, scope='root'):
        cursor, items = None, []
        while True:
            page = self.catalogue.browse(scope, cursor=cursor)
            self.assertLessEqual(response_bytes(page), 8192)
            self.assertEqual(page['page']['offset'], len(items))
            items.extend(page['items'])
            cursor = page['page']['nextCursor']
            if cursor is None:
                self.assertEqual(len(items), page['page']['total'])
                self.assertEqual(len(items), len({i['id'] for i in items}))
                return items

    def test_root_is_small_and_schemas_are_lazy(self):
        with patch('schemaxis.schema.export_schema', side_effect=AssertionError('eager schema')):
            root = CapabilityCatalogue().browse()
            items = self.browse_all()
        self.assertLess(response_bytes(root), 8192)
        self.assertEqual({i['kind'] for i in items}, {'application', 'domain'})
        self.assertNotIn('options', json.dumps(items))
        self.assertEqual({i['id'] for i in items if i['kind'] == 'application'},
                         {'app/'+provider for provider in registry.ADAPTORS})

    def test_breadcrumb_and_direct_contract_agree(self):
        c = self.catalogue
        domain = next(i for i in self.browse_all() if i['id'] == 'domain/geometry')
        group = next(i for i in self.browse_all(domain['id']) if i['id'] == 'group/freecad/solids')
        operation = next(i for i in self.browse_all(group['id']) if i['label'] == 'box')
        self.assertIn(group['id'], operation['parents'])
        self.assertEqual(c.describe(operation['id']), c.describe('operation/freecad/box'))

    def test_search_scopes_facets_and_empty_results(self):
        c = self.catalogue
        found = c.search('EXTRUSION', scope='domain/geometry', input_kind='profile', output_kind='solid')
        self.assertEqual([i['id'] for i in found['items']], ['operation/freecad/extrude'])
        self.assertTrue(all(i['provider'] == 'paraview' for i in c.search('extrusion', scope='app/paraview')['items']))
        self.assertEqual(c.search('nonexistent phrase')['page']['total'], 0)
        self.assertIn('operation/paraview/probeLine', [i['id'] for i in c.search('1D', scope='domain/data-analysis')['items']])
        self.assertEqual(c.search('', scope='operation/freecad/box')['page']['total'], 1)

    def test_pagination_has_no_gaps_duplicates_or_budget_overruns(self):
        c = self.catalogue
        for action in ('browse', 'search'):
            cursor, collected = None, []
            while True:
                kwargs = dict(limit=100, max_bytes=4096, cursor=cursor)
                page = (c.browse('app/freecad', **kwargs) if action == 'browse'
                        else c.search('', scope='app/freecad', **kwargs))
                self.assertLessEqual(response_bytes(page), 4096)
                self.assertGreater(page['page']['returned'], 0)
                self.assertEqual(page['page']['offset'], len(collected))
                collected.extend(i['id'] for i in page['items'])
                cursor = page['page']['nextCursor']
                self.assertEqual(page['page']['hasMore'], cursor is not None)
                if cursor is None:
                    break
            self.assertEqual(len(collected), page['page']['total'])
            self.assertEqual(collected, sorted(set(collected)))
        self.assertEqual(len(collected), len(registry.declarations('freecad')))

    def test_cursor_survives_new_service_but_rejects_changed_requests(self):
        c = self.catalogue
        first = c.browse('app/paraview', limit=1)
        cursor = first['page']['nextCursor']
        self.assertEqual(c.browse('app/paraview', cursor=cursor),
                         CapabilityCatalogue().browse('app/paraview', cursor=cursor))
        self.assertFault('INVALID_CURSOR', lambda: c.browse('app/freecad', cursor=cursor))
        self.assertFault('INVALID_CURSOR', lambda: c.search('', scope='app/paraview', cursor=cursor))
        search_cursor = c.search('slice', limit=1)['page']['nextCursor']
        self.assertFault('INVALID_CURSOR', lambda: c.search('sphere', cursor=search_cursor))
        self.assertFault('INVALID_CURSOR', lambda: c.search('slice', input_kind='data', cursor=search_cursor))

    def test_malformed_and_stale_cursors_are_recoverable(self):
        c = self.catalogue
        for value in ('%', '!', 'A'*2049, 'e30=', 'bnVsbA==', 'W10=', 4):
            self.assertFault('INVALID_CURSOR', lambda: c.browse(cursor=value))
        cursor = c.browse(limit=1)['page']['nextCursor']
        decoded = json.loads(base64.urlsafe_b64decode(cursor))
        for offset in (-1, True, 90000, '1'):
            bad = base64.urlsafe_b64encode(json.dumps({**decoded, 'offset': offset}).encode()).decode()
            self.assertFault('INVALID_CURSOR', lambda: c.browse(cursor=bad))
        stale = base64.urlsafe_b64encode(json.dumps({**decoded, 'revision': 'old'}).encode()).decode()
        self.assertFault('STALE_CATALOGUE', lambda: c.browse(cursor=stale))
        self.assertFault('STALE_CATALOGUE', lambda: c.describe('box', revision='old'))

    def test_unknown_and_ambiguous_paths_include_recovery_links(self):
        ambiguous = self.assertFault('AMBIGUOUS_CAPABILITY', lambda: self.catalogue.describe('box'))
        self.assertIn('operation/freecad/box', ambiguous['observed']['alternatives'])
        missing = self.assertFault('UNKNOWN_CAPABILITY', lambda: self.catalogue.describe('operation/freecad/bxo'))
        self.assertEqual(missing['observed']['parent'], 'app/freecad')
        self.assertIn('operation/freecad/box', missing['observed']['alternatives'])
        self.assertFault('NOT_AN_OPERATION', lambda: self.catalogue.describe('app/freecad'))
        self.assertFault('INVALID_CAPABILITY_ID', lambda: self.catalogue.browse([]))

    def test_invalid_limits_and_sections_are_not_silently_coerced(self):
        c = self.catalogue
        for value in (0, 101, True, 2.5, '10'):
            self.assertFault('INVALID_PAGE_LIMIT', lambda: c.browse(limit=value))
        for value in (0, 65537, True, '8192'):
            self.assertFault('INVALID_BYTE_LIMIT', lambda: c.browse(max_bytes=value))
        for sections in ([], 'schema', ['bad'], [[]]):
            self.assertFault('UNKNOWN_CONTRACT_SECTION', lambda: c.describe('operation/freecad/box', sections=sections))
        self.assertFault('INVALID_QUERY', lambda: c.search('x'*257))
        self.assertFault('INVALID_QUERY', lambda: c.search('', input_kind=[]))

    def test_detail_preserves_authoritative_declarations_and_schema(self):
        for provider, name in [('freecad', 'extrude'), ('paraview', 'slice'), ('calc', 'fromRows')]:
            result = self.catalogue.describe(operation_id(provider, name))
            sections = result['sections']
            self.assertEqual(sections['declaration'], registry.declarations(provider)[name])
            self.assertEqual(sections['schema']['literalOptions'], export_schema(provider, operation=name))
            reference = sections['schema']['authoredDocument']
            self.assertEqual(reference['digest'], digest(export_schema(provider, authored=True, version=reference['documentVersion'])))
            self.assertEqual(result['completeSections'], list(SECTIONS))
            self.assertEqual(sections['requirements']['inputs'], sections['declaration']['inputs'])

    def test_section_selection_caching_and_copy_isolation(self):
        c, identity = self.catalogue, 'operation/freecad/box'
        full = c.describe(identity)
        for section in SECTIONS:
            selected = c.describe(identity, sections=[section])
            self.assertEqual(selected['contractDigest'], full['contractDigest'])
            self.assertEqual(selected['sections'], {section: full['sections'][section]})
        cached = c.describe(identity, known_digest=full['contractDigest'])
        self.assertTrue(cached['notModified'])
        self.assertNotIn('sections', cached)
        full['sections']['declaration']['options'].clear()
        full['capability']['parents'].clear()
        self.assertTrue(c.describe(identity)['sections']['declaration']['options'])
        self.assertTrue(c.describe(identity)['capability']['parents'])
        self.assertFalse(c.describe(identity, known_digest='old')['notModified'])

    def test_schema_fragments_reconstruct_the_complete_authoritative_document(self):
        c, identity = self.catalogue, 'operation/freecad/box'
        def read(pointer=''):
            response = c.schema(identity, pointer=pointer, max_bytes=2048, limit=3)
            self.assertLessEqual(response_bytes(response), 2048)
            if response['mode'] == 'value':
                return response['value']
            self.assertNotIn('value', response)
            members = []
            while True:
                members.extend(response['items'])
                cursor = response['page']['nextCursor']
                if cursor is None:
                    break
                response = c.schema(identity, pointer=pointer, max_bytes=2048, limit=3, cursor=cursor)
                self.assertLessEqual(response_bytes(response), 2048)
            if response['container'] == 'array':
                return [read(member['pointer']) for member in members]
            return {member['key']: read(member['pointer']) for member in members}
        self.assertEqual(read(), export_schema('freecad', authored=True, version='schemaxis.freecad/1'))

    def test_selected_node_pointer_and_references_are_exact(self):
        c = self.catalogue
        for provider, name in [('freecad', 'box'), ('paraview', 'slice')]:
            identity = operation_id(provider, name)
            reference = c.describe(identity)['sections']['schema']['authoredDocument']
            pointer = reference['nodePointer']
            self.assertTrue(pointer.startswith('/properties/nodes/'))
            fragment = c.schema(identity, pointer=pointer, max_bytes=65536)
            self.assertEqual(fragment['mode'], 'value')
            schema = export_schema(provider, authored=True, version=reference['documentVersion'])
            value = schema
            for token in pointer.split('/')[1:]:
                value = value[int(token)] if isinstance(value, list) else value[token]
            self.assertEqual(fragment['value'], value)
            self.assertIn('filter', value['properties'])
            self.assertIn('id', value['properties'])
            self.assertIn('options', value['properties'])
            self.assertNotEqual(pointer.rsplit('/', 1)[-1], 'if')
            self.assertEqual(c.schema(identity, pointer='/$defs/json', max_bytes=65536)['value'],
                             schema['$defs']['json'])

    def test_schema_pointer_faults_and_cursor_scope(self):
        c, identity = self.catalogue, 'operation/freecad/box'
        for pointer in ('not-a-pointer', '/absent', '/properties/nodes/anyOf/99', '/properties/~2x', '/required/00'):
            self.assertFault('INVALID_SCHEMA_POINTER', lambda: c.schema(identity, pointer=pointer))
        self.assertFault('INVALID_CURSOR', lambda: c.schema(identity, cursor='bad'))
        cursor = c.schema(identity, limit=1, max_bytes=2048)['page']['nextCursor']
        self.assertFault('INVALID_CURSOR', lambda: c.schema(identity, pointer='/$defs', cursor=cursor))
        self.assertFault('INVALID_CURSOR', lambda: c.schema('operation/freecad/extrude', cursor=cursor))
        self.assertFault('NOT_AN_OPERATION', lambda: c.schema('root'))

    def test_status_axes_remain_independent_and_unknown(self):
        result = self.catalogue.describe('operation/paraview/pvPlotOverLine')
        self.assertEqual(result['capability']['status'], {
            'declaration': 'declared', 'runtimeAvailability': 'unknown',
            'qualification': 'unknown', 'inputCompatibility': 'unknown'})
        self.assertEqual(result['sections']['examples']['items'], [])

    def test_revision_and_contract_identity_track_changed_contracts(self):
        original = registry.declarations
        def changed(provider):
            result = original(provider)
            if provider == 'freecad':
                result['box']['options']['length']['value']['maximum'] = 99999
            return result
        with patch.object(registry, 'declarations', side_effect=changed):
            c = CapabilityCatalogue()
        self.assertNotEqual(c.revision, self.catalogue.revision)
        identity = 'operation/freecad/box'
        self.assertNotEqual(c.describe(identity)['contractDigest'], self.catalogue.describe(identity)['contractDigest'])

    def test_metadata_cannot_advertise_undeclared_operations(self):
        original = registry.binding
        def bad(path):
            if path.endswith('.capabilities:catalogue'):
                return lambda: {'operations': {'invented': {'purpose': 'not supported'}}}
            return original(path)
        with patch.object(registry, 'binding', side_effect=bad):
            self.assertFault('INVALID_CAPABILITY_METADATA', CapabilityCatalogue)

    def test_curated_references_exist_and_examples_plan(self):
        c, count = self.catalogue, 0
        for provider, metadata in c._metadata.items():
            for ref in metadata.get('references', []):
                self.assertTrue((ROOT/ref.split('#')[0].split(':')[0]).is_file(), ref)
            for operation, item in metadata.get('operations', {}).items():
                for example in item.get('examples', []):
                    if 'document' in example:
                        registry.plan(example['document'])
                        count += 1
                    if 'reference' in example:
                        self.assertTrue((ROOT/example['reference']).is_file())
        self.assertGreaterEqual(count, 5)

    def test_public_cli_and_planning_never_import_or_launch_native_apps(self):
        script = r'''
import importlib.abc, json, sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'bpy','paraview','vtk','vtkmodules','FreeCAD','FreeCADGui','Part','Mesh','Sketcher','PySide','PySide2'}:
            raise AssertionError('native import: ' + fullname)
sys.meta_path.insert(0, NoNative())
def audit(event, args):
    if event in {'subprocess.Popen','os.system','os.posix_spawn','os.fork','os.exec'}:
        raise AssertionError('native process: ' + event)
sys.addaudithook(audit)
from schemaxis.__main__ import main
from schemaxis.adaptors.registry import plan
def cli(*args):
    sys.argv = ['schemaxis', *args]
    return main()
assert cli('capabilities', 'browse')['items']
assert cli('capabilities', 'schema', 'operation/freecad/box', '--pointer', '/required')['value']
assert cli('capabilities', 'search', 'plane', '--scope', 'domain/data-analysis')['items']
detail = cli('capabilities', 'describe', 'operation/freecad/box')['sections']
declaration = detail['declaration']
options = {key: value['value']['default'] for key, value in declaration['options'].items()}
options['length'] = 25
node = {'id': 'body', 'filter': detail['provenance']['operationKey'], 'options': options}
document = {'version': detail['requirements']['documentVersion'], 'nodes': [node], 'output': 'body'}
assert plan(document)['nodes'][0]['options']['length'] == 25
assert cli('describe', 'box', '--provider', 'freecad') == declaration
assert cli('query', '--operations', 'box')['supported']
assert cli('schema', '--provider', 'freecad', '--operation', 'box') == detail['schema']['literalOptions']
assert cli(*detail['schema']['authoredDocument']['command'][1:])['properties']['version']['const'] == document['version']
assert cli('discover')['providers']
'''
        completed = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                   env={**os.environ, 'PYTHONPATH': str(ROOT/'src')},
                                   text=True, capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_cli_fault_exit_and_byte_budget(self):
        for args, expected in [(['browse', '--max-bytes', '2048'], 0),
                               (['describe', 'box'], 1), (['browse', '--cursor', 'invalid'], 1)]:
            result = subprocess.run([sys.executable, '-m', 'schemaxis', 'capabilities', *args],
                                    cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT/'src')},
                                    text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            value = json.loads(result.stdout)
            if expected:
                self.assertTrue(value['fault']['recovery'])
            else:
                self.assertLessEqual(len(result.stdout.encode()), 2048)
                self.assertTrue(value['page']['hasMore'])
