"""Pandoc report `epub` declaration: an optional EPUB 3 publication whose package and content are inspected independently.

Host tests only. A stand-in executable replays the genuine Pandoc 3.12.1 outputs kept in examples/schemaxis/fixtures/pandoc-epub
through the unchanged stage launchers, receipts and inspectors; the real writer and reader run in tools/qualify_pandoc_epub.py.
"""
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from schemaxis.adaptors.pandoc import adaptor, epub
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import pandoc_docx_fixture as docx  # noqa: E402
import pandoc_epub_baseline as baseline  # noqa: E402
import pandoc_epub_fixture as fx  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
# What a report WITHOUT `epub` produced before the declaration existed, computed from the pre-change adaptor source with
# `baseline.fingerprint`. Absence must keep every plan, tree, command, launcher, capture, summary and artifact byte for byte.
BEFORE = {'plan': '90b0b0476f24ddd1e171bf8314e4cc017f96cc43ac976b1c65a80706358ce003',
          'tree': '412d96fc1572ff0ff039e404edf7d6dacf730097bca5ef60c255e90fa9c4e14f',
          'model': 'ff1650f1e94d789e4c98461ec23d7c1d26acf8adb07c8a7f9c34d2f728606b7e',
          'commands': 'b31807ef51d47b23761b505cd6467d83622594d0bed951d075e3c5936fd93c23',
          'captured': '714340c667fdf98575e49e59b2e7cee0175371a25a171a71083d55742f0c7e5a',
          'summary': '529fcf0789cd9ca65c4a9191ba9dfe4a2ece777a36b0044ab531e55581e98ed4',
          'launchers': '062be679bcf55df17f7778cb7c029b71caa2fcb3df1f323775cabd059549e9fa',
          'inputs': 'be0696565f6dedf8fb9bde6539b242b870b947831b6fa3e7b6882abadf28b4df',
          'artifacts': 'aa95383108c8f5c2aa4d664814ae63312a45ce2856180eacf5225c8d193b61f6',
          'artifactNames': ['report.html', 'report.docx', 'report-summary.json'],
          'result': 'cb2fc890999c761aea8678827bb90e425881daa47207561717713ed487c542c3'}


def sha(data): return hashlib.sha256(data).hexdigest()


def fault(case, call, *args, **kwargs):
    with case.assertRaises(SchemaxisError) as caught: call(*args, **kwargs)
    return caught.exception.fault


def rewrite(data, change):
    """Rewrite an EPUB: `change` receives the ordered [(name, bytes)] and returns the members to write (mimetype stored, the rest deflated)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive: members = [(i.filename, archive.read(i)) for i in archive.infolist()]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, body in change(members):
            archive.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), body, zipfile.ZIP_STORED if name == 'mimetype' else zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def edit(name, old, new, count=1):
    """A change that replaces `old` by `new` in one member (or, with name None, in every member), requiring the text to be there."""
    def change(members):
        out = []
        for member, body in members:
            if name is None or member == name:
                found = body.count(old)
                if name is not None: assert found >= 1, (name, old)
                body = body.replace(old, new)
            out.append((member, body))
        return out
    return change


def add(name, body):
    return lambda members: [*members, (name, body)]


def drop(name):
    return lambda members: [m for m in members if m[0] != name]


class Genuine(unittest.TestCase):
    """One genuine replayed run with an EPUB, shared by the read-only checks; forged variants are restored after use."""

    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix='pandoc-epub-')); cls.run_directory = cls.directory / 'run'
        cls.executable = fx.stand_in(cls.directory)
        cls.document = fx.document(cls.directory)
        cls.result = adaptor.run(cls.document, cls.run_directory, executable=cls.executable)
        cls.prepared = adaptor.plan(cls.document)
        cls.model = adaptor.expected({**cls.prepared, '_directory': cls.run_directory})
        cls.epub = (cls.run_directory / 'report.epub').read_bytes()
        cls.readback = json.loads((cls.run_directory / 'epub-reopened.json').read_text())

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.directory, ignore_errors=True)

    def check(self, data, language=fx.LANGUAGE, title=fx.TITLE, model=None):
        return epub.package_report(data, title, language, self.model if model is None else model)

    def refused(self, change, text=None, data=None, **kwargs):
        error = fault(self, self.check, rewrite(self.epub if data is None else data, change), **kwargs)
        self.assertEqual(error.code, 'VERIFICATION_FAILED', error.message)
        if text: self.assertIn(text, error.message)
        return error

    def snapshot(self):
        return {p: p.read_bytes() for p in self.run_directory.rglob('*') if p.is_file()}

    def restore(self, saved):
        for p in list(self.run_directory.rglob('*')):
            if p.is_file() and p not in saved: p.unlink()
        for p, body in saved.items():
            p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(body)

    def refresh(self):
        """Recompute every receipt digest the way a forger who rewrites all evidence would: evidence, artifacts and stage input bindings."""
        directory = self.run_directory; receipt = json.loads((directory / 'verification.json').read_text())
        prepared = adaptor.plan(json.loads((directory / 'authored.json').read_text()), retained=True)
        for stage in adaptor.commands(receipt['executable'], prepared.get('epub')):
            (directory / (stage + '-inputs.json')).write_text(json.dumps({str(directory / n): adaptor.digest(directory, n) for n in adaptor.stage_inputs(stage, prepared)}, sort_keys=True))
        receipt['evidence'] = {name: adaptor.digest(directory, name) for name in receipt['evidence']}
        receipt['artifacts'] = adaptor.artifacts(directory, (directory / 'report.epub').exists())
        (directory / 'verification.json').write_text(json.dumps(receipt))

    def verify_message(self):
        error = fault(self, adaptor.verify, self.run_directory)
        self.assertEqual(error.code, 'VERIFICATION_FAILED', error.message)
        return error.message

    def forged_verify(self, name, change, text):
        """Replace one retained member by a forged variant, refresh every digest coherently, and require verification to refuse it."""
        saved = self.snapshot()
        try:
            path = self.run_directory / name; path.write_bytes(change(path.read_bytes())); self.refresh()
            self.assertIn(text, self.verify_message())
        finally: self.restore(saved)


class Planning(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.directory = Path(tempfile.mkdtemp(prefix='pandoc-epub-plan-'))

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.directory, ignore_errors=True)

    def document(self, **epub_field):
        document = fx.document(self.directory, language=None); document.update(epub_field); return document

    def test_an_absent_declaration_stays_absent_and_the_plan_is_the_old_plan(self):
        planned = adaptor.plan(self.document())
        self.assertNotIn('epub', planned)
        self.assertNotIn(adaptor.EPUB_LOSS, planned['losses'])
        self.assertEqual(adaptor.query(self.document()), (['report'], {}))
        self.assertEqual(adaptor.plan(self.document(), retained=True), planned)

    def test_the_declared_language_is_planned_exactly_as_authored_with_one_trailing_loss(self):
        for language in ('en', 'fr', 'fr-CA', 'zh-Hans-CN', 'ar', 'yue', 'de-CH-1996', 'EN', 'sr-Latn-RS'):
            with self.subTest(language):
                planned = adaptor.plan(self.document(epub={'language': language}))
                self.assertEqual(planned['epub'], {'language': language}); self.assertEqual(planned['losses'][-1], adaptor.EPUB_LOSS)
                self.assertEqual(planned['losses'].count(adaptor.EPUB_LOSS), 1)
                self.assertEqual(adaptor.plan(self.document(epub={'language': language}), retained=True), planned)
        without = adaptor.plan(self.document())
        self.assertEqual(adaptor.plan(self.document(epub={'language': 'en'}))['losses'][:-1], without['losses'])

    def test_the_loss_makes_no_conformance_device_accessibility_or_detection_claim(self):
        text = adaptor.EPUB_LOSS
        for phrase in ('not an EPUBCheck conformance', 'device rendering', 'accessibility', 'language-detection', "author's declaration", 'refused, never truncated', 'Calibre'):
            self.assertIn(phrase, text)

    def test_unsafe_missing_or_mistyped_languages_are_refused_at_the_field(self):
        for value in (True, False, 1, 0, 1.5, None, [], ['en'], {}, {'language': 'en'}, '', 'e', 'english', 'toolong-subtag-xxxxxxxxx', 'en_US', 'en US', 'en\n', 'en-', '-en',
                      'en--US', 'en-US-', 'ÿen', 'fr-é', '--help', '-fjson', 'en;rm', 'en/../x', 'en\0', ' en', 'en ', '12', 'e1', 'en-a', 'en-123456789', 'a-b-c-d-e-f',
                      'en-US-x-a-b-c', 'x' * 36, 'en-' + 'a' * 40):
            with self.subTest(value=repr(value)):
                error = fault(self, adaptor.plan, self.document(epub={'language': value}))
                self.assertEqual((error.code, error.location), ('INVALID_ARGUMENT', '$.epub.language'), error.message)

    def test_the_declaration_is_a_closed_object_with_one_required_field(self):
        for value in (True, None, [], 'en', 5, 1.5):
            with self.subTest(value=repr(value)): self.assertEqual(fault(self, adaptor.plan, self.document(epub=value)).location, '$.epub')
        self.assertEqual(fault(self, adaptor.plan, self.document(epub={})).code, 'MISSING_ARGUMENT')
        for extra in ('cover', 'metadata', 'author', 'css', 'stylesheet', 'fonts', 'identifier', 'template', 'filters', 'path', 'toc', 'version', 'native'):
            with self.subTest(extra=extra):
                error = fault(self, adaptor.plan, self.document(epub={'language': 'en', extra: 'x'}))
                self.assertEqual((error.code, error.location), ('UNKNOWN_ARGUMENT', '$.epub'))

    def test_a_refusal_happens_before_any_file_or_native_work(self):
        directory = Path(tempfile.mkdtemp(prefix='pandoc-epub-refuse-')); self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        for value in ({'language': True}, {'language': 'en_US'}, {'language': 'en', 'cover': 'x.png'}, True):
            with self.subTest(value=value), patch.object(adaptor, 'read_source', side_effect=AssertionError('source read')), \
                    patch.object(adaptor, 'launch', side_effect=AssertionError('native stage launched')), patch.object(adaptor, 'bounded', side_effect=AssertionError('file read')):
                error = fault(self, adaptor.run, self.document(epub=value), directory / 'run', executable=shutil.which('true'))
                self.assertIn(error.code, ('INVALID_ARGUMENT', 'UNKNOWN_ARGUMENT')); self.assertFalse((directory / 'run').exists())

    def test_planning_with_the_declaration_opens_no_file(self):
        document = self.document(epub={'language': 'fr-CA'})
        with patch('builtins.open', side_effect=AssertionError('planning read a file')), patch('os.open', side_effect=AssertionError('planning opened a file')):
            adaptor.plan(document); self.assertEqual(adaptor.query(document), (['report'], {}))

    def test_the_generated_schema_and_declaration_describe_the_closed_optional_object(self):
        schema = adaptor.schema(); field = schema['properties']['epub']
        self.assertNotIn('epub', schema['required']); self.assertEqual(field['required'], ['language'])
        self.assertIs(field.get('additionalProperties', False), False)
        self.assertEqual((field['properties']['language']['minLength'], field['properties']['language']['maxLength']), (2, 35))
        self.assertIn('epub', adaptor.DECLARATIONS['report']['options'])

    def test_the_earlier_machine_wording_cannot_accompany_an_epub(self):
        planned = adaptor.plan(self.document(epub={'language': 'en'}))
        stored = {**planned, 'losses': [*planned['losses'][:-2], adaptor.LEGACY_TRANSCRIPT_LOSS]}
        self.assertIsNone(adaptor.same_plan(stored, planned))
        self.assertEqual(adaptor.same_plan(planned, planned), 'current')


class Absent(unittest.TestCase):
    def test_a_report_without_the_declaration_is_unchanged_from_the_pre_change_source(self):
        with tempfile.TemporaryDirectory() as name: self.assertEqual(baseline.fingerprint(adaptor, name), BEFORE)

    def test_the_native_stages_artifacts_and_inputs_of_an_epub_free_report_are_the_old_ones(self):
        self.assertEqual(list(adaptor.commands('/x/pandoc')), ['version', 'api', 'html', 'docx', 'reopen'])
        self.assertEqual(list(adaptor.commands('/x/pandoc', None)), ['version', 'api', 'html', 'docx', 'reopen'])
        self.assertEqual(adaptor.stage_inputs('epub', {}), ['report-input.json']); self.assertEqual(adaptor.stage_inputs('epubreopen', {}), ['report.epub'])
        with tempfile.TemporaryDirectory() as name:
            for n in ('report.html', 'report.docx', 'report-summary.json', 'report.epub'): (Path(name) / n).write_bytes(b'x')
            self.assertEqual([Path(a['file']).name for a in adaptor.artifacts(Path(name))], ['report.html', 'report.docx', 'report-summary.json'])
            self.assertEqual([Path(a['file']).name for a in adaptor.artifacts(Path(name), True)], ['report.html', 'report.docx', 'report-summary.json', 'report.epub'])

    def test_the_epub_commands_are_fixed_and_the_language_is_the_only_variable(self):
        native = adaptor.commands('/x/pandoc', {'language': 'zh-Hans-CN'}); tail = ['--data-dir=native-data', '+RTS', '-M512M', '-RTS']
        self.assertEqual(native['epub'], ['/x/pandoc', '--from=json', '--to=epub3', '--standalone', '--sandbox', '--metadata=lang:zh-Hans-CN', '--output=report.epub', 'report-input.json', *tail])
        self.assertEqual(native['epubreopen'], ['/x/pandoc', '--from=epub', '--to=json', '--sandbox', '--output=epub-reopened.json', 'report.epub', *tail])
        self.assertEqual({k: v for k, v in native.items() if k not in ('epub', 'epubreopen')}, adaptor.commands('/x/pandoc'))
        for option in ('--extract-media', '--filter', '--lua-filter', '--template', '--css', '--epub-', '--include', '--resource-path', '--metadata-file', '--data-dir=/'):
            self.assertFalse(any(part.startswith(option) for part in [*native['epub'], *native['epubreopen']]), option)


class Run(Genuine):
    def test_the_publication_is_appended_as_artifact_three_and_the_old_indices_stay(self):
        receipt = json.loads((self.run_directory / 'verification.json').read_text())
        self.assertEqual([Path(a['file']).name for a in receipt['artifacts']], ['report.html', 'report.docx', 'report-summary.json', 'report.epub'])
        self.assertEqual([a['kind'] for a in receipt['artifacts']], ['text', 'file', 'text', 'file'])
        self.assertEqual(receipt['artifacts'][3]['sha256'], sha(self.epub))
        self.assertEqual((self.result['verified'], self.result['artifacts'], self.result['status']), (True, 4, 'succeeded'))
        self.assertEqual(self.result['epub'], {'language': fx.LANGUAGE, 'chapters': 2, 'entries': 12, 'mediaFiles': 2})

    def test_the_fresh_reader_json_is_evidence_not_a_publication(self):
        receipt = json.loads((self.run_directory / 'verification.json').read_text())
        self.assertIn('epub-reopened.json', receipt['evidence']); self.assertIn('report.epub', {Path(a['file']).name for a in receipt['artifacts']})
        self.assertNotIn('epub-reopened.json', {Path(a['file']).name for a in receipt['artifacts']})
        for stage in ('epub', 'epubreopen'):
            for suffix in ('-launcher.py', '-inputs.json', '-submission.json', '.stdout', '.stderr'): self.assertIn(stage + suffix, receipt['evidence'])
        launcher = (self.run_directory / 'epub-launcher.py').read_text()
        for part in ("'--to=epub3'", "'--sandbox'", "'--metadata=lang:fr-CA'", "'--from=json'"): self.assertIn(part, launcher)

    def test_the_summary_names_the_epub_and_the_other_publications_are_still_checked(self):
        summary = json.loads((self.run_directory / 'report-summary.json').read_text())
        self.assertEqual(summary['epub'], {'language': fx.LANGUAGE, 'chapters': 2, 'entries': 12, 'mediaFiles': 2}); self.assertEqual(summary['losses'][-1], adaptor.EPUB_LOSS)
        self.assertEqual((summary['sections'], summary['blocks'], summary['tables'], summary['images'], summary['transcripts']), (4, 12, 2, 2, 2))

    def test_verification_is_read_only_and_repeatable(self):
        before = self.snapshot()
        self.assertEqual(adaptor.verify(self.run_directory), adaptor.verify(self.run_directory)); self.assertEqual(self.snapshot(), before)

    def test_the_package_covers_multilingual_title_text_tables_images_and_both_transcript_shapes(self):
        kinds = [b['kind'] for b in self.model]
        self.assertEqual(kinds.count('image'), 2); self.assertEqual(kinds.count('table'), 2)  # one authored table and one timecode cue table
        self.assertEqual(sum(b['kind'] == 'heading' for b in self.model), 4)
        with zipfile.ZipFile(io.BytesIO(self.epub)) as archive:
            names = archive.namelist(); self.assertEqual(names[0], 'mimetype'); self.assertEqual(archive.read('mimetype'), b'application/epub+zip')
            self.assertEqual(archive.getinfo('mimetype').compress_type, zipfile.ZIP_STORED)
            chapter = archive.read('EPUB/text/ch002.xhtml').decode()
        self.assertIn('Start (HH:MM:SS.mmm)', chapter); self.assertIn('the author deleted every cue', chapter)

    def test_a_report_without_the_declaration_runs_through_the_same_replay_with_three_artifacts_and_no_epub_files(self):
        directory = self.directory / 'plain'; document = fx.document(self.directory, language=None)
        result = adaptor.run(document, directory, executable=self.executable)
        self.assertEqual((result['artifacts'], 'epub' in result), (3, False))
        self.assertFalse(any(p.name.startswith(('report.epub', 'epub')) for p in directory.iterdir()))
        receipt = json.loads((directory / 'verification.json').read_text())
        self.assertEqual([Path(a['file']).name for a in receipt['artifacts']], ['report.html', 'report.docx', 'report-summary.json'])
        self.assertNotIn('epub', json.loads((directory / 'report-summary.json').read_text()))
        self.assertEqual(adaptor.verify(directory), {k: v for k, v in result.items() if k != 'status'})

    def test_the_html_docx_summary_and_receipt_of_both_reports_are_independent_of_the_declaration(self):
        directory = self.directory / 'plain2'
        adaptor.run(fx.document(self.directory, language=None), directory, executable=self.executable)
        for name in ('report.html', 'report.docx', 'reopened.json', 'api.json', 'report-input.json', 'captures.json'):
            self.assertEqual((directory / name).read_bytes(), (self.run_directory / name).read_bytes(), name)
        plain_summary = json.loads((directory / 'report-summary.json').read_text()); epub_summary = json.loads((self.run_directory / 'report-summary.json').read_text())
        self.assertEqual({k: v for k, v in epub_summary.items() if k not in ('epub', 'losses')}, {k: v for k, v in plain_summary.items() if k != 'losses'})
        self.assertEqual(epub_summary['losses'][:-1], plain_summary['losses'])


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pandoc-epub-life-')); self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.executable = fx.stand_in(self.directory); self.document = fx.document(self.directory)

    def result(self, name='run'): return json.loads((self.directory / name / 'result.json').read_text())

    def test_a_cancelled_run_is_never_reported_as_published(self):
        with patch.object(adaptor, 'cancellation_requested', return_value=True):
            error = fault(self, adaptor.run, self.document, self.directory / 'run', executable=self.executable)
        self.assertEqual(error.code, 'RUNNER_CANCELLED'); self.assertEqual(self.result()['status'], 'failed'); self.assertFalse(self.result()['verified'])

    def test_a_timeout_in_an_epub_stage_fails_the_run(self):
        real = adaptor.execute
        def execute(argv, directory, stage, remaining, environment):
            if stage == 'epub': from schemaxis.errors import fail; fail('RUNNER_TIMED_OUT', 'stage deadline', stage)
            return real(argv, directory, stage, remaining, environment)
        with patch.object(adaptor, 'execute', execute): error = fault(self, adaptor.run, self.document, self.directory / 'run', executable=self.executable)
        self.assertEqual(error.code, 'RUNNER_TIMED_OUT'); self.assertEqual(self.result()['status'], 'failed')
        self.assertFalse((self.directory / 'run' / 'verification.json').exists())

    def test_the_total_deadline_covers_the_epub_stages(self):
        ticks = iter(range(10 ** 6))
        with patch.object(adaptor.time, 'monotonic', lambda: next(ticks) * 40.0):
            error = fault(self, adaptor.run, self.document, self.directory / 'run', executable=self.executable, timeout=300)
        self.assertIn(error.code, ('RUNNER_TIMED_OUT', 'NATIVE_EXECUTION_FAILED'), error.message); self.assertEqual(self.result()['status'], 'failed')

    def test_a_writer_that_exits_nonzero_or_writes_nothing_is_not_a_publication(self):
        broken = self.directory / 'broken'; shutil.copytree(fx.FIXTURE, broken); (broken / 'report.epub').unlink()
        error = fault(self, adaptor.run, self.document, self.directory / 'missing', executable=fx.stand_in(self.directory, broken))
        self.assertNotEqual(error.code, ''); self.assertEqual(self.result('missing')['status'], 'failed'); self.assertFalse((self.directory / 'missing' / 'report-summary.json').exists())

    def test_an_empty_or_garbage_epub_is_refused_with_a_stable_fault(self):
        for label, body in (('empty', b''), ('garbage', b'not a zip'), ('truncated', (fx.FIXTURE / 'report.epub').read_bytes()[:200])):
            broken = self.directory / label; shutil.copytree(fx.FIXTURE, broken); (broken / 'report.epub').write_bytes(body)
            with self.subTest(label):
                error = fault(self, adaptor.run, self.document, self.directory / ('run-' + label), executable=fx.stand_in(self.directory, broken))
                self.assertEqual(error.code, 'VERIFICATION_FAILED'); self.assertEqual(self.result('run-' + label)['status'], 'failed')

    def test_the_existing_text_budget_applies_unchanged_to_an_epub_report(self):
        document = copy.deepcopy(self.document)
        document['sections'][0]['content'] += [{'kind': 'paragraph', 'text': 'y' * 2000} for _ in range(30)]
        document['sections'][1]['content'] += [{'kind': 'paragraph', 'text': 'y' * 2000} for _ in range(4)]
        error = fault(self, adaptor.plan, document); self.assertEqual(error.code, 'REPORT_RESOURCE_LIMIT'); self.assertIn('65536', error.message)
        document['epub'] = {'language': 'fr-CA'}; self.assertEqual(fault(self, adaptor.plan, document).code, 'REPORT_RESOURCE_LIMIT')


class Package(Genuine):
    def test_the_genuine_package_is_accepted_with_its_facts(self):
        facts = self.check(self.epub)
        self.assertEqual((facts['chapters'], facts['entries'], len(facts['media'])), (2, 12, 2)); self.assertRegex(facts['identifier'], r'^urn:uuid:[0-9a-f-]{36}$')

    def test_native_readback_is_checked_against_the_model_and_the_package(self):
        facts = self.check(self.epub); epub.readback_report(self.readback, fx.TITLE, fx.LANGUAGE, facts, self.model)

    def test_changed_body_words_cells_and_blocks_are_refused(self):
        chapter = 'EPUB/text/ch001.xhtml'
        self.refused(edit(chapter, b'<p>deep</p>', b'<p>dEEp</p>'), 'semantics differ')
        self.refused(edit(chapter, b'<td>z</td>', b'<td>Z</td>'), 'semantics differ')
        self.refused(edit(chapter, b'<th>A&amp;B</th>', b'<th>A&amp;C</th>'), 'semantics differ')
        self.refused(edit(chapter, b'<p>deep</p>', b'<p>deep</p>\n<p>injected</p>'), 'semantics differ')
        self.refused(edit(chapter, b'<p>deep</p>\n', b''), 'semantics differ')
        self.refused(edit(chapter, b'<td>z</td>\n</tr>', b'</tr>\n<tr>\n<td>q</td>\n</tr>'), None)
        self.refused(edit('EPUB/text/ch002.xhtml', b'<td>00:00:05.410</td>', b'<td>00:00:05.411</td>'), 'semantics differ')
        self.refused(edit(chapter, '日本語'.encode(), '日本誤'.encode()), 'semantics differ')

    def test_changed_title_or_language_anywhere_is_refused(self):
        self.refused(edit(None, b'Rapport', b'Rapports'))
        for name, old, new in (('EPUB/content.opf', b'<dc:title id="epub-title-1">Rapport', b'<dc:title id="epub-title-1">Rapports'),
                               ('EPUB/text/title_page.xhtml', b'<h1 class="title">Rapport', b'<h1 class="title">Rapports'),
                               ('EPUB/nav.xhtml', b'<h1 id="toc-title">Rapport', b'<h1 id="toc-title">Rapports'),
                               ('EPUB/toc.ncx', b'<docTitle>\n    <text>Rapport', b'<docTitle>\n    <text>Rapports')):
            with self.subTest(name): self.refused(edit(name, old, new))
        self.refused(edit(None, b'fr-CA', b'en-CA'))
        self.refused(edit('EPUB/content.opf', b'<dc:language>fr-CA', b'<dc:language>en-CA'))
        self.refused(edit('EPUB/text/ch001.xhtml', b'lang="fr-CA" xml:lang="fr-CA"', b'lang="fr-CA" xml:lang="en"'))
        error = fault(self, self.check, self.epub, language='en-CA'); self.assertEqual(error.code, 'VERIFICATION_FAILED')
        error = fault(self, self.check, self.epub, title=fx.TITLE + 'x'); self.assertEqual(error.code, 'VERIFICATION_FAILED')

    def test_spine_manifest_and_navigation_changes_are_refused(self):
        opf = 'EPUB/content.opf'
        def swap(members):
            text = dict(members)[opf].decode(); one = '    <itemref idref="ch001_xhtml" />\n'; two = '    <itemref idref="ch002_xhtml" />\n'
            return [(n, text.replace(one + two, two + one).encode() if n == opf else b) for n, b in members]
        self.refused(swap, None)
        self.refused(edit(opf, b'    <itemref idref="ch002_xhtml" />\n', b''), None)
        self.refused(edit(opf, b'    <itemref idref="ch002_xhtml" />\n', b'    <itemref idref="ch002_xhtml" />\n    <itemref idref="ncx" />\n'), None)
        self.refused(edit(opf, b'    <item id="ch002_xhtml" href="text/ch002.xhtml" media-type="application/xhtml+xml" />\n', b''), 'manifest')
        self.refused(edit(opf, b'<item id="file0_png" href="media/file0.png" media-type="image/png" />', b'<item id="file0_png" href="media/file0.png" media-type="image/jpeg" />'), 'manifest')
        self.refused(edit(opf, b'media/file1.png', b'media/file7.png'), 'manifest')
        self.refused(edit(opf, b'</manifest>', b'  <item id="x" href="https://example.test/x.js" media-type="text/javascript" />\n  </manifest>'), 'manifest')
        self.refused(edit(opf, b'<dc:identifier id="epub-id-1">urn:uuid:', b'<dc:identifier id="epub-id-1">uuid:'), 'identifier')
        self.refused(edit('EPUB/toc.ncx', b'content="urn:uuid:', b'content="urn:uuid:0'), 'identifier')
        self.refused(edit('EPUB/nav.xhtml', 'Détails'.encode(), b'Autre'), 'table of contents')
        self.refused(edit('EPUB/nav.xhtml', b'text/ch001.xhtml#section-2', b'text/ch002.xhtml#section-2'), 'table of contents')
        self.refused(edit('EPUB/nav.xhtml', b'text/ch002.xhtml#section-4', b'javascript:alert(1)'), 'table of contents')
        self.refused(edit('EPUB/toc.ncx', b'text/ch001.xhtml#section-3', b'text/ch001.xhtml#section-9'), 'NCX')
        self.refused(edit('EPUB/toc.ncx', b'<navPoint id="navPoint-3">', b'<navPoint id="navPoint-9">'), 'NCX')
        self.refused(edit('EPUB/content.opf', b'<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />', b'<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" />'), 'manifest')
        self.refused(edit('META-INF/container.xml', b'EPUB/content.opf', b'EPUB/other.opf'), 'differs')

    def test_the_container_mimetype_and_member_rules_are_exact(self):
        self.refused(edit('mimetype', b'application/epub+zip', b'application/epub+zip\n'), 'mimetype')
        self.refused(edit('mimetype', b'application/epub+zip', b'application/zip'), 'mimetype')
        self.refused(lambda m: [*m[1:], m[0]], 'mimetype')
        def deflated(members):
            return members
        data = self.epub
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist(): target.writestr(info.filename, source.read(info))
        self.assertEqual(fault(self, self.check, buffer.getvalue()).code, 'VERIFICATION_FAILED')
        info = zipfile.ZipInfo('mimetype'); info.extra = b'\xfe\xca\x00\x00'
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(buffer, 'w') as target:
            for item in source.infolist():
                entry = zipfile.ZipInfo(item.filename, (1980, 1, 1, 0, 0, 0)); entry.compress_type = zipfile.ZIP_STORED if item.filename == 'mimetype' else zipfile.ZIP_DEFLATED
                if item.filename == 'mimetype': entry.extra = b'\xfe\xca\x00\x00'
                target.writestr(entry, source.read(item))
        self.assertIn('mimetype', fault(self, self.check, buffer.getvalue()).message)
        for name in ('EPUB/fonts/f.otf', 'EPUB/media/x.svg', 'EPUB/extra.xhtml', 'EPUB/scripts/x.js', 'META-INF/encryption.xml', 'META-INF/rights.xml', 'EPUB/text/ch003.xhtml', 'EPUB/text/ch000.xhtml'):
            with self.subTest(name): self.refused(add(name, b'x'), 'member')
        self.refused(add('EPUB/media/file9.png', b'x'), 'differs')
        for name in ('EPUB/nav.xhtml', 'EPUB/toc.ncx', 'EPUB/text/title_page.xhtml', 'EPUB/text/ch002.xhtml', 'EPUB/content.opf', 'EPUB/styles/stylesheet1.css'):
            with self.subTest(dropped=name): self.refused(drop(name), 'member')
        self.refused(drop('EPUB/media/file0.png'), 'differs')

    def test_unsafe_archive_members_are_refused(self):
        for name in ('../evil.txt', '/abs.txt', 'EPUB\\text\\x.xhtml', 'EPUB/../x', 'EPUB//x', './x', 'EPUB/x y.txt', 'EPUB/é.txt', 'EPUB/text/'):
            with self.subTest(name=name): self.refused(add(name, b'x'), 'unsafe')
        self.refused(add('epub/NAV.XHTML', b'x'), None); self.refused(add('EPUB/NAV.XHTML', b'x'), 'duplicate')
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore'); self.refused(add('EPUB/nav.xhtml', b'x'), 'duplicate')

    def test_symlink_directory_encrypted_and_oversize_members_are_refused(self):
        def special(attr, flags=None):
            buffer = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(self.epub)) as source, zipfile.ZipFile(buffer, 'w') as target:
                for item in source.infolist():
                    entry = zipfile.ZipInfo(item.filename, (1980, 1, 1, 0, 0, 0)); entry.compress_type = item.compress_type
                    if item.filename == 'EPUB/styles/stylesheet1.css': entry.external_attr = attr
                    target.writestr(entry, source.read(item))
            return buffer.getvalue()
        for label, attr in (('symlink', 0o120777 << 16), ('directory', 0o040755 << 16), ('fifo', 0o010644 << 16), ('dos directory', 0x10)):
            with self.subTest(label): self.assertIn('regular file', fault(self, self.check, special(attr)).message)
        raw = bytearray(self.epub); index = raw.index(b'PK\x01\x02') + 8; raw[index] |= 1
        self.assertEqual(fault(self, self.check, bytes(raw)).code, 'VERIFICATION_FAILED')
        self.refused(add('EPUB/media/file8.png', bytes(epub.MAX_MEDIA_BYTES + 1)), 'byte limit')
        self.refused(add('EPUB/media/file8.png', bytes(5 * 1024 * 1024)), 'byte limit')
        self.refused(lambda m: [*m, *[(f'EPUB/more/{i}.txt', b'') for i in range(epub.MAX_ENTRIES)]], 'entry limit')
        bomb = rewrite(self.epub, lambda m: [*m, ('EPUB/text/ch009.xhtml', bytes(epub.MAX_PART_BYTES - 1))])
        self.assertLess(len(bomb), 40000); self.assertEqual(fault(self, self.check, bomb).code, 'VERIFICATION_FAILED')
        self.assertEqual(fault(self, self.check, b'PK\x03\x04' + b'\0' * 30).code, 'VERIFICATION_FAILED')
        raw = bytearray(self.epub); raw[raw.index(b'EPUB/nav.xhtml') + 20] ^= 0xFF
        self.assertEqual(fault(self, self.check, bytes(raw)).code, 'VERIFICATION_FAILED')

    def test_scripts_external_resources_styles_doctypes_and_markup_outside_the_profile_are_refused(self):
        chapter = 'EPUB/text/ch001.xhtml'
        self.refused(edit(chapter, b'<body epub:type="bodymatter">', b'<body epub:type="bodymatter">\n<script>alert(1)</script>'), None)
        self.refused(edit(chapter, b'<link rel="stylesheet" type="text/css" href="../styles/stylesheet1.css" />', b'<script src="https://example.test/x.js"></script>'), None)
        self.refused(edit(chapter, b'../styles/stylesheet1.css', b'https://example.test/x.css'), None)
        self.refused(edit(chapter, b'<style>\n  </style>', b'<style>p{display:none}</style>'), None)
        self.refused(edit(chapter, b'<p>deep</p>', b'<p style="display:none">deep</p>'), None)
        self.refused(edit(chapter, b'<p>deep</p>', b'<p>deep<a href="https://example.test">x</a></p>'), None)
        self.refused(edit(chapter, b'<p>deep</p>', b'<p onclick="x()">deep</p>'), None)
        self.refused(edit(chapter, b'<p>deep</p>', b'<p>deep</p><iframe src="https://example.test"></iframe>'), None)
        self.refused(edit(chapter, b'<p>deep</p>', b'<p>deep</p><svg><circle/></svg>'), None)
        self.refused(edit(chapter, b'../media/file0.png', b'https://example.test/a.png'), 'image')
        self.refused(edit(chapter, b'../media/file0.png', b'data:image/png;base64,AAAA'), 'image')
        self.refused(edit(chapter, b'../media/file0.png', b'../media/file9.png'), 'missing')
        self.refused(edit(chapter, b'alt="Second"', b'alt="Other"'), 'semantics differ')
        self.refused(edit(chapter, b'width:60mm', b'width:61mm'), 'semantics differ')
        self.refused(edit(chapter, b'style="width:60mm"', b'style="width:60mm;height:1px"'), 'image')
        self.refused(edit(chapter, b'<!DOCTYPE html>', b'<!DOCTYPE html [<!ENTITY x "y">]>'), 'document type')
        self.refused(edit(chapter, b'<!DOCTYPE html>', b'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">'), 'document type')
        self.refused(edit(chapter, b'<p>deep</p>', b'<p>deep</p><!-- hidden words -->'), 'comment')
        self.refused(edit(chapter, b'<p>deep</p>', b'<p>deep</p><?php echo 1 ?>'), 'processing instruction')
        self.refused(edit(chapter, b'<p>deep</p>', b'<p><![CDATA[deep]]></p>'), 'CDATA')
        self.refused(edit(chapter, b'<p>deep</p>', b'<p>&nbsp;deep</p>'), None)
        self.refused(edit(chapter, b'<p>deep</p>', b'<p>&xxe;</p>'), None)
        self.refused(edit(chapter, b'<?xml version="1.0" encoding="UTF-8"?>', b'<?xml version="1.0" encoding="ISO-8859-1"?>'), 'declaration')
        self.refused(edit(chapter, b'<p>deep</p>', b'<p>de\xffep</p>'), None)
        self.refused(edit('EPUB/styles/stylesheet1.css', b'/* This defines', b'@import url(https://example.test/x.css);\n/* This defines'), 'differs from qualified')
        self.refused(edit('META-INF/com.apple.ibooks.display-options.xml', b'true', b'false'), 'differs from qualified')

    def test_media_bytes_geometry_and_membership_are_checked(self):
        other = docx.png(8, 4, 99)
        self.refused(edit('EPUB/media/file0.png', self.png_of('EPUB/media/file0.png'), other), 'semantics differ')
        self.refused(edit('EPUB/media/file1.png', self.png_of('EPUB/media/file1.png'), self.png_of('EPUB/media/file0.png')), None)
        bad = bytearray(self.png_of('EPUB/media/file0.png')); bad[20] ^= 1
        self.refused(edit('EPUB/media/file0.png', self.png_of('EPUB/media/file0.png'), bytes(bad)), None)
        self.refused(edit('EPUB/media/file0.png', self.png_of('EPUB/media/file0.png'), b'<svg xmlns="http://www.w3.org/2000/svg"/>'), None)
        model = copy.deepcopy(self.model); images = [b for b in model if b['kind'] == 'image']; images[0]['widthMm'] = 61.0
        self.assertIn('semantics differ', fault(self, self.check, self.epub, model=model).message)
        images[0]['widthMm'] = 60; images[1]['sha256'] = '0' * 64
        self.assertIn('semantics differ', fault(self, self.check, self.epub, model=model).message)

    def test_an_unreferenced_media_member_is_refused_even_when_its_bytes_equal_a_referenced_image(self):
        first = self.png_of('EPUB/media/file0.png'); item = b'    <item id="file0_png" href="media/file0.png" media-type="image/png" />\n'
        listed = b'    <item id="file5_png" href="media/file5.png" media-type="image/png" />\n'
        def extra(members):
            return [(n, b.replace(item, item + listed) if n == 'EPUB/content.opf' else b) for n, b in members] + [('EPUB/media/file5.png', first)]
        self.refused(extra, 'media membership differs')
        self.assertIn('EPUB/media/file5.png', self.refused(extra).message)
        # the same member without its manifest item, and a manifest item without the member, are the older refusals
        self.refused(add('EPUB/media/file5.png', first), 'differs')
        self.refused(edit('EPUB/content.opf', item, item + listed), 'differs')
        # the digest set alone cannot decide membership: both digests are referenced, yet a third name carries file1's bytes too
        second = self.png_of('EPUB/media/file1.png'); listed6 = listed.replace(b'file5', b'file6')
        def twice(members):
            return [(n, b.replace(item, item + listed + listed6) if n == 'EPUB/content.opf' else b) for n, b in members] + [('EPUB/media/file5.png', first), ('EPUB/media/file6.png', second)]
        self.refused(twice, 'media membership differs')

    def test_media_closure_is_decided_by_referenced_member_names(self):
        counter = [0]; used = set()
        body = epub.xml_part(epub.XML_DECLARATION + (
            b'<body xmlns="http://www.w3.org/1999/xhtml"><section id="section-1" class="level1"><h1>T</h1>'
            b'<p><img src="../media/file0.png" style="width:10mm" alt="a" /></p><p><img src="../media/file0.png" style="width:10mm" alt="b" /></p></section></body>'), 'x')
        media = {'EPUB/media/file0.png': b'png-bytes', 'EPUB/media/file1.png': b'png-bytes'}
        blocks = epub.chapter_blocks(body, counter, media, used)
        self.assertEqual([b['kind'] for b in blocks], ['heading', 'image', 'image'])
        self.assertEqual(blocks[1]['sha256'], blocks[2]['sha256']); self.assertEqual(used, {'EPUB/media/file0.png'})
        self.assertNotEqual(used, set(media))

    def png_of(self, name):
        with zipfile.ZipFile(io.BytesIO(self.epub)) as archive: return archive.read(name)

    def test_a_model_that_differs_from_the_package_is_refused_in_every_block_kind(self):
        for index, block in enumerate(self.model):
            changed = copy.deepcopy(self.model)
            if block['kind'] == 'heading': changed[index]['text'] += 'x'
            elif block['kind'] == 'paragraph': changed[index]['text'] += 'x'
            elif block['kind'] == 'table': changed[index]['rows'][-1][-1] += 'x'
            else: changed[index]['alt'] += 'x'
            with self.subTest(index=index, kind=block['kind']): self.assertEqual(fault(self, self.check, self.epub, model=changed).code, 'VERIFICATION_FAILED')
        for changed in (self.model[:-1], [*self.model, {'kind': 'paragraph', 'text': 'more'}], self.model[::-1], []):
            self.assertEqual(fault(self, self.check, self.epub, model=changed).code, 'VERIFICATION_FAILED')

    def test_language_tags_are_validated_by_the_same_rule_as_planning(self):
        for value in ('en', 'fr-CA', 'zh-Hans-CN', 'yue'): self.assertTrue(epub.valid_language(value))
        for value in (True, 1, None, 'e', 'en_US', 'en\n', 'é', '-en', 'x' * 36, b'en'): self.assertFalse(epub.valid_language(value), repr(value))


LOCAL = struct.Struct('<4sHHHHHIIIHH')
CENTRAL = struct.Struct('<4sHHHHHHIIIHHHHHII')
END = struct.Struct('<4sHHHHIIH')


def walk(data):
    """Read the genuine fixture's ZIP with struct alone (no zipfile): the fields and raw packed bytes of each member, in physical order."""
    _, _, _, _, count, size, offset, _ = END.unpack_from(data, len(data) - END.size); entries = []; position = offset
    for _ in range(count):
        (_, made, needed, flags, method, clock, day, crc, packed, unpacked, name_length, extra, comment, _, _, external, header) = CENTRAL.unpack_from(data, position)
        name = data[position + CENTRAL.size:position + CENTRAL.size + name_length]; position += CENTRAL.size + name_length
        assert (extra, comment) == (0, 0) and header == sum(LOCAL.size + len(e['name']) + len(e['raw']) for e in entries)
        begin = header + LOCAL.size + name_length
        entries.append({'name': name, 'made': made, 'needed': needed, 'flags': flags, 'method': method, 'clock': clock, 'day': day, 'crc': crc,
                        'packed': packed, 'size': unpacked, 'external': external, 'raw': data[begin:begin + packed]})
    return entries


def build(entries, central=None, prefix=b'', suffix=b'', eocd=None):
    """Write a ZIP byte by byte. Every field can be overridden per entry ('local', 'central', 'local_extra', 'central_extra', 'descriptor', 'gap')."""
    out = bytearray(prefix); offsets = []
    for e in entries:
        l = {**e, **e.get('local', {})}; extra = e.get('local_extra', b''); offsets.append(len(out) - len(prefix))
        out += LOCAL.pack(b'PK\x03\x04', l['needed'], l['flags'], l['method'], l['clock'], l['day'], l['crc'], l['packed'], l['size'], len(l['name']), len(extra))
        out += l['name'] + extra + e['raw'] + e.get('descriptor', b'') + e.get('gap', b'')
    start = len(out) - len(prefix); order = list(range(len(entries))) if central is None else central
    for i in order:
        e = entries[i]; c = {**e, **e.get('central', {})}; extra = e.get('central_extra', b'')
        out += CENTRAL.pack(b'PK\x01\x02', c['made'], c['needed'], c['flags'], c['method'], c['clock'], c['day'], c['crc'], c['packed'], c['size'], len(c['name']),
                            len(extra), 0, 0, 0, c['external'], offsets[i] + e.get('offset_delta', 0)) + c['name'] + extra
    end = {'disk': 0, 'directory_disk': 0, 'here': len(order), 'total': len(order), 'size': len(out) - len(prefix) - start, 'offset': start, 'comment': b'', **(eocd or {})}
    out += END.pack(b'PK\x05\x06', end['disk'], end['directory_disk'], end['here'], end['total'], end['size'], end['offset'], len(end['comment'])) + end['comment']
    return bytes(out + suffix)


def descriptor(entry, signature=True):
    """Make one member use the lawful trailing data descriptor: zeroed local CRC/sizes, flag bit 3 in both headers."""
    values = struct.pack('<III', entry['crc'], entry['packed'], entry['size'])
    return {**entry, 'flags': entry['flags'] | 8, 'local': {'crc': 0, 'packed': 0, 'size': 0}, 'descriptor': (b'PK\x07\x08' if signature else b'') + values}


def patched(entries, name, **changes):
    return [{**e, **changes} if e['name'] == name.encode() else e for e in entries]


def stdlib_reads(data):
    """True when the standard-library reader opens every member without complaint (the tolerance the physical checks must not rely on)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive: return all(archive.read(i) is not None for i in archive.infolist())
    except Exception: return False


class Framing(Genuine):
    """Literal byte-level forgeries of the ZIP container itself: the central directory stays coherent, so the standard reader is not an oracle."""

    def setUp(self):
        self.entries = walk(self.epub)

    def test_the_literal_writer_reproduces_the_genuine_package_byte_for_byte(self):
        self.assertEqual(build(self.entries), self.epub)
        self.assertEqual([e['name'] for e in self.entries][0], b'mimetype'); self.assertEqual(self.entries[0]['method'], 0)

    def test_the_genuine_framing_is_accepted_with_a_lawful_data_descriptor_with_or_without_signature(self):
        for signature in (True, False):
            with self.subTest(signature=signature):
                entries = [descriptor(e, signature) if e['name'] == b'EPUB/nav.xhtml' else e for e in self.entries]
                data = build(entries); self.assertTrue(stdlib_reads(data)); self.assertNotEqual(data, self.epub)
                self.assertEqual(self.check(data)['entries'], 12)

    def test_prefix_suffix_gaps_and_hidden_bytes_are_refused_although_the_standard_reader_opens_them(self):
        cases = {'html prefix': build(self.entries, prefix=b'<html><script>alert(1)</script></html>'), 'trailing bytes': build(self.entries, suffix=b'<script>1</script>'),
                 'hidden bytes between members': build([{**e, 'gap': b'HIDDEN'} if e['name'] == b'EPUB/toc.ncx' else e for e in self.entries]),
                 'hidden bytes after the last member': build([{**e, 'gap': b'\0'} if e is self.entries[-1] else e for e in self.entries]),
                 'hidden bytes after mimetype': build([{**e, 'gap': b'x'} if e['name'] == b'mimetype' else e for e in self.entries]),
                 'local extra on a later member': build([{**e, 'local_extra': b'\xfe\xca\x00\x00'} if e['name'] == b'EPUB/nav.xhtml' else e for e in self.entries]),
                 'local-only extra on mimetype': build([{**e, 'local_extra': b'\xfe\xca\x00\x00'} if e['name'] == b'mimetype' else e for e in self.entries])}
        for label, data in cases.items():
            with self.subTest(label):
                self.assertTrue(stdlib_reads(data), label)
                self.assertEqual(fault(self, self.check, data).code, 'VERIFICATION_FAILED')

    def test_mimetype_extra_fields_are_refused_in_the_local_central_or_both_headers(self):
        extra = b'\xfe\xca\x00\x00'
        for label, change in (('local only', {'local_extra': extra}), ('central only', {'central_extra': extra}), ('both', {'local_extra': extra, 'central_extra': extra})):
            with self.subTest(label): self.assertIn('mimetype', fault(self, self.check, build(patched(self.entries, 'mimetype', **change))).message)

    def test_a_forged_end_record_is_refused(self):
        count = len(self.entries)
        for label, end in (('comment', {'comment': b'x'}), ('count', {'here': count - 1, 'total': count - 1}), ('split counts', {'here': count - 1}), ('disk', {'disk': 1}),
                           ('directory disk', {'directory_disk': 1}), ('zip64 count', {'here': 0xFFFF, 'total': 0xFFFF}), ('zip64 offset', {'offset': 0xFFFFFFFF}),
                           ('directory offset', {'offset': len(self.epub) - 1}), ('directory size', {'size': 1})):
            with self.subTest(label): self.assertEqual(fault(self, self.check, build(self.entries, eocd=end)).code, 'VERIFICATION_FAILED')
        data = self.epub[:-22]; self.assertEqual(fault(self, self.check, data).code, 'VERIFICATION_FAILED')
        self.assertEqual(fault(self, self.check, self.epub + b'\0' * 22).code, 'VERIFICATION_FAILED')

    def test_a_reordered_central_directory_is_refused(self):
        count = len(self.entries); swapped = [1, 0, *range(2, count)]
        self.assertIn('previous member ends', fault(self, self.check, build(self.entries, central=swapped)).message)
        self.assertIn('previous member ends', fault(self, self.check, build(self.entries, central=[0, *range(count - 1, 0, -1)])).message)
        # mimetype physically last but listed first by the central directory: its entry no longer starts at offset 0.
        moved = [*self.entries[1:], self.entries[0]]; listed_first = build(moved, central=[count - 1, *range(count - 1)])
        self.assertTrue(stdlib_reads(listed_first)); self.assertIn('previous member ends', fault(self, self.check, listed_first).message)
        # mimetype physically and centrally last: a coherent archive that is only wrong about the first member.
        self.assertIn('mimetype must be the first member', fault(self, self.check, build(moved)).message)
        # two central entries naming one local header
        self.assertEqual(fault(self, self.check, build(self.entries, central=[0, 1, 1, *range(3, count)], eocd={'here': count, 'total': count})).code, 'VERIFICATION_FAILED')

    def test_every_local_header_field_must_repeat_the_central_entry(self):
        nav = 'EPUB/nav.xhtml'; entry = next(e for e in self.entries if e['name'] == nav.encode())
        cases = {'crc': {'crc': entry['crc'] ^ 1}, 'packed size': {'packed': entry['packed'] + 1}, 'size': {'size': entry['size'] + 1}, 'method': {'method': 0},
                 'flags': {'flags': 0}, 'version needed': {'needed': 10}, 'time': {'clock': 1}, 'date': {'day': 0x22}, 'name': {'name': b'EPUB/nav.xhtmL'},
                 'shorter name': {'name': b'EPUB/nav.xhtm'}, 'descriptor flag': {'flags': 0x808}, 'unsupported flag': {'flags': 0x800 | 0x4}}
        for label, local in cases.items():
            with self.subTest(label): self.assertIn('local header differs', fault(self, self.check, build(patched(self.entries, nav, local=local))).message)
        for label, local in (('mimetype crc', {'crc': 0}), ('mimetype method', {'method': 8}), ('mimetype name', {'name': b'mimetypf'}), ('mimetype size', {'size': 21})):
            with self.subTest(label): self.assertEqual(fault(self, self.check, build(patched(self.entries, 'mimetype', local=local))).code, 'VERIFICATION_FAILED')

    def test_every_central_entry_field_must_repeat_the_member_bytes(self):
        nav = 'EPUB/nav.xhtml'; entry = next(e for e in self.entries if e['name'] == nav.encode())
        cases = {'crc': {'crc': entry['crc'] ^ 1}, 'packed size': {'packed': entry['packed'] - 1}, 'size': {'size': entry['size'] - 1}, 'method': {'method': 0},
                 'flags': {'flags': 0}, 'name': {'name': b'EPUB/NAV.xhtml'}, 'descriptor flag': {'flags': 0x808}, 'encrypted': {'flags': 0x801}}
        for label, central in cases.items():
            with self.subTest(label): self.assertEqual(fault(self, self.check, build(patched(self.entries, nav, central=central))).code, 'VERIFICATION_FAILED')
        self.assertEqual(fault(self, self.check, build(patched(self.entries, nav, offset_delta=-1))).code, 'VERIFICATION_FAILED')
        self.assertEqual(fault(self, self.check, build(patched(self.entries, nav, offset_delta=1))).code, 'VERIFICATION_FAILED')

    def test_a_forged_data_descriptor_is_refused(self):
        nav = next(e for e in self.entries if e['name'] == b'EPUB/nav.xhtml'); good = descriptor(nav)
        bad = {'wrong crc': {**good, 'descriptor': b'PK\x07\x08' + struct.pack('<III', nav['crc'] ^ 1, nav['packed'], nav['size'])},
               'wrong size': {**good, 'descriptor': b'PK\x07\x08' + struct.pack('<III', nav['crc'], nav['packed'], nav['size'] + 1)},
               'missing': {**good, 'descriptor': b''}, 'short': {**good, 'descriptor': b'PK\x07\x08' + struct.pack('<II', nav['crc'], nav['packed'])},
               'long': {**good, 'descriptor': good['descriptor'] + b'\0'}, 'local sizes nonzero and wrong': {**good, 'local': {'crc': 1, 'packed': 2, 'size': 3}},
               'central without flag': {**good, 'central': {'flags': nav['flags']}}}
        for label, changed in bad.items():
            with self.subTest(label):
                entries = [changed if e['name'] == nav['name'] else e for e in self.entries]
                self.assertEqual(fault(self, self.check, build(entries)).code, 'VERIFICATION_FAILED')

    def test_deflate_streams_must_be_complete_exact_and_unpadded(self):
        css = next(e for e in self.entries if e['name'] == b'EPUB/styles/stylesheet1.css')
        for label, changed in (('padding inside the packed length', {**css, 'raw': css['raw'] + b'\0', 'packed': css['packed'] + 1}),
                               ('truncated stream', {**css, 'raw': css['raw'][:-4], 'packed': css['packed'] - 4}),
                               ('declared larger than inflated', {**css, 'size': css['size'] + 1}), ('declared smaller than inflated', {**css, 'size': css['size'] - 1}),
                               ('stored claiming other sizes', {**css, 'method': 0})):
            with self.subTest(label):
                entries = [changed if e is css else e for e in self.entries]; data = build(entries)
                self.assertEqual(fault(self, self.check, data).code, 'VERIFICATION_FAILED')

    def test_oversize_members_are_never_inflated_past_their_declared_size(self):
        bomb = zlib_deflate(bytes(epub.MAX_PART_BYTES))
        entry = {'name': b'EPUB/text/ch009.xhtml', 'made': 0, 'needed': 20, 'flags': 0x800, 'method': 8, 'clock': 0, 'day': 0x21, 'crc': 0, 'packed': len(bomb),
                 'size': epub.MAX_PART_BYTES - 1, 'external': 0, 'raw': bomb}
        self.assertEqual(fault(self, self.check, build([*self.entries, entry])).code, 'VERIFICATION_FAILED')

    def test_physical_forgeries_are_refused_by_verification_even_with_every_hash_refreshed(self):
        entries = self.entries; count = len(entries)
        cases = {'script prefix': lambda data: b'<html><script>1</script>' + data, 'trailing bytes': lambda data: data + b'<script>1</script>',
                 'hidden bytes between members': lambda data: build([{**e, 'gap': b'HIDDEN'} if e['name'] == b'EPUB/nav.xhtml' else e for e in entries]),
                 'central reordered': lambda data: build(entries, central=[1, 0, *range(2, count)]),
                 'mimetype local extra': lambda data: build(patched(entries, 'mimetype', local_extra=b'\xfe\xca\x00\x00')),
                 'local header disagrees': lambda data: build(patched(entries, 'EPUB/nav.xhtml', local={'crc': 0}))}
        for label, change in cases.items():
            with self.subTest(label): self.forged_verify('report.epub', change, 'EPUB')

    def test_a_package_that_nothing_but_the_standard_reader_accepts_is_not_a_publication(self):
        data = b'PK' + self.epub
        self.assertEqual(fault(self, self.check, data).code, 'VERIFICATION_FAILED')
        self.assertEqual(fault(self, self.check, b'').code, 'VERIFICATION_FAILED')
        self.assertEqual(fault(self, self.check, self.epub[:100]).code, 'VERIFICATION_FAILED')
        self.assertEqual(fault(self, self.check, bytes(len(self.epub))).code, 'VERIFICATION_FAILED')
        for cut in (5, 40, 200, len(self.epub) - 30, len(self.epub) - 1):
            with self.subTest(cut=cut): self.assertEqual(fault(self, self.check, self.epub[:cut]).code, 'VERIFICATION_FAILED')


def zlib_deflate(body):
    import zlib
    stream = zlib.compressobj(9, zlib.DEFLATED, -15); return stream.compress(body) + stream.flush()


class Readback(Genuine):
    def refused_readback(self, change, text=None):
        value = copy.deepcopy(self.readback); change(value); facts = self.check(self.epub)
        error = fault(self, epub.readback_report, value, fx.TITLE, fx.LANGUAGE, facts, self.model)
        self.assertEqual(error.code, 'VERIFICATION_FAILED', error.message)
        if text: self.assertIn(text, error.message)

    def chapter(self, value, number=1): return value['blocks'][2 * number][ 'c'][1]

    def test_forged_native_readback_is_refused(self):
        def word(v): self.chapter(v)[1]['c'][0]['c'] = 'Autre'
        def dropped(v): del self.chapter(v)[1]
        def injected(v): self.chapter(v).append({'t': 'Para', 'c': [{'t': 'Str', 'c': 'extra'}]})
        def title(v): v['meta']['title']['c'][0]['c'] = 'Autre'
        def language(v): v['meta']['language']['c'][0]['c'] = 'en'
        def identifier(v): v['meta']['identifier']['c'][0]['c'] = 'urn:uuid:00000000-0000-0000-0000-000000000000'
        def order(v): v['blocks'][2], v['blocks'][4] = v['blocks'][4], v['blocks'][2]
        def marker(v): v['blocks'][1]['c'][0]['c'][0][0] = 'ch009.xhtml'
        def section(v): v['blocks'][2]['c'][0][0] = 'ch001.xhtml_section-9'
        def level(v): v['blocks'][2]['c'][0][1][1] = 'level2'
        def meta(v): v['meta']['subject'] = {'t': 'MetaInlines', 'c': []}
        def block(v): v['blocks'].append({'t': 'RawBlock', 'c': ['html', '<script>x</script>']})
        def raw(v): self.chapter(v).insert(1, {'t': 'RawBlock', 'c': ['html', '<b>x</b>']})
        def softbreak(v): self.chapter(v)[1]['c'][1] = {'t': 'SoftBreak'}
        def span(v): self.chapter(v)[1]['c'][0] = {'t': 'Span', 'c': [['', [], []], [{'t': 'Str', 'c': 'Méthode'}]]}
        def image(v): self.chapter(v)[-1]['c'][-1]['c'][-1]['c'][0]['c'][2][0] = 'media/file9.png'
        def width(v): self.chapter(v)[-1]['c'][-1]['c'][-1]['c'][0]['c'][0][2][0][1] = 'width:61mm'
        def cell(v):
            table = [b for b in self.chapter(v) if b['t'] == 'Table'][0]; table['c'][4][0][3][0][1][0][4][0]['c'][0]['c'] = 'zz'
        def footer(v):
            table = [b for b in self.chapter(v) if b['t'] == 'Table'][0]; table['c'][5][1] = [1]
        for function in (word, dropped, injected, title, language, identifier, order, marker, section, level, meta, block, raw, softbreak, span, cell, footer):
            with self.subTest(function.__name__): self.refused_readback(function)
        value = copy.deepcopy(self.readback)
        for container in (value['blocks'][4]['c'][1][-1],):
            self.assertIn(container['t'], ('Para', 'Plain', 'Div', 'Table'))

    def test_malformed_readback_shapes_never_escape_as_raw_errors(self):
        facts = self.check(self.epub)
        for value in (None, [], {}, {'meta': {}, 'blocks': []}, {'meta': 1, 'blocks': 1}, {**self.readback, 'blocks': [None]}, {**self.readback, 'blocks': [{'t': 'Div'}] * 5},
                      {**self.readback, 'meta': {**self.readback['meta'], 'title': 'x'}}, {**self.readback, 'blocks': self.readback['blocks'][:-1]}):
            with self.subTest(value=str(value)[:60]):
                self.assertEqual(fault(self, epub.readback_report, value, fx.TITLE, fx.LANGUAGE, facts, self.model).code, 'VERIFICATION_FAILED')


class Forged(Genuine):
    """Coherent forgeries: the retained member is replaced AND every evidence digest, artifact digest and stage-input binding is recomputed."""

    def test_the_unforged_run_verifies_after_a_digest_refresh(self):
        saved = self.snapshot()
        try: self.refresh(); self.assertEqual(adaptor.verify(self.run_directory)['artifacts'], 4)
        finally: self.restore(saved)

    def test_forged_packages_are_refused_even_with_every_hash_refreshed(self):
        cases = {'body word': edit('EPUB/text/ch001.xhtml', b'<p>deep</p>', b'<p>dEEp</p>'), 'table cell': edit('EPUB/text/ch001.xhtml', b'<td>z</td>', b'<td>Z</td>'),
                 'title everywhere': edit(None, b'Rapport', b'Rapports'), 'language everywhere': edit(None, b'fr-CA', b'en-CA'),
                 'spine order': edit('EPUB/content.opf', b'    <itemref idref="ch002_xhtml" />\n', b''), 'manifest': edit('EPUB/content.opf', b'media/file0.png', b'media/file5.png'),
                 'navigation': edit('EPUB/nav.xhtml', 'Détails'.encode(), b'Autre'), 'mimetype': edit('mimetype', b'application/epub+zip', b'application/zip'),
                 'script': edit('EPUB/text/ch001.xhtml', b'<p>deep</p>', b'<p>deep</p><script>1</script>'), 'external css': edit('EPUB/text/ch001.xhtml', b'../styles/stylesheet1.css', b'https://example.test/x.css'),
                 'external image': edit('EPUB/text/ch001.xhtml', b'../media/file1.png', b'https://example.test/b.png'), 'font': add('EPUB/fonts/f.otf', b'x'),
                 'unsafe member': add('../evil', b'x'), 'media body': edit('EPUB/media/file0.png', self.png('EPUB/media/file0.png'), docx.png(8, 4, 99))}
        for label, change in cases.items():
            with self.subTest(label): self.forged_verify('report.epub', lambda data, change=change: rewrite(data, change), 'EPUB')

    def png(self, name):
        with zipfile.ZipFile(io.BytesIO(self.epub)) as archive: return archive.read(name)

    def test_forged_native_readback_is_refused_even_with_every_hash_refreshed(self):
        def forge(data):
            value = json.loads(data); value['blocks'][2]['c'][1][1]['c'][0]['c'] = 'Autre'; return json.dumps(value).encode()
        self.forged_verify('epub-reopened.json', forge, 'native EPUB readback')
        self.forged_verify('epub-reopened.json', lambda data: b'{}', 'native EPUB readback')
        self.forged_verify('epub-reopened.json', lambda data: b'[', 'malformed retained JSON')

    def test_a_claimed_publication_that_is_missing_or_unclaimed_is_refused(self):
        saved = self.snapshot()
        try:
            (self.run_directory / 'report.epub').unlink(); self.refresh_without_epub_digest()
            self.assertIn('report.epub', self.verify_message())
        finally: self.restore(saved)
        # An EPUB file beside a report whose authored declaration (and plan) carry none is an undeclared member.
        try:
            authored = json.loads((self.run_directory / 'authored.json').read_text()); del authored['epub']
            (self.run_directory / 'authored.json').write_text(json.dumps(authored)); (self.run_directory / 'plan.json').write_text(json.dumps(adaptor.plan(authored)))
            self.assertIn('differs', self.verify_message())
            self.refresh(); self.assertIn('differs', self.verify_message())
        finally: self.restore(saved)
        # A receipt that omits the EPUB artifact while the authored report declares one.
        try:
            receipt = json.loads((self.run_directory / 'verification.json').read_text()); receipt['artifacts'] = receipt['artifacts'][:3]
            (self.run_directory / 'verification.json').write_text(json.dumps(receipt)); self.assertIn('differs', self.verify_message())
        finally: self.restore(saved)
        try:
            receipt = json.loads((self.run_directory / 'verification.json').read_text()); del receipt['evidence']['epub-reopened.json']
            (self.run_directory / 'verification.json').write_text(json.dumps(receipt)); self.assertIn('evidence membership differs', self.verify_message())
        finally: self.restore(saved)

    def refresh_without_epub_digest(self):
        directory = self.run_directory; receipt = json.loads((directory / 'verification.json').read_text())
        receipt['artifacts'] = adaptor.artifacts(directory, False) + [{'file': str(directory / 'report.epub'), 'kind': 'file', 'sha256': '0' * 64}]
        (directory / 'verification.json').write_text(json.dumps(receipt))

    def test_a_forged_declaration_language_is_refused_when_the_plan_and_capture_are_rewritten(self):
        saved = self.snapshot()
        try:
            authored = json.loads((self.run_directory / 'authored.json').read_text()); authored['epub']['language'] = 'en-CA'
            (self.run_directory / 'authored.json').write_text(json.dumps(authored)); (self.run_directory / 'plan.json').write_text(json.dumps(adaptor.plan(authored)))
            self.refresh(); message = self.verify_message(); self.assertTrue('native command' in message or 'launcher' in message or 'EPUB' in message, message)
        finally: self.restore(saved)

    def test_an_epub_added_to_a_report_without_the_declaration_is_undeclared(self):
        directory = self.directory / 'plain-forge'; adaptor.run(fx.document(self.directory, language=None), directory, executable=self.executable)
        shutil.copyfile(self.run_directory / 'report.epub', directory / 'report.epub')
        error = fault(self, adaptor.verify, directory); self.assertEqual(error.code, 'VERIFICATION_FAILED'); self.assertIn('undeclared', error.message)


class Declarations(unittest.TestCase):
    def test_discovery_guidance_and_readiness_describe_the_epub(self):
        from schemaxis.adaptors.pandoc import capabilities
        catalogue = capabilities.catalogue(); operation = catalogue['operations']['report']
        for term in ('EPUB', 'EPUB 3', 'epub3', 'ebook', 'e-book'): self.assertIn(term, operation['keywords'])
        guidance = json.loads((ROOT / 'src/schemaxis/adaptors/pandoc/guidance.json').read_text())['routes']['schemaxis.pandoc/1']['fields']
        for address in ('/properties/epub', '/properties/epub/properties/language'):
            record = guidance[address]; self.assertEqual(record['status'], 'reviewed')
            for key in ('explanation', 'defaultMeaning', 'pitfalls'): self.assertTrue(record[key], (address, key))
        self.assertIn('EPUBCheck', guidance['/properties/epub']['explanation'])
        route = json.loads((ROOT / 'src/schemaxis/adaptors/pandoc/readiness.json').read_text())['routes']['schemaxis.pandoc/1']
        self.assertIn('verification/2026-10-25-pandoc-50.md', route['completion']['review']); self.assertTrue((ROOT / 'verification/2026-10-25-pandoc-50.md').is_file())
        self.assertIn('tests/unit/test_pandoc_epub.py', route['conformance']); self.assertIn('tools/qualify_pandoc_epub.py', route['acceptance'])
        ids = {e['id']: e for e in route['examples']}
        self.assertIn('epub-report', ids); self.assertEqual((ids['invalid-epub-language']['fault'], ids['invalid-epub-language']['schemaValid']), ('INVALID_ARGUMENT', True))

    def test_examples_and_the_studio_template_plan_or_name_the_field(self):
        planned = adaptor.plan(json.loads((ROOT / 'examples/schemaxis/pandoc-report-epub.json').read_text()))
        self.assertEqual(planned['epub'], {'language': 'fr-CA'}); self.assertEqual(planned['losses'][-1], adaptor.EPUB_LOSS)
        error = fault(self, adaptor.plan, json.loads((ROOT / 'examples/schemaxis/pandoc-report-epub-invalid.json').read_text()))
        self.assertEqual((error.code, error.location), ('INVALID_ARGUMENT', '$.epub.language'))
        studio = json.loads((ROOT / 'src/schemaxis/adaptors/pandoc/studio.json').read_text())
        template = next(t for t in studio['templates'] if t['id'] == 'report-epub')
        self.assertEqual(adaptor.plan(template['document'])['epub'], {'language': 'en'})

    def test_search_cases_find_the_epub_route_and_the_neighbours_stay_apart(self):
        cases = {c['id']: c for c in json.loads((ROOT / 'src/schemaxis/adaptors/pandoc/search-cases.json').read_text())}
        self.assertEqual(cases['publish-epub']['status'], 'reviewed'); self.assertTrue(cases['publish-epub']['expected'])
        self.assertTrue(any('epub' in json.dumps(c).lower() for c in cases.values() if c['id'] != 'publish-epub'))


if __name__ == '__main__':
    unittest.main()
