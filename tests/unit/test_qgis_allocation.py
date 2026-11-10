"""Host-only tamper boundary of the retained QGIS publication verifier.

These tests construct hand-made evidence directories; they do not import QGIS and
make no native qualification claim.
"""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from schemaxis.adaptors.qgis import adaptor
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'examples/schemaxis/fixtures/qgis/assets.geojson'


class RetainedEvidenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        document = json.loads((ROOT / 'examples/schemaxis/qgis-attributes.json').read_text())
        document['nodes'][0]['options']['file'] = str(FIXTURE)
        document['preview'] = False
        self.document = document
        self.plan = adaptor.plan(document)
        retained = 'input-' + document['nodes'][0]['id'] + '.geojson'
        shutil.copyfile(FIXTURE, self.directory / retained)
        ids = [node['id'] for node in self.plan['nodes']]
        node_snapshots = {identity: {'features': []} for identity in ids}
        files = {
            'authored.json': document, 'plan.json': self.plan,
            'result.json': {'status': 'succeeded', 'verified': True},
            'verification.json': {},
            'sources.json': {ids[0]: {'file': str(FIXTURE), 'retained': retained,
                                      'sha256': adaptor.file_digest(FIXTURE)}},
            'built.json': {'stage': 'build', 'pid': 1, 'plan': self.plan, 'runtime': '4.2.3',
                           'snapshot': {}, 'nodeSnapshots': node_snapshots,
                           'attributes': {i: {} for i in ids[1:]}},
            'reopened.json': {'stage': 'reopen', 'pid': 2, 'plan': self.plan, 'runtime': '4.2.3',
                              'snapshot': {}, 'projectReopened': True}}
        for name, value in files.items():
            self.write(name, value)
        for name in ('result.gpkg', 'project.qgz', 'worker.py', 'attribute_contract.py', 'attribute_worker.py'):
            (self.directory / name).write_text('x')
        for identity in ids:
            for extension in ('.csv', '.json', '.gpkg'):
                (self.directory / ('summary-' + identity + extension)).write_text('{}')

    def write(self, name, value):
        (self.directory / name).write_text(value if isinstance(value, str) else json.dumps(value))

    def assertFault(self, location, *words):
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(self.directory)
        fault = caught.exception.fault
        self.assertEqual(fault.code, 'VERIFICATION_FAILED')
        self.assertEqual(fault.location, location)
        self.assertTrue(fault.recovery)
        for word in words:
            self.assertIn(word, fault.message)
        return fault

    def test_non_object_receipts_are_malformed_not_tracebacks(self):
        for name in ('result.json', 'verification.json', 'sources.json', 'built.json', 'reopened.json'):
            for value in ([], None, '"x"', 3):
                with self.subTest(name=name, value=value):
                    original = (self.directory / name).read_text()
                    self.write(name, value)
                    try:
                        self.assertFault(name, 'JSON object')
                    finally:
                        self.write(name, original)

    def test_malformed_and_missing_json_are_distinct(self):
        self.write('built.json', '{"stage": ')
        self.assertFault('built.json', 'not valid JSON')
        self.write('built.json', '[' * 100000)
        self.assertFault('built.json', 'not valid JSON')
        (self.directory / 'reopened.json').unlink()
        self.assertFault('reopened.json', 'missing')

    def test_tampered_nonfinite_attributes_fail_structurally(self):
        built = json.loads((self.directory / 'built.json').read_text())
        identity = self.plan['nodes'][0]['id']
        built['nodeSnapshots'][identity]['features'] = [{'attributes': {'score': 1}}]
        text = json.dumps(built).replace('"score": 1', '"score": Infinity')
        self.write('built.json', text)
        fault = self.assertFault('$')
        self.assertIn('OverflowError', fault.message)

    def test_unreadable_retained_attribute_container_is_structural(self):
        built = json.loads((self.directory / 'built.json').read_text())
        identity = self.plan['nodes'][0]['id']
        built['nodeSnapshots'][identity] = {'features': [{'attributes': 'not a row'}]}
        self.write('built.json', built)
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.verify(self.directory)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')


if __name__ == '__main__':
    unittest.main()
