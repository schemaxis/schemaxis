"""Host-only corrections with author-declared cue timing edits: schemaxis.whispercpp.correct/3 and schemaxis.timedtext.reviewed/3.

Nothing here launches a native executable. The draft is a genuine native whisper.cpp 1.9.5 output retained as a fixture: the public
sample (three cues, boundaries 0/5410/9040/11000 ms, 11000 ms of audio). These tests never count as native qualification of any route.
correct/1 and correct/2 promise the original timestamps, so each refuses a timing member and their literal output is pinned here.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.adaptors.whispercpp import corrections as first
from schemaxis.adaptors.whispercpp import corrections_deletion as second
from schemaxis.adaptors.whispercpp import corrections_timing as c
from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'examples/schemaxis/whispercpp-corrections-fixtures'
JFK, SILENCE = FIXTURES / 'jfk-short-cues-segments.json', FIXTURES / 'silence-hallucinated-segments.json'
JFK_SHA = '0fb466aec743b3a236655d7b29e4d3a1003bcd5230abcd4276af56b08cb4ba04'
SILENCE_SHA = 'ce623bde74e436a134230ba80cee7613fd61358acac8e1094ff35d5293ca27be'
NOTE = 'Illustrative automated declaration; no person listened to or reviewed this recording.'
REPLACED = 'And so, my fellow Americans: ask not what'
SENTINEL = 'SENTINEL-whisper-cli-was-launched'


def timing(index, start, end): return {'index': index, 'startMs': start, 'endMs': end}


class Base(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)
        self.draft = self.dir / 'segments.json'; shutil.copyfile(JFK, self.draft)
        self.document = {'version': c.VERSION, 'draft': {'path': str(self.draft)}, 'basisSha256': JFK_SHA,
                         'review': {'status': 'human-corrected', 'note': NOTE},
                         'timings': [timing(0, 120, 5300), timing(2, 9100, 10950)]}

    def fault(self, action, code=None, location=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        fault = caught.exception.fault
        if code: self.assertEqual(fault.code, code, fault.to_dict())
        if location: self.assertEqual(fault.location, location)
        self.assertTrue(fault.recovery or fault.code == 'VERIFICATION_FAILED', fault.to_dict())
        return fault

    def edited(self, **change):
        document = copy.deepcopy(self.document); document.update(change); return document

    def run_job(self, name='run', document=None): return c.run(document or self.document, self.dir / name, timeout=30)
    def reviewed(self, name='run'): return json.loads((self.dir / name / 'reviewed-segments.json').read_text())
    def ledger(self, name='run'): return json.loads((self.dir / name / 'corrections.json').read_text())

    def refresh(self, directory):
        receipt = c.read_json(directory, 'verification.json'); plan = c.read_json(directory, 'plan.json')
        receipt['artifacts'] = c.artifacts(directory, c.wants_review(plan))
        receipt['evidence'] = {n: c.digest(directory, n) for n in receipt['evidence']}
        c.atomic_json(directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)


class OldRoutesRefuseTimingEdits(Base):
    """Before this route, no way existed to edit a time; the older routes still have none and never reinterpret their members."""

    def test_correct_1_and_2_refuse_a_timing_member_and_keep_their_own_versions(self):
        plain = {k: v for k, v in self.document.items() if k not in ('version', 'timings')}
        self.fault(lambda: first.plan({'version': first.VERSION, **plain, 'timings': self.document['timings']}), 'UNKNOWN_ARGUMENT', '$')
        self.fault(lambda: second.plan({'version': second.VERSION, **plain, 'timings': self.document['timings']}), 'UNKNOWN_ARGUMENT', '$')
        self.fault(lambda: second.plan({'version': second.VERSION, **plain, 'corrections': [{'index': 0, 'text': 'x', 'startMs': 1}]}), 'UNKNOWN_ARGUMENT', '$.corrections[0]')
        self.assertEqual((first.VERSION, second.VERSION, c.VERSION), ('schemaxis.whispercpp.correct/1', 'schemaxis.whispercpp.correct/2', 'schemaxis.whispercpp.correct/3'))
        self.assertEqual((first.PLAN_VERSION, second.PLAN_VERSION, c.PLAN_VERSION), tuple(f'schemaxis.whispercpp.correction-plan/{n}' for n in (1, 2, 3)))
        self.assertEqual((first.LEDGER_VERSION, second.LEDGER_VERSION, c.LEDGER_VERSION), tuple(f'schemaxis.whispercpp.corrections/{n}' for n in (1, 2, 3)))

    def test_the_older_routes_keep_the_original_timestamps_and_their_literal_output(self):
        old = {'version': second.VERSION, 'draft': {'path': str(self.draft)}, 'basisSha256': JFK_SHA, 'review': {'status': 'human-corrected', 'note': NOTE},
               'corrections': [{'index': 0, 'text': REPLACED}], 'deletions': [1]}
        second.run(old, self.dir / 'old2', timeout=30)
        reviewed = json.loads((self.dir / 'old2' / 'reviewed-segments.json').read_text())
        self.assertEqual((reviewed['version'], [(s['startMs'], s['endMs']) for s in reviewed['segments']]), ('schemaxis.timedtext.reviewed/2', [(0, 5410), (9040, 11000)]))
        self.assertNotIn('timingEditCount', reviewed['review']); self.assertNotIn('originalTimings', reviewed['review'])
        self.assertEqual(second.verify(self.dir / 'old2')['deletions'], 1)
        self.assertEqual(second.LOSSES[1][:60], 'Text replacement and whole-cue deletion by unique source ind')
        self.assertIn('no timing edits', second.LOSSES[1]); self.assertIn('no timing edits', first.LOSSES[1])
        self.assertNotIn('timingEdits', json.loads((self.dir / 'old2' / 'corrections.json').read_text()))
        first.run({'version': first.VERSION, 'draft': {'path': str(self.draft)}, 'basisSha256': JFK_SHA, 'review': {'status': 'human-corrected', 'note': NOTE},
                   'corrections': [{'index': 0, 'text': REPLACED}]}, self.dir / 'old1', timeout=30)
        old1 = json.loads((self.dir / 'old1' / 'reviewed-segments.json').read_text())
        self.assertEqual((old1['version'], [(s['startMs'], s['endMs']) for s in old1['segments']]), ('schemaxis.timedtext.reviewed/1', [(0, 5410), (5410, 9040), (9040, 11000)]))

    def test_the_route_is_registered_as_a_separate_host_only_version(self):
        route = registry.resolve(self.document, legacy=True)[1]
        self.assertEqual((route['module'], route['acceptedArtifacts']), ('schemaxis.adaptors.whispercpp.corrections_timing', ['text']))
        self.assertEqual(registry.resolve({'version': second.VERSION}, legacy=True)[1]['module'], 'schemaxis.adaptors.whispercpp.corrections_deletion')
        qualification = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/qualification.json').read_text())
        self.assertNotIn(c.VERSION, qualification['routes'])


class QualifierRefusal(unittest.TestCase):
    TOOL = ROOT / 'tools/qualify_whispercpp_timing.py'

    def refused(self, flags, env_extra):
        with tempfile.TemporaryDirectory() as scratch:
            out = Path(scratch) / 'never-created'
            env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), **env_extra}
            argv = [sys.executable, *flags, str(self.TOOL), '--pandoc', '/nonexistent/pandoc', '--jfk-draft', '/nonexistent/segments.json', '--output-directory', str(out)]
            done = subprocess.run(argv, capture_output=True, text=True, timeout=60, env=env, cwd=scratch)
            self.assertNotEqual(done.returncode, 0); self.assertIn('refused', done.stderr + done.stdout); self.assertIn('-O', done.stderr + done.stdout)
            self.assertFalse(out.exists(), 'no output directory may be created before the refusal')

    def test_optimized_python_is_refused_before_any_work_or_output(self):
        self.refused(['-O'], {}); self.refused(['-OO'], {}); self.refused([], {'PYTHONOPTIMIZE': '1'})


class Planning(Base):
    def test_plan_reads_no_file_and_keeps_authored_members(self):
        document = self.edited(); document['draft']['path'] = '/definitely/not/there/segments.json'
        with patch('builtins.open', side_effect=AssertionError('read')), patch('os.open', side_effect=AssertionError('opened')):
            planned = c.plan(document); self.assertEqual(c.query(document), (['correct'], {}))
        self.assertEqual((planned['version'], planned['operation'], planned['timings']), (c.PLAN_VERSION, 'correct', self.document['timings']))
        self.assertEqual(planned['losses'], c.LOSSES); self.assertNotIn('captionReview', planned)
        self.assertEqual(c.plan({**self.document, 'captionReview': True})['losses'][-2:], [c.REVIEW_LOSS, c.EMPTY_LOSS])
        self.assertFalse(any('preserved' in loss and 'timing' in loss and 'never' not in loss and 'Unedited' not in loss for loss in c.LOSSES))

    def test_the_timing_grammar_is_closed_typed_and_has_no_floats_or_booleans(self):
        for label, change, code, location in (
                ('duplicate', lambda d: d.update(timings=[timing(0, 1, 2), timing(0, 3, 4)]), 'TIMING_DUPLICATE', '$.timings[1].index'),
                ('deleted', lambda d: d.update(deletions=[2]), 'TIMING_DELETION_CONFLICT', '$.timings[1].index'),
                ('reversed', lambda d: d.update(timings=[timing(0, 200, 100)]), 'TIMING_INTERVAL_INVALID', '$.timings[0]'),
                ('empty interval', lambda d: d.update(timings=[timing(0, 100, 100)]), 'TIMING_INTERVAL_INVALID', '$.timings[0]'),
                ('float', lambda d: d['timings'][0].update(startMs=1.5), 'INVALID_ARGUMENT', None),
                ('whole float', lambda d: d['timings'][0].update(endMs=300.0), 'INVALID_ARGUMENT', None),
                ('boolean', lambda d: d['timings'][0].update(startMs=True), 'INVALID_ARGUMENT', None),
                ('text', lambda d: d['timings'][0].update(startMs='10'), 'INVALID_ARGUMENT', None),
                ('negative', lambda d: d['timings'][0].update(startMs=-1), 'INVALID_ARGUMENT', None),
                ('beyond the integer limit', lambda d: d['timings'][0].update(endMs=timed_text.MAX_NUMBER + 1), 'INVALID_ARGUMENT', None),
                ('missing end', lambda d: d['timings'][0].pop('endMs'), 'MISSING_ARGUMENT', None),
                ('only a delta', lambda d: d['timings'].__setitem__(0, {'index': 0, 'shiftMs': 100}), 'UNKNOWN_ARGUMENT', '$.timings[0]'),
                ('extra member', lambda d: d['timings'][0].update(note='x'), 'UNKNOWN_ARGUMENT', '$.timings[0]'),
                ('object not array', lambda d: d.update(timings={'0': timing(0, 1, 2)}), 'INVALID_ARGUMENT', None),
                ('index beyond the cue budget', lambda d: d['timings'][0].update(index=timed_text.MAX_CUES), 'INVALID_ARGUMENT', None),
                ('unknown member', lambda d: d.update(retime=[]), 'UNKNOWN_ARGUMENT', '$')):
            document = self.edited(); change(document)
            with self.subTest(label): self.fault(lambda: c.plan(document), code, location)
        self.fault(lambda: c.plan(self.edited(timings=[timing(i, i * 10, i * 10 + 5) for i in range(timed_text.MAX_CUES + 1)])), 'INVALID_ARGUMENT')

    def test_status_must_agree_with_the_edits_including_timing_only_and_unchanged_with_timings(self):
        c.plan(self.edited(timings=[timing(0, 1, 2)]))
        self.fault(lambda: c.plan(self.edited(review={'status': 'human-reviewed-unchanged', 'note': NOTE})), 'CORRECTIONS_STATUS_CONFLICT', '$.review.status')
        self.fault(lambda: c.plan(self.edited(timings=[], review={'status': 'human-corrected', 'note': NOTE})), 'CORRECTIONS_STATUS_CONFLICT', '$.corrections')
        c.plan(self.edited(timings=[], review={'status': 'human-reviewed-unchanged', 'note': NOTE}))

    def test_schema_declares_timings_as_integer_original_source_intervals(self):
        schema = c.schema(); item = schema['properties']['timings']['items']
        self.assertEqual(schema['properties']['version'], {'const': c.VERSION})
        self.assertEqual(schema['properties']['timings']['maxItems'], timed_text.MAX_CUES)
        self.assertEqual({k: item['properties'][k]['type'] for k in ('index', 'startMs', 'endMs')}, {'index': 'integer', 'startMs': 'integer', 'endMs': 'integer'})
        self.assertEqual(set(item['required']), {'index', 'startMs', 'endMs'}); self.assertFalse(item['additionalProperties'])
        self.assertEqual(set(schema['required']), {'version', 'draft', 'basisSha256', 'review'})


class TimingEdits(Base):
    def test_valid_edits_publish_exact_times_everywhere_and_bind_original_and_new(self):
        result = self.run_job()
        self.assertEqual((result['verified'], result['cues'], result['sourceCues'], result['corrections'], result['deletions'], result['timingEdits'], result['nativeProcesses']),
                         (True, 3, 3, 0, 0, 2, 0))
        self.assertEqual((result['accuracyCertified'], result['identityVerified'], result['synchronizationCertified']), (False, False, False))
        out = self.dir / 'run'
        self.assertEqual((out / 'captions.srt').read_text(), ('1\n00:00:00,120 --> 00:00:05,300\nAnd so my fellow Americans, ask not what\n\n'
                                                              '2\n00:00:05,410 --> 00:00:09,040\nyour country can do for you, ask what you\n\n'
                                                              '3\n00:00:09,100 --> 00:00:10,950\ncan do for your country.\n\n'))
        self.assertIn('00:00:09.100 --> 00:00:10.950\ncan do for your country.', (out / 'captions.vtt').read_text())
        reviewed = self.reviewed(); review = reviewed['review']
        self.assertEqual((reviewed['version'], [(s['startMs'], s['endMs']) for s in reviewed['segments']]), ('schemaxis.timedtext.reviewed/3', [(120, 5300), (5410, 9040), (9100, 10950)]))
        self.assertEqual((review['timingEditedIndices'], review['timingEditCount'], review['originalTimings']),
                         ([0, 2], 2, [{'sourceIndex': 0, 'startMs': 0, 'endMs': 5410}, {'sourceIndex': 1, 'startMs': 5410, 'endMs': 9040}, {'sourceIndex': 2, 'startMs': 9040, 'endMs': 11000}]))
        self.assertEqual((review['accuracyCertified'], review['identityVerified'], review['synchronizationCertified']), (False, False, False))
        self.assertEqual(review['basis']['sha256'], JFK_SHA)
        ledger = self.ledger()
        self.assertEqual((ledger['version'], ledger['reviewedVersion'], ledger['timingEditCount'], ledger['unchangedCueCount'], ledger['synchronizationCertified']),
                         ('schemaxis.whispercpp.corrections/3', 'schemaxis.timedtext.reviewed/3', 2, 1, False))
        self.assertEqual(ledger['timingEdits'], [
            {'sourceIndex': 0, 'publishedIndex': 0, 'originalStartMs': 0, 'originalEndMs': 5410, 'startMs': 120, 'endMs': 5300, 'text': 'And so my fellow Americans, ask not what'},
            {'sourceIndex': 2, 'publishedIndex': 2, 'originalStartMs': 9040, 'originalEndMs': 11000, 'startMs': 9100, 'endMs': 10950, 'text': 'can do for your country.'}])
        self.assertEqual([(r['originalStartMs'], r['originalEndMs'], r['startMs'], r['endMs'], r['retimed']) for r in ledger['retained']],
                         [(0, 5410, 120, 5300, True), (5410, 9040, 5410, 9040, False), (9040, 11000, 9100, 10950, True)])
        self.assertIn('not', ledger['statement']); self.assertEqual(ledger['reviewedSha256'], hashlib.sha256((out / 'reviewed-segments.json').read_bytes()).hexdigest())
        self.assertEqual(c.verify(out)['timingEdits'], 2)

    def test_timing_only_is_human_corrected_and_text_deletion_and_timing_combine_with_original_source_indices(self):
        document = self.edited(corrections=[{'index': 0, 'text': REPLACED}], deletions=[1], timings=[timing(2, 8000, 10000)])
        result = self.run_job(document=document)
        self.assertEqual((result['cues'], result['sourceCues'], result['corrections'], result['deletions'], result['timingEdits']), (2, 3, 1, 1, 1))
        reviewed = self.reviewed(); review = reviewed['review']
        self.assertEqual([(s['index'], s['startMs'], s['endMs'], s['text']) for s in reviewed['segments']], [(0, 0, 5410, REPLACED), (1, 8000, 10000, 'can do for your country.')])
        self.assertEqual((review['correctedIndices'], review['deletedSourceIndices'], review['retainedSourceIndices'], review['timingEditedIndices']), ([0], [1], [0, 2], [2]))
        ledger = self.ledger()
        self.assertEqual([(e['sourceIndex'], e['publishedIndex']) for e in ledger['timingEdits']], [(2, 1)])
        self.assertEqual(ledger['deletions'], [{'sourceIndex': 1, 'originalStartMs': 5410, 'originalEndMs': 9040, 'original': 'your country can do for you, ask what you'}])
        # The published interval of a retimed cue may use time the deleted cue held in the draft; the retained cues are the whole set judged.
        self.assertEqual(self.run_job('only', self.edited(timings=[timing(0, 0, 5000)]))['reviewStatus'], 'human-corrected')

    def test_a_cue_both_replaced_and_retimed_shows_original_and_published_times_in_every_ledger_section(self):
        document = self.edited(corrections=[{'index': 0, 'text': REPLACED}], deletions=[1], timings=[timing(0, 120, 5300), timing(2, 8000, 10000)])
        self.run_job(document=document)
        ledger = self.ledger()
        self.assertEqual(ledger['replacements'], [{'sourceIndex': 0, 'publishedIndex': 0, 'originalStartMs': 0, 'originalEndMs': 5410, 'startMs': 120, 'endMs': 5300,
                                                    'original': 'And so my fellow Americans, ask not what', 'replacement': REPLACED}])
        self.assertEqual(ledger['timingEdits'][0], {'sourceIndex': 0, 'publishedIndex': 0, 'originalStartMs': 0, 'originalEndMs': 5410, 'startMs': 120, 'endMs': 5300, 'text': REPLACED})
        self.assertEqual([(r['sourceIndex'], r['originalStartMs'], r['originalEndMs'], r['startMs'], r['endMs'], r['edited'], r['retimed'], r['text']) for r in ledger['retained']],
                         [(0, 0, 5410, 120, 5300, True, True, REPLACED), (2, 9040, 11000, 8000, 10000, False, True, 'can do for your country.')])
        # The same cue shows the same pairs in every section; the published times equal the reviewed document's cue.
        published = [(s['startMs'], s['endMs']) for s in self.reviewed()['segments']]
        self.assertEqual(published[0], (ledger['replacements'][0]['startMs'], ledger['replacements'][0]['endMs']))
        self.assertEqual(published[0], (ledger['timingEdits'][0]['startMs'], ledger['timingEdits'][0]['endMs']))
        self.assertEqual(published[0], (ledger['retained'][0]['startMs'], ledger['retained'][0]['endMs']))
        # A deleted cue has no published time: only the original names exist in its section.
        self.assertEqual(set(ledger['deletions'][0]), {'sourceIndex', 'originalStartMs', 'originalEndMs', 'original'})
        # A replaced but not retimed cue repeats the original as the published time.
        self.run_job('text-only', self.edited(corrections=[{'index': 1, 'text': REPLACED}], timings=[timing(0, 120, 5300)]))
        replaced = self.ledger('text-only')['replacements'][0]
        self.assertEqual((replaced['originalStartMs'], replaced['originalEndMs'], replaced['startMs'], replaced['endMs']), (5410, 9040, 5410, 9040))
        self.assertEqual((c.verify(self.dir / 'run')['timingEdits'], c.verify(self.dir / 'text-only')['timingEdits']), (2, 1))

    def test_adjacent_touching_intervals_are_valid_and_the_audio_end_is_reachable(self):
        self.run_job(document=self.edited(timings=[timing(0, 0, 4000), timing(1, 4000, 8000), timing(2, 8000, 11000)]))
        self.assertEqual([(s['startMs'], s['endMs']) for s in self.reviewed()['segments']], [(0, 4000), (4000, 8000), (8000, 11000)])

    def test_the_finished_set_is_judged_so_edit_order_never_creates_a_false_overlap(self):
        # Cue 1 moving later only fits once cue 2 has also moved; both orders publish identical bytes.
        later, earlier = [timing(1, 9040, 9500), timing(2, 9500, 11000)], [timing(2, 9500, 11000), timing(1, 9040, 9500)]
        self.assertFalse(c.final_times is None)
        c.run(self.edited(timings=later), self.dir / 'one', timeout=30); c.run(self.edited(timings=earlier), self.dir / 'two', timeout=30)
        for name in ('reviewed-segments.json', 'captions.srt', 'captions.vtt', 'transcript.txt'):
            self.assertEqual((self.dir / 'one' / name).read_bytes(), (self.dir / 'two' / name).read_bytes(), name)
        # A deleted neighbour's draft time is no obstacle: cue 0 may now run through where cue 1 used to be.
        self.run_job('through', self.edited(deletions=[1], timings=[timing(0, 0, 9000)]))
        self.assertEqual([(s['startMs'], s['endMs']) for s in self.reviewed('through')['segments']], [(0, 9000), (9040, 11000)])

    def test_refusals_name_the_offending_edit_and_never_clamp_reorder_or_round(self):
        for label, document, code, location in (
                ('overlap with the previous cue', self.edited(timings=[timing(1, 5000, 9040)]), 'TIMING_OVERLAP', '$.timings[0]'),
                ('overlap with the next cue', self.edited(timings=[timing(0, 0, 5411)]), 'TIMING_OVERLAP', '$.timings[0]'),
                ('overlap blamed on the later cue\'s edit', self.edited(timings=[timing(2, 9300, 10000), timing(1, 5410, 9500)]), 'TIMING_OVERLAP', '$.timings[0]'),
                ('past the audio', self.edited(timings=[timing(2, 9040, 11001)]), 'TIMING_AFTER_AUDIO', '$.timings[0]'),
                ('wholly past the audio', self.edited(timings=[timing(2, 11000, 12000)]), 'TIMING_AFTER_AUDIO', '$.timings[0]'),
                ('a no-op', self.edited(timings=[timing(1, 5410, 9040)]), 'TIMING_NOOP', '$.timings[0]'),
                ('index beyond the draft', self.edited(timings=[timing(3, 100, 200)]), 'TIMING_INDEX_INVALID', '$.timings[0].index'),
                ('stale basis', self.edited(basisSha256='1' * 64), 'CORRECTIONS_STALE', '$.basisSha256'),
                ('reordering is refused not applied', self.edited(timings=[timing(0, 6000, 7000), timing(1, 5410, 9041)]), 'TIMING_OVERLAP', '$.timings[1]')):
            with self.subTest(label):
                fault = self.fault(lambda: c.run(document, self.dir / ('f-' + label.replace(' ', '-')), timeout=30), code, location)
                self.assertFalse((self.dir / ('f-' + label.replace(' ', '-')) / 'reviewed-segments.json').exists())
        self.assertEqual(self.fault(lambda: c.run(self.edited(timings=[timing(2, 9040, 11001)]), self.dir / 'detail', timeout=30), 'TIMING_AFTER_AUDIO').observed['audioDurationMs'], 11000)

    def test_a_noop_is_refused_even_when_only_one_end_is_unchanged_it_is_not(self):
        # One unchanged end with one changed end is a genuine edit; both unchanged is the no-op refused above.
        self.assertEqual(self.run_job(document=self.edited(timings=[timing(0, 0, 5000)]))['timingEdits'], 1)

    def test_an_edit_to_a_deleted_cue_is_refused_in_planning_and_indices_stay_original_after_deletions(self):
        self.fault(lambda: c.plan(self.edited(deletions=[0], timings=[timing(0, 1, 2)])), 'TIMING_DELETION_CONFLICT', '$.timings[0].index')
        # After deleting cue 0, source index 2 is still index 2 even though it is published as cue 1.
        self.run_job(document=self.edited(deletions=[0], timings=[timing(2, 9100, 10950)]))
        self.assertEqual(self.reviewed()['review']['timingEditedIndices'], [2])
        self.fault(lambda: c.run(self.edited(deletions=[0], timings=[timing(1, 5500, 9000), timing(2, 9040, 11000)]), self.dir / 'noop', timeout=30), 'TIMING_NOOP', '$.timings[1]')

    def test_the_source_cannot_change_after_capture_and_the_draft_is_never_modified(self):
        before = self.draft.read_bytes(); self.run_job()
        self.assertEqual(self.draft.read_bytes(), before)
        self.draft.write_bytes(before + b' ')
        self.fault(lambda: c.run(self.document, self.dir / 'changed', timeout=30), 'CORRECTIONS_STALE')
        self.draft.write_bytes(before)
        self.draft.write_bytes(before.replace(b'"startMs": 5410', b'"startMs": 5411', 1))
        self.fault(lambda: c.run(self.document, self.dir / 'changed2', timeout=30), 'CORRECTIONS_STALE')
        self.draft.unlink()
        self.fault(lambda: c.run(self.document, self.dir / 'missing', timeout=30), 'DRAFT_SOURCE_MISSING')

    def test_a_reviewed_document_of_any_version_is_still_refused_as_a_draft(self):
        self.run_job('one')
        for name in ('one',):
            path = self.dir / name / 'reviewed-segments.json'
            document = {**self.document, 'draft': {'path': str(path)}, 'basisSha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            self.fault(lambda: c.run(document, self.dir / 'again', timeout=30), 'DRAFT_NOT_MACHINE_DRAFT', '$.draft.path')

    def test_every_cue_deleted_is_still_the_only_empty_state_and_timing_edits_cannot_make_one(self):
        document = self.edited(deletions=[0, 1, 2], timings=[])
        self.assertEqual(self.run_job(document=document)['cues'], 0)
        self.assertEqual(self.reviewed()['review']['originalTimings'], [])
        self.fault(lambda: c.run({**document, 'captionReview': True}, self.dir / 'review', timeout=30), 'CAPTION_REVIEW_EMPTY', '$.captionReview')
        silent = {**self.document, 'draft': {'path': str(self.dir / 'silence.json')}, 'basisSha256': SILENCE_SHA, 'timings': [timing(0, 100, 900)]}
        shutil.copyfile(SILENCE, self.dir / 'silence.json')
        self.assertEqual(self.run_job('silent', silent)['cues'], 1)
        zero = json.loads(SILENCE.read_text()); zero['segments'] = []; zero['segmentCount'] = 0
        path = self.dir / 'zero.json'; path.write_bytes(timed_text.canonical_json(zero))
        self.fault(lambda: c.run({**silent, 'draft': {'path': str(path)}, 'basisSha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'timings': [], 'deletions': [0]}, self.dir / 'zero', timeout=30), 'TIMED_TEXT_INVALID')

    def test_caption_review_recomputes_every_heuristic_from_the_edited_durations(self):
        document = self.edited(captionReview=True, timings=[timing(0, 0, 900), timing(2, 9040, 9060)])
        self.run_job(document=document)
        report = json.loads((self.dir / 'run' / 'caption-review.json').read_text())
        by_index = {cue['index']: cue for cue in report['cues']}
        self.assertEqual((by_index[0]['durationMs'], by_index[0]['flags']), (900, ['short-duration', 'dense-text']))
        self.assertEqual((by_index[2]['durationMs'], by_index[2]['flags']), (20, ['short-duration', 'dense-text']))
        self.assertEqual(by_index[1]['durationMs'], 3630)
        self.assertEqual(report['segmentsSha256'], self.ledger()['reviewedSha256'])
        self.assertEqual((report['review']['accuracyCertified'], report['review']['readabilityCertified'], report['review']['passCertified']), (False, False, False))
        unedited = self.edited(captionReview=True, timings=[timing(0, 0, 5410 - 1)]); self.run_job('other', unedited)
        self.assertEqual(json.loads((self.dir / 'other' / 'caption-review.json').read_text())['cues'][0]['durationMs'], 5409)

    def test_total_budget_is_judged_on_the_finished_cues_and_the_other_limits_remain(self):
        draft = json.loads(SILENCE.read_text()); one = draft['segments'][0]
        draft['segments'] = [{**one, 'index': i, 'startMs': i * 10, 'endMs': i * 10 + 10, 'text': 'a' * 65} for i in range(500)]; draft['segmentCount'] = 500
        draft['audio'].update(frames=160000, durationMs=10000, bytes=320044)
        path = self.dir / 'wide.json'; path.write_bytes(timed_text.canonical_json(draft)); pin = hashlib.sha256(path.read_bytes()).hexdigest()
        base = {'version': c.VERSION, 'draft': {'path': str(path)}, 'basisSha256': pin, 'review': {'status': 'human-corrected', 'note': NOTE},
                'corrections': [{'index': i, 'text': 'b' * 100} for i in range(10)], 'timings': [timing(0, 1, 9)]}
        self.fault(lambda: c.run(base, self.dir / 'over', timeout=30), 'TIMED_TEXT_RESOURCE_LIMIT', '$.corrections[0].text')
        fits = c.run({**base, 'deletions': [100, 101, 102, 103, 104]}, self.dir / 'fits', timeout=30)
        self.assertEqual((fits['cues'], fits['sourceCues'], fits['deletions'], fits['timingEdits']), (495, 500, 5, 1))
        self.fault(lambda: c.plan({**base, 'review': {'status': 'human-corrected', 'note': 'x' * 501}}), 'INVALID_ARGUMENT')
        self.fault(lambda: c.plan({**base, 'corrections': [{'index': 0, 'text': 'x' * 257}]}), 'INVALID_ARGUMENT')


class SemanticReplay(Base):
    """Every ordinary hash is refreshed after each change, so only independent replay can notice it."""

    def setUp(self):
        super().setUp(); self.document.update(captionReview=True, corrections=[{'index': 1, 'text': 'your country can do for you, ask what you do'}])
        self.run_job(); self.directory = self.dir / 'run'
        self.saved = {p: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}

    def restore(self):
        for path in [p for p in self.directory.iterdir() if p.is_file() and p not in self.saved]: path.unlink()
        for path, data in self.saved.items(): path.write_bytes(data)

    def tamper(self, name, mutate):
        try:
            path = self.directory / name; original = path.read_bytes(); changed = mutate(original)
            self.assertNotEqual(changed, original, 'vacuous probe ' + name)
            path.write_bytes(changed); self.refresh(self.directory)
            self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED')
        finally: self.restore()

    def test_a_clean_run_verifies_before_and_after_every_probe(self):
        self.assertTrue(c.verify(self.directory)['verified'])

    def test_every_publication_timing_and_original_record_is_replayed(self):
        for label, name, mutate in (
                ('published end', 'reviewed-segments.json', lambda b: b.replace(b'"endMs": 5300', b'"endMs": 5301', 1)),
                ('published start', 'reviewed-segments.json', lambda b: b.replace(b'"startMs": 9100', b'"startMs": 9099', 1)),
                ('original recorded', 'reviewed-segments.json', lambda b: b.replace(b'"endMs": 5410', b'"endMs": 5409', 1)),
                ('edited indices', 'reviewed-segments.json', lambda b: b.replace(b'"timingEditedIndices": [\n      0,\n      2\n    ]', b'"timingEditedIndices": [\n      0\n    ]')),
                ('edit count', 'reviewed-segments.json', lambda b: b.replace(b'"timingEditCount": 2', b'"timingEditCount": 1')),
                ('sync claim', 'reviewed-segments.json', lambda b: b.replace(b'"synchronizationCertified": false', b'"synchronizationCertified": true')),
                ('identity claim', 'reviewed-segments.json', lambda b: b.replace(b'"identityVerified": false', b'"identityVerified": true')),
                ('status', 'reviewed-segments.json', lambda b: b.replace(b'"status": "human-corrected"', b'"status": "human-reviewed-unchanged"', 1)),
                ('text', 'reviewed-segments.json', lambda b: b.replace(b'can do for your country.', b'can do for your county.')),
                ('policy text', 'reviewed-segments.json', lambda b: b.replace(b'Author-edited cue intervals', b'Author-edited cue interval')),
                ('transcript', 'transcript.txt', lambda b: b + b'extra\n'),
                ('srt time', 'captions.srt', lambda b: b.replace(b'00:00:00,120', b'00:00:00,000')),
                ('vtt time', 'captions.vtt', lambda b: b.replace(b'00:00:09.100', b'00:00:09.040')),
                ('ledger original', 'corrections.json', lambda b: b.replace(b'"originalEndMs": 5410', b'"originalEndMs": 5300', 1)),
                ('ledger edit', 'corrections.json', lambda b: b.replace(b'"endMs": 10950', b'"endMs": 10951', 1)),
                ('ledger claim', 'corrections.json', lambda b: b.replace(b'"synchronizationCertified": false', b'"synchronizationCertified": true')),
                ('caption review', 'caption-review.json', lambda b: b.replace(b'"durationMs": 5180', b'"durationMs": 5410', 1))):
            with self.subTest(label): self.tamper(name, mutate)
        self.assertTrue(c.verify(self.directory)['verified'])

    def test_captured_draft_authored_edits_plan_and_result_are_bound_together(self):
        for label, name, mutate in (
                ('captured draft', 'captured-draft.json', lambda b: b.replace(b'And so my', b'And so, my')),
                ('capture pin', 'captures.json', lambda b: b.replace(JFK_SHA.encode(), b'1' * 64)),
                ('authored timing', 'authored.json', lambda b: json.dumps({**json.loads(b), 'timings': [timing(0, 130, 5300), timing(2, 9100, 10950)]}).encode()),
                ('authored dropped edit', 'authored.json', lambda b: json.dumps({**json.loads(b), 'timings': [timing(0, 120, 5300)]}).encode()),
                ('plan', 'plan.json', lambda b: b.replace(b'"startMs": 120', b'"startMs": 121')),
                ('result', 'result.json', lambda b: b.replace(b'"timingEdits": 2', b'"timingEdits": 1')),
                ('receipt', 'verification.json', lambda b: b.replace(b'host-only', b'native'))):
            with self.subTest(label): self.tamper(name, mutate)

    def test_a_coherent_forgery_that_keeps_original_times_is_refused(self):
        # A self-consistent reviewed/3 document that claims no timing edit and carries the original times, with matching files.
        reviewed = json.loads((self.directory / 'reviewed-segments.json').read_text())
        for cue, original in zip(reviewed['segments'], reviewed['review']['originalTimings']): cue['startMs'], cue['endMs'] = original['startMs'], original['endMs']
        reviewed['review'].update(timingEditCount=0, timingEditedIndices=[]); timed_text.validate(reviewed)
        cues = reviewed['segments']
        self.tamper('reviewed-segments.json', lambda b: timed_text.canonical_json(reviewed))
        self.tamper('captions.srt', lambda b: timed_text.srt_text(cues).encode())
        self.tamper('captions.vtt', lambda b: timed_text.vtt_text(cues).encode())

    def test_membership_is_exact_and_native_evidence_or_a_planted_launcher_is_a_failure(self):
        for name, content in (('transcribe-launcher.py', 'native'), ('whisper.stderr', 'log'), ('extra.txt', 'x')):
            try: (self.directory / name).write_text(content); self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED')
            finally: self.restore()
        try:
            planted = self.directory / '.dispatch' / 'transcribe'; planted.mkdir(parents=True); marker = self.dir / 'ran.marker'
            (planted / 'replay-x.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("ran")\n')
            self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED'); self.assertFalse(marker.exists())
        finally: shutil.rmtree(self.directory / '.dispatch', ignore_errors=True); self.restore()
        self.assertTrue(c.verify(self.directory)['verified'])


class HostOnly(Base):
    def test_a_fake_whisper_executable_is_never_launched_by_planning_running_or_verifying(self):
        fake = self.dir / 'bin' / 'whisper-cli'; fake.parent.mkdir()
        marker = self.dir / 'sentinel.marker'
        fake.write_text(f'#!/bin/sh\necho {SENTINEL} > {marker}\nexit 0\n'); fake.chmod(0o755)
        c.plan(self.document)
        with patch('subprocess.Popen', side_effect=AssertionError('process')), patch('subprocess.run', side_effect=AssertionError('process')), patch('os.execv', side_effect=AssertionError('exec')):
            result = c.run(self.document, self.dir / 'hosted', executable=str(fake), timeout=30)
            c.verify(self.dir / 'hosted')
        self.assertEqual((result['runtime'], result['nativeProcesses']), ('host-only', 0)); self.assertFalse(marker.exists())
        self.assertEqual(c.resources(self.document, {}, 'x'), {'threads': 1})
        self.fault(lambda: c.resources(self.document, {'threads': 2}, 'x'), 'INVALID_EXECUTION')


class Interfaces(Base):
    def cli(self, *arguments):
        if arguments and arguments[0] == 'run':
            arguments = (*arguments, '--backend', 'native')
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'SCHEMAXIS_WHISPERCPP': '/nonexistent/whisper-cli', 'PATH': '/nonexistent'}
        return subprocess.run([sys.executable, '-m', 'schemaxis', *arguments], capture_output=True, text=True, env=environment, cwd=self.dir, timeout=120)

    def test_cli_plan_run_and_verify_without_any_whisper_executable(self):
        document = self.dir / 'document.json'; document.write_text(json.dumps(self.document))
        planned = self.cli('plan', str(document)); self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual(json.loads(planned.stdout)['timings'], self.document['timings'])
        ran = self.cli('run', str(document), '--output-directory', str(self.dir / 'cli-run')); self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertEqual((json.loads(ran.stdout)['runtime'], json.loads(ran.stdout)['timingEdits']), ('host-only', 2))
        checked = self.cli('verify', str(self.dir / 'cli-run')); self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertTrue(json.loads(checked.stdout)['verified'])
        bad = self.dir / 'bad.json'; bad.write_text(json.dumps(self.edited(timings=[timing(1, 5000, 9040)])))
        failed = self.cli('run', str(bad), '--output-directory', str(self.dir / 'cli-bad')); self.assertNotEqual(failed.returncode, 0)
        self.assertIn('TIMING_OVERLAP', failed.stdout + failed.stderr)

    def test_discovery_and_guidance_cover_the_route(self):
        guidance = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/guidance.json').read_text())
        fields = guidance['routes'][c.VERSION]['fields']
        for pointer in ('/properties/timings', '/properties/timings/items', '/properties/timings/items/properties/index',
                        '/properties/timings/items/properties/startMs', '/properties/timings/items/properties/endMs'):
            self.assertEqual(fields[pointer]['status'], 'reviewed', pointer)
        joined = ' '.join(' '.join(fields['/properties/timings']['explanation'].split()).split())
        for fragment in ('original', 'whole new interval', 'declaration'): self.assertIn(fragment, joined.lower())
        from schemaxis.adaptors.whispercpp import capabilities
        catalogue = capabilities.catalogue()
        self.assertIn('correct/3', ' '.join(catalogue['requirements']))
        self.assertIn('retime captions', catalogue['application']['keywords'])

    def test_shipped_examples_plan_and_the_invalid_ones_refuse_for_their_stated_reason(self):
        for name in ('whispercpp-timing-edit', 'whispercpp-timing-combined', 'whispercpp-timing-unchanged-conflict-invalid'):
            document = json.loads((ROOT / f'examples/schemaxis/{name}.json').read_text())
            self.assertTrue(document['review']['note'].startswith('Illustrative'), name); self.assertIn('no person', document['review']['note'])
        c.plan(json.loads((ROOT / 'examples/schemaxis/whispercpp-timing-edit.json').read_text()))
        c.plan(json.loads((ROOT / 'examples/schemaxis/whispercpp-timing-combined.json').read_text()))
        self.fault(lambda: c.plan(json.loads((ROOT / 'examples/schemaxis/whispercpp-timing-unchanged-conflict-invalid.json').read_text())), 'CORRECTIONS_STATUS_CONFLICT')
        for name, code in (('whispercpp-timing-overlap-invalid', 'TIMING_OVERLAP'), ('whispercpp-timing-after-audio-invalid', 'TIMING_AFTER_AUDIO')):
            invalid = json.loads((ROOT / f'examples/schemaxis/{name}.json').read_text()); self.assertEqual(invalid['basisSha256'], JFK_SHA)
            c.plan(invalid)  # valid against the schema; refused only against the draft
            invalid['draft']['path'] = str(self.draft)
            self.fault(lambda: c.run(invalid, self.dir / name, timeout=30), code, '$.timings[0]')

    def test_the_shipped_workflow_example_chains_the_artifact_into_the_pandoc_transcript_block(self):
        graph = json.loads((ROOT / 'examples/schemaxis/whispercpp-timing-workflow.json').read_text())
        self.assertEqual([o['id'] for o in graph['operations']], ['correct', 'report'])
        self.assertEqual(graph['operations'][0]['document']['version'], c.VERSION)
        block = graph['operations'][1]['document']['sections'][0]['content'][0]
        self.assertEqual((block['kind'], block['timeFormat'], block['segments']['path']), ('transcript', 'timecode', {'$artifact': 'correct', 'index': 0}))


if __name__ == '__main__':
    unittest.main()
