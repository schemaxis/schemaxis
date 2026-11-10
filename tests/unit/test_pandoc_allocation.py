"""Image width is accepted at planning only where the native writers can reproduce it."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.pandoc import adaptor
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
IMAGE_AT = '$.sections[1].content[1]'


class PandocImageWidth(unittest.TestCase):
    def document(self, width=None):
        document = json.loads((ROOT/'examples/schemaxis/pandoc-report.json').read_text())
        if width is not None: document['sections'][1]['content'][1]['widthMm'] = width
        return document

    def fault(self, document, code):
        with self.assertRaises(SchemaxisError) as caught: adaptor.plan(document)
        self.assertEqual(caught.exception.fault.code, code)
        return caught.exception.fault

    def width(self, document):
        return adaptor.plan(document)['sections'][1]['content'][1]['widthMm']

    def test_width_above_the_docx_writer_page_limit_is_refused_before_native_launch(self):
        # Pandoc 3.12.1 clamps DOCX pictures to 5334000 EMU (148.17 mm); 149 and 150 mm were
        # accepted by the plan yet always failed verification after a full native run.
        for width in (148.17, 149, 150):
            with self.subTest(width=width): self.fault(self.document(width), 'INVALID_ARGUMENT')
        for width in (10, 10.0, 80, 148, 148.0):
            with self.subTest(width=width): self.assertEqual(self.width(self.document(width)), width)

    def test_width_precision_the_html_writer_cannot_round_trip_is_refused(self):
        # Pandoc writes HTML widths to five decimals, so 12.3456789 reads back as 12.34568.
        for width in (12.3456789, 33.333333333333336, 10.000001, 80.123456):
            with self.subTest(width=width):
                fault = self.fault(self.document(width), 'INVALID_REPORT_IMAGE')
                self.assertEqual(fault.location, IMAGE_AT + '.widthMm')
                self.assertIn('decimal', fault.message)
        for width in (12.34567, 80.001, 12.5, 1e1, 99.99999):
            with self.subTest(width=width): self.assertEqual(self.width(self.document(width)), width)

    def test_generated_schema_declares_the_same_maximum(self):
        image = adaptor.schema()['properties']['sections']['items']['properties']['content']['items']['anyOf'][2]
        self.assertEqual(image['properties']['widthMm']['maximum'], 148)
        self.assertEqual(image['properties']['widthMm']['minimum'], 10)

    def test_retained_reports_keep_the_rule_they_were_planned_under(self):
        # A retained authored.json is re-planned during verify; the strict evidence inspection
        # (not the new authoring limit) decides whether the retained publication still verifies.
        for width in (149, 150, 12.3456789):
            with self.subTest(width=width):
                self.assertEqual(self.width_retained(self.document(width)), width)
        document = self.document(149)
        with patch.object(adaptor, 'plan', wraps=adaptor.plan) as spy, self.assertRaises(SchemaxisError):
            adaptor.verify(self.empty_directory(document))
        self.assertTrue(spy.called and spy.call_args.kwargs.get('retained') is True)

    def width_retained(self, document):
        return adaptor.plan(document, retained=True)['sections'][1]['content'][1]['widthMm']

    def empty_directory(self, document):
        directory = Path(tempfile.mkdtemp(prefix='pandoc-retained-'))
        self.addCleanup(shutil.rmtree, directory, True)
        (directory/'authored.json').write_text(json.dumps(document))
        return directory

    def test_retained_path_still_refuses_widths_no_schema_ever_allowed(self):
        for width in (9, 151, True, float('nan')):
            with self.subTest(width=width), self.assertRaises(SchemaxisError):
                adaptor.plan(self.document(width), retained=True)


if __name__ == '__main__':
    unittest.main()
