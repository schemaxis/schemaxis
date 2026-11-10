"""Pandoc `transcript` block over a reviewed/3 document: author-edited cue times, stated truthfully and published exactly.

Host tests only: no Pandoc is launched here. The native HTML, DOCX and EPUB readback is `tools/qualify_whispercpp_timing.py`.
The provenance paragraph must say the times were edited by the author (count and source indexes) and must never claim the machine
draft's timing was preserved; the tables carry the exact edited integers (or HH:MM:SS.mmm) in the published cue order.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from schemaxis.adaptors.pandoc import adaptor
from schemaxis.adaptors.whispercpp import corrections_deletion as deletion
from schemaxis.adaptors.whispercpp import corrections_timing as timing
from schemaxis.core import timed_text

sys.path.insert(0, str(Path(__file__).parent))
import test_timed_text as source  # noqa: E402
from test_pandoc_timedtext import report  # noqa: E402

NOTE = 'Illustrative automated declaration; no person listened to or reviewed this.'


class Fixture(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pandoc-timing-')); self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.draft = self.directory / 'segments.json'; self.draft.write_bytes(source.encode(source.document()))
        self.digest = hashlib.sha256(self.draft.read_bytes()).hexdigest()

    def reviewed(self, *, timings=(), deletions=(), corrections=(), name='reviewed-segments.json', version=timing):
        authored = {'version': version.VERSION, 'draft': {'path': str(self.draft)}, 'basisSha256': self.digest,
                    'review': {'status': 'human-corrected' if timings or deletions or corrections else 'human-reviewed-unchanged', 'note': NOTE}}
        if timings: authored['timings'] = list(timings)
        if deletions: authored['deletions'] = list(deletions)
        if corrections: authored['corrections'] = list(corrections)
        outputs, _, _ = version.derive(version.plan(authored), self.draft.read_bytes())
        path = self.directory / name; path.write_bytes(outputs['reviewed-segments.json']); return path

    def view(self, **kw): return adaptor.transcript_view(self.reviewed(**kw).read_bytes(), '$')


EDITS = [{'index': 0, 'startMs': 100, 'endMs': 5400}, {'index': 1, 'startMs': 5500, 'endMs': 10900}]


class Reviewed3(Fixture):
    def test_the_paragraph_says_the_times_were_author_edited_with_count_and_source_indexes(self):
        view = self.view(timings=EDITS)
        self.assertEqual(view['source'], timed_text.REVIEWED3_VERSION)
        paragraph, columns, rows = adaptor.transcript_content(view)
        self.assertEqual((columns, rows), (adaptor.TRANSCRIPT_COLUMNS, [['100', '5400', 'And so, my fellow Americans,'], ['5500', '10900', 'ask not what your country can do.']]))
        for fragment in ('Status: human-corrected, declared by the author of the corrections.', f'machine draft SHA-256 {self.digest}, 2 cues',
                         '2 cues given author-edited start and end times (source cue indexes 0, 1)',
                         "The times shown for the 2 cues listed above are edited times recorded in this document as the author's, not the machine draft's; the original machine times are not shown here.",
                         'Whether any time is synchronized with the audio is not verified or certified.', 'not verified or certified', 'Language en; 2 cues; audio duration 11000 ms'):
            self.assertIn(fragment, paragraph)
        for forbidden in ('preserved', 'original timestamps', 'timings are unchanged', 'unchanged times', 'retained timing'):
            self.assertNotIn(forbidden, paragraph)

    def test_one_edit_uses_the_singular_and_names_only_the_edited_source_index(self):
        paragraph, _, rows = adaptor.transcript_content(self.view(timings=EDITS[1:]))
        self.assertIn('1 cue given author-edited start and end times (source cue indexes 1)', paragraph)
        self.assertIn("The times shown for the 1 cue listed above are", paragraph)
        self.assertIn('The other 1 cue shows the original machine times as recorded in this document.', paragraph)
        self.assertEqual(rows[0][:2], ['0', '5410']); self.assertEqual(rows[1][:2], ['5500', '10900'])

    def test_a_reviewed3_with_text_deletion_and_timing_names_each_kind_of_edit(self):
        view = self.view(corrections=[{'index': 1, 'text': 'ask not what your country can do for you.'}], deletions=[0], timings=[{'index': 1, 'startMs': 5000, 'endMs': 10000}])
        paragraph, _, rows = adaptor.transcript_content(view)
        for fragment in ('1 cue replaced by authored text (source cue indexes 1)', '1 cue of 2 deleted by the author (source cue indexes 0)',
                         '1 cue given author-edited start and end times (source cue indexes 1)', 'the remaining 1 cue are numbered from zero as published'):
            self.assertIn(fragment, paragraph)
        self.assertEqual(rows, [['5000', '10000', 'ask not what your country can do for you.']])

    def test_timecode_publishes_the_exact_edited_times(self):
        view = self.view(timings=EDITS)
        paragraph, columns, rows = adaptor.transcript_content(view, 'timecode')
        self.assertEqual((columns, rows), (adaptor.TIMECODE_COLUMNS, [['00:00:00.100', '00:00:05.400', 'And so, my fellow Americans,'], ['00:00:05.500', '00:00:10.900', 'ask not what your country can do.']]))
        self.assertIn('HH:MM:SS.mmm', paragraph)

    def test_an_unedited_reviewed3_states_that_every_time_is_the_machine_drafts(self):
        view = self.view(corrections=[{'index': 0, 'text': 'And so my fellow Americans.'}], version=timing)
        paragraph, _, rows = adaptor.transcript_content(view)
        self.assertIn("The author edited no cue times; the times shown are the machine draft's original times as recorded in this document, and Pandoc did not check them against the draft file.", paragraph)
        self.assertIn('1 cue replaced by authored text (source cue indexes 0)', paragraph)
        self.assertNotIn('author-edited', paragraph); self.assertNotIn('edited times', paragraph); self.assertNotIn('Every time shown is', paragraph)
        self.assertIn('Whether any time is synchronized with the audio is not verified or certified.', paragraph)
        self.assertEqual(rows[0][:2], ['0', '5410'])

    def test_an_untouched_reviewed3_says_nothing_changed_and_makes_no_authored_time_claim(self):
        paragraph, _, rows = adaptor.transcript_content(self.view())
        self.assertIn('Status: human-reviewed-unchanged', paragraph); self.assertIn('no cue text or time changed', paragraph)
        self.assertIn('The author edited no cue times; the times shown are the machine draft\'s original times as recorded in this document', paragraph)
        for forbidden in ('author-edited', 'edited times', 'authenticat', 'verified against the machine'): self.assertNotIn(forbidden, paragraph)
        self.assertEqual([r[:2] for r in rows], [['0', '5410'], ['5410', '11000']])

    def test_text_replacement_and_retiming_of_the_same_cue_names_both_and_shows_only_the_published_time(self):
        view = self.view(corrections=[{'index': 0, 'text': 'And so, my fellow citizens,'}], timings=EDITS[:1])
        paragraph, _, rows = adaptor.transcript_content(view)
        for fragment in ('1 cue replaced by authored text (source cue indexes 0)', '1 cue given author-edited start and end times (source cue indexes 0)',
                         "The times shown for the 1 cue listed above are edited times recorded in this document as the author's, not the machine draft's; the original machine times are not shown here.",
                         'The other 1 cue shows the original machine times as recorded in this document.'):
            self.assertIn(fragment, paragraph)
        self.assertEqual([r[:3] for r in rows], [['100', '5400', 'And so, my fellow citizens,'], ['5410', '11000', 'ask not what your country can do.']])
        self.assertNotIn('"0", "5410"', json.dumps(rows)); self.assertNotIn('Pandoc did not check', paragraph)

    def test_text_edits_without_timing_edits_never_claim_authored_times(self):
        view = self.view(corrections=[{'index': 1, 'text': 'ask not what your country can do for you.'}], deletions=[0])
        paragraph, _, rows = adaptor.transcript_content(view)
        self.assertIn('the remaining 1 cue are numbered from zero as published', paragraph)
        self.assertIn('The author edited no cue times', paragraph); self.assertNotIn('author-edited', paragraph)
        self.assertEqual(rows[0][:2], ['5410', '11000'])

    def test_the_all_cues_deleted_state_publishes_provenance_only(self):
        view = self.view(deletions=[0, 1])
        paragraph, columns, rows = adaptor.transcript_content(view)
        self.assertEqual((columns, rows), ([], []))
        self.assertIn('the author deleted every cue', paragraph); self.assertIn('No cue times are shown because no cues are retained.', paragraph)
        for forbidden in ('Every time shown', 'original times', 'edited times', 'synchronized'): self.assertNotIn(forbidden, paragraph)

    def test_summary_binds_closed_typed_members_and_older_summaries_do_not_change(self):
        path = self.reviewed(timings=EDITS); view = adaptor.transcript_view(path.read_bytes(), '$')
        block = report(path)['sections'][0]['content'][0]
        summary = adaptor.transcript_summary(block, view)
        self.assertEqual((summary['sourceCues'], summary['deletedCues'], summary['timingEditedCues'], summary['timingEditedSourceIndices'], summary['cues']), (2, 0, 2, [0, 1], 2))
        self.assertTrue(all(type(i) is int for i in summary['timingEditedSourceIndices']))
        self.assertEqual(set(summary), {'source', 'kind', 'status', 'sha256', 'bytes', 'cues', 'characters', 'sourceCues', 'deletedCues', 'timingEditedCues', 'timingEditedSourceIndices'})
        old = adaptor.transcript_summary(block, adaptor.transcript_view(self.reviewed(deletions=[1], version=deletion).read_bytes(), '$'))
        self.assertEqual(set(old), {'source', 'kind', 'status', 'sha256', 'bytes', 'cues', 'characters', 'sourceCues', 'deletedCues'})

    def test_observations_state_the_edited_times_and_the_old_observations_keep_their_wording(self):
        for version, kw in ((timing, {'timings': EDITS}), (deletion, {'deletions': [1]})):
            path = self.reviewed(version=version, name=f'{version.__name__}.json', **kw)
            prepared = adaptor.plan(report(path))
            (self.directory / 'transcript-0-0.json').write_bytes(path.read_bytes())
            observations = adaptor.transcript_observations(self.directory, prepared)
            self.assertEqual(len(observations), 1)
            if version is timing:
                self.assertIn(f'{timed_text.REVIEWED3_VERSION}; 0 of 2 source cues deleted by the author; 2 cues with author-edited times (source cue indexes 0, 1)', observations[0])
                self.assertIn("recorded in this document as the author's times and not as the machine draft's", observations[0])
                self.assertNotIn('published as the author', observations[0])
            else:
                self.assertEqual(observations, [f'$.sections[0].content[0]: {timed_text.REVIEWED2_VERSION}; 1 of 2 source cues deleted by the author; 1 cue retained; '
                                                'one three-column table of the retained cues follows the provenance paragraph'])

    def test_observations_branch_on_edit_count_and_retained_cues(self):
        cases = (('combined', {'corrections': [{'index': 0, 'text': 'And so, my fellow citizens,'}], 'timings': EDITS[:1]},
                  '0 of 2 source cues deleted', '1 cue with author-edited times (source cue indexes 0), recorded in this document as the author\'s times and not as the machine draft\'s; 2 cues retained'),
                 ('text-only', {'corrections': [{'index': 0, 'text': 'And so, my fellow citizens,'}]},
                  '0 of 2 source cues deleted', "no cue times edited by the author; the times shown are those recorded in this document as the machine draft's originals; 2 cues retained"),
                 ('untouched', {}, '0 of 2 source cues deleted', "no cue times edited by the author; the times shown are those recorded in this document as the machine draft's originals; 2 cues retained"),
                 ('all-gone', {'deletions': [0, 1]}, '2 of 2 source cues deleted', 'no cue times are shown; 0 cues retained'))
        for label, kw, deleted, tail in cases:
            with self.subTest(label):
                path = self.reviewed(name=f'{label}.json', **kw); prepared = adaptor.plan(report(path))
                (self.directory / 'transcript-0-0.json').write_bytes(path.read_bytes())
                text = adaptor.transcript_observations(self.directory, prepared)[0]
                self.assertIn(f'{timed_text.REVIEWED3_VERSION}; {deleted} by the author; {tail}', text)
                if label != 'combined': self.assertNotIn('author-edited times', text); self.assertNotIn("author's times", text)

    def test_the_native_content_model_and_ast_tables_hold_the_exact_new_integers_in_order(self):
        for fmt, expected in ((None, [['100', '5400', 'And so, my fellow Americans,'], ['5500', '10900', 'ask not what your country can do.']]),
                              ('timecode', [['00:00:00.100', '00:00:05.400', 'And so, my fellow Americans,'], ['00:00:05.500', '00:00:10.900', 'ask not what your country can do.']])):
            with self.subTest(fmt):
                path = self.reviewed(timings=EDITS); document = report(path)
                if fmt: document['sections'][0]['content'][0]['timeFormat'] = fmt
                prepared = adaptor.plan(document)
                (self.directory / 'transcript-0-0.json').write_bytes(path.read_bytes())
                model = adaptor.expected({**prepared, '_directory': self.directory})
                tables = [item for item in model if item['kind'] == 'table']
                self.assertEqual(len(tables), 1); self.assertEqual(tables[0]['rows'][1:], expected); self.assertEqual(tables[0]['rows'][0], list(adaptor.TIMECODE_COLUMNS if fmt else adaptor.TRANSCRIPT_COLUMNS))
                tree = adaptor.ast(prepared, [1, 23], self.directory)
                self.assertEqual(sum(item['t'] == 'Table' for item in tree['blocks']), 1)
                self.assertIn(json.dumps(expected[1][1]), json.dumps(tree['blocks']))

    def test_the_transcript_loss_sentence_is_not_rewritten_for_a_reviewed3_plan(self):
        path = self.reviewed(timings=EDITS); prepared = adaptor.plan(report(path))
        older = adaptor.plan(report(self.reviewed(deletions=[1], version=deletion, name='old.json')))
        self.assertEqual(prepared['losses'], older['losses'])


if __name__ == '__main__':
    unittest.main()
