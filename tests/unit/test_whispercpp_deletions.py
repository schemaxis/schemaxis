"""Host-only corrections with explicit cue deletion: schemaxis.whispercpp.correct/2 and schemaxis.timedtext.reviewed/2.

Nothing here launches a native executable. The drafts are two genuine native whisper.cpp 1.9.5 outputs retained as fixtures: the public
sample (three cues, boundaries 0/5410/9040/11000 ms) and a two second silent recording whose one cue "You" is a recognition artefact.
These tests never count as native qualification of any route.
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

from schemaxis.adaptors import registry
from schemaxis.adaptors.whispercpp import corrections as first
from schemaxis.adaptors.whispercpp import corrections_deletion as c
from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'examples/schemaxis/whispercpp-corrections-fixtures'
JFK, SILENCE = FIXTURES / 'jfk-short-cues-segments.json', FIXTURES / 'silence-hallucinated-segments.json'
JFK_SHA = '0fb466aec743b3a236655d7b29e4d3a1003bcd5230abcd4276af56b08cb4ba04'
SILENCE_SHA = 'ce623bde74e436a134230ba80cee7613fd61358acac8e1094ff35d5293ca27be'
NOTE = 'Illustrative example declaration; no person reviewed this recording for it.'
REPLACED = 'And so, my fellow Americans: ask not what'


class Base(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)
        self.draft = self.dir / 'segments.json'; shutil.copyfile(JFK, self.draft)
        self.document = {'version': c.VERSION, 'draft': {'path': str(self.draft)}, 'basisSha256': JFK_SHA,
                         'review': {'status': 'human-corrected', 'note': NOTE}, 'corrections': [{'index': 0, 'text': REPLACED}], 'deletions': [1]}
        self.silent = {'version': c.VERSION, 'draft': {'path': str(self.dir / 'silence.json')}, 'basisSha256': SILENCE_SHA,
                       'review': {'status': 'human-corrected', 'note': NOTE}, 'deletions': [0]}
        shutil.copyfile(SILENCE, self.dir / 'silence.json')

    def fault(self, action, code=None, location=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        fault = caught.exception.fault
        if code: self.assertEqual(fault.code, code, fault.to_dict())
        if location: self.assertEqual(fault.location, location)
        self.assertTrue(fault.recovery or fault.code == 'VERIFICATION_FAILED', fault.to_dict())
        return fault

    def edited(self, **change):
        document = copy.deepcopy(self.document); document.update(change); return document

    def run_job(self, name='run', document=None):
        return c.run(document or self.document, self.dir / name, timeout=30)

    def refresh(self, directory):
        receipt = c.read_json(directory, 'verification.json'); plan = c.read_json(directory, 'plan.json')
        receipt['artifacts'] = c.artifacts(directory, c.wants_review(plan))
        receipt['evidence'] = {n: c.digest(directory, n) for n in receipt['evidence']}
        c.atomic_json(directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)

    def reviewed(self, name='run'): return json.loads((self.dir / name / 'reviewed-segments.json').read_text())
    def ledger(self, name='run'): return json.loads((self.dir / name / 'corrections.json').read_text())


class Planning(Base):
    def test_route_is_a_new_separate_host_only_version_and_the_first_route_is_untouched(self):
        route = registry.resolve(self.document, legacy=True)[1]
        self.assertEqual(route['module'], 'schemaxis.adaptors.whispercpp.corrections_deletion')
        self.assertEqual((route['acceptedArtifacts'], c.VERSION), (['text'], 'schemaxis.whispercpp.correct/2'))
        old = registry.resolve({'version': first.VERSION}, legacy=True)[1]
        self.assertEqual((old['module'], first.VERSION), ('schemaxis.adaptors.whispercpp.corrections', 'schemaxis.whispercpp.correct/1'))
        qualification = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/qualification.json').read_text())
        self.assertNotIn(c.VERSION, qualification['routes'])
        self.assertEqual(first.PLAN_VERSION, 'schemaxis.whispercpp.correction-plan/1')
        # The text-only route still refuses every deletion member: it has no deletion grammar.
        document = {k: v for k, v in self.document.items() if k != 'version'}
        self.fault(lambda: first.plan({'version': first.VERSION, **document}), 'UNKNOWN_ARGUMENT', '$')

    def test_plan_checks_shape_only_and_keeps_authored_members(self):
        document = self.edited(); document['draft']['path'] = '/definitely/not/there/segments.json'
        from unittest.mock import patch
        with patch('builtins.open', side_effect=AssertionError('read')), patch('os.open', side_effect=AssertionError('opened')):
            planned = c.plan(document); self.assertEqual(c.query(document), (['correct'], {}))
        self.assertEqual((planned['version'], planned['operation'], planned['deletions']), (c.PLAN_VERSION, 'correct', [1]))
        self.assertEqual(planned['losses'], c.LOSSES); self.assertNotIn('captionReview', planned)
        self.assertNotIn('deletions', c.plan({k: v for k, v in self.document.items() if k != 'deletions'}))
        self.assertEqual(c.plan({**self.document, 'captionReview': True})['losses'][-1], c.EMPTY_LOSS)

    def test_the_deletion_grammar_is_closed_and_distinct_from_replacement(self):
        for label, change, code, location in (
                ('duplicate', lambda d: d.update(deletions=[1, 2, 1]), 'DELETION_DUPLICATE', '$.deletions[2]'),
                ('conflict', lambda d: d.update(deletions=[0]), 'CORRECTION_DELETION_CONFLICT', '$.corrections[0].index'),
                ('object entry', lambda d: d.update(deletions=[{'index': 1}]), 'INVALID_ARGUMENT', None),
                ('text entry', lambda d: d.update(deletions=['1']), 'INVALID_ARGUMENT', None),
                ('boolean', lambda d: d.update(deletions=[True]), 'INVALID_ARGUMENT', None),
                ('negative', lambda d: d.update(deletions=[-1]), 'INVALID_ARGUMENT', None),
                ('beyond the cue budget', lambda d: d.update(deletions=[timed_text.MAX_CUES]), 'INVALID_ARGUMENT', None),
                ('not an array', lambda d: d.update(deletions=1), 'INVALID_ARGUMENT', None),
                ('replacement with delete flag', lambda d: d['corrections'][0].update(delete=True), 'UNKNOWN_ARGUMENT', '$.corrections[0]'),
                ('empty replacement text', lambda d: d['corrections'][0].update(text=''), 'INVALID_ARGUMENT', None),
                ('blank replacement text', lambda d: d['corrections'][0].update(text='   '), 'CORRECTION_TEXT_INVALID', '$.corrections[0].text'),
                ('unknown member', lambda d: d.update(removals=[1]), 'UNKNOWN_ARGUMENT', '$')):
            document = self.edited(); change(document)
            with self.subTest(label): self.fault(lambda: c.plan(document), code, location)
        too_many = self.edited(deletions=list(range(timed_text.MAX_CUES)), corrections=[], review={'status': 'human-corrected', 'note': NOTE}); c.plan(too_many)
        self.fault(lambda: c.plan(self.edited(deletions=list(range(timed_text.MAX_CUES + 1)))), 'INVALID_ARGUMENT')

    def test_status_must_agree_with_the_edits_including_deletions(self):
        only_deletion = self.edited(corrections=[]); c.plan(only_deletion)
        self.fault(lambda: c.plan(self.edited(corrections=[], deletions=[], review={'status': 'human-corrected', 'note': NOTE})), 'CORRECTIONS_STATUS_CONFLICT', '$.corrections')
        self.fault(lambda: c.plan(self.edited(review={'status': 'human-reviewed-unchanged', 'note': NOTE})), 'CORRECTIONS_STATUS_CONFLICT', '$.review.status')
        self.fault(lambda: c.plan(self.edited(corrections=[], review={'status': 'human-reviewed-unchanged', 'note': NOTE})), 'CORRECTIONS_STATUS_CONFLICT', '$.review.status')
        c.plan(self.edited(corrections=[], deletions=[], review={'status': 'human-reviewed-unchanged', 'note': NOTE}))

    def test_schema_declares_deletions_as_integer_source_indices(self):
        schema = c.schema()
        self.assertEqual(schema['properties']['version'], {'const': c.VERSION})
        self.assertEqual(schema['properties']['deletions']['type'], 'array')
        self.assertEqual(schema['properties']['deletions']['items']['type'], 'integer')
        self.assertEqual(schema['properties']['deletions']['maxItems'], timed_text.MAX_CUES)
        self.assertEqual(set(schema['required']), {'version', 'draft', 'basisSha256', 'review'})
        self.assertFalse(schema['additionalProperties'])


class PartialDeletion(Base):
    def test_one_cue_is_deleted_and_another_replaced_with_exact_publications(self):
        result = self.run_job()
        self.assertEqual((result['verified'], result['cues'], result['sourceCues'], result['corrections'], result['deletions'], result['nativeProcesses']), (True, 2, 3, 1, 1, 0))
        out = self.dir / 'run'
        self.assertEqual((out / 'transcript.txt').read_text(), REPLACED + '\ncan do for your country.\n')
        self.assertEqual((out / 'captions.srt').read_text(), f'1\n00:00:00,000 --> 00:00:05,410\n{REPLACED}\n\n2\n00:00:09,040 --> 00:00:11,000\ncan do for your country.\n\n')
        self.assertEqual((out / 'captions.vtt').read_text(), f'WEBVTT\n\n00:00:00.000 --> 00:00:05.410\n{REPLACED}\n\n00:00:09.040 --> 00:00:11.000\ncan do for your country.\n\n')
        reviewed = self.reviewed()
        self.assertEqual(reviewed['version'], 'schemaxis.timedtext.reviewed/2')
        self.assertEqual([(s['index'], s['startMs'], s['endMs']) for s in reviewed['segments']], [(0, 0, 5410), (1, 9040, 11000)])
        self.assertEqual(reviewed['segmentCount'], 2)
        review = reviewed['review']
        self.assertEqual((review['deletedSourceIndices'], review['retainedSourceIndices'], review['correctedIndices'], review['basis']['cueCount']), ([1], [0, 2], [0], 3))
        self.assertEqual((review['accuracyCertified'], review['identityVerified']), (False, False))
        # The segmentation target is recounted on the retained cues.
        self.assertEqual((reviewed['segmentation']['cueCount'], reviewed['segmentation']['cuesOverTarget'], reviewed['segmentation']['maxSegmentLength']), (2, 0, 42))
        view = timed_text.parse((out / 'reviewed-segments.json').read_bytes(), expected_sha256=self.ledger()['reviewedSha256'])
        self.assertEqual(view['source'], timed_text.REVIEWED2_VERSION)

    def test_ledger_records_source_text_timing_deletions_and_the_published_mapping(self):
        self.run_job(); ledger = self.ledger()
        self.assertEqual(ledger['version'], 'schemaxis.whispercpp.corrections/2')
        self.assertEqual((ledger['sourceCueCount'], ledger['publishedCueCount'], ledger['correctionCount'], ledger['deletionCount'], ledger['unchangedCueCount']), (3, 2, 1, 1, 1))
        self.assertEqual(ledger['replacements'], [{'sourceIndex': 0, 'publishedIndex': 0, 'startMs': 0, 'endMs': 5410,
                                                   'original': 'And so my fellow Americans, ask not what', 'replacement': REPLACED}])
        self.assertEqual(ledger['deletions'], [{'sourceIndex': 1, 'startMs': 5410, 'endMs': 9040, 'original': 'your country can do for you, ask what you'}])
        self.assertEqual(ledger['retained'], [
            {'publishedIndex': 0, 'sourceIndex': 0, 'startMs': 0, 'endMs': 5410, 'original': 'And so my fellow Americans, ask not what', 'text': REPLACED, 'edited': True},
            {'publishedIndex': 1, 'sourceIndex': 2, 'startMs': 9040, 'endMs': 11000, 'original': 'can do for your country.', 'text': 'can do for your country.', 'edited': False}])
        self.assertEqual((ledger['basis']['sha256'], ledger['basis']['cueCount'], ledger['identityVerified'], ledger['accuracyCertified']), (JFK_SHA, 3, False, False))
        self.assertEqual(ledger['reviewedSha256'], hashlib.sha256((self.dir / 'run' / 'reviewed-segments.json').read_bytes()).hexdigest())

    def test_authoring_order_does_not_change_the_publications(self):
        one = self.edited(deletions=[2, 1], corrections=[{'index': 0, 'text': REPLACED}])
        two = self.edited(deletions=[1, 2], corrections=[{'index': 0, 'text': REPLACED}])
        c.run(one, self.dir / 'one', timeout=30); c.run(two, self.dir / 'two', timeout=30)
        for name in ('reviewed-segments.json', 'transcript.txt', 'captions.srt', 'captions.vtt', 'corrections.json'):
            self.assertEqual((self.dir / 'one' / name).read_bytes(), (self.dir / 'two' / name).read_bytes(), name)

    def test_deleting_only_retains_timings_and_text_untouched_and_the_draft_is_not_modified(self):
        before = self.draft.read_bytes()
        self.run_job(document=self.edited(corrections=[], deletions=[0]))
        self.assertEqual(self.draft.read_bytes(), before)
        reviewed = self.reviewed(); source = json.loads(before)
        self.assertEqual([(s['startMs'], s['endMs'], s['text']) for s in reviewed['segments']], [(s['startMs'], s['endMs'], s['text']) for s in source['segments'][1:]])
        self.assertEqual([s['index'] for s in reviewed['segments']], [0, 1])
        for key in ('audio', 'model', 'nativeJsonSha256', 'language'): self.assertEqual(reviewed[key], source[key])
        self.assertEqual(self.ledger()['replacements'], [])

    def test_unchanged_declaration_has_no_edits_and_maps_every_cue_to_itself(self):
        self.run_job(document=self.edited(corrections=[], deletions=[], review={'status': 'human-reviewed-unchanged', 'note': NOTE}))
        reviewed = self.reviewed(); review = reviewed['review']
        self.assertEqual((review['status'], review['deletionCount'], review['correctionCount'], review['retainedSourceIndices']), ('human-reviewed-unchanged', 0, 0, [0, 1, 2]))
        self.assertEqual([s['text'] for s in reviewed['segments']], [s['text'] for s in json.loads(self.draft.read_text())['segments']])

    def test_caption_review_is_recomputed_on_the_retained_cues(self):
        self.run_job(document=self.edited(captionReview=True))
        report = json.loads((self.dir / 'run' / 'caption-review.json').read_text())
        self.assertEqual((report['cueCount'], [cue['index'] for cue in report['cues']]), (2, [0, 1]))
        self.assertEqual(report['segmentsSha256'], self.ledger()['reviewedSha256'])
        self.assertIs(report['review']['accuracyCertified'], False)


class EveryCueDeleted(Base):
    """The reason for the route: a text-only correction cannot remove the hallucinated cue of a silent recording."""

    def test_the_text_only_route_cannot_remove_the_cue(self):
        blank = {'version': first.VERSION, 'draft': self.silent['draft'], 'basisSha256': SILENCE_SHA, 'review': {'status': 'human-corrected', 'note': NOTE},
                 'corrections': [{'index': 0, 'text': ' '}]}
        self.fault(lambda: first.plan(blank), 'CORRECTION_TEXT_INVALID', '$.corrections[0].text')
        self.fault(lambda: first.plan({**blank, 'corrections': [{'index': 0, 'text': ''}]}), 'INVALID_ARGUMENT')
        self.fault(lambda: first.plan({**blank, 'deletions': [0]}), 'UNKNOWN_ARGUMENT', '$')

    def test_deleting_every_cue_publishes_exact_empty_files_and_a_valid_empty_reviewed_document(self):
        result = self.run_job('silent', self.silent)
        self.assertEqual((result['verified'], result['cues'], result['sourceCues'], result['deletions'], result['reviewStatus']), (True, 0, 1, 1, 'human-corrected'))
        out = self.dir / 'silent'
        self.assertEqual((out / 'transcript.txt').read_bytes(), b'')
        self.assertEqual((out / 'captions.srt').read_bytes(), b'')
        self.assertEqual((out / 'captions.vtt').read_bytes(), b'WEBVTT\n\n')
        reviewed = self.reviewed('silent')
        self.assertEqual((reviewed['segments'], reviewed['segmentCount']), ([], 0))
        self.assertEqual(reviewed['review']['basis'], {'version': timed_text.SOURCE_VERSION, 'sha256': SILENCE_SHA, 'bytes': SILENCE.stat().st_size, 'cueCount': 1})
        self.assertEqual((reviewed['review']['deletedSourceIndices'], reviewed['review']['retainedSourceIndices']), ([0], []))
        view = timed_text.parse((out / 'reviewed-segments.json').read_bytes())
        self.assertEqual((view['cues'], view['status'], view['review']['sourceCueCount']), ([], 'human-corrected', 1))
        ledger = self.ledger('silent')
        self.assertEqual(ledger['deletions'], [{'sourceIndex': 0, 'startMs': 0, 'endMs': 2000, 'original': 'You'}])
        self.assertEqual((ledger['retained'], ledger['replacements'], ledger['publishedCueCount'], ledger['sourceCueCount']), ([], [], 0, 1))
        self.assertEqual(c.verify(out)['cues'], 0)

    def test_every_cue_of_a_multi_cue_draft_can_be_deleted_only_by_listing_each_one(self):
        document = self.edited(corrections=[], deletions=[0, 1, 2])
        self.assertEqual(self.run_job(document=document)['cues'], 0)
        self.assertEqual(self.reviewed()['review']['deletedSourceIndices'], [0, 1, 2])
        self.fault(lambda: c.run(self.edited(corrections=[], deletions=[0, 1, 2, 3]), self.dir / 'beyond', timeout=30), 'DELETION_INDEX_INVALID', '$.deletions[3]')

    def test_the_original_zero_cue_machine_draft_stays_refused(self):
        zero = json.loads(SILENCE.read_text()); zero['segments'] = []; zero['segmentCount'] = 0
        path = self.dir / 'zero.json'; path.write_bytes(timed_text.canonical_json(zero))
        document = {**self.silent, 'draft': {'path': str(path)}, 'basisSha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        fault = self.fault(lambda: c.run(document, self.dir / 'zero-run', timeout=30), 'TIMED_TEXT_INVALID', '$.draft.segments')
        self.assertIn('nonempty', fault.message)
        self.assertFalse((self.dir / 'zero-run' / 'reviewed-segments.json').exists())
        failed = json.loads((self.dir / 'zero-run' / 'result.json').read_text()); self.assertEqual(failed['status'], 'failed')
        self.fault(lambda: first.run({'version': first.VERSION, 'draft': document['draft'], 'basisSha256': document['basisSha256'],
                                      'review': {'status': 'human-reviewed-unchanged', 'note': NOTE}}, self.dir / 'zero-first', timeout=30), 'TIMED_TEXT_INVALID', '$.draft.segments')

    def test_caption_review_of_no_cues_is_refused_because_it_would_read_as_a_pass(self):
        self.fault(lambda: c.run({**self.silent, 'captionReview': True}, self.dir / 'review', timeout=30), 'CAPTION_REVIEW_EMPTY', '$.captionReview')
        self.assertFalse((self.dir / 'review' / 'caption-review.json').exists())

    def test_the_empty_publication_is_never_a_speech_or_silence_claim(self):
        self.run_job('silent', self.silent)
        texts = ' '.join(self.reviewed('silent')['review'][k] for k in ('statement', 'note')) + self.ledger('silent')['statement']
        for forbidden in ('silent recording', 'no speech', 'verified the audio', 'certified accurate'):
            self.assertNotIn(forbidden, texts)
        self.assertIn('not certified', texts)


class RunFaults(Base):
    def test_stale_basis_and_out_of_range_indices_are_distinct_run_faults(self):
        self.fault(lambda: c.run(self.edited(basisSha256='1' * 64), self.dir / 'stale', timeout=30), 'CORRECTIONS_STALE', '$.basisSha256')
        self.fault(lambda: c.run(self.edited(deletions=[1, 3]), self.dir / 'range', timeout=30), 'DELETION_INDEX_INVALID', '$.deletions[1]')
        self.fault(lambda: c.run(self.edited(corrections=[{'index': 3, 'text': 'x'}], deletions=[1]), self.dir / 'replace', timeout=30), 'CORRECTION_INDEX_INVALID', '$.corrections[0].index')
        self.fault(lambda: c.run(self.edited(corrections=[{'index': 2, 'text': 'can do for your country.'}]), self.dir / 'noop', timeout=30), 'CORRECTION_NOOP', '$.corrections[0].text')
        for name in ('stale', 'range', 'replace', 'noop'):
            self.assertFalse((self.dir / name / 'reviewed-segments.json').exists(), name)
            self.assertEqual(json.loads((self.dir / name / 'result.json').read_text())['status'], 'failed')

    def test_a_changed_draft_is_stale_and_a_missing_one_is_distinct(self):
        self.draft.write_bytes(self.draft.read_bytes() + b' ')
        self.fault(lambda: c.run(self.document, self.dir / 'changed', timeout=30), 'CORRECTIONS_STALE')
        self.draft.unlink()
        self.fault(lambda: c.run(self.document, self.dir / 'missing', timeout=30), 'DRAFT_SOURCE_MISSING')

    def test_a_reviewed_document_of_either_version_is_still_refused_as_a_draft(self):
        self.run_job('one', self.document); self.run_job('silent', self.silent)
        first_run = first.run({'version': first.VERSION, 'draft': {'path': str(self.draft)}, 'basisSha256': JFK_SHA, 'review': {'status': 'human-corrected', 'note': NOTE},
                               'corrections': [{'index': 0, 'text': REPLACED}]}, self.dir / 'text-only', timeout=30)
        self.assertTrue(first_run['verified'])
        for label, path in (('reviewed/2', self.dir / 'one' / 'reviewed-segments.json'), ('empty reviewed/2', self.dir / 'silent' / 'reviewed-segments.json'),
                            ('reviewed/1', self.dir / 'text-only' / 'reviewed-segments.json')):
            document = {**self.document, 'draft': {'path': str(path)}, 'basisSha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            with self.subTest(label):
                self.fault(lambda: c.run(document, self.dir / ('again-' + label.replace('/', '')), timeout=30), 'DRAFT_NOT_MACHINE_DRAFT', '$.draft.path')
                self.fault(lambda: first.run({k: v for k, v in document.items() if k != 'deletions'} | {'version': first.VERSION}, self.dir / ('first-' + label.replace('/', '')), timeout=30),
                           'DRAFT_NOT_MACHINE_DRAFT', '$.draft.path')

    def test_total_budget_is_judged_on_the_finished_retained_cues(self):
        draft = json.loads(SILENCE.read_text()); one = draft['segments'][0]
        draft['segments'] = [{**one, 'index': i, 'startMs': i * 10, 'endMs': i * 10 + 10, 'text': 'a' * 65} for i in range(500)]; draft['segmentCount'] = 500
        draft['audio'].update(frames=160000, durationMs=10000, bytes=320044)
        path = self.dir / 'wide.json'; path.write_bytes(timed_text.canonical_json(draft)); pin = hashlib.sha256(path.read_bytes()).hexdigest()
        base = {'version': c.VERSION, 'draft': {'path': str(path)}, 'basisSha256': pin, 'review': {'status': 'human-corrected', 'note': NOTE},
                'corrections': [{'index': i, 'text': 'b' * 100} for i in range(10)]}
        fault = self.fault(lambda: c.run(base, self.dir / 'over', timeout=30), 'TIMED_TEXT_RESOURCE_LIMIT', '$.corrections[0].text')
        self.assertEqual(fault.observed['characters'], 500 * 65 + 350)
        # Deleting five untouched cues brings the finished transcript inside the budget, so the same replacements are accepted.
        fits = c.run({**base, 'deletions': [100, 101, 102, 103, 104]}, self.dir / 'fits', timeout=30)
        self.assertEqual((fits['cues'], fits['sourceCues'], fits['deletions']), (495, 500, 5))
        self.assertEqual(self.reviewed('fits')['review']['retainedSourceIndices'][99:101], [99, 105])


class SemanticReplay(Base):
    """Every ordinary hash is refreshed after each change, so only independent replay can notice it."""

    def setUp(self):
        super().setUp(); self.document['captionReview'] = True
        self.run_job(); self.directory = self.dir / 'run'
        self.saved = {p: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}

    def restore(self):
        for path in [p for p in self.directory.iterdir() if p.is_file() and p not in self.saved]: path.unlink()
        for path, data in self.saved.items(): path.write_bytes(data)

    def tamper(self, name, mutate, directory=None):
        directory = directory or self.directory
        try:
            path = directory / name; original = path.read_bytes(); changed = mutate(original)
            self.assertNotEqual(changed, original, 'vacuous probe ' + name)
            path.write_bytes(changed); self.refresh(directory)
            self.fault(lambda: c._native_verify(directory), 'VERIFICATION_FAILED')
            self.fault(lambda: c.verify(directory), 'VERIFICATION_FAILED')
        finally: self.restore() if directory == self.directory else None

    def test_a_clean_run_verifies_before_and_after_every_probe(self):
        self.assertTrue(c.verify(self.directory)['verified'])

    def test_every_publication_and_every_deletion_record_is_replayed(self):
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'"deletedSourceIndices": [\n      1\n    ]', b'"deletedSourceIndices": [\n      2\n    ]'))
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'"retainedSourceIndices": [\n      0,\n      2\n    ]', b'"retainedSourceIndices": [\n      0,\n      1\n    ]'))
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'"deletionCount": 1', b'"deletionCount": 0'))
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'"cueCount": 3', b'"cueCount": 2', 1))
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'"endMs": 5410', b'"endMs": 5411', 1))
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'"identityVerified": false', b'"identityVerified": true'))
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'"status": "human-corrected"', b'"status": "human-reviewed-unchanged"', 1))
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'can do for your country.', b'can do for your county.'))
        self.tamper('transcript.txt', lambda b: b + b'your country can do for you, ask what you\n')
        self.tamper('captions.srt', lambda b: b.replace(b'2\n00:00:09,040', b'3\n00:00:09,040'))
        self.tamper('captions.vtt', lambda b: b.replace(b'WEBVTT\n\n', b'WEBVTT\n\nNOTE\n\n'))
        self.tamper('corrections.json', lambda b: b.replace(b'"sourceIndex": 2', b'"sourceIndex": 1', 1))
        self.tamper('corrections.json', lambda b: b.replace(b'"deletionCount": 1', b'"deletionCount": 2'))
        self.tamper('corrections.json', lambda b: b.replace(b'"original": "your country can do for you, ask what you"', b'"original": "your country can do for you"'))
        self.tamper('caption-review.json', lambda b: b.replace(b'"cueCount": 2', b'"cueCount": 3'))
        self.assertTrue(c.verify(self.directory)['verified'])

    def test_captured_draft_authored_edits_plan_and_result_are_bound_together(self):
        self.tamper('captured-draft.json', lambda b: b.replace(b'And so my', b'And so, my'))
        self.tamper('captures.json', lambda b: b.replace(JFK_SHA.encode(), b'1' * 64))
        self.tamper('authored.json', lambda b: json.dumps({**json.loads(b), 'deletions': [2]}).encode())
        self.tamper('authored.json', lambda b: json.dumps({**json.loads(b), 'deletions': [1, 2]}).encode())
        self.tamper('plan.json', lambda b: b.replace(b'"deletions": [\n    1\n  ]', b'"deletions": [\n    2\n  ]'))
        self.tamper('result.json', lambda b: b.replace(b'"deletions": 1', b'"deletions": 0'))
        self.tamper('verification.json', lambda b: b.replace(b'host-only', b'native'))

    def test_a_forged_empty_state_is_refused_even_with_refreshed_hashes(self):
        # Replace the partial publications with a self-consistent, contract-valid empty reviewed/2 document and matching empty files.
        reviewed = json.loads((self.directory / 'reviewed-segments.json').read_text())
        reviewed['segments'] = []; reviewed['segmentCount'] = 0; reviewed.pop('segmentation')
        reviewed['review'].update(correctionCount=0, correctedIndices=[], deletionCount=3, deletedSourceIndices=[0, 1, 2], retainedSourceIndices=[])
        timed_text.validate(reviewed)
        self.tamper('reviewed-segments.json', lambda b: timed_text.canonical_json(reviewed))
        for name, empty in (('transcript.txt', b''), ('captions.srt', b''), ('captions.vtt', b'WEBVTT\n\n')): self.tamper(name, lambda b, e=empty: e)

    def test_membership_is_exact_and_native_evidence_is_a_failure(self):
        for name, content in (('transcribe-launcher.py', 'native evidence has no place here'), ('whisper.stderr', 'log'), ('extra.txt', 'x')):
            try:
                (self.directory / name).write_text(content); self.fault(lambda: c._native_verify(self.directory), 'VERIFICATION_FAILED')
            finally: self.restore()
        try:
            planted = self.directory / '.dispatch' / 'transcribe'; planted.mkdir(parents=True); marker = self.dir / 'ran.marker'
            (planted / 'replay-x.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("ran")\n')
            self.fault(lambda: c._native_verify(self.directory), 'VERIFICATION_FAILED'); self.assertFalse(marker.exists())
        finally: shutil.rmtree(self.directory / '.dispatch', ignore_errors=True); self.restore()
        self.assertTrue(c.verify(self.directory)['verified'])

    def test_the_empty_run_is_replayed_too(self):
        c.run(self.silent, self.dir / 'silent', timeout=30)
        directory = self.dir / 'silent'; saved = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        for name, mutate in (('transcript.txt', lambda b: b'You\n'), ('captions.vtt', lambda b: b + b'00:00:00.000 --> 00:00:02.000\nYou\n\n'),
                             ('captions.srt', lambda b: b'1\n00:00:00,000 --> 00:00:02,000\nYou\n\n'),
                             ('reviewed-segments.json', lambda b: b.replace(b'"deletionCount": 1', b'"deletionCount": 0')),
                             ('corrections.json', lambda b: b.replace(b'"deletionCount": 1', b'"deletionCount": 0')),
                             ('authored.json', lambda b: json.dumps({**json.loads(b), 'deletions': []}).encode())):
            try:
                path = directory / name; path.write_bytes(mutate(path.read_bytes())); self.refresh(directory)
                self.fault(lambda: c._native_verify(directory), 'VERIFICATION_FAILED')
            finally:
                for p, data in saved.items(): p.write_bytes(data)
        self.assertTrue(c.verify(directory)['verified'])


class Interfaces(Base):
    def cli(self, *arguments):
        if arguments and arguments[0] == 'run':
            arguments = (*arguments, '--backend', 'native')
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'SCHEMAXIS_WHISPERCPP': '/nonexistent/whisper-cli', 'PATH': '/nonexistent'}
        return subprocess.run([sys.executable, '-m', 'schemaxis', *arguments], capture_output=True, text=True, env=environment, cwd=self.dir, timeout=120)

    def test_cli_plan_run_and_verify_without_any_whisper_executable(self):
        document = self.dir / 'document.json'; document.write_text(json.dumps(self.silent))
        planned = self.cli('plan', str(document)); self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual(json.loads(planned.stdout)['deletions'], [0])
        ran = self.cli('run', str(document), '--output-directory', str(self.dir / 'cli-run')); self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertEqual((json.loads(ran.stdout)['runtime'], json.loads(ran.stdout)['cues']), ('host-only', 0))
        checked = self.cli('verify', str(self.dir / 'cli-run')); self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertTrue(json.loads(checked.stdout)['verified'])
        bad = self.dir / 'bad.json'; bad.write_text(json.dumps({**self.silent, 'deletions': [0, 0]}))
        failed = self.cli('run', str(bad), '--output-directory', str(self.dir / 'cli-bad')); self.assertNotEqual(failed.returncode, 0)
        self.assertIn('DELETION_DUPLICATE', failed.stdout + failed.stderr)

    def test_workflow_publishes_a_text_artifact_at_index_zero_for_the_pandoc_transcript_path(self):
        from schemaxis import workflow
        document = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'correct', 'document': self.silent}]}
        result = workflow.execute(document, self.dir / 'workflow')
        self.assertIn('succeeded', json.dumps(result))
        published = list((self.dir / 'workflow').rglob('reviewed-segments.json')); self.assertEqual(len(published), 1)
        self.assertEqual(timed_text.parse(published[0].read_bytes())['cues'], [])
        self.assertTrue(workflow.verify(self.dir / 'workflow')['verified'])

    def test_shipped_examples_plan(self):
        for name in ('whispercpp-deletions-partial', 'whispercpp-deletions-all', 'whispercpp-deletions-unchanged'):
            c.plan(json.loads((ROOT / f'examples/schemaxis/{name}.json').read_text()))
        for name, code in (('whispercpp-deletions-conflict-invalid', 'CORRECTION_DELETION_CONFLICT'), ('whispercpp-deletions-duplicate-invalid', 'DELETION_DUPLICATE')):
            self.fault(lambda: c.plan(json.loads((ROOT / f'examples/schemaxis/{name}.json').read_text())), code)
        stale = json.loads((ROOT / 'examples/schemaxis/whispercpp-deletions-range-invalid.json').read_text()); c.plan(stale)

    def test_discovery_and_guidance_cover_the_route(self):
        from schemaxis.studio_guidance import audit
        self.assertTrue(audit('whispercpp')['complete'])
        guidance = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/guidance.json').read_text())
        fields = guidance['routes'][c.VERSION]['fields']
        self.assertEqual({'', '/properties/version', '/properties/draft', '/properties/draft/properties/path', '/properties/basisSha256', '/properties/review',
                          '/properties/review/properties/status', '/properties/review/properties/note', '/properties/corrections', '/properties/corrections/items',
                          '/properties/corrections/items/properties/index', '/properties/corrections/items/properties/text', '/properties/deletions',
                          '/properties/deletions/items', '/properties/captionReview'}, set(fields))
        self.assertTrue(all(r['status'] == 'reviewed' for r in fields.values()))
        joined = ' '.join(fields['/properties/deletions']['explanation'].split())
        for fragment in ('source', 'unique', 'declaration'): self.assertIn(fragment, joined + ' ' + ' '.join(fields['']['pitfalls']))


if __name__ == '__main__':
    unittest.main()
