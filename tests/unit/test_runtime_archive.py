"""Native runtime archives carry the licence notices of the code they bundle."""
from importlib.metadata import PathDistribution
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from schemaxis import artifacts

ROOT = Path(__file__).resolve().parents[2]


def archived():
    with zipfile.ZipFile(io.BytesIO(artifacts.runtime_archive())) as archive:
        return {name: archive.read(name) for name in archive.namelist()
                if name.startswith(artifacts.LICENCES + '/')}


class RuntimeArchiveLicenceTests(unittest.TestCase):
    def test_source_checkout_notices_are_archived(self):
        expected = {'LICENSE', 'NOTICE', 'COPYRIGHT', *('LICENSES/' + p.name for p in (ROOT/'LICENSES').iterdir())}
        found = archived()
        self.assertEqual({name.partition('/')[2] for name in found}, expected)
        for name in expected:
            self.assertEqual(found[artifacts.LICENCES + '/' + name], (ROOT/name).read_bytes())

    def test_installed_distribution_notices_are_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            info = Path(tmp)/'schemaxis-0.4.0.dist-info'
            (info/'licenses/LICENSES').mkdir(parents=True)
            (info/'METADATA').write_text('Metadata-Version: 2.4\nName: schemaxis\nVersion: 0.4.0\n'
                                         'License-File: LICENSE\nLicense-File: NOTICE\n'
                                         'License-File: LICENSES/yaml-ISC.txt\n')
            for name in ('LICENSE', 'NOTICE', 'LICENSES/yaml-ISC.txt'):
                (info/'licenses'/name).write_text('installed ' + name + '\n')
            with patch.object(artifacts, '_checkout_root', return_value=None), \
                    patch.object(artifacts, '_distribution', return_value=PathDistribution(info)):
                found = archived()
        self.assertEqual(found, {artifacts.LICENCES + '/' + name: ('installed ' + name + '\n').encode()
                                 for name in ('LICENSE', 'NOTICE', 'LICENSES/yaml-ISC.txt')})


if __name__ == '__main__':
    unittest.main()
