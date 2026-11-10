"""Hostile retained Pandoc evidence: structured faults, hidden content and native-build limits."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from schemaxis.adaptors.pandoc import adaptor
from schemaxis.adaptors.pandoc.inspection import html_report
from schemaxis.core.faults import Fault, SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import pandoc_docx_fixture as fixture  # noqa: E402

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
MODEL = [{'kind': 'heading', 'level': 1, 'text': 'Result'}, {'kind': 'paragraph', 'text': 'Literal <value> & units'}]
APPROVED = 'p {margin: 0}'
HTML = ('<!DOCTYPE html>\n<html><head><title>Report</title><style>' + APPROVED + '</style></head><body>'
        '<header><h1>Report</h1></header><h1>Result</h1><p>Literal &lt;value&gt; &amp; units</p></body></html>')
RELATIONSHIP = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
BODY = ('<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>Report</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Result</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Literal &lt;value&gt; &amp; units</w:t></w:r></w:p>'
        '<w:sectPr/>')
DOCX = fixture.parts(BODY)


def package(change=None, add=None, drop=()): return fixture.build(BODY, change=change, add=add, drop=drop)


def docx_report(data, title, model): fixture.check(data, title, model)


class PandocEvidence(unittest.TestCase):
    def refused(self, action, fragment=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        if fragment: self.assertIn(fragment, caught.exception.fault.message)
        return caught.exception.fault

    def html(self, source):
        approved = __import__('hashlib').sha256(APPROVED.encode()).hexdigest()
        with patch('schemaxis.adaptors.pandoc.inspection.QUALIFIED_STYLESHEET_SHA256', approved):
            html_report(source, 'Report', MODEL)

    def test_html_reference_shape_and_content_outside_reported_elements(self):
        self.html(HTML)
        for label, old, new in [
                ('text after body', '</body>', '</body>FAKE VISIBLE CONCLUSION'),
                ('element after body', '</body>', '</body><p>FAKE CONCLUSION</p>'),
                ('element between head and body', '<body>', '<div>FAKE</div><body>'),
                ('text in head', '<title>', 'FAKE<title>'),
                ('text in body', '<header>', 'FAKE<header>'),
                ('text in table', '<p>', '<table>FAKE<tbody><tr><td>x</td></tr></tbody></table><p>'),
                ('trailing element', '</html>', '</html><p>FAKE</p>'),
                ('comment', '<body>', '<body><!-- hidden -->'),
                ('processing instruction', '<body>', '<body><?php echo 1 ?>'),
                ('document type', '<!DOCTYPE html>', '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0//EN">'),
                ('unclosed element', '</body>', '<p>open</body>')]:
            with self.subTest(label): self.refused(lambda: self.html(HTML.replace(old, new, 1)))
        with self.subTest('depth'):
            self.refused(lambda: self.html(HTML.replace('<body>', '<body>' + '<p>' * 40, 1).replace('</body>', '</p>' * 40 + '</body>')), 'nesting')

    def test_docx_reference_shape_and_hidden_package_content(self):
        docx_report(package(), 'Report', MODEL)
        header = b'<w:hdr xmlns:w="%s"><w:p><w:r><w:t>FAKE</w:t></w:r></w:p></w:hdr>' % W.encode()
        external = (b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="x" Type="%s%s" '
                    b'Target="https://invalid.example/a" TargetMode="External"/></Relationships>')
        internal = (b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="x" Type="%sattachedTemplate" '
                    b'Target="template.dotm"/></Relationships>')
        document = DOCX['word/document.xml']
        for label, data in {
                'macro': package(add={'word/vbaProject.bin': b'MZ'}),
                'embedded object': package(add={'word/embeddings/oleObject1.bin': b'x'}),
                'custom xml': package(add={'customXml/item1.xml': b'<x>hidden</x>'}),
                'header part': package(add={'word/header1.xml': header}),
                'unreferenced non-png media': package(add={'word/media/x.svg': b'<svg/>'}),
                'external relationship in package root': package(change={'_rels/.rels': external % (RELATIONSHIP.encode(), b'hyperlink')}),
                'internal attached template': package(change={'word/_rels/document.xml.rels': internal % RELATIONSHIP.encode()}),
                'header reference': package(change={'word/document.xml': document.replace(b'<w:sectPr/>', b'<w:sectPr><w:headerReference/></w:sectPr>')}),
                'text in footnotes': package(add={'word/footnotes.xml': b'<w:footnotes xmlns:w="%s"><w:footnote><w:p><w:r><w:t>FAKE</w:t></w:r></w:p></w:footnote></w:footnotes>' % W.encode()}),
                'huge extent': package(change={'word/document.xml': document.replace(
                    b'<w:p><w:r>', b'<w:p><w:r><w:drawing><wp:extent xmlns:wp="x" cx="' + b'9' * 400 + b'" cy="1"/><a:blip xmlns:a="x" xmlns:r="x"/></w:drawing></w:r></w:p><w:p><w:r>', 1)}),
                'not a zip': b'PK\x03\x04 truncated'}.items():
            with self.subTest(label): self.refused(lambda: docx_report(data, 'Report', MODEL))

    def test_docx_encrypted_or_corrupt_members_are_structured(self):
        data = bytearray(package())
        zipped = zipfile.ZipFile(io.BytesIO(bytes(data))).getinfo('word/document.xml')
        corrupt = bytearray(data); corrupt[zipped.header_offset + 30 + len(zipped.filename) + 4] ^= 0xFF
        encrypted = bytearray(data); encrypted[zipped.header_offset + 6] |= 1
        position = bytes(encrypted).find(b'PK\x01\x02' + b'\x14')
        while position >= 0:
            if bytes(encrypted[position + 46:position + 46 + len(zipped.filename)]) == zipped.filename.encode(): encrypted[position + 8] |= 1
            position = bytes(encrypted).find(b'PK\x01\x02', position + 4)
        for label, blob in (('corrupt stream', corrupt), ('encrypted member', encrypted)):
            with self.subTest(label): self.refused(lambda: docx_report(bytes(blob), 'Report', MODEL))

    def test_retained_json_is_strict_bounded_and_structured(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for label, text in {'deep': '[' * 100000 + ']' * 100000, 'duplicate key': '{"a":1,"a":2}', 'NaN': '{"a":NaN}',
                                'Infinity': '[Infinity]', 'invalid': '{', 'invalid UTF-8': None}.items():
                (directory/'x.json').write_bytes(b'\xff\xfe\x00' if text is None else text.encode())
                with self.subTest(label): self.refused(lambda: adaptor.read(directory, 'x.json'))
            (directory/'x.json').write_text('{"a":[1,2,{"b":null}]}')
            self.assertEqual(adaptor.read(directory, 'x.json'), {'a': [1, 2, {'b': None}]})

    def test_verify_converts_unexpected_inspection_errors(self):
        for error in (RecursionError('deep'), OverflowError('big'), RuntimeError('encrypted'), ZeroDivisionError(), EOFError()):
            with self.subTest(type(error).__name__), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)/'report'; directory.mkdir(); (directory/'authored.json').write_text('{}')
                with patch.object(adaptor, 'plan', side_effect=error):
                    fault = self.refused(lambda: adaptor._native_verify(directory), type(error).__name__)
                self.assertEqual(fault.phase, 'pipeline')

    def test_member_check_rejects_undeclared_and_unreferenced_files(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in ('report.html', 'verification.json', 'report.html.metadata.json', 'publication-metadata.json'): (directory/name).write_text('x')
            (directory/'native-data').mkdir(); (directory/'.dispatch').mkdir()
            adaptor.members(directory, {'report.html'})
            # The workflow coordinator's attempt record is framework-owned, but must be a regular file.
            (directory/'job.json').write_text('{}')
            adaptor.members(directory, {'report.html'})
            (directory/'job.json').unlink(); (directory/'job.json').symlink_to(directory/'report.html')
            self.refused(lambda: adaptor.members(directory, {'report.html'}), 'regular file')
            (directory/'job.json').unlink()
            (directory/'report.pdf').write_text('fake')
            self.refused(lambda: adaptor.members(directory, {'report.html'}), 'undeclared')
            (directory/'report.pdf').unlink()
            (directory/'unknown.metadata.json').write_text('{}')
            self.refused(lambda: adaptor.members(directory, {'report.html'}), 'undeclared')
            (directory/'unknown.metadata.json').unlink()
            (directory/'reopened'/'media').mkdir(parents=True)
            (directory/'reopened'/'media'/'a.png').write_bytes(b'x')
            adaptor.members(directory, {'report.html', 'reopened/media/a.png'})
            (directory/'reopened'/'media'/'extra.png').write_bytes(b'x')
            self.refused(lambda: adaptor.members(directory, {'report.html', 'reopened/media/a.png'}), 'membership')
            (directory/'reopened'/'media'/'extra.png').unlink()
            (directory/'reopened'/'media'/'link.png').symlink_to(directory/'report.html')
            self.refused(lambda: adaptor.members(directory, {'report.html', 'reopened/media/a.png'}), 'symlink')

    def test_incomplete_native_build_has_a_specific_structured_fault(self):
        observed = {'exitCode': 97, 'stderr': 'Could not find data file data/data/docx/[Content_Types].xml\n'}
        failure = SchemaxisError(Fault('RUNNER_FAILED', 'native execution did not complete', 'x', 'pipeline', observed=observed))
        with tempfile.TemporaryDirectory() as temp, patch.object(adaptor, 'execute', side_effect=failure):
            with self.assertRaises(SchemaxisError) as caught:
                adaptor.launch(Path(temp), 'docx', ['/x/pandoc'], {'sections': []}, 1e12)
        fault = caught.exception.fault
        self.assertEqual((fault.code, fault.location), ('UNSUPPORTED_NATIVE_BUILD', 'docx'))
        self.assertIn('official self-contained', fault.message); self.assertIn('Could not find data file', fault.observed['stderr'])
        other = SchemaxisError(Fault('RUNNER_FAILED', 'native execution did not complete', 'x', 'pipeline', observed={'stderr': 'other'}))
        with tempfile.TemporaryDirectory() as temp, patch.object(adaptor, 'execute', side_effect=other):
            with self.assertRaises(SchemaxisError) as caught: adaptor.launch(Path(temp), 'docx', ['/x/pandoc'], {'sections': []}, 1e12)
        self.assertEqual(caught.exception.fault.code, 'RUNNER_FAILED')

    def test_fresh_directory_race_is_structured(self):
        document = json.loads((Path(__file__).resolve().parents[2]/'examples/schemaxis/pandoc-report.json').read_text())
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'report'
            real = Path.mkdir
            def racing(self, *args, **kwargs):
                real(self, *args, **kwargs); raise FileExistsError(str(self))
            with patch.object(Path, 'mkdir', racing), patch.object(adaptor, 'plan', return_value={'sections': []}):
                with self.assertRaises(SchemaxisError) as caught: adaptor._native_run(document, target, executable='/bin/true', timeout=5)
            self.assertEqual(caught.exception.fault.code, 'OUTPUT_EXISTS')


if __name__ == '__main__': unittest.main()
