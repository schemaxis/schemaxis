"""Pandoc report `metadata` declaration: bounded authors and description carried by HTML, DOCX and EPUB 3, inspected independently.

Host tests only. A stand-in executable replays the genuine Pandoc 3.12.1 outputs kept in examples/schemaxis/fixtures/pandoc-metadata through the
unchanged stage launchers, receipts and inspectors; the real writers and readers run in tools/qualify_pandoc_metadata.py.
"""
import copy
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
import zipfile

from schemaxis.adaptors.pandoc import adaptor, epub, inspection
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import pandoc_epub_baseline as baseline  # noqa: E402
import pandoc_epub_fixture as earlier  # noqa: E402
import pandoc_metadata_fixture as fx  # noqa: E402
import test_pandoc_epub as zipbytes  # noqa: E402

SIMPLE = {'version': adaptor.VERSION, 'operation': 'report', 'title': 'Metadata report',
          'sections': [{'heading': 'Method', 'content': [{'kind': 'paragraph', 'text': 'Measured values.'}]}]}


def report(**metadata):
    document = copy.deepcopy(SIMPLE); document['metadata'] = metadata; return document


def fault(case, call, *args, **kwargs):
    with case.assertRaises(SchemaxisError) as caught: call(*args, **kwargs)
    return caught.exception.fault


def docx_rewrite(data, member, pattern, repl):
    """Rewrite one DOCX part by regular expression, requiring the pattern to match."""
    buffer = io.BytesIO(); found = 0
    with zipfile.ZipFile(io.BytesIO(data)) as old, zipfile.ZipFile(buffer, 'w') as new:
        for info in old.infolist():
            body = old.read(info.filename)
            if info.filename == member: body, n = re.subn(pattern.encode(), repl.encode(), body, count=1); found += n
            new.writestr(info, body)
    assert found, (member, pattern); return buffer.getvalue()


class Planning(unittest.TestCase):
    def test_absent_metadata_keeps_every_earlier_byte(self):
        with tempfile.TemporaryDirectory() as name: self.assertEqual(baseline.fingerprint(adaptor, name), zipbytes.BEFORE)
        plan = adaptor.plan(copy.deepcopy(SIMPLE))
        self.assertNotIn('metadata', plan); self.assertEqual(plan['losses'], adaptor.LOSSES)

    def test_valid_declarations_keep_order_and_text(self):
        for declared in ({'authors': ['B. Auteur', 'A. Example']}, {'description': 'A summary & <notes>.'}, {'authors': ['Solo'], 'description': 'x'},
                         {'authors': ['José Ångström', '李雷', 'محمد', 'a' * 100], 'description': ' '.join(['wörd'] * 100) + ' 🙂'}):
            plan = adaptor.plan(report(**declared))
            self.assertEqual(plan['metadata'], declared); self.assertEqual(plan['losses'][-1], adaptor.METADATA_LOSS)
        self.assertEqual(adaptor.plan(report(authors=['B', 'A']))['metadata']['authors'], ['B', 'A'])

    def test_every_malformed_declaration_is_refused_at_its_field(self):
        cases = [(True, 'INVALID_ARGUMENT', '$.metadata'), ('A', 'INVALID_ARGUMENT', '$.metadata'), (['A'], 'INVALID_ARGUMENT', '$.metadata'), (None, 'INVALID_ARGUMENT', '$.metadata'),
                 ({}, 'MISSING_ARGUMENT', '$.metadata'), ({'authors': ['A'], 'keywords': ['x']}, 'UNKNOWN_ARGUMENT', '$.metadata'), ({'author': ['A']}, 'UNKNOWN_ARGUMENT', '$.metadata'),
                 ({'authors': True}, 'INVALID_ARGUMENT', '$.metadata.authors'), ({'authors': 'A'}, 'INVALID_ARGUMENT', '$.metadata.authors'), ({'authors': {'0': 'A'}}, 'INVALID_ARGUMENT', '$.metadata.authors'),
                 ({'authors': []}, 'INVALID_ARGUMENT', '$.metadata.authors'), ({'authors': [f'a{n}' for n in range(9)]}, 'INVALID_ARGUMENT', '$.metadata.authors'),
                 ({'authors': [True]}, 'INVALID_ARGUMENT', '$.metadata.authors[0]'), ({'authors': ['A', 1]}, 'INVALID_ARGUMENT', '$.metadata.authors[1]'), ({'authors': [None]}, 'INVALID_ARGUMENT', '$.metadata.authors[0]'),
                 ({'authors': [['A']]}, 'INVALID_ARGUMENT', '$.metadata.authors[0]'), ({'authors': [{'name': 'A'}]}, 'INVALID_ARGUMENT', '$.metadata.authors[0]'), ({'authors': ['']}, 'INVALID_ARGUMENT', '$.metadata.authors[0]'),
                 ({'authors': ['a' * 101]}, 'INVALID_ARGUMENT', '$.metadata.authors[0]'), ({'authors': ['A; B']}, 'INVALID_ARGUMENT', '$.metadata.authors[0]'), ({'authors': ['A', ';']}, 'INVALID_ARGUMENT', '$.metadata.authors[1]'),
                 ({'authors': ['A', 'B', 'A']}, 'INVALID_ARGUMENT', '$.metadata.authors[2]'), ({'authors': [' A']}, 'INVALID_REPORT_TEXT', '$.metadata.authors[0]'), ({'authors': ['A ']}, 'INVALID_REPORT_TEXT', '$.metadata.authors[0]'),
                 ({'authors': ['A  B']}, 'INVALID_REPORT_TEXT', '$.metadata.authors[0]'), ({'authors': ['A\nB']}, 'INVALID_REPORT_TEXT', '$.metadata.authors[0]'), ({'authors': ['A\tB']}, 'INVALID_REPORT_TEXT', '$.metadata.authors[0]'),
                 ({'authors': ['A B']}, 'INVALID_REPORT_TEXT', '$.metadata.authors[0]'), ({'authors': ['A\x00']}, 'INVALID_REPORT_TEXT', '$.metadata.authors[0]'), ({'authors': ['a‮b']}, 'INVALID_REPORT_TEXT', '$.metadata.authors[0]'),
                 ({'description': True}, 'INVALID_ARGUMENT', '$.metadata.description'), ({'description': 1}, 'INVALID_ARGUMENT', '$.metadata.description'), ({'description': ['x']}, 'INVALID_ARGUMENT', '$.metadata.description'),
                 ({'description': None}, 'INVALID_ARGUMENT', '$.metadata.description'), ({'description': ''}, 'INVALID_ARGUMENT', '$.metadata.description'), ({'description': 'a' * 1001}, 'INVALID_ARGUMENT', '$.metadata.description'),
                 ({'description': 'a\nb'}, 'INVALID_REPORT_TEXT', '$.metadata.description'), ({'description': 'a\r'}, 'INVALID_REPORT_TEXT', '$.metadata.description'), ({'description': ' a'}, 'INVALID_REPORT_TEXT', '$.metadata.description'),
                 ({'description': 'a  b'}, 'INVALID_REPORT_TEXT', '$.metadata.description'), ({'description': 'a⁠b'}, 'INVALID_REPORT_TEXT', '$.metadata.description'), ({'description': 'a​b'}, 'INVALID_REPORT_TEXT', '$.metadata.description')]
        for value, code, location in cases:
            document = copy.deepcopy(SIMPLE); document['metadata'] = value
            error = fault(self, adaptor.plan, document)
            self.assertEqual((error.code, error.location), (code, location), (value, error.to_dict()))
            self.assertTrue(error.message, value)

    def test_boundaries_accept_the_longest_values_and_refuse_one_more(self):
        adaptor.plan(report(authors=[chr(0x4e00 + n) * 100 for n in range(8)], description='d' * 1000))
        for value in ({'authors': ['a' * 101]}, {'description': 'd' * 1001}, {'authors': [str(n) for n in range(9)]}): self.assertEqual(fault(self, adaptor.plan, report(**value)).code, 'INVALID_ARGUMENT')
        # Characters, not bytes, are counted.
        adaptor.plan(report(authors=['\U0001f642' * 100], description='日' * 1000))

    def test_semicolon_inside_a_description_is_plain_text(self):
        self.assertEqual(adaptor.plan(report(description='a; b; c'))['metadata'], {'description': 'a; b; c'})

    def test_equal_names_differing_in_case_or_marks_are_distinct_authors(self):
        adaptor.plan(report(authors=['A. Example', 'a. example', 'Zoë', 'Zoë']))

    def test_metadata_counts_toward_the_report_text_budget(self):
        authors, description = ['A' * 100], 'd' * 1000
        def sized(last):
            document = report(authors=authors, description=description)
            document['title'] = 'T'
            document['sections'] = [{'heading': 'H', 'content': [{'kind': 'paragraph', 'text': 'p' * 2048} for _ in range(31)] + [{'kind': 'paragraph', 'text': 'q' * last}]}]
            return document
        # 1 + 1 + 31 * 2048 + 946 + 1100 = 65536 exactly.
        adaptor.plan(sized(946)); self.assertEqual(fault(self, adaptor.plan, sized(947)).code, 'REPORT_RESOURCE_LIMIT')
        document = sized(946); del document['metadata']; adaptor.plan(sized(947) | {'metadata': {'authors': ['A' * 99], 'description': description}})
        document['sections'][0]['content'][-1]['text'] = 'q' * 947; adaptor.plan(document)

    def test_planning_is_immutable_and_deterministic(self):
        document = report(authors=['A', 'B'], description='d'); before = json.dumps(document, sort_keys=True)
        plan = adaptor.plan(document); self.assertEqual(json.dumps(document, sort_keys=True), before)
        plan['metadata']['authors'].append('Mallory'); plan['metadata']['description'] = 'changed'
        self.assertEqual(json.dumps(document, sort_keys=True), before); self.assertEqual(adaptor.plan(document), adaptor.plan(copy.deepcopy(document)))
        document['metadata']['authors'].append('C'); self.assertEqual(adaptor.plan(report(authors=['A', 'B'], description='d'))['metadata']['authors'], ['A', 'B'])

    def test_changed_declaration_changes_plan_and_capture(self):
        base = report(authors=['A', 'B'], description='d'); plan = adaptor.plan(base); capture = adaptor.metadata_capture(plan['metadata'])
        for change in (lambda m: m['authors'].reverse(), lambda m: m['authors'].append('C'), lambda m: m.update(description='e'), lambda m: m.pop('description'), lambda m: m.pop('authors')):
            other = copy.deepcopy(base); change(other['metadata']); changed = adaptor.plan(other)
            self.assertNotEqual(changed, plan); self.assertNotEqual(adaptor.metadata_capture(changed['metadata']), capture)
        self.assertEqual(capture, adaptor.metadata_capture({'description': 'd', 'authors': ['A', 'B']}))
        self.assertEqual(capture['characters'], 3); self.assertEqual(len(capture['sha256']), 64)

    def test_declaration_is_text_only_never_markup(self):
        declared = {'authors': ['<script>alert(1)</script>', '&amp'], 'description': '<a href="https://example.test">x</a> & [y](z)'}
        tree = adaptor.ast(adaptor.plan(report(**declared)), [1, 23, 1, 2], Path('/nonexistent'))
        self.assertEqual(set(tree['meta']), {'title', 'author', 'description'})
        self.assertEqual([i['t'] for a in tree['meta']['author']['c'] for i in a['c']], ['Str', 'Str'])
        self.assertEqual(tree['meta']['description'], {'t': 'MetaString', 'c': declared['description']})
        self.assertEqual(tree['meta']['author']['c'][0]['c'], [{'t': 'Str', 'c': '<script>alert(1)</script>'}])

    def test_loss_statement_makes_no_identity_accessibility_or_review_claim(self):
        text = adaptor.METADATA_LOSS
        for needle in ('declarations', 'nothing verifies who the authors are', 'does not imply accessibility, review or peer review', 'semicolon', 'not shown in the text'): self.assertIn(needle, text)
        self.assertNotIn(adaptor.METADATA_LOSS, adaptor.plan(copy.deepcopy(SIMPLE))['losses'])

    def test_schema_declares_the_closed_object(self):
        metadata = adaptor.schema()['properties']['metadata']
        self.assertEqual(set(metadata['properties']), {'authors', 'description'}); self.assertFalse(metadata.get('additionalProperties', True))
        self.assertEqual((metadata['properties']['authors']['minItems'], metadata['properties']['authors']['maxItems']), (1, 8))
        self.assertEqual(metadata['properties']['authors']['items']['maxLength'], 100); self.assertEqual(metadata['properties']['description']['maxLength'], 1000)
        self.assertNotIn('metadata', adaptor.schema()['required'])

    def test_epub_still_refuses_authors_and_metadata_keys(self):
        document = copy.deepcopy(SIMPLE); document['epub'] = {'language': 'en', 'authors': ['A']}
        self.assertEqual(fault(self, adaptor.plan, document).code, 'UNKNOWN_ARGUMENT')


class Replay(unittest.TestCase):
    """One genuine replayed run with metadata and an EPUB; forged variants are restored after use."""
    snapshot, restore, refresh, verify_message, forged_verify = (getattr(zipbytes.Genuine, n) for n in ('snapshot', 'restore', 'refresh', 'verify_message', 'forged_verify'))

    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix='pandoc-metadata-')); cls.run_directory = cls.directory / 'run'
        cls.executable = fx.stand_in(cls.directory); cls.document = fx.document(cls.directory)
        cls.result = adaptor.run(cls.document, cls.run_directory, executable=cls.executable)
        cls.prepared = adaptor.plan(cls.document); cls.metadata = cls.prepared['metadata']
        cls.model = adaptor.expected({**cls.prepared, '_directory': cls.run_directory})
        cls.html = (cls.run_directory / 'report.html').read_text(encoding='utf-8'); cls.docx = (cls.run_directory / 'report.docx').read_bytes()
        cls.epub = (cls.run_directory / 'report.epub').read_bytes()
        cls.back = json.loads((cls.run_directory / 'reopened.json').read_text()); cls.epub_back = json.loads((cls.run_directory / 'epub-reopened.json').read_text())

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.directory, ignore_errors=True)

    def refused(self, call, text, *args, **kwargs):
        error = fault(self, call, *args, **kwargs); self.assertEqual(error.code, 'VERIFICATION_FAILED', error.message); self.assertIn(text, error.message); return error

    def test_run_publishes_and_verifies_every_format(self):
        self.assertEqual(self.result['artifacts'], 4)
        self.assertEqual(self.result['metadata'], {'authors': 3, 'description': True, 'characters': sum(map(len, fx.AUTHORS)) + len(fx.DESCRIPTION), 'formats': ['html', 'docx', 'epub']})
        self.assertEqual(adaptor.verify(self.run_directory)['metadata'], self.result['metadata'])
        self.assertEqual([Path(a['file']).name for a in adaptor.read(self.run_directory, 'verification.json')['artifacts']], ['report.html', 'report.docx', 'report-summary.json', 'report.epub'])

    def test_capture_provenance_and_plan_record_the_declaration(self):
        captures = adaptor.read(self.run_directory, 'captures.json'); self.assertEqual(captures['metadata'], adaptor.metadata_capture(fx.metadata()))
        self.assertEqual(captures['metadata']['authors'], fx.AUTHORS); self.assertEqual(adaptor.read(self.run_directory, 'plan.json')['metadata'], fx.metadata())
        self.assertEqual(adaptor.read(self.run_directory, 'authored.json')['metadata'], fx.metadata())
        self.assertEqual(adaptor.read(self.run_directory, 'report-summary.json')['metadata']['formats'], ['html', 'docx', 'epub'])
        evidence = adaptor.read(self.run_directory, 'verification.json')['evidence']
        self.assertIn('captures.json', evidence); self.assertNotIn('metadata', evidence)
        tree = adaptor.read(self.run_directory, 'report-input.json'); self.assertEqual(tree['meta']['author']['c'][2]['c'][0], {'t': 'Str', 'c': 'Rob'})

    def test_independent_literals_in_the_genuine_outputs(self):
        for literal in ('<meta name="author" content="Zoë Müller" />', '<p class="author">李雷 (Li Lei)</p>', 'content="Rob &amp; &lt;b&gt; &quot;Q&quot; O&#39;Neil"', '<meta name="description" content="Résumé'):
            self.assertIn(literal, self.html)
        self.assertNotIn(fx.DESCRIPTION.split(' ')[0] + ' des', self.html.split('<body>')[1])
        with zipfile.ZipFile(io.BytesIO(self.docx)) as archive: core = archive.read('docProps/core.xml').decode()
        self.assertIn('<dc:creator>Zoë Müller; 李雷 (Li Lei); Rob &amp; &lt;b&gt; &quot;Q&quot; O&#39;Neil</dc:creator>', core); self.assertIn('<dc:description>Résumé des mesures', core)
        with zipfile.ZipFile(io.BytesIO(self.epub)) as archive: opf = archive.read('EPUB/content.opf').decode()
        self.assertEqual(re.findall(r'<dc:creator id="epub-creator-(\d)">', opf), ['1', '2', '3']); self.assertEqual(opf.count('>aut</meta>'), 3); self.assertIn('<dc:description>Résumé', opf)
        # Pandoc 3.12.1's EPUB reader returns the creators in reverse of the package order.
        self.assertEqual([i['c'][0]['c'] for i in self.epub_back['meta']['author']['c']], ['Rob & <b> "Q" O\'Neil', '李雷 (Li Lei)', 'Zoë Müller'])
        self.assertNotIn('description', self.back['meta'])

    def check_html(self, source, metadata=None): return inspection.html_report(source, fx.fx.TITLE, self.model, self.metadata if metadata is None else metadata)

    def test_html_forgeries_are_refused(self):
        self.check_html(self.html)
        for label, old, new in (('author meta removed', '  <meta name="author" content="Zoë Müller" />\n', ''), ('author meta stale', 'content="李雷 (Li Lei)"', 'content="李雷"'),
                                ('description removed', re.search(r'  <meta name="description"[^\n]*\n', self.html)[0], ''), ('description stale', 'content="Résumé', 'content="Resume'),
                                ('extra author meta', '  <meta name="description"', '  <meta name="author" content="Mallory" />\n  <meta name="description"'),
                                ('reordered', '  <meta name="author" content="Zoë Müller" />\n  <meta name="author" content="李雷 (Li Lei)" />\n', '  <meta name="author" content="李雷 (Li Lei)" />\n  <meta name="author" content="Zoë Müller" />\n')):
            self.refused(self.check_html, 'HTML author/description metadata differs', self.html.replace(old, new, 1)); 
        for label, old, new, text in (('visible author removed', '<p class="author">Zoë Müller</p>\n', '', 'title block differs'), ('visible author forged', '<p class="author">Zoë Müller</p>', '<p class="author">Mallory</p>', 'visible author list differs'),
                                      ('restyled', '<p class="author">Zoë Müller</p>', '<p class="author" style="display:none">Zoë Müller</p>', 'unexpected HTML content/attribute'),
                                      ('nested link', '<p class="author">Zoë Müller</p>', '<p class="author"><a href="https://e.test">Zoë Müller</a></p>', 'HTML'),
                                      ('author in body', '<p>', '<p class="author">Mallory</p><p>', 'unexpected HTML')):
            self.refused(self.check_html, text, self.html.replace(old, new, 1))

    def test_html_without_a_declaration_refuses_injected_or_missing_metadata(self):
        legacy = (earlier.FIXTURE / 'report.html').read_text(encoding='utf-8'); inspection.html_report(legacy, earlier.TITLE, self.model, None)
        for injected in ('  <meta name="author" content="Mallory" />\n  <title>', '  <meta name="description" content="x" />\n  <title>'):
            self.refused(inspection.html_report, 'HTML author/description metadata differs', legacy.replace('  <title>', injected, 1), earlier.TITLE, self.model)
        self.refused(inspection.html_report, 'HTML title block differs', legacy.replace('</h1>\n</header>', '</h1>\n<p class="author">Mallory</p>\n</header>', 1), earlier.TITLE, self.model)
        self.refused(self.check_html, 'HTML author/description metadata differs', legacy, self.metadata)

    def check_docx(self, data, metadata=None): return inspection.docx_report(data, fx.fx.TITLE, self.model, self.metadata if metadata is None else metadata)

    def test_docx_forgeries_are_refused(self):
        self.check_docx(self.docx)
        core, body = 'docProps/core.xml', 'word/document.xml'
        for label, member, pattern, repl, text in (
                ('creator stale', core, '<dc:creator>Zoë Müller', '<dc:creator>Zoe Muller', 'core properties differ'), ('creator separator', core, '; 李雷', ';李雷', 'core properties differ'),
                ('creator empty', core, '<dc:creator>[^<]*</dc:creator>', '<dc:creator></dc:creator>', 'core properties differ'), ('description removed', core, '<dc:description>[^<]*</dc:description>', '', 'core properties differ'),
                ('description stale', core, '<dc:description>Résumé', '<dc:description>Resume', 'core properties differ'), ('keywords injected', core, '<cp:keywords></cp:keywords>', '<cp:keywords>k</cp:keywords>', 'core properties differ'),
                ('author paragraph removed', body, r'<w:p>\s*<w:pPr>\s*<w:pStyle w:val="Author" />\s*</w:pPr>\s*<w:r><w:t xml:space="preserve">Zoë Müller</w:t></w:r>\s*</w:p>', '', 'visible author list differs'),
                ('author paragraph forged', body, r'(Author" />\s*</w:pPr>\s*<w:r><w:t xml:space="preserve">)Zoë Müller', r'\1Mallory', 'visible author list differs'),
                ('author style demoted', body, 'w:val="Author"', 'w:val="BodyText"', 'DOCX')):
            self.refused(self.check_docx, text, docx_rewrite(self.docx, member, pattern, repl))
        legacy = (earlier.FIXTURE / 'report.docx').read_bytes(); inspection.docx_report(legacy, earlier.TITLE, self.model, None)
        for member, pattern, repl in ((core, '<dc:creator></dc:creator>', '<dc:creator>Mallory</dc:creator>'), (core, '(<dc:creator></dc:creator>)', r'\1<dc:description>x</dc:description>')):
            self.refused(inspection.docx_report, 'core properties differ', docx_rewrite(legacy, member, pattern, repl), earlier.TITLE, self.model)
        self.refused(self.check_docx, 'core properties differ', legacy)

    def test_docx_readback_forgeries_are_refused(self):
        def check(value, metadata=None): inspection.ast_report(value, self.run_directory, fx.fx.TITLE, self.model, self.metadata if metadata is None else metadata)
        check(self.back)
        def forged(change): value = copy.deepcopy(self.back); change(value); return value
        self.refused(check, 'readback authors differ', forged(lambda v: v['meta']['author']['c'][0]['c'].__setitem__(0, {'t': 'Str', 'c': 'Mallory'})))
        self.refused(check, 'readback authors differ', forged(lambda v: v['meta']['author']['c'].reverse()))
        self.refused(check, 'readback metadata differs', forged(lambda v: v['meta'].pop('author')))
        self.refused(check, 'readback metadata differs', forged(lambda v: v['meta'].update(description={'t': 'MetaString', 'c': 'x'})))
        legacy = json.loads((earlier.FIXTURE / 'reopened.json').read_text())
        self.refused(check, 'readback metadata differs', legacy)
        legacy['meta']['author'] = {'t': 'MetaInlines', 'c': [{'t': 'Str', 'c': 'Mallory'}]}
        self.refused(lambda v: inspection.ast_report(v, self.run_directory, earlier.TITLE, self.model, None), 'readback metadata differs', legacy)

    def check_epub(self, data, metadata=None): return epub.package_report(data, fx.fx.TITLE, fx.fx.LANGUAGE, self.model, self.metadata if metadata is None else metadata)

    def test_epub_forgeries_are_refused(self):
        self.check_epub(self.epub); opf, page = 'EPUB/content.opf', 'EPUB/text/title_page.xhtml'
        def edit(name, pattern, repl):
            def change(members):
                out = []; found = 0
                for member, body in members:
                    if member == name: body, n = re.subn(pattern.encode(), repl.encode(), body, count=1); found += n
                    out.append((member, body))
                assert found, (name, pattern); return out
            return change
        for label, name, pattern, repl in (
                ('creator stale', opf, '>Zoë Müller</dc:creator>', '>Zoe Muller</dc:creator>'), ('role changed', opf, '>aut</meta>', '>edt</meta>'),
                ('creator reordered', opf, r'(    <dc:creator id="epub-creator-1">[^\n]*\n[^\n]*\n)(    <dc:creator id="epub-creator-2">[^\n]*\n[^\n]*\n)', r'\2\1'),
                ('creator removed', opf, r'    <dc:creator id="epub-creator-3">[^\n]*\n[^\n]*\n', ''), ('description removed', opf, r'    <dc:description>[^\n]*\n', ''),
                ('description stale', opf, '<dc:description>Résumé', '<dc:description>Resume'), ('title page author removed', page, r'  <p class="author">Zoë Müller</p>\n', ''),
                ('title page author forged', page, '>Zoë Müller</p>', '>Mallory</p>'), ('title page link', page, '<p class="author">Zoë Müller</p>', '<p class="author"><a href="https://e.test">Zoë Müller</a></p>')):
            error = fault(self, self.check_epub, zipbytes.rewrite(self.epub, edit(name, pattern, repl))); self.assertEqual(error.code, 'VERIFICATION_FAILED', label)
        legacy = (earlier.FIXTURE / 'report.epub').read_bytes(); epub.package_report(legacy, earlier.TITLE, earlier.LANGUAGE, self.model, None)
        self.refused(self.check_epub, 'EPUB', legacy)
        injected = zipbytes.rewrite(legacy, edit(opf, r'    <meta property="dcterms:modified"', '    <dc:creator id="epub-creator-1">Mallory</dc:creator>\n    <meta property="dcterms:modified"'))
        self.assertEqual(fault(self, epub.package_report, injected, earlier.TITLE, earlier.LANGUAGE, self.model, None).code, 'VERIFICATION_FAILED')

    def test_epub_readback_forgeries_are_refused(self):
        facts = self.check_epub(self.epub)
        def check(value, metadata=None): epub.readback_report(value, fx.fx.TITLE, fx.fx.LANGUAGE, facts, self.model, self.metadata if metadata is None else metadata)
        check(self.epub_back)
        def forged(change): value = copy.deepcopy(self.epub_back); change(value); return value
        self.refused(check, 'readback authors differ', forged(lambda v: v['meta']['author']['c'].reverse()))
        self.refused(check, 'readback authors differ', forged(lambda v: v['meta']['author']['c'][0]['c'].__setitem__(0, {'t': 'Str', 'c': 'Mallory'})))
        self.refused(check, 'readback description differs', forged(lambda v: v['meta']['description']['c'].__setitem__(0, {'t': 'Str', 'c': 'x'})))
        self.refused(check, 'readback metadata differs', forged(lambda v: v['meta'].pop('author')))
        self.refused(check, 'readback metadata differs', forged(lambda v: v['meta'].pop('description')))
        legacy = json.loads((earlier.FIXTURE / 'epub-reopened.json').read_text())
        self.refused(check, 'readback metadata differs', legacy)

    def test_refreshed_receipt_forgeries_are_refused(self):
        self.forged_verify('captures.json', lambda b: json.dumps({**json.loads(b), 'metadata': {**json.loads(b)['metadata'], 'authors': ['Mallory', *fx.AUTHORS[1:]]}}).encode(), 'captured metadata record differs')
        self.forged_verify('captures.json', lambda b: json.dumps({k: v for k, v in json.loads(b).items() if k != 'metadata'}).encode(), 'capture membership differs')
        self.forged_verify('captures.json', lambda b: json.dumps({**json.loads(b), 'metadata': {**json.loads(b)['metadata'], 'sha256': '0' * 64}}).encode(), 'captured metadata record differs')
        self.forged_verify('report-summary.json', lambda b: json.dumps({k: v for k, v in json.loads(b).items() if k != 'metadata'}).encode(), 'report summary differs')
        self.forged_verify('report-summary.json', lambda b: json.dumps({**json.loads(b), 'metadata': {**json.loads(b)['metadata'], 'authors': 2}}).encode(), 'report summary differs')
        self.forged_verify('plan.json', lambda b: json.dumps({k: v for k, v in json.loads(b).items() if k != 'metadata'}).encode(), 'effective report plan differs')
        self.forged_verify('authored.json', lambda b: json.dumps({**json.loads(b), 'metadata': {**json.loads(b)['metadata'], 'authors': fx.AUTHORS[::-1]}}).encode(), 'effective report plan differs')
        saved = self.snapshot()
        try:
            path = self.run_directory / 'authored.json'; document = json.loads(path.read_text()); document['metadata']['authors'][0] = 'A;B'; path.write_text(json.dumps(document))
            error = fault(self, adaptor.verify, self.run_directory); self.assertEqual((error.code, error.location), ('INVALID_ARGUMENT', '$.metadata.authors[0]')); self.assertIn('semicolon', error.message)
        finally: self.restore(saved)
        self.assertTrue(adaptor.verify(self.run_directory)['verified'])

    def test_stale_native_output_for_changed_or_removed_metadata_is_refused(self):
        """Replaying the genuine outputs for a report whose metadata differs (or is absent) must fail: the native files are stale."""
        for label, change in (('author', lambda m: m['authors'].__setitem__(0, 'Mallory')), ('order', lambda m: m['authors'].reverse()), ('description', lambda m: m.update(description='Other')),
                              ('authors removed', lambda m: m.pop('authors')), ('description removed', lambda m: m.pop('description')), ('author added', lambda m: m['authors'].append('Extra'))):
            document = fx.document(self.directory); change(document['metadata']); target = self.directory / ('stale-' + label.replace(' ', '-'))
            error = fault(self, adaptor.run, document, target, executable=self.executable); self.assertEqual(error.code, 'VERIFICATION_FAILED', label)
            self.assertEqual(adaptor.read(target, 'result.json')['status'], 'failed')
        absent = fx.document(self.directory, declared=False); target = self.directory / 'stale-absent'
        self.assertEqual(fault(self, adaptor.run, absent, target, executable=self.executable).code, 'VERIFICATION_FAILED')

    def test_earlier_fixture_without_metadata_still_runs_and_has_no_metadata_member(self):
        directory = Path(tempfile.mkdtemp(prefix='pandoc-earlier-'))
        try:
            document = earlier.document(directory); result = adaptor.run(document, directory / 'run', executable=earlier.stand_in(directory))
            self.assertNotIn('metadata', result); self.assertEqual(result['artifacts'], 4)
            for name in ('captures.json', 'report-summary.json', 'plan.json', 'authored.json'): self.assertNotIn('metadata', adaptor.read(directory / 'run', name))
            self.assertEqual(adaptor.verify(directory / 'run'), {k: v for k, v in result.items() if k != 'status'})
            # An earlier retained run is not made to verify as one that declared metadata.
            forged = json.loads((directory / 'run/authored.json').read_text()); forged['metadata'] = fx.metadata()
            (directory / 'run/authored.json').write_text(json.dumps(forged))
            self.assertEqual(fault(self, adaptor.verify, directory / 'run').code, 'VERIFICATION_FAILED')
        finally: shutil.rmtree(directory, ignore_errors=True)


if __name__ == '__main__': unittest.main()
