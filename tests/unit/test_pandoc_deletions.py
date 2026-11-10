"""Pandoc `transcript` block over a reviewed/2 document: partial deletion and the justified no-cue state.

Host tests only: no Pandoc is launched here. The native HTML and DOCX readback is `tools/qualify_whispercpp_deletions.py`.
A report of no cues publishes the provenance paragraph alone, so no spoken words are invented and the trusted native readers,
which require a table to hold a header and at least one data row, are not relaxed.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.pandoc import adaptor
from schemaxis.adaptors.whispercpp import corrections_deletion as deletion
from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import test_timed_text as source  # noqa: E402
from test_pandoc_timedtext import report, timed_text_fault  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pandoc-deletions-')); self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.draft = self.directory / 'segments.json'; self.draft.write_bytes(source.encode(source.document()))
        self.digest = hashlib.sha256(self.draft.read_bytes()).hexdigest()

    def reviewed(self, *, deletions=(), corrections=(), status=None, name='reviewed-segments.json'):
        authored = {'version': deletion.VERSION, 'draft': {'path': str(self.draft)}, 'basisSha256': self.digest,
                    'review': {'status': status or ('human-corrected' if deletions or corrections else 'human-reviewed-unchanged'), 'note': 'Illustrative automated declaration; no person reviewed this.'}}
        if deletions: authored['deletions'] = list(deletions)
        if corrections: authored['corrections'] = list(corrections)
        outputs, _, _ = deletion.derive(deletion.plan(authored), self.draft.read_bytes())
        path = self.directory / name; path.write_bytes(outputs['reviewed-segments.json']); return path

    def view(self, **kw): return adaptor.transcript_view(self.reviewed(**kw).read_bytes(), '$')


class Reviewed2(Fixture):

    def test_timecode_preserves_deletion_counts_and_omits_an_empty_table(self):
        for indices, expected_rows in (((0,), [['00:00:05.410', '00:00:11.000', 'ask not what your country can do.']]),
                                       ((0, 1), [])):
            with self.subTest(deletions=indices):
                path = self.reviewed(deletions=indices)
                document = report(path)
                block = document['sections'][0]['content'][0]
                block['timeFormat'] = 'timecode'
                prepared = adaptor.plan(document)
                view = adaptor.transcript_view(path.read_bytes(), '$')
                paragraph, columns, rows = adaptor.transcript_content(view, 'timecode')
                self.assertEqual(rows, expected_rows)
                self.assertEqual(columns, adaptor.TIMECODE_COLUMNS if rows else [])
                self.assertIn('audio duration 00:00:11.000', paragraph)
                summary = adaptor.transcript_summary(block, view)
                self.assertEqual((summary['sourceCues'], summary['deletedCues'], summary['timeFormat']),
                                 (2, len(indices), 'timecode'))
                (self.directory / 'transcript-0-0.json').write_bytes(path.read_bytes())
                model = adaptor.expected({**prepared, '_directory': self.directory})
                tree = adaptor.ast(prepared, [1, 23], self.directory)
                self.assertEqual(sum(item['kind'] == 'table' for item in model), 1 if rows else 0)
                self.assertEqual(sum(item['t'] == 'Table' for item in tree['blocks']), 1 if rows else 0)

    def test_partial_deletion_states_the_deleted_source_cues_and_publishes_only_retained_rows(self):
        view = self.view(deletions=[0], corrections=[{'index': 1, 'text': 'ask not what your country can do for you.'}])
        paragraph, columns, rows = adaptor.transcript_content(view)
        self.assertEqual((columns, rows), (adaptor.TRANSCRIPT_COLUMNS, [['5410', '11000', 'ask not what your country can do for you.']]))
        for fragment in ('Status: human-corrected, declared by the author of the corrections.', f'machine draft SHA-256 {self.digest}, 2 cues',
                         '1 cue replaced by authored text (source cue indexes 1)', '1 cue of 2 deleted by the author (source cue indexes 0)',
                         'the remaining 1 cue are numbered from zero as published', 'not verified or certified', 'Language en; 1 cue; audio duration 11000 ms', view['sha256']):
            self.assertIn(fragment, paragraph)
        self.assertNotIn('a person has not reviewed it', paragraph)
        adaptor.plain(paragraph, '$')

    def test_the_no_cue_state_publishes_the_paragraph_alone_with_no_invented_words(self):
        view = self.view(deletions=[0, 1]); self.assertEqual(view['cues'], [])
        paragraph, columns, rows = adaptor.transcript_content(view)
        self.assertEqual((columns, rows), ([], []))
        for fragment in ('Status: human-corrected, declared by the author of the corrections.', f'machine draft SHA-256 {self.digest}, 2 cues', '2 cues of 2 deleted by the author (source cue indexes 0, 1)',
                         'the author deleted every cue, so no cues are retained and no spoken words are published here', "this is the author's declaration, not evidence that the recording holds no speech",
                         'Language en; 0 cues;', 'not verified or certified'):
            self.assertIn(fragment, paragraph)
        for text in ('And so', 'ask not what', 'machine-draft.'): self.assertNotIn(text, paragraph)
        adaptor.plain(paragraph, '$')

    def test_ast_and_expected_model_hold_one_paragraph_and_a_table_only_when_cues_remain(self):
        for deletions, kinds, tree in (((0,), ['heading', 'paragraph', 'paragraph', 'table'], ['Header', 'Para', 'Para', 'Table']),
                                       ((0, 1), ['heading', 'paragraph', 'paragraph'], ['Header', 'Para', 'Para'])):
            with self.subTest(deletions=deletions):
                directory = Path(tempfile.mkdtemp(prefix='ast-')); self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
                document = report('/x/segments.json'); document['sections'][0]['content'].insert(0, {'kind': 'paragraph', 'text': 'Intro.'})
                prepared = adaptor.plan(document)
                (directory / 'transcript-0-1.json').write_bytes(self.reviewed(deletions=deletions).read_bytes())
                self.assertEqual([b['t'] for b in adaptor.ast(prepared, [1, 23], directory)['blocks']], tree)
                self.assertEqual([b['kind'] for b in adaptor.expected({**prepared, '_directory': directory})], kinds)

    def test_summary_gains_deletion_counts_only_for_reviewed2_and_earlier_summaries_are_unchanged(self):
        block = {'segments': {'path': '/x/segments.json'}}
        empty = adaptor.transcript_summary(block, self.view(deletions=[0, 1]))
        self.assertEqual((empty['status'], empty['cues'], empty['characters'], empty['sourceCues'], empty['deletedCues']), ('human-corrected', 0, 0, 2, 2))
        partial = adaptor.transcript_summary(block, self.view(deletions=[1]))
        self.assertEqual((partial['cues'], partial['sourceCues'], partial['deletedCues']), (1, 2, 1))
        keys = {'source', 'kind', 'status', 'sha256', 'bytes', 'cues', 'characters'}
        self.assertEqual(set(adaptor.transcript_summary(block, adaptor.transcript_view(self.draft.read_bytes(), '$'))), keys)
        from test_timed_text import reviewed_document
        self.assertEqual(set(adaptor.transcript_summary(block, adaptor.transcript_view(source.encode(reviewed_document()), '$'))), keys)

    def test_a_run_captures_the_empty_document_and_binds_its_status(self):
        path = self.reviewed(deletions=[0, 1])
        with patch.object(adaptor, 'launch', side_effect=SchemaxisError(timed_text_fault())):
            with self.assertRaises(SchemaxisError):
                adaptor.run(report(path, sha256=hashlib.sha256(path.read_bytes()).hexdigest()), self.directory / 'run', executable=shutil.which('true'))
        captured = json.loads((self.directory / 'run/captures.json').read_text())['transcript-0-0.json']
        self.assertEqual((captured['status'], captured['cues'], captured['sourceCues'], captured['deletedCues']), ('human-corrected', 0, 2, 2))
        self.assertEqual((self.directory / 'run/transcript-0-0.json').read_bytes(), path.read_bytes())

    def test_a_forged_empty_or_inconsistent_reviewed2_document_is_refused_at_capture(self):
        good = json.loads(self.reviewed(deletions=[0]).read_text())
        def forge(change):
            value = copy.deepcopy(good); change(value); return value
        empty = lambda d: (d.update(segments=[], segmentCount=0), d['review'].update(retainedSourceIndices=[]))
        for label, change in (('empty without every cue deleted', empty),
                              ('mapping disagrees', lambda d: d['review'].update(retainedSourceIndices=[0])),
                              ('deleted index moved', lambda d: d['review'].update(deletedSourceIndices=[1])),
                              ('identity claimed', lambda d: d['review'].update(identityVerified=True)),
                              ('unchanged with a deletion', lambda d: d['review'].update(status='human-reviewed-unchanged'))):
            target = self.directory / 'forged.json'; target.write_bytes(source.encode(forge(change)))
            with self.subTest(label), patch.object(adaptor, 'launch', side_effect=AssertionError('native stage launched')):
                with self.assertRaises(SchemaxisError) as caught:
                    adaptor.run(report(target), self.directory / ('run-' + label.replace(' ', '-')), executable=shutil.which('true'))
            self.assertIn(caught.exception.fault.code, ('TIMED_TEXT_INVALID', 'TIMED_TEXT_REVIEW_UNSUPPORTED'), label)

    def test_plans_keep_the_existing_transcript_loss_and_the_earlier_wording_is_never_accepted_for_reviewed2(self):
        current = adaptor.plan(report('/x/segments.json'))
        self.assertEqual(current['losses'][-1], adaptor.TRANSCRIPT_LOSS)
        path = self.reviewed(deletions=[0, 1]); executable = shutil.which('true')
        with patch.object(adaptor, 'launch', side_effect=SchemaxisError(timed_text_fault())):
            with self.assertRaises(SchemaxisError): adaptor.run(report(path), self.directory / 'run', executable=executable)
        run = self.directory / 'run'
        (run / 'verification.json').write_text(json.dumps({'executable': executable, 'runtime': 'pandoc 3.12.1', 'artifacts': [], 'evidence': {}}))
        stored = json.loads((run / 'plan.json').read_text()); stored['losses'][-1] = adaptor.LEGACY_TRANSCRIPT_LOSS
        (run / 'plan.json').write_text(json.dumps(stored))
        with self.assertRaises(SchemaxisError) as caught: adaptor.verify(run, require_result=False)
        self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('VERIFICATION_FAILED', 'plan.json'))

    def test_the_report_budget_counts_the_no_cue_paragraph(self):
        view = self.view(deletions=[0, 1]); paragraph, columns, rows = adaptor.transcript_content(view)
        self.assertEqual(len(paragraph) + sum(len(x) for x in columns) + sum(len(x) for r in rows for x in r), len(paragraph))

class Observations(Fixture):
    """`inspect` states the actual publication of each captured reviewed/2 transcript; the summary is compared exactly by verify."""

    def inspect(self, paths, *, shapes=None, formats=None):
        """The report summary `inspect` writes for these captured transcripts, with the three native readbacks stubbed out."""
        directory = Path(tempfile.mkdtemp(prefix='observations-')); self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        document = report(paths[0]); document['sections'][0]['content'] = [{'kind': 'transcript', 'segments': {'path': str(path)}} for path in paths]
        if formats is not None:
            self.assertEqual(len(formats), len(paths))
            for block, requested in zip(document['sections'][0]['content'], formats):
                if requested is not None: block['timeFormat'] = requested
        prepared = adaptor.plan(document)
        for j, path in enumerate(paths): (directory / f'transcript-0-{j}.json').write_bytes(Path(path).read_bytes())
        (directory / 'report.html').write_text('x'); (directory / 'report.docx').write_bytes(b'x')
        from schemaxis.adaptors.pandoc import inspection
        with patch.object(inspection, 'html_report'), patch.object(inspection, 'docx_report'), patch.object(inspection, 'ast_report'), patch.object(adaptor, 'read', return_value={}):
            return adaptor.inspect(directory, prepared)

    def test_observations_and_mixed_time_formats_share_document_order(self):
        partial = self.reviewed(deletions=[0], name='partial.json')
        empty = self.reviewed(deletions=[0, 1], name='empty.json')
        summary = self.inspect([partial, empty], formats=['timecode', 'milliseconds'])
        self.assertEqual(summary['tables'], 1)
        self.assertEqual(summary['transcriptTimeFormats'], ['timecode', 'milliseconds'])
        observations = summary['transcriptObservations']
        self.assertEqual(len(observations), 2)
        self.assertTrue(observations[0].startswith('$.sections[0].content[0]:'))
        self.assertIn('1 of 2 source cues deleted', observations[0])
        self.assertIn('one three-column table', observations[0])
        self.assertTrue(observations[1].startswith('$.sections[0].content[1]:'))
        self.assertIn('2 of 2 source cues deleted', observations[1])
        self.assertIn('no table is published', observations[1])

    def test_every_cue_deleted_reports_that_no_table_is_published(self):
        summary = self.inspect([self.reviewed(deletions=[0, 1])])
        self.assertEqual(summary['tables'], 0)
        self.assertEqual(len(summary['transcriptObservations']), 1)
        text = summary['transcriptObservations'][0]
        for fragment in ('$.sections[0].content[0]: ', timed_text.REVIEWED2_VERSION, '2 of 2 source cues deleted by the author', '0 cues retained', 'no table is published',
                         'only the provenance paragraph', 'plan transcript-loss sentence'):
            self.assertIn(fragment, text)
        self.assertNotIn('one three-column table of the', text)

    def test_partial_deletion_reports_the_retained_count_and_one_table(self):
        summary = self.inspect([self.reviewed(deletions=[0])])
        text, = summary['transcriptObservations']
        for fragment in ('$.sections[0].content[0]: ', timed_text.REVIEWED2_VERSION, '1 of 2 source cues deleted by the author', '1 cue retained', 'one three-column table'):
            self.assertIn(fragment, text)
        self.assertNotIn('no table is published', text)

    def test_replacement_only_reviewed2_reports_no_deletion_and_a_table(self):
        text, = self.inspect([self.reviewed(corrections=[{'index': 0, 'text': 'And so, my fellow Americans:'}])])['transcriptObservations']
        for fragment in ('0 of 2 source cues deleted by the author', '2 cues retained', 'one three-column table'): self.assertIn(fragment, text)

    def test_machine_draft_and_reviewed1_add_no_observation_member(self):
        from test_timed_text import reviewed_document
        reviewed1 = self.directory / 'reviewed1.json'; reviewed1.write_bytes(source.encode(reviewed_document()))
        for label, paths in (('machine draft', [self.draft]), ('reviewed/1', [reviewed1]), ('both', [self.draft, reviewed1])):
            with self.subTest(label):
                summary = self.inspect(paths)
                self.assertNotIn('transcriptObservations', summary)
                self.assertEqual(set(summary), {'title', 'sections', 'blocks', 'tables', 'images', 'losses', 'transcripts'})
                self.assertEqual(summary['losses'][-1], adaptor.TRANSCRIPT_LOSS)

    def test_only_the_reviewed2_transcript_is_named_and_by_its_own_block_address(self):
        summary = self.inspect([self.draft, self.reviewed(deletions=[1])])
        text, = summary['transcriptObservations']
        self.assertTrue(text.startswith('$.sections[0].content[1]: '), text)
        self.assertEqual(summary['transcripts'], 2)

    def test_two_reviewed2_transcripts_are_listed_in_document_order(self):
        first, second = self.reviewed(deletions=[0, 1], name='a.json'), self.reviewed(deletions=[0], name='b.json')
        texts = self.inspect([first, second])['transcriptObservations']
        self.assertEqual([t.split(':')[0] for t in texts], ['$.sections[0].content[0]', '$.sections[0].content[1]'])
        self.assertIn('no table is published', texts[0]); self.assertIn('one three-column table', texts[1])

    def test_the_summary_member_is_bound_by_the_exact_comparison_verify_makes(self):
        path = self.reviewed(deletions=[0, 1]); honest = self.inspect([path])
        forged = {**honest, 'transcriptObservations': [honest['transcriptObservations'][0].replace('no table is published', 'one three-column table is published')]}
        self.assertNotEqual(honest, forged)
        self.assertEqual(self.inspect([path]), honest)
        stripped = {k: v for k, v in honest.items() if k != 'transcriptObservations'}
        self.assertNotEqual(honest, stripped)

    def test_the_observation_is_built_from_the_validated_retained_view(self):
        path = self.reviewed(deletions=[0, 1]); forged = json.loads(path.read_text()); forged['review']['retainedSourceIndices'] = [0]; path.write_bytes(source.encode(forged))
        with self.assertRaises(SchemaxisError): self.inspect([path])


if __name__ == '__main__':
    unittest.main()
