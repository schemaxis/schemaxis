"""Regression checks for bounded native discovery and the relocated consumer boundary."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from schemaxis.adaptors.paraview import handback
from schemaxis.adaptors.paraview.handback_native import file_properties
from schemaxis.core.faults import SchemaxisError
from tests.unit.test_paraview_handback import bundle, proof, sha


class Iterator:
    def __init__(self, entries):
        self.entries = entries

    def Begin(self):
        self.index = 0

    def IsAtEnd(self):
        return self.index == len(self.entries)

    def Next(self):
        self.index += 1

    def GetKey(self):
        return self.entries[self.index][0]

    def GetProperty(self):
        return self.entries[self.index][1]

    def GetDomain(self):
        return self.entries[self.index]


class Domain:
    def IsA(self, name):
        return name == 'vtkSMFileListDomain'


class FileProperty:
    def __init__(self, values):
        self.values = values

    def IsA(self, name):
        return name == 'vtkSMStringVectorProperty'

    def NewDomainIterator(self):
        return Iterator([Domain()])

    def GetNumberOfElements(self):
        return len(self.values)

    def GetElement(self, index):
        return self.values[index]


class ProxyProperty:
    def __init__(self, proxies):
        self.proxies = proxies

    def IsA(self, name):
        return name == 'vtkSMProxyProperty'

    def GetNumberOfProxies(self):
        return len(self.proxies)

    def GetProxy(self, index):
        return self.proxies[index]


class Proxy:
    def __init__(self, **properties):
        self.properties = list(properties.items())

    def NewPropertyIterator(self):
        return Iterator(self.properties)


class NativeDiscovery(unittest.TestCase):
    def test_supported_file_domains_are_complete(self):
        nested = Proxy(AuxiliaryFiles=FileProperty(['/owned-test/leaf.dat']))
        self.assertEqual(file_properties(Proxy(Child=ProxyProperty([nested]))),
                         {'Child[0].AuxiliaryFiles': ['/owned-test/leaf.dat']})
        self.assertEqual(file_properties(Proxy(AuxiliaryFiles=FileProperty([''] * 64))),
                         {'AuxiliaryFiles': []})

    def test_native_discovery_refuses_instead_of_truncating(self):
        leaf = Proxy(AuxiliaryFiles=FileProperty(['/owned-test/outside.dat']))
        cases = {
            'file value beyond bound': Proxy(AuxiliaryFiles=FileProperty([''] * 64 + ['/owned-test/outside.dat'])),
            'proxy beyond bound': Proxy(Children=ProxyProperty([Proxy()] * 16 + [leaf])),
            'nested file beyond depth': Proxy(Child=ProxyProperty([
                Proxy(Child=ProxyProperty([Proxy(Child=ProxyProperty([leaf]))]))])),
        }
        for label, proxy in cases.items():
            with self.subTest(label):
                with self.assertRaises(SchemaxisError) as error:
                    file_properties(proxy)
                self.assertEqual(error.exception.fault.code, 'UNSUPPORTED_STATE_BUNDLE')


class EvidenceBoundary(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root, self.manifest = bundle(self.temporary.name)

    def test_huge_integer_time_is_a_structured_fault(self):
        manifest = {**self.manifest, 'time': 10 ** 400}
        (self.root / handback.MANIFEST).write_text(json.dumps(manifest))
        with self.assertRaises(SchemaxisError) as error:
            handback.check_bundle(self.root)
        self.assertEqual(error.exception.fault.code, 'VERIFICATION_FAILED')

    def test_deep_property_evidence_is_a_structured_fault(self):
        manifest = copy.deepcopy(self.manifest)
        loaded = proof(self.root, manifest, Path(self.temporary.name) / 'relocated')
        value = 0
        for _ in range(2000):
            value = [value]
        manifest['pipeline']['half']['properties'][0]['value'] = value
        loaded['pipeline']['half']['properties'][0]['value'] = value
        with self.assertRaises(SchemaxisError) as error:
            handback.verify_reload(loaded, manifest, sha(self.root / handback.MANIFEST))
        self.assertEqual(error.exception.fault.code, 'VERIFICATION_FAILED')

    def test_relocated_copy_is_rechecked_after_consumer_and_original_restored(self):
        manifest_digest = sha(self.root / handback.MANIFEST)
        original_data = (self.root / self.manifest['members'][0]['path']).read_bytes()
        artifact = {'identity': {'kind': 'state-bundle'}, 'file': str(self.root / handback.STATE),
                    'manifestSha256': manifest_digest}
        observed = []

        class Submission:
            def to_dict(self):
                return {'exitCode': 0}

        def consumer(source):
            relocated, original, _, _ = re.findall(r"'([^']+)'", source)
            observed.append(Path(relocated))
            self.assertFalse(Path(original).exists())
            target = Path(relocated) / self.manifest['members'][0]['path']
            payload = target.read_bytes()
            target.write_bytes(payload.replace(b'PolyData', b'PolyDatb'))
            self.assertEqual(target.stat().st_size, len(payload))
            return Submission()

        with self.assertRaises(SchemaxisError) as error:
            handback.reload(self.temporary.name, {'artifacts': [artifact]}, consumer)
        self.assertEqual(error.exception.fault.code, 'VERIFICATION_FAILED')
        self.assertTrue(self.root.is_dir())
        self.assertTrue(observed[0].is_dir(), 'failed reload evidence should remain for diagnosis')
        self.assertEqual(sha(self.root / handback.MANIFEST), manifest_digest)
        self.assertEqual((self.root / self.manifest['members'][0]['path']).read_bytes(), original_data)
        handback.check_bundle(self.root, manifest_digest)


class Submission:
    def to_dict(self):
        return {'exitCode': 0}


class PinnedReload(unittest.TestCase):
    """The receipt's manifest digest is required before launch and pinned in the fresh process."""

    BAD = {'missing': ..., 'null': None, 'empty': '', 'short': '0' * 63, 'upper': 'A' * 64, 'integer': 7,
           'wrong': '0' * 64}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root, self.manifest = bundle(self.temporary.name)
        self.digest = sha(self.root / handback.MANIFEST)

    def snapshot(self):
        return sorted((str(path.relative_to(self.directory)), path.is_file() and sha(path))
                      for path in self.directory.rglob('*'))

    def test_missing_or_invalid_digest_refuses_before_any_launch(self):
        before = self.snapshot()
        for label, value in self.BAD.items():
            with self.subTest(label):
                artifact = {'identity': {'kind': 'state-bundle'}, 'file': str(self.root / handback.STATE)}
                if value is not ...:
                    artifact['manifestSha256'] = value
                calls = []
                with self.assertRaises(SchemaxisError) as error:
                    handback.reload(self.directory, {'artifacts': [artifact]}, calls.append)
                self.assertEqual(error.exception.fault.code, 'VERIFICATION_FAILED')
                self.assertEqual(calls, [])
                self.assertEqual(self.snapshot(), before, 'nothing may be created, moved or changed')

    def test_child_invocation_carries_the_pinned_digest(self):
        artifact = {'identity': {'kind': 'state-bundle'}, 'file': str(self.root / handback.STATE),
                    'manifestSha256': self.digest}
        sources = []
        handback.reload(self.directory, {'artifacts': [artifact]}, lambda source: sources.append(source)
                        or Submission())
        source, = sources
        self.assertIn(f', {self.digest!r})\n', source)
        self.assertEqual(re.findall(r"'([^']+)'", source)[-1], self.digest)

    def child(self, digest):
        """Run the native child entry with ParaView imports trapped; return the import attempts."""
        import builtins
        import shutil
        from unittest import mock
        from schemaxis.adaptors.paraview import handback_native
        relocated = self.directory / 'moved' / 'bundle'
        if not relocated.exists():
            shutil.copytree(self.root, relocated)
        imported, real = [], builtins.__import__

        def trap(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith('paraview') or (level and name == 'native_run'):
                imported.append(name)
                raise ImportError('native import trapped by test')
            return real(name, globals, locals, fromlist, level)
        withheld = self.directory / 'withheld-original'
        with mock.patch('builtins.__import__', trap), self.assertRaises(Exception) as error:
            handback_native.reload_bundle(relocated, withheld, self.directory / 'proof.json', *digest)
        return imported, error.exception, json.loads((self.directory / 'proof.json').read_text())

    def test_child_refuses_unpinned_or_mismatched_copy_before_native_import(self):
        for label, value in self.BAD.items():
            with self.subTest(label):
                imported, error, evidence = self.child(() if value is ... else (value,))
                self.assertEqual(imported, [])
                self.assertIsInstance(error, SchemaxisError)
                self.assertEqual(error.fault.code, 'VERIFICATION_FAILED')
                self.assertEqual((evidence['status'], evidence['fault']['code']), ('failed', 'VERIFICATION_FAILED'))
                self.assertNotIn('manifestSha256', evidence)

    def test_child_with_matching_pin_proceeds_to_native_load(self):
        imported, error, evidence = self.child((self.digest,))
        self.assertEqual(imported, ['paraview'])
        self.assertIsInstance(error, ImportError)
        self.assertEqual(evidence['manifestSha256'], self.digest)


if __name__ == '__main__':
    unittest.main()
