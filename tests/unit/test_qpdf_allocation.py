"""Host-only checks that the published QPDF assembly summary identifies the captured source bytes.

Native stages are replaced by canned observations; native acceptance is a separate tool.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_qpdf import MEDIA, code_of, document, record  # noqa: E402

from schemaxis.adaptors.qpdf import adaptor, inspection  # noqa: E402

LEGACY = 'schemaxis.qpdf.summary/1'
CURRENT = 'schemaxis.qpdf.summary/2'
PATHS = {'qpdf': '/q', 'mupdf': '/m'}


class FakeNative:
    """Patches every native stage with canned results that depend only on the plan."""

    def __init__(self):
        self.admitted = {'a': inspection.admit_source(document([{}], label='a'), (1,))}
        self.geometry = self.admitted['a']['geometry'][1]
        self.final = document([{'/MediaBox': MEDIA}, {'/MediaBox': MEDIA, '/Rotate': 90}], root={}, label='final')

    def observe(self, paths, work, tag, jobs):
        sizes = [inspection.predicted_pixels(self.geometry, 0), inspection.predicted_pixels(self.geometry, 90)]
        count = 1 if tag == 'e' else 2
        return [record(1 if tag == 'e' else index, self.geometry, rotate, size, count=count)
                for index, (rotate, size) in enumerate(zip((0, 90), sizes), 1)]

    def identity(self, paths, work, stem=''):
        for stage in ('version-qpdf' + stem, 'version-mupdf' + stem):
            self.launch(work, stage, [])
        return 'fake'

    def admit(self, paths, work, prepared):
        for entry in prepared['sources']:
            for stage in ('check-' + entry['name'], 'json-' + entry['name']):
                self.launch(work, stage, [])
        return self.admitted

    def launch(self, directory, stage, command, names=(), memory=1 << 30):
        for suffix in adaptor.STAGE_SUFFIXES:
            Path(directory, stage + suffix).write_bytes(b'{}' if suffix.endswith('.json') else b'')
        if stage == 'assemble':
            Path(directory, 'assembled.pdf').write_bytes(b'%PDF-1.7 assembled')
        return 0, b'', b''

    def __enter__(self):
        self.patches = [patch.object(adaptor, 'runtime', lambda *a, **k: PATHS), patch.object(adaptor, 'identity', self.identity),
                        patch.object(adaptor, 'admit_sources', self.admit), patch.object(adaptor, 'launch', self.launch),
                        patch.object(adaptor, 'inspect_pdf', lambda *a, **k: self.final), patch.object(adaptor, 'observe', self.observe)]
        for entry in self.patches:
            entry.start()
        return self

    def __exit__(self, *exc):
        for entry in self.patches:
            entry.stop()


def request(source):
    return {'version': adaptor.VERSION, 'operation': 'assemble', 'sources': [{'name': 'a', 'path': str(source)}],
            'pages': [{'source': 'a', 'page': 1}, {'source': 'a', 'page': 1, 'rotate': 90}]}


class QpdfSummarySourceIdentity(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def execute(self, name, data):
        source = self.root / (name + '-source.pdf')
        source.write_bytes(data)
        directory = self.root / name
        with FakeNative():
            adaptor._native_run(request(source), directory)
        return directory

    def verify(self, directory):
        with FakeNative():
            return adaptor.verify_semantic(directory, PATHS)

    def summary(self, directory):
        return json.loads((directory / 'assembly-summary.json').read_text())

    def rewrite(self, directory, summary):
        """Replace the summary and refresh the receipt digest, as a consistent forger or a legacy producer would."""
        data = adaptor.encode(summary)
        (directory / 'assembly-summary.json').write_bytes(data)
        receipt = json.loads((directory / 'verification.json').read_text())
        receipt['artifacts'] = adaptor.publications(directory, (directory / 'assembled.pdf').read_bytes(), data)
        (directory / 'verification.json').write_text(json.dumps(receipt))

    def test_summary_binds_each_page_source_to_the_captured_bytes(self):
        data = b'%PDF-1.4 first source'
        directory = self.execute('one', data)
        summary = self.summary(directory)
        self.assertEqual(summary['version'], CURRENT)
        self.assertEqual(summary['sources'], [{'name': 'a', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'pages': 1, 'discarded': []}])
        capture = json.loads((directory / 'capture.json').read_text())['sources']
        self.assertEqual([(s['name'], s['bytes'], s['sha256']) for s in capture],
                         [(s['name'], s['bytes'], s['sha256']) for s in summary['sources']])
        self.assertEqual(self.verify(directory)['verified'], True)

    def test_equal_appearance_from_different_bytes_is_distinguishable(self):
        first = self.summary(self.execute('one', b'%PDF-1.4 first source'))
        second = self.summary(self.execute('two', b'%PDF-1.4 second source, same pages'))
        self.assertEqual(first['pages'], second['pages'])
        self.assertNotEqual(first['sources'], second['sources'])

    def test_forged_source_digest_is_a_verification_failure(self):
        directory = self.execute('one', b'%PDF-1.4 first source')
        summary = self.summary(directory)
        summary['sources'][0]['sha256'] = '0' * 64
        self.rewrite(directory, summary)
        self.assertEqual(code_of(lambda: self.verify(directory)), 'VERIFICATION_FAILED')

    def test_genuine_legacy_summary_still_verifies(self):
        directory = self.execute('one', b'%PDF-1.4 first source')
        summary = self.summary(directory)
        summary['version'] = LEGACY
        for entry in summary['sources']:
            del entry['bytes'], entry['sha256']
        self.rewrite(directory, summary)
        self.assertTrue(self.verify(directory)['verified'])

    def test_version_and_shape_must_agree(self):
        directory = self.execute('one', b'%PDF-1.4 first source')
        current = self.summary(directory)
        legacy_with_digests = {**current, 'version': LEGACY}
        current_without_digests = {**current, 'sources': [{k: v for k, v in s.items() if k not in ('bytes', 'sha256')} for s in current['sources']]}
        for label, summary in {'legacy carrying digests': legacy_with_digests, 'current without digests': current_without_digests,
                               'unknown version': {**current, 'version': 'schemaxis.qpdf.summary/3'}}.items():
            with self.subTest(label):
                self.rewrite(directory, summary)
                self.assertEqual(code_of(lambda: self.verify(directory)), 'VERIFICATION_FAILED')

    def test_non_object_summary_is_a_verification_failure(self):
        directory = self.execute('one', b'%PDF-1.4 first source')
        for text in ('[]', 'null', '{}'):
            with self.subTest(text):
                (directory / 'assembly-summary.json').write_text(text)
                receipt = json.loads((directory / 'verification.json').read_text())
                receipt['artifacts'] = adaptor.publications(directory, (directory / 'assembled.pdf').read_bytes(), text.encode())
                (directory / 'verification.json').write_text(json.dumps(receipt))
                self.assertEqual(code_of(lambda: self.verify(directory)), 'VERIFICATION_FAILED')


if __name__ == '__main__':
    unittest.main()
