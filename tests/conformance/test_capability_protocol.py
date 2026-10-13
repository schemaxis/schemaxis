"""Host-only conformance of registered adaptors to progressive discovery."""
import unittest

from schemaxis.adaptors import registry
from schemaxis.capabilities import CapabilityCatalogue, operation_id, response_bytes
from schemaxis.schema import export_schema


class CapabilityProtocolConformanceTests(unittest.TestCase):
    def test_every_registered_declaration_is_reachable_without_invented_operations(self):
        catalogue = CapabilityCatalogue()
        for provider in registry.ADAPTORS:
            with self.subTest(provider=provider):
                seen, cursor = [], None
                while True:
                    result = catalogue.search('', scope='app/' + provider, limit=100, cursor=cursor)
                    self.assertLessEqual(response_bytes(result), 8192)
                    seen.extend(item['id'] for item in result['items'])
                    cursor = result['page']['nextCursor']
                    if cursor is None:
                        break
                expected = sorted(operation_id(provider, name) for name in registry.declarations(provider))
                self.assertEqual(seen, expected)

    def test_all_operation_options_and_bindings_are_returned_intact(self):
        catalogue = CapabilityCatalogue()
        for provider in registry.ADAPTORS:
            for name, declaration in registry.declarations(provider).items():
                with self.subTest(provider=provider, operation=name):
                    contract = catalogue.describe(operation_id(provider, name))['sections']
                    self.assertEqual(contract['declaration'], declaration)
                    self.assertEqual(contract['schema']['literalOptions'], export_schema(provider, operation=name))
                    self.assertEqual(contract['requirements']['checks'], declaration.get('checks', []))
                    self.assertEqual(contract['requirements']['requires'], declaration.get('requires', []))
