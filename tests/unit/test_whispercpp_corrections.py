"""Host-only human corrections: pinned basis, closed edits, new reviewed contract, ledger and semantic replay.

Nothing here launches a native executable. The draft is the committed real whisper.cpp output of the
public sample (three cues, native boundaries 0/5410/9040/11000 ms), so these tests never count as
native qualification of any route.
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
from schemaxis.adaptors.whispercpp import corrections as c
from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'examples/schemaxis/whispercpp-corrections-fixtures/jfk-short-cues-segments.json'
BASIS = '0fb466aec743b3a236655d7b29e4d3a1003bcd5230abcd4276af56b08cb4ba04'
EDITS = [{'index': 0, 'text': 'And so, my fellow Americans: ask not what'}, {'index': 1, 'text': 'your country can do for you; ask what you'}]
SRT = ('1\n00:00:00,000 --> 00:00:05,410\nAnd so, my fellow Americans: ask not what\n\n'
       '2\n00:00:05,410 --> 00:00:09,040\nyour country can do for you; ask what you\n\n'
       '3\n00:00:09,040 --> 00:00:11,000\ncan do for your country.\n\n')
NOTE = 'Illustrative example declaration; no person reviewed this recording for it.'


class Base(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)
        self.draft = self.dir / 'segments.json'; shutil.copyfile(FIXTURE, self.draft)
        self.document = {'version': c.VERSION, 'draft': {'path': str(self.draft)}, 'basisSha256': BASIS,
                         'review': {'status': 'human-corrected', 'note': NOTE}, 'corrections': copy.deepcopy(EDITS)}

    def fault(self, action, code=None, location=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        fault = caught.exception.fault
        if code: self.assertEqual(fault.code, code, fault.to_dict())
        if location: self.assertEqual(fault.location, location)
        self.assertTrue(fault.recovery or fault.code == 'VERIFICATION_FAILED', fault.to_dict())
        return fault

    def run_job(self, name='run', document=None):
        return c.run(document or self.document, self.dir / name, timeout=30)

    def refresh(self, directory):
        """Refresh every ordinary hash: receipt artifacts, evidence digests and publication metadata."""
        receipt = c.read_json(directory, 'verification.json')
        plan = c.read_json(directory, 'plan.json')
        receipt['artifacts'] = c.artifacts(directory, c.wants_review(plan))
        receipt['evidence'] = {n: c.digest(directory, n) for n in receipt['evidence']}
        c.atomic_json(directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)


class Planning(Base):
    def test_plan_checks_shape_only_and_never_reads_the_draft(self):
        self.document['draft']['path'] = '/definitely/not/there/segments.json'
        with patch('builtins.open', side_effect=AssertionError('planning read a file')), patch('os.open', side_effect=AssertionError('planning opened a file')):
            planned = c.plan(self.document)
            self.assertEqual(c.query(self.document), (['correct'], {}))
        self.assertEqual((planned['version'], planned['operation']), (c.PLAN_VERSION, 'correct'))
        self.assertEqual(planned['losses'], c.LOSSES)
        self.assertNotIn('captionReview', planned)
        self.assertIn('host-only', planned['losses'][0].lower())

    def test_route_is_registered_separately_and_host_only(self):
        route = registry.resolve(self.document, legacy=True)[1]
        self.assertEqual(route['module'], 'schemaxis.adaptors.whispercpp.corrections')
        self.assertEqual(route['acceptedArtifacts'], ['text'])
        primary = registry.resolve({'version': 'schemaxis.whispercpp/1'}, legacy=True)[1]
        self.assertNotEqual(route['module'], primary['module'])
        qualification = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/qualification.json').read_text())
        self.assertNotIn(c.VERSION, qualification['routes'])

    def test_shipped_examples_and_exact_faults(self):
        for name in ('whispercpp-corrections', 'whispercpp-corrections-unchanged', 'whispercpp-corrections-stale-invalid'):
            c.plan(json.loads((ROOT / f'examples/schemaxis/{name}.json').read_text()))
        blank = json.loads((ROOT / 'examples/schemaxis/whispercpp-corrections-blank-invalid.json').read_text())
        self.fault(lambda: c.plan(blank), 'CORRECTION_TEXT_INVALID', '$.corrections[1].text')

    def test_a_note_must_be_publishable_as_pandoc_plain_text(self):
        for label, note in (('no-break space', 'Illustrative\u00a0note'), ('ideographic space', 'Illustrative\u3000note'), ('tab', 'Illustrative\tnote'), ('word joiner', 'Illustrative\u2060note'),
                            ('byte order mark', 'Illustrative\ufeffnote'), ('zero-width space', 'Illustrative\u200bnote'), ('zero-width joiner', 'Illustrative\u200dnote'), ('private use', 'Illustrative\ue000note')):
            document = copy.deepcopy(self.document); document['review']['note'] = note
            with self.subTest(label): self.assertIn('review note', self.fault(lambda: c.plan(document), 'CORRECTIONS_NOTE_INVALID', '$.review.note').message)
        self.document['review']['note'] = 'Note illustrative : café — 日本語 «citation»'
        c.plan(self.document)

    def test_caption_unicode_that_a_note_may_not_use_stays_legitimate_in_corrections(self):
        for text in ('can do for you\u00a0now', 'می\u200cخواهم', 'left\u200eright'):
            document = copy.deepcopy(self.document); document['corrections'][1]['text'] = text; c.plan(document)

    def test_unrecognised_keys_are_refused_with_location_and_recovery(self):
        for mutate, location in ((lambda d: d.update(operation='correct'), '$'), (lambda d: d['draft'].update(sha256='a' * 64), '$.draft'),
                                 (lambda d: d['review'].update(reviewer='someone'), '$.review'), (lambda d: d['corrections'][0].update(startMs=0), '$.corrections[0]'),
                                 (lambda d: d['corrections'][1].update(endMs=9000), '$.corrections[1]')):
            document = copy.deepcopy(self.document); mutate(document)
            fault = self.fault(lambda: c.plan(document), 'UNKNOWN_ARGUMENT', location)
            self.assertIn('allowed members', fault.recovery)
            if location.startswith('$.corrections'): self.assertIn('timings cannot be edited', fault.recovery)

    def test_values_are_validated_before_any_read(self):
        def bad(mutate, code, location=None):
            document = copy.deepcopy(self.document); mutate(document); return self.fault(lambda: c.plan(document), code, location)
        bad(lambda d: d.update(version='schemaxis.whispercpp/1'), 'UNSUPPORTED_VERSION', '$.version')
        for path in ('segments.json', '/a/../segments.json', '/a/segments.txt', '/a/seg\0ments.json'):
            bad(lambda d, p=path: d['draft'].update(path=p), 'INVALID_DRAFT_SOURCE', '$.draft.path')
        for pin in ('A' * 64, 'g' * 64):
            bad(lambda d, p=pin: d.update(basisSha256=p), 'INVALID_SHA256', '$.basisSha256')
        bad(lambda d: d.update(basisSha256='a' * 63), 'INVALID_ARGUMENT')
        del_basis = copy.deepcopy(self.document); del del_basis['basisSha256']
        self.fault(lambda: c.plan(del_basis), 'MISSING_ARGUMENT', '$.basisSha256')
        bad(lambda d: d['review'].update(status='verified-by-human'), 'INVALID_ARGUMENT')
        bad(lambda d: d['review'].update(status='machine-draft'), 'INVALID_ARGUMENT')
        for note in ('', 'two  spaces', ' padded', 'markup <b>', 'arrow --> here', 'line\nbreak', 'x' * 501, '‮override'):
            fault = bad(lambda d, n=note: d['review'].update(note=n), None)
            self.assertIn(fault.code, ('CORRECTIONS_NOTE_INVALID', 'INVALID_ARGUMENT'), note)
            self.assertIn(fault.location, ('$.review.note',))
        bad(lambda d: d['review'].pop('note'), 'MISSING_ARGUMENT', '$.review.note')
        bad(lambda d: d['corrections'][0].update(index=True), 'INVALID_ARGUMENT')
        bad(lambda d: d['corrections'][0].update(index=-1), 'INVALID_ARGUMENT')
        bad(lambda d: d['corrections'][0].update(index=1.0), 'INVALID_ARGUMENT')
        bad(lambda d: d['corrections'][0].update(index=512), 'INVALID_ARGUMENT')
        bad(lambda d: d['corrections'].append({'index': 2}), 'MISSING_ARGUMENT', '$.corrections[2].text')
        bad(lambda d: d.update(corrections='all'), 'INVALID_ARGUMENT')
        bad(lambda d: d.update(captionReview='yes'), 'INVALID_ARGUMENT')
        bad(lambda d: d.update(corrections=[{'index': i % 512, 'text': 'x'} for i in range(513)]), 'INVALID_ARGUMENT')

    def test_duplicate_blank_and_markup_edits_are_located(self):
        document = copy.deepcopy(self.document); document['corrections'].append({'index': 0, 'text': 'Another'})
        fault = self.fault(lambda: c.plan(document), 'CORRECTION_DUPLICATE', '$.corrections[2].index')
        self.assertIn('$.corrections[0]', fault.message)
        for text, fragment in (('   ', 'blank'), ('​', 'no visible'), (' padded', 'space'), ('a <b> tag', 'markup'), ('a --> b', 'arrow'), ('line\nbreak', 'control'),
                               ('‮bad', 'bidirectional'), ('�', 'replacement')):
            document = copy.deepcopy(self.document); document['corrections'][0]['text'] = text
            fault = self.fault(lambda: c.plan(document), 'CORRECTION_TEXT_INVALID', '$.corrections[0].text')
            self.assertIn(fragment, fault.message, text)
        document = copy.deepcopy(self.document); document['corrections'][0]['text'] = 'x' * 257
        self.fault(lambda: c.plan(document), 'INVALID_ARGUMENT')

    def test_status_must_agree_with_the_edits(self):
        document = copy.deepcopy(self.document); document['corrections'] = []
        self.fault(lambda: c.plan(document), 'CORRECTIONS_STATUS_CONFLICT', '$.corrections')
        document.pop('corrections')
        self.fault(lambda: c.plan(document), 'CORRECTIONS_STATUS_CONFLICT', '$.corrections')
        document['review']['status'] = 'human-reviewed-unchanged'
        self.assertEqual(c.plan(document)['review']['status'], 'human-reviewed-unchanged')
        document['corrections'] = copy.deepcopy(EDITS)
        self.fault(lambda: c.plan(document), 'CORRECTIONS_STATUS_CONFLICT', '$.review.status')

    def test_caption_review_is_present_only_when_authored(self):
        self.assertNotIn('captionReview', c.plan(self.document))
        self.document['captionReview'] = False
        self.assertIs(c.plan(self.document)['captionReview'], False)
        self.document['captionReview'] = True
        self.assertEqual(len(c.plan(self.document)['losses']), len(c.LOSSES) + 1)

    def test_schema_declares_the_exact_route(self):
        schema = c.schema()
        self.assertEqual(schema['properties']['version']['const'], c.VERSION)
        self.assertEqual(set(schema['required']), {'version', 'draft', 'basisSha256', 'review'})
        self.assertEqual(set(schema['properties']), {'version', 'draft', 'basisSha256', 'review', 'corrections', 'captionReview'})


class Publication(Base):
    def test_corrected_run_publishes_exact_files_and_never_launches_a_native_process(self):
        draft_bytes = self.draft.read_bytes()
        with patch('subprocess.Popen', side_effect=AssertionError('a process was launched')), patch('os.execve', side_effect=AssertionError('exec')):
            result = self.run_job()
        directory = self.dir / 'run'
        self.assertEqual({k: result[k] for k in ('verified', 'reviewStatus', 'runtime', 'nativeProcesses', 'cues', 'corrections', 'basisSha256', 'accuracyCertified', 'identityVerified')},
                         {'verified': True, 'reviewStatus': 'human-corrected', 'runtime': 'host-only', 'nativeProcesses': 0, 'cues': 3, 'corrections': 2, 'basisSha256': BASIS,
                          'accuracyCertified': False, 'identityVerified': False})
        self.assertEqual(self.draft.read_bytes(), draft_bytes)
        self.assertEqual(hashlib.sha256((directory / 'captured-draft.json').read_bytes()).hexdigest(), BASIS)
        self.assertEqual((directory / 'captions.srt').read_text(), SRT)
        self.assertEqual((directory / 'transcript.txt').read_text(), 'And so, my fellow Americans: ask not what\nyour country can do for you; ask what you\ncan do for your country.\n')
        self.assertEqual((directory / 'captions.vtt').read_text(),
                         'WEBVTT\n\n00:00:00.000 --> 00:00:05.410\nAnd so, my fellow Americans: ask not what\n\n00:00:05.410 --> 00:00:09.040\nyour country can do for you; ask what you\n\n00:00:09.040 --> 00:00:11.000\ncan do for your country.\n\n')
        names = {p.name for p in directory.iterdir()}
        self.assertFalse([n for n in names if 'launcher' in n or 'submission' in n or n.endswith(('.stdout', '.stderr')) or n in ('runtime.json', 'model.json', 'native.json')], names)
        self.assertEqual([Path(x['file']).name for x in c.read_json(directory, 'verification.json')['artifacts']],
                         ['reviewed-segments.json', 'transcript.txt', 'captions.srt', 'captions.vtt', 'corrections.json'])
        self.assertEqual(c.read_json(directory, 'verification.json')['artifacts'][0]['kind'], 'text')
        self.assertEqual(c.verify(directory), {k: v for k, v in result.items() if k != 'status'})

    def test_reviewed_document_preserves_timings_and_provenance_under_the_new_contract(self):
        self.run_job(); directory = self.dir / 'run'
        reviewed = json.loads((directory / 'reviewed-segments.json').read_text()); draft = json.loads(self.draft.read_text())
        self.assertEqual(reviewed['version'], 'schemaxis.timedtext.reviewed/1')
        for key in ('language', 'timeUnit', 'audio', 'model', 'nativeJsonSha256', 'segmentCount'): self.assertEqual(reviewed[key], draft[key])
        self.assertEqual([(s['index'], s['startMs'], s['endMs']) for s in reviewed['segments']], [(s['index'], s['startMs'], s['endMs']) for s in draft['segments']])
        self.assertEqual([s['text'] for s in reviewed['segments']], [EDITS[0]['text'], EDITS[1]['text'], draft['segments'][2]['text']])
        review = reviewed['review']
        self.assertEqual((review['status'], review['accuracyCertified'], review['identityVerified'], review['note']), ('human-corrected', False, False, NOTE))
        self.assertEqual((review['basis'], review['correctionCount'], review['correctedIndices']), ({'version': 'schemaxis.whispercpp.segments/1', 'sha256': BASIS, 'bytes': FIXTURE.stat().st_size}, 2, [0, 1]))
        self.assertEqual(reviewed['segmentation']['maxSegmentLength'], 42)
        self.assertEqual(reviewed['segmentation']['cuesOverTarget'], 0)
        view = timed_text.parse((directory / 'reviewed-segments.json').read_bytes())
        self.assertEqual((view['status'], view['source'], view['review']['correctedIndices']), ('human-corrected', timed_text.REVIEWED_VERSION, [0, 1]))
        self.assertEqual(view['audioSha256'], draft['audio']['sha256']); self.assertEqual(view['nativeJsonSha256'], draft['nativeJsonSha256'])
        self.assertEqual((directory / 'reviewed-segments.json').read_bytes(), timed_text.canonical_json(reviewed))
        # The machine contract is untouched: the draft still reads as a draft, and the reviewed shape is refused on it.
        self.assertEqual(timed_text.parse(self.draft.read_bytes())['status'], 'machine-draft')
        forged = copy.deepcopy(draft); forged['review'] = review
        with self.assertRaises(SchemaxisError) as caught: timed_text.validate(forged)
        self.assertEqual(caught.exception.fault.code, 'TIMED_TEXT_REVIEW_UNSUPPORTED')

    def test_ledger_binds_the_basis_and_records_exact_original_and_replacement_text(self):
        self.run_job(); directory = self.dir / 'run'
        ledger = json.loads((directory / 'corrections.json').read_text())
        draft = json.loads(self.draft.read_text())
        self.assertEqual(ledger['version'], 'schemaxis.whispercpp.corrections/1')
        self.assertEqual(ledger['basis'], {'version': 'schemaxis.whispercpp.segments/1', 'sha256': BASIS, 'bytes': FIXTURE.stat().st_size})
        self.assertEqual(ledger['reviewedSha256'], hashlib.sha256((directory / 'reviewed-segments.json').read_bytes()).hexdigest())
        self.assertEqual((ledger['cueCount'], ledger['correctionCount'], ledger['unchangedCueCount']), (3, 2, 1))
        self.assertEqual(ledger['entries'], [{'index': 0, 'startMs': 0, 'endMs': 5410, 'original': draft['segments'][0]['text'], 'replacement': EDITS[0]['text']},
                                              {'index': 1, 'startMs': 5410, 'endMs': 9040, 'original': draft['segments'][1]['text'], 'replacement': EDITS[1]['text']}])
        self.assertEqual((ledger['status'], ledger['note'], ledger['accuracyCertified'], ledger['identityVerified']), ('human-corrected', NOTE, False, False))

    def test_authoring_order_does_not_change_the_publications(self):
        self.run_job('forward'); self.document['corrections'].reverse(); self.run_job('reverse')
        for name in c.published(False):
            self.assertEqual((self.dir / 'forward' / name).read_bytes(), (self.dir / 'reverse' / name).read_bytes(), name)

    def test_unchanged_review_publishes_the_same_words_with_its_own_status(self):
        document = {'version': c.VERSION, 'draft': {'path': str(self.draft)}, 'basisSha256': BASIS,
                    'review': {'status': 'human-reviewed-unchanged', 'note': 'Read against the speech text; nothing changed.'}}
        result = self.run_job('same', document); directory = self.dir / 'same'
        self.assertEqual((result['reviewStatus'], result['corrections']), ('human-reviewed-unchanged', 0))
        ledger = json.loads((directory / 'corrections.json').read_text()); reviewed = json.loads((directory / 'reviewed-segments.json').read_text())
        self.assertEqual((ledger['entries'], ledger['unchangedCueCount']), ([], 3))
        self.assertEqual(reviewed['review']['correctedIndices'], [])
        self.assertEqual([s['text'] for s in reviewed['segments']], [s['text'] for s in json.loads(self.draft.read_text())['segments']])
        self.assertEqual(c.verify(directory)['reviewStatus'], 'human-reviewed-unchanged')

    def test_caption_review_is_recomputed_on_corrected_text_and_certifies_nothing(self):
        self.document['captionReview'] = True
        result = self.run_job(); directory = self.dir / 'run'
        report = json.loads((directory / 'caption-review.json').read_text())
        reviewed_sha = hashlib.sha256((directory / 'reviewed-segments.json').read_bytes()).hexdigest()
        self.assertEqual(report['segmentsSha256'], reviewed_sha)
        self.assertEqual([cue['codePoints'] for cue in report['cues']], [len(EDITS[0]['text']), len(EDITS[1]['text']), len('can do for your country.')])
        self.assertFalse(report['review']['accuracyCertified']); self.assertTrue(report['review']['humanReviewRequired'])
        self.assertEqual(result['artifacts'], 6); self.assertIn('captionReview', result)
        self.assertEqual(c.read_json(directory, 'verification.json')['artifacts'][-1]['file'], str(directory / 'caption-review.json'))

    def test_segmentation_member_is_recounted_on_the_corrected_text(self):
        draft = json.loads(self.draft.read_text())
        long_text = 'x' * 60
        document = copy.deepcopy(self.document); document['corrections'] = [{'index': 2, 'text': long_text}]
        self.assertEqual(draft['segmentation']['cuesOverTarget'], 0)
        # A different pinned draft keeps the same bytes contract; edit the source and its pin together.
        document['basisSha256'] = BASIS
        self.run_job('long', document)
        reviewed = json.loads((self.dir / 'long' / 'reviewed-segments.json').read_text())
        self.assertEqual(reviewed['segmentation']['cuesOverTarget'], 1)
        self.assertFalse(reviewed['segmentation']['enforced'])
        self.assertNotIn('machine draft', reviewed['segmentation']['statement'].split('for the machine draft')[0])

    def test_source_capture_is_the_run_time_bytes_not_a_later_path(self):
        self.run_job(); directory = self.dir / 'run'
        before = (directory / 'captured-draft.json').read_bytes()
        self.draft.write_bytes(b'{"changed": true}')
        self.assertEqual(c.verify(directory)['verified'], True)
        self.assertEqual((directory / 'captured-draft.json').read_bytes(), before)
        self.assertEqual(c.read_json(directory, 'captures.json'), {'source': str(self.draft), 'sha256': BASIS, 'bytes': len(before)})

    def test_reusable_inputs_hash_the_current_draft_bytes(self):
        self.assertEqual(c.reusableInputs(self.document), {'draft': BASIS})
        self.draft.write_bytes(self.draft.read_bytes() + b'\n')
        self.assertNotEqual(c.reusableInputs(self.document)['draft'], BASIS)
        self.fault(lambda: c.reusableInputs({**self.document, 'draft': {'path': str(self.dir / 'missing.json')}}), 'DRAFT_SOURCE_MISSING')


class RunFaults(Base):
    def failed(self, code, location=None, name='bad'):
        fault = self.fault(lambda: self.run_job(name), code, location)
        directory = self.dir / name
        self.assertEqual(c.read_json(directory, 'result.json')['status'], 'failed')
        self.assertFalse([p.name for p in directory.iterdir() if p.name in c.published(True)], 'nothing is published after a refusal')
        return fault

    def test_stale_basis_is_refused_and_names_both_digests(self):
        self.document['basisSha256'] = '1' * 64
        fault = self.failed('CORRECTIONS_STALE', '$.basisSha256')
        self.assertEqual((fault.observed['expected'], fault.observed['actual']), ('1' * 64, BASIS))
        self.assertIn('copy its sha256', fault.recovery)

    def test_a_changed_draft_is_stale_even_when_the_edit_would_still_apply(self):
        self.draft.write_bytes(self.draft.read_bytes().replace(b'And so my', b'And so, my'))
        self.failed('CORRECTIONS_STALE', '$.basisSha256')

    def test_invalid_noop_and_reviewed_draft_inputs(self):
        self.document['corrections'][1]['index'] = 3
        fault = self.failed('CORRECTION_INDEX_INVALID', '$.corrections[1].index', 'index')
        self.assertEqual(fault.observed['cueCount'], 3)
        self.document['corrections'][1]['index'] = 2
        draft = json.loads(self.draft.read_text())
        self.document['corrections'][1]['text'] = draft['segments'][2]['text']
        self.failed('CORRECTION_NOOP', '$.corrections[1].text', 'noop')

    def test_a_reviewed_document_is_not_a_draft_and_the_original_is_never_modified(self):
        self.run_job('first')
        reviewed = self.dir / 'first' / 'reviewed-segments.json'
        second = {**self.document, 'draft': {'path': str(reviewed)}, 'basisSha256': hashlib.sha256(reviewed.read_bytes()).hexdigest()}
        fault = self.fault(lambda: self.run_job('second', second), 'DRAFT_NOT_MACHINE_DRAFT', '$.draft.path')
        self.assertIn('original machine', fault.recovery)
        self.assertEqual(hashlib.sha256(self.draft.read_bytes()).hexdigest(), BASIS)

    def test_a_literal_that_overflows_to_infinity_in_the_draft_is_refused_when_parsed(self):
        data = self.draft.read_bytes().replace(b'"durationMs": 11000', b'"durationMs": 1e400'); self.assertNotEqual(data, self.draft.read_bytes())
        self.draft.write_bytes(data); self.document['basisSha256'] = hashlib.sha256(data).hexdigest()
        fault = self.failed('TIMED_TEXT_INVALID_JSON', '$.draft', 'overflow')
        self.assertIn('infinity', fault.message)

    def test_draft_must_satisfy_the_machine_contract(self):
        broken = json.loads(self.draft.read_text()); broken['extra'] = 1
        self.draft.write_bytes(timed_text.canonical_json(broken)); self.document['basisSha256'] = hashlib.sha256(self.draft.read_bytes()).hexdigest()
        self.failed('TIMED_TEXT_UNKNOWN_KEY')
        self.draft.write_bytes(b'not json'); self.document['basisSha256'] = hashlib.sha256(b'not json').hexdigest()
        self.failed('TIMED_TEXT_INVALID_JSON', name='bad2')

    def test_source_problems_are_distinct_faults(self):
        self.document['draft']['path'] = str(self.dir / 'missing.json')
        fault = self.failed('DRAFT_SOURCE_MISSING', name='missing')
        self.assertIn('does not exist', fault.message); self.assertEqual(fault.location, str(self.dir / 'missing.json'))
        self.document['draft']['path'] = str(self.dir / 'no-such-folder' / 'segments.json')
        self.failed('DRAFT_SOURCE_MISSING', name='missing-folder')
        self.document['draft']['path'] = str(self.draft / 'inside.json')
        self.failed('DRAFT_SOURCE_MISSING', name='not-a-folder')
        link = self.dir / 'link.json'; link.symlink_to(self.draft); self.document['draft']['path'] = str(link)
        self.failed('INVALID_DRAFT_SOURCE', name='link')
        dangling = self.dir / 'dangling.json'; dangling.symlink_to(self.dir / 'gone.json'); self.document['draft']['path'] = str(dangling)
        self.failed('INVALID_DRAFT_SOURCE', name='dangling')
        self.document['draft']['path'] = str(self.dir / 'folder.json'); (self.dir / 'folder.json').mkdir()
        self.failed('INVALID_DRAFT_SOURCE', name='folder')

    def test_absent_required_members_are_missing_arguments_not_invalid_objects(self):
        for member, location in (('draft', '$.draft'), ('review', '$.review'), ('basisSha256', '$.basisSha256')):
            document = copy.deepcopy(self.document); del document[member]
            self.fault(lambda: c.plan(document), 'MISSING_ARGUMENT', location)
            self.fault(lambda: c.run(document, self.dir / ('absent-' + member), timeout=30), 'MISSING_ARGUMENT', location)
        for mutate, location in ((lambda d: d['draft'].clear(), '$.draft.path'), (lambda d: d['review'].pop('status'), '$.review.status'), (lambda d: d['review'].pop('note'), '$.review.note')):
            document = copy.deepcopy(self.document); mutate(document)
            self.fault(lambda: c.plan(document), 'MISSING_ARGUMENT', location)
        for value in (None, 'path', [], 3):
            document = copy.deepcopy(self.document); document['draft'] = value
            self.fault(lambda: c.plan(document), 'INVALID_DOCUMENT', '$.draft')

    def test_existing_output_is_never_replaced(self):
        self.run_job()
        before = {p.name: p.read_bytes() for p in (self.dir / 'run').iterdir() if p.is_file()}
        self.fault(lambda: self.run_job(), 'OUTPUT_EXISTS')
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.dir / 'run').iterdir() if p.is_file()})

    def long_draft(self):
        """A valid machine draft of 320 cues of 100 characters: 32000 of the 32768 total, so corrections can cross it."""
        draft = json.loads(self.draft.read_text()); draft.pop('segmentation', None)
        draft['segments'] = [dict(index=i, startMs=i * 30, endMs=i * 30 + 30, text='y' * 100) for i in range(320)]; draft['segmentCount'] = 320
        data = timed_text.canonical_json(draft); self.draft.write_bytes(data); timed_text.validate(draft)
        return hashlib.sha256(data).hexdigest()

    def test_total_character_budget_is_enforced_on_the_corrected_transcript_at_the_contributing_correction(self):
        self.document['basisSha256'] = self.long_draft()
        lengths = (200, 256, 220, 256, 210, 256)  # total 32000 + 156 + 100 + 120 + 156 + 110 + 156 = 32798 > 32768
        self.document['corrections'] = [{'index': i, 'text': 'x' * n} for i, n in enumerate(lengths)]
        fault = self.failed('TIMED_TEXT_RESOURCE_LIMIT', '$.corrections[1].text', 'budget')
        self.assertEqual((fault.observed['characters'], fault.observed['limit'], fault.observed['draftCharacters'], fault.observed['index']), (32798, 32768, 32000, 1))
        self.assertIn('shorten', fault.recovery); self.assertIn('corrections cannot add or merge cues', fault.recovery); self.assertNotIn('cue-length', fault.recovery)
        self.assertIn('32798', fault.message)
        # exactly at the limit is accepted: four cues of 256 and one of 244 add 4 * 156 + 144 = 768
        self.document['corrections'] = [{'index': i, 'text': 'x' * 256} for i in range(4)] + [{'index': 4, 'text': 'x' * 244}]
        self.assertEqual(self.run_job('at-limit')['verified'], True)

    def test_a_later_shrinking_correction_is_not_refused_for_an_earlier_growing_one(self):
        self.document['basisSha256'] = self.long_draft()
        growing = [{'index': i, 'text': 'x' * 256} for i in range(6)]  # +936: the running total passes 32768 before the shrinks below
        shrinking = [{'index': 6, 'text': 'a'}, {'index': 7, 'text': 'b'}]  # -198, so the finished transcript holds 32738
        self.document['corrections'] = growing + shrinking
        result = self.run_job('shrunk'); self.assertEqual((result['verified'], result['corrections'], result['cues']), (True, 8, 320))
        self.assertEqual(len(timed_text.plain_text(timed_text.parse((self.dir / 'shrunk/reviewed-segments.json').read_bytes())['cues'])), 32738 + 320)
        # the same set in the other authored order is equally accepted, and verification replays it
        self.document['corrections'] = shrinking + growing
        self.assertEqual(self.run_job('shrunk-first')['corrections'], 8)
        c.verify(self.dir / 'shrunk'); c.verify(self.dir / 'shrunk-first')
        # with only one shrink the finished transcript is over the limit and the growing correction is named
        self.document['corrections'] = growing + shrinking[:1]
        self.failed('TIMED_TEXT_RESOURCE_LIMIT', '$.corrections[0].text', 'over')


class SemanticReplay(Base):
    """Every ordinary hash is refreshed after each change, so only independent replay can notice it."""

    def setUp(self):
        super().setUp(); self.document['captionReview'] = True
        self.run_job(); self.directory = self.dir / 'run'
        self.saved = {p: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}

    def restore(self):
        for path in [p for p in self.directory.iterdir() if p.is_file() and p not in self.saved]: path.unlink()
        for path, data in self.saved.items(): path.write_bytes(data)

    def tamper(self, name, mutate):
        try:
            path = self.directory / name; path.write_bytes(mutate(path.read_bytes())); self.refresh(self.directory)
            self.fault(lambda: c._native_verify(self.directory), 'VERIFICATION_FAILED')
            self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED')
        finally: self.restore()

    def test_every_publication_is_replayed(self):
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'"endMs": 5410', b'"endMs": 5411', 1))
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'"status": "human-corrected"', b'"status": "human-reviewed-unchanged"'))
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'"identityVerified": false', b'"identityVerified": true'))
        self.tamper('reviewed-segments.json', lambda b: b.replace(b'ask not what', b'ask all what', 1))
        self.tamper('reviewed-segments.json', lambda b: json.dumps(json.loads(b)).encode())
        self.tamper('transcript.txt', lambda b: b.replace(b'country', b'county'))
        self.tamper('captions.srt', lambda b: b.replace(b'00:00:05,410', b'00:00:05,411'))
        self.tamper('captions.vtt', lambda b: b.replace(b'Americans', b'Amerikans'))
        self.tamper('corrections.json', lambda b: b.replace(b'"original": "And so my', b'"original": "And so, my'))
        self.tamper('corrections.json', lambda b: b.replace(b'"correctionCount": 2', b'"correctionCount": 3'))
        self.tamper('caption-review.json', lambda b: b.replace(b'"flaggedCueCount": 0', b'"flaggedCueCount": 1'))
        self.assertTrue(c.verify(self.directory)['verified'])

    def test_captured_draft_and_authored_edits_are_bound_to_the_pin_and_each_other(self):
        self.tamper('captured-draft.json', lambda b: b.replace(b'And so my', b'And so, my'))
        self.tamper('captures.json', lambda b: b.replace(BASIS.encode(), b'1' * 64))
        edited = lambda b: json.dumps({**json.loads(b), 'corrections': [{'index': 0, 'text': 'Different words here'}]}).encode()
        self.tamper('authored.json', edited)
        self.tamper('plan.json', lambda b: b.replace(b'"human-corrected"', b'"human-reviewed-unchanged"'))
        self.tamper('authored.json', lambda b: json.dumps({**json.loads(b), 'basisSha256': '2' * 64}).encode())

    def test_result_and_receipt_forgeries(self):
        for key, value in (('accuracyCertified', True), ('identityVerified', True), ('nativeProcesses', 1), ('verified', 1), ('corrections', 3), ('invented', 'claim')):
            self.tamper('result.json', lambda b, k=key, v=value: json.dumps({**json.loads(b), k: v}).encode())
        for mutation in (lambda r: r.update(accuracyCertified=True), lambda r: r['evidence'].pop('captures.json'), lambda r: r['evidence'].update({'native.json': '0' * 64}),
                         lambda r: r['artifacts'].pop(), lambda r: r.update(runtime='whisper.cpp 1.9.5')):
            try:
                receipt = c.read_json(self.directory, 'verification.json'); mutation(receipt); c.atomic_json(self.directory / 'verification.json', receipt)
                self.fault(lambda: c._native_verify(self.directory), 'VERIFICATION_FAILED')
            finally: self.restore()

    def test_membership_is_exact_and_native_evidence_is_a_failure(self):
        for name in ('stray.txt', 'orphan.metadata.json', 'transcribe-launcher.py', 'native.json', 'runtime.json', 'version.stdout'):
            try:
                (self.directory / name).write_text('unexpected'); self.fault(lambda: c._native_verify(self.directory), 'VERIFICATION_FAILED')
            finally: self.restore()
        try:
            (self.directory / 'caption-review.json').unlink(); self.fault(lambda: c._native_verify(self.directory), 'VERIFICATION_FAILED')
        finally: self.restore()
        try:
            (self.directory / 'corrections.json').unlink(); self.fault(lambda: c._native_verify(self.directory), 'VERIFICATION_FAILED')
        finally: self.restore()
        try:
            (self.directory / 'captions.srt').unlink(); (self.directory / 'captions.srt').symlink_to(self.directory / 'captions.vtt')
            self.fault(lambda: c._native_verify(self.directory), 'VERIFICATION_FAILED')
        finally:
            (self.directory / 'captions.srt').unlink(missing_ok=True); self.restore()
        self.assertTrue(c.verify(self.directory)['verified'])

    def test_a_planted_dispatch_directory_is_an_unexpected_member_and_is_never_run(self):
        self.assertFalse((self.directory / '.dispatch').exists(), 'the host route never creates .dispatch')
        marker = self.dir / 'executed.marker'
        planted = self.directory / '.dispatch' / 'transcribe'; planted.mkdir(parents=True)
        (planted / 'replay-x.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("ran")\n')
        try:
            for verifier in (c.verify, c._native_verify):
                fault = self.fault(lambda: verifier(self.directory), 'VERIFICATION_FAILED', '.dispatch')
                self.assertIn('unexpected', fault.message)
            self.refresh(self.directory)  # refreshing every ordinary hash does not legitimise it
            self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED', '.dispatch')
            shutil.rmtree(self.directory / '.dispatch'); (self.directory / '.dispatch').mkdir()
            self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED', '.dispatch')  # even an empty one
            shutil.rmtree(self.directory / '.dispatch'); (self.directory / '.dispatch').symlink_to(self.dir)
            self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED', '.dispatch')
        finally:
            (self.directory / '.dispatch').unlink(missing_ok=True) if (self.directory / '.dispatch').is_symlink() else shutil.rmtree(self.directory / '.dispatch', ignore_errors=True)
        self.assertFalse(marker.exists(), 'verification never executes a planted script')
        self.assertTrue(c.verify(self.directory)['verified'])

    def test_unrefreshed_ordinary_hashes_also_fail_the_public_verifier(self):
        try:
            path = self.directory / 'transcript.txt'; path.write_bytes(path.read_bytes() + b'x\n')
            self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED')
        finally: self.restore()

    def test_caption_review_membership_must_match_the_authored_option(self):
        document = copy.deepcopy(self.document); document['captionReview'] = False
        c.atomic_json(self.directory / 'authored.json', document); self.refresh(self.directory)
        self.fault(lambda: c._native_verify(self.directory), 'VERIFICATION_FAILED')


class Interfaces(Base):
    def cli(self, *arguments):
        if arguments and arguments[0] == 'run':
            arguments = (*arguments, '--backend', 'native')
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'SCHEMAXIS_WHISPERCPP': '/nonexistent/whisper-cli', 'PATH': '/nonexistent'}
        return subprocess.run([sys.executable, '-m', 'schemaxis', *arguments], capture_output=True, text=True, env=environment, cwd=self.dir, timeout=120)

    def test_cli_plan_run_and_verify_without_any_whisper_executable(self):
        document = self.dir / 'document.json'; document.write_text(json.dumps(self.document))
        planned = self.cli('plan', str(document)); self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual(json.loads(planned.stdout)['operation'], 'correct')
        ran = self.cli('run', str(document), '--output-directory', str(self.dir / 'cli-run')); self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertEqual(json.loads(ran.stdout)['runtime'], 'host-only')
        checked = self.cli('verify', str(self.dir / 'cli-run')); self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertTrue(json.loads(checked.stdout)['verified'])
        stale = self.dir / 'stale.json'; stale.write_text(json.dumps({**self.document, 'basisSha256': '3' * 64}))
        failed = self.cli('run', str(stale), '--output-directory', str(self.dir / 'cli-stale')); self.assertNotEqual(failed.returncode, 0)
        self.assertIn('CORRECTIONS_STALE', failed.stdout + failed.stderr)

    def test_workflow_example_hands_the_reviewed_artifact_to_the_pandoc_transcript_path(self):
        from schemaxis import workflow
        document = json.loads((ROOT / 'examples/schemaxis/whispercpp-corrections-workflow.json').read_text())
        planned = workflow.inspect_plan(document)
        self.assertEqual([o['id'] for o in planned['operations']], ['correct', 'report'])
        self.assertEqual(planned['operations'][0]['provisionalPlan']['operation'], 'correct')
        report = planned['operations'][1]['provisionalPlan']
        self.assertEqual((report['status'], report['references']), ('deferred', [{'$artifact': 'correct', 'index': 0}]))

    def test_workflow_runs_the_correction_job_and_publishes_a_text_artifact_at_index_zero(self):
        from schemaxis import workflow
        document = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'correct', 'document': self.document}]}
        result = workflow.execute(document, self.dir / 'workflow')
        job = result['operations'][0] if 'operations' in result else result
        self.assertIn('succeeded', json.dumps(result))
        published = [p for p in (self.dir / 'workflow').rglob('reviewed-segments.json')]
        self.assertEqual(len(published), 1)
        self.assertEqual(timed_text.parse(published[0].read_bytes())['status'], 'human-corrected')
        self.assertIsNotNone(job)

    def test_discovery_and_guidance_cover_the_route(self):
        from schemaxis.studio_guidance import audit
        self.assertTrue(audit('whispercpp')['complete'])
        guidance = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/guidance.json').read_text())
        fields = guidance['routes'][c.VERSION]['fields']
        self.assertEqual({'', '/properties/version', '/properties/draft', '/properties/draft/properties/path', '/properties/basisSha256', '/properties/review',
                          '/properties/review/properties/status', '/properties/review/properties/note', '/properties/corrections', '/properties/corrections/items',
                          '/properties/corrections/items/properties/index', '/properties/corrections/items/properties/text', '/properties/captionReview'}, set(fields))
        self.assertIn('declaration', fields['/properties/review/properties/status']['explanation'] + ' '.join(fields['']['pitfalls']))
        self.assertTrue(all(r['status'] == 'reviewed' for r in fields.values()))


if __name__ == '__main__':
    unittest.main()
