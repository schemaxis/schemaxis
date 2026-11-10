"""Pandoc `transcript` block: planning without file reads, capture faults, exact content and retained binding."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.adaptors.pandoc import adaptor
from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import test_timed_text as source  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LEGACY = {'pandoc-report': 'edc7c8310a5727e6c812f453f4e40b4f375f1a981aa3928edb995a4c433fabb4',
          'pandoc-report-variant': 'a7440b42fa864cd8c59ea30c571a38cc2f8de1bc83cc9bffaf1599c2c4ed2eb2',
          'pandoc-transcript': '4fa1ab417d729793a08fbd9c582131c480bc6e392589e05495c0116112286543',
          'pandoc-multilingual-transcript': '377e30178afbb082794edaf62abe8a919d61e2242b944a506a7034374c7d93f6'}


def report(path, *, sha256=None, extra=None):
    segments = {'path': str(path), **({'sha256': sha256} if sha256 else {})}
    return {'version': adaptor.VERSION, 'operation': 'report', 'title': 'Interview transcript', 'sections': [
        {'heading': 'Transcript', 'content': [{'kind': 'transcript', 'segments': segments, **(extra or {})}]}]}


class Planning(unittest.TestCase):
    def fault(self, document, code, location=None):
        with self.assertRaises(SchemaxisError) as caught: adaptor.plan(document)
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.message)
        if location: self.assertEqual(caught.exception.fault.location, location)
        return caught.exception.fault

    def test_plan_checks_shape_only_and_never_reads_a_file(self):
        document = report('/definitely/not/there/segments.json', sha256='a' * 64)
        with patch('builtins.open', side_effect=AssertionError('planning read a file')), patch('os.open', side_effect=AssertionError('planning opened a file')):
            planned = adaptor.plan(document)
            self.assertEqual(adaptor.query(document), (['report'], {}))
        self.assertEqual(planned['sections'][0]['content'][0], {'kind': 'transcript', 'segments': {'path': '/definitely/not/there/segments.json', 'sha256': 'a' * 64}})
        self.assertEqual(planned['losses'][-1], adaptor.TRANSCRIPT_LOSS)
        self.assertEqual(planned['losses'][:-1], adaptor.LOSSES)

    def test_shipped_example_plans_and_reports_the_machine_draft_loss(self):
        planned = adaptor.plan(json.loads((ROOT/'examples/schemaxis/pandoc-transcript-artifact.json').read_text()))
        self.assertIn('machine-draft', planned['losses'][-1])
        self.assertEqual([b['kind'] for b in planned['sections'][0]['content']], ['paragraph', 'transcript'])

    def test_path_and_pin_shape_are_closed(self):
        at = '$.sections[0].content[0]'
        for path in ('segments.json', '/a/../segments.json', '/a/segments.txt', '/a/segments', '/a/seg\0ments.json'):
            with self.subTest(path): self.fault(report(path), 'INVALID_TRANSCRIPT_SOURCE', at + '.segments.path')
        for pin in ('A' * 64, 'g' * 64):
            with self.subTest(pin): self.fault(report('/a/segments.json', sha256=pin), 'INVALID_SHA256', at + '.segments.sha256')
        for pin in ('a' * 63, 'a' * 65, 7):
            with self.subTest(pin): self.fault(report('/a/segments.json', sha256=pin), 'INVALID_ARGUMENT')
        self.fault(report('/a/segments.json', extra={'timeFormat': 'clock'}), 'INVALID_ARGUMENT')
        self.fault(report('/a/segments.json', extra={'segments': 1}), 'INVALID_ARGUMENT')
        bad = report('/a/segments.json'); bad['sections'][0]['content'][0]['segments']['label'] = 'x'
        self.fault(bad, 'INVALID_ARGUMENT')
        bad = report('/a/segments.json'); del bad['sections'][0]['content'][0]['segments']
        self.fault(bad, 'INVALID_ARGUMENT')
        bad = report('/a/segments.json'); bad['sections'][0]['content'][0]['segments'] = {'sha256': 'a' * 64}
        self.fault(bad, 'INVALID_ARGUMENT')
        bad = report('/a/segments.json'); bad['sections'][0]['content'][0]['segments']['path'] = {'$artifact': 'x', 'index': 0}
        self.fault(bad, 'INVALID_ARGUMENT')

    def test_a_report_holds_at_most_two_transcript_blocks(self):
        document = report('/a/segments.json'); block = document['sections'][0]['content'][0]
        document['sections'][0]['content'] = [block, copy.deepcopy(block)]
        adaptor.plan(document)
        document['sections'][0]['content'].append(copy.deepcopy(block))
        self.fault(document, 'REPORT_RESOURCE_LIMIT', '$.sections')

    def test_legacy_plans_are_byte_identical_to_the_previous_release(self):
        for name, expected in LEGACY.items():
            document = json.loads((ROOT/f'examples/schemaxis/{name}.json').read_text())
            for retained in (False, True):
                planned = adaptor.plan(document, retained=retained)
                self.assertEqual(hashlib.sha256(json.dumps(planned, sort_keys=True).encode()).hexdigest(), expected, name)
                self.assertEqual(planned['losses'], adaptor.LOSSES)
                self.assertNotIn('"kind": "transcript"', json.dumps(planned))
                self.assertNotIn(adaptor.TRANSCRIPT_LOSS, planned['losses'])

    def test_route_accepts_text_handoffs_and_the_schema_offers_the_block(self):
        manifest = json.loads((ROOT/'src/schemaxis/adaptors/pandoc/adaptor.json').read_text())
        self.assertEqual(manifest['routes']['schemaxis.pandoc/1']['acceptedArtifacts'], ['text', 'image'])
        kinds = json.dumps(adaptor.schema())
        self.assertIn('"transcript"', kinds)
        self.assertEqual(registry.resolve(report('/a/segments.json'), legacy=True)[1]['acceptedArtifacts'], ['text', 'image'])


class Workflow(unittest.TestCase):
    def test_whisper_workflow_example_hands_the_segments_artifact_to_the_transcript_path(self):
        from schemaxis import workflow
        document = json.loads((ROOT/'examples/schemaxis/pandoc-whisper-workflow.json').read_text())
        planned = workflow.inspect_plan(document)
        self.assertEqual([o['id'] for o in planned['operations']], ['transcribe', 'report'])
        report_plan = planned['operations'][1]['provisionalPlan']
        self.assertEqual((report_plan['status'], report_plan['references']), ('deferred', [{'$artifact': 'transcribe', 'index': 0}]))
        block = document['operations'][1]['document']['sections'][0]['content'][0]
        self.assertEqual(block['segments']['path'], {'$artifact': 'transcribe', 'index': 0})
        self.assertEqual(planned['operations'][0]['provisionalPlan']['operation'], 'transcribe')

    def test_a_file_artifact_index_is_a_deferred_plan_and_only_the_text_and_image_kinds_are_accepted(self):
        from schemaxis import workflow
        document = json.loads((ROOT/'examples/schemaxis/pandoc-whisper-workflow.json').read_text())
        document['operations'][1]['document']['sections'][0]['content'][0]['segments']['path']['index'] = 2
        # Index 2 is captions.srt, a `file` artifact; the kind check happens when the producer's receipt is known,
        # so planning stays deferred and the route's accepted kinds are exactly text and image.
        self.assertEqual(workflow.inspect_plan(document)['operations'][1]['provisionalPlan']['status'], 'deferred')
        accepted = registry.resolve(document['operations'][1]['document'], legacy=True)[1]['acceptedArtifacts']
        self.assertEqual(accepted, ['text', 'image'])
        self.assertNotIn('file', accepted)


class Capture(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pandoc-timed-'))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.executable = shutil.which('true')
        self.path = self.directory/'segments.json'
        self.path.write_bytes(source.encode(source.document()))

    def run_report(self, document, name='run', **patches):
        with patch.object(adaptor, 'launch', side_effect=AssertionError('native stage launched before capture succeeded')):
            return adaptor.run(document, self.directory/name, executable=self.executable)

    def refused(self, document, code, name='run'):
        with self.assertRaises(SchemaxisError) as caught: self.run_report(document, name)
        fault = caught.exception.fault
        self.assertEqual(fault.code, code, fault.message)
        failed = json.loads((self.directory/name/'result.json').read_text())
        self.assertEqual((failed['status'], failed['verified'], failed['fault']['code']), ('failed', False, code))
        return fault

    def test_missing_source_is_a_distinct_fault_with_recovery(self):
        fault = self.refused(report(self.directory/'absent.json'), 'TRANSCRIPT_SOURCE_MISSING')
        self.assertEqual(fault.location, '$.sections[0].content[0].segments.path')
        self.assertTrue(fault.recovery)

    def test_unusable_sources_are_invalid_not_missing(self):
        (self.directory/'folder.json').mkdir()
        os.symlink(self.path, self.directory/'link.json')
        big = self.directory/'big.json'; big.write_bytes(b' ' * (timed_text.MAX_DOCUMENT_BYTES + 1))
        for name in ('folder.json', 'link.json', 'big.json'):
            with self.subTest(name):
                fault = self.refused(report(self.directory/name), 'TRANSCRIPT_SOURCE_INVALID', name + '-run')
                self.assertTrue(fault.recovery)

    def test_non_transcript_text_and_changed_contracts_are_refused_before_native_work(self):
        cases = {'plain.json': (b'Good morning.\n', 'TIMED_TEXT_INVALID_JSON'), 'array.json': (b'[{"kind":"paragraph","text":"x"}]', 'TIMED_TEXT_INVALID'),
                 'blocks.json': (json.dumps({'kind': 'transcript', 'sections': []}).encode(), 'TIMED_TEXT_UNSUPPORTED_VERSION')}
        reviewed = source.document(); reviewed['review'] = {'status': 'human-reviewed'}
        cases['reviewed.json'] = (source.encode(reviewed), 'TIMED_TEXT_REVIEW_UNSUPPORTED')
        extra = source.document(); extra['title'] = 'x'
        cases['extra.json'] = (source.encode(extra), 'TIMED_TEXT_UNKNOWN_KEY')
        overlap = source.document(); overlap['segments'][1]['startMs'] = 100
        cases['overlap.json'] = (source.encode(overlap), 'TIMED_TEXT_TIMING')
        for name, (data, code) in cases.items():
            with self.subTest(name):
                (self.directory/name).write_bytes(data)
                fault = self.refused(report(self.directory/name), code, name + '-run')
                self.assertTrue(fault.recovery)
        self.assertTrue(fault.location.startswith('$.sections[0].content[0].segments'))

    def test_pin_mismatch_is_refused_and_a_matching_pin_is_bound(self):
        self.refused(report(self.path, sha256='0' * 64), 'TIMED_TEXT_DIGEST_MISMATCH')
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(SchemaxisError) as caught: self.run_report(report(self.path, sha256=digest), 'bound')
        self.assertIn('native stage launched', caught.exception.fault.message)
        captured = json.loads((self.directory/'bound/captures.json').read_text())
        self.assertEqual(captured['transcript-0-0.json'], {'source': str(self.path), 'kind': 'timed-text', 'status': 'machine-draft',
            'sha256': digest, 'bytes': self.path.stat().st_size, 'cues': 2, 'characters': 61})
        self.assertEqual((self.directory/'bound/transcript-0-0.json').read_bytes(), self.path.read_bytes())

    def test_text_the_report_route_cannot_publish_exactly_is_refused_with_the_cue_location(self):
        for text in ('two  spaces', 'non breaking', 'word⁠joiner'):
            changed = source.document(); changed['segments'][1]['text'] = text
            (self.directory/'cue.json').write_bytes(source.encode(changed))
            fault = self.refused(report(self.directory/'cue.json'), 'INVALID_REPORT_TEXT', 'cue-' + hashlib.sha256(text.encode()).hexdigest()[:6])
            self.assertEqual(fault.location, '$.sections[0].content[0].segments.segments[1].text')

    def test_report_budgets_count_transcripts_and_refuse_instead_of_truncating(self):
        many = source.document(); many['segments'] = [{'index': i, 'startMs': i, 'endMs': i + 1, 'text': 'word'} for i in range(300)]
        many['segmentCount'] = 300; many['audio'].update(frames=16000 * 400, durationMs=400000, bytes=12800044)
        (self.directory/'many.json').write_bytes(source.encode(many))
        document = report(self.directory/'many.json'); block = document['sections'][0]['content'][0]
        document['sections'][0]['content'] = [block, copy.deepcopy(block)]
        self.refused(document, 'REPORT_RESOURCE_LIMIT', 'cues')
        wide = source.document(); wide['segments'] = [{'index': i, 'startMs': i, 'endMs': i + 1, 'text': 'x' * 128} for i in range(256)]
        wide['segmentCount'] = 256; wide['audio'].update(frames=16000 * 400, durationMs=400000, bytes=12800044)
        (self.directory/'wide.json').write_bytes(source.encode(wide))
        document = report(self.directory/'wide.json')
        document['sections'][0]['content'] += [{'kind': 'paragraph', 'text': 'y' * 2000}] * 17
        fault = self.refused(document, 'REPORT_RESOURCE_LIMIT', 'characters')
        self.assertIn('65536', fault.message)

    def test_reuse_identity_follows_the_source_bytes(self):
        document = report(self.path)
        first = adaptor.reusableInputs(document)
        self.assertEqual(first, {'transcript-0-0': hashlib.sha256(self.path.read_bytes()).hexdigest()})
        changed = source.document(); changed['segments'][0]['text'] = 'Different words.'
        self.path.write_bytes(source.encode(changed))
        self.assertNotEqual(adaptor.reusableInputs(document), first)
        with self.assertRaises(SchemaxisError) as caught: adaptor.reusableInputs(report(self.directory/'absent.json'))
        self.assertEqual(caught.exception.fault.code, 'TRANSCRIPT_SOURCE_MISSING')


class Content(unittest.TestCase):
    def view(self, **changes):
        value = source.document(); value.update(changes)
        return timed_text.parse(source.encode(value))

    def test_paragraph_and_table_carry_exact_text_times_and_provenance(self):
        view = self.view()
        paragraph, columns, rows = adaptor.transcript_content(view)
        self.assertEqual(columns, ['Start (ms)', 'End (ms)', 'Text'])
        self.assertEqual(rows, [['0', '5410', 'And so, my fellow Americans,'], ['5410', '11000', 'ask not what your country can do.']])
        for fragment in ('Status: machine-draft.', 'has not reviewed it', 'accuracy is not certified', 'Language en; 2 cues; audio duration 11000 ms',
                         view['sha256'], 'a' * 64, 'b' * 64):
            self.assertIn(fragment, paragraph)
        self.assertNotIn('Cue length target', paragraph)
        self.assertNotIn('human', paragraph.replace('a person', ''))

    def test_cue_length_target_is_reported_as_not_enforced(self):
        value = source.document(); value['segmentation'] = {'maxSegmentLength': 20, 'nativeOptions': ['-ml', '20', '-sow'], 'enforced': False,
            'unit': 'code points', 'cueCount': 2, 'cuesOverTarget': 2, 'statement': 'A target.'}
        paragraph = adaptor.transcript_content(timed_text.parse(source.encode(value)))[0]
        self.assertTrue(paragraph.endswith('Cue length target 20 characters, not enforced; 2 cues exceed it.') or 'Cue length target 20 characters, not enforced; 2 cues exceed it.' in paragraph)

    def test_ast_and_expected_model_expand_to_one_paragraph_and_one_table(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name); document = report('/x/segments.json')
            document['sections'][0]['content'].insert(0, {'kind': 'paragraph', 'text': 'Intro.'})
            prepared = adaptor.plan(document)
            (directory/'transcript-0-1.json').write_bytes(source.encode(source.document()))
            tree = adaptor.ast(prepared, [1, 23], directory)
            self.assertEqual([b['t'] for b in tree['blocks']], ['Header', 'Para', 'Para', 'Table'])
            model = adaptor.expected({**prepared, '_directory': directory})
            self.assertEqual([b['kind'] for b in model], ['heading', 'paragraph', 'paragraph', 'table'])
            self.assertEqual(model[3]['rows'][0], ['Start (ms)', 'End (ms)', 'Text'])
            self.assertEqual(model[3]['rows'][2], ['5410', '11000', 'ask not what your country can do.'])
            # The table is the existing writer's table: same AST as an authored table with the same cells.
            literal = adaptor.ast(adaptor.plan({'version': adaptor.VERSION, 'operation': 'report', 'title': 'Interview transcript', 'sections': [
                {'heading': 'Transcript', 'content': [{'kind': 'table', 'columns': model[3]['rows'][0], 'rows': model[3]['rows'][1:]}]}]}), [1, 23], directory)
            self.assertEqual(tree['blocks'][3], literal['blocks'][1])

    def test_tampered_retained_source_cannot_reach_the_published_model(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name); prepared = adaptor.plan(report('/x/segments.json'))
            changed = source.document(); changed['segments'][0]['text'] = 'a < b'
            (directory/'transcript-0-0.json').write_bytes(source.encode(changed))
            with self.assertRaises(SchemaxisError) as caught: adaptor.ast(prepared, [1, 23], directory)
            self.assertEqual(caught.exception.fault.code, 'TIMED_TEXT_CUE_TEXT')


class Retained(unittest.TestCase):
    """`verify` binds the retained captured bytes before any native evidence is trusted."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pandoc-retained-'))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.path = self.directory/'segments.json'; self.path.write_bytes(source.encode(source.document()))
        self.executable = shutil.which('true')
        with patch.object(adaptor, 'launch', side_effect=SchemaxisError(timed_text_fault())):
            with self.assertRaises(SchemaxisError): adaptor.run(report(self.path), self.directory/'run', executable=self.executable)
        self.run_directory = self.directory/'run'
        (self.run_directory/'verification.json').write_text(json.dumps({'executable': self.executable, 'runtime': 'pandoc 3.12.1', 'artifacts': [], 'evidence': {}}))

    def message(self):
        with self.assertRaises(SchemaxisError) as caught: adaptor.verify(self.run_directory, require_result=False)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        return caught.exception.fault.message

    def test_unchanged_capture_passes_the_binding_and_stops_at_native_evidence(self):
        self.assertNotIn('transcript', self.message())

    def test_changed_captured_bytes_are_refused(self):
        changed = source.document(); changed['segments'][0]['text'] = 'Altered words.'
        (self.run_directory/'transcript-0-0.json').write_bytes(source.encode(changed))
        self.assertIn('captured transcript/source binding differs', self.message())

    def test_invalid_captured_bytes_are_refused_as_verification_failures(self):
        (self.run_directory/'transcript-0-0.json').write_bytes(b'{"kind":"paragraph"}')
        self.assertIn('no longer satisfies the timed-text contract', self.message())
        (self.run_directory/'transcript-0-0.json').unlink()
        self.assertIn('select intact bounded regular evidence', self.message())

    def test_a_forged_capture_record_is_refused(self):
        captures = json.loads((self.run_directory/'captures.json').read_text())
        for field, value in (('cues', 1), ('sha256', '0' * 64), ('status', 'human-reviewed'), ('source', '/elsewhere/segments.json'), ('characters', 1)):
            changed = copy.deepcopy(captures); changed['transcript-0-0.json'][field] = value
            (self.run_directory/'captures.json').write_text(json.dumps(changed))
            self.assertIn('captured transcript/source binding differs', self.message())
        dropped = {}
        (self.run_directory/'captures.json').write_text(json.dumps(dropped))
        self.assertIn('binding differs', self.message())
        extra = {**captures, 'transcript-0-9.json': captures['transcript-0-0.json']}
        (self.run_directory/'captures.json').write_text(json.dumps(extra))
        self.assertIn('capture membership differs', self.message())

    def test_a_plan_written_before_reviewed_documents_still_verifies_and_other_texts_do_not(self):
        stored = json.loads((self.run_directory/'plan.json').read_text())
        self.assertEqual(stored['losses'][-1], adaptor.TRANSCRIPT_LOSS)
        legacy = copy.deepcopy(stored); legacy['losses'][-1] = adaptor.LEGACY_TRANSCRIPT_LOSS
        (self.run_directory/'plan.json').write_text(json.dumps(legacy))
        message = self.message()
        self.assertNotIn('effective report plan differs', message); self.assertNotIn('earlier transcript loss wording', message)
        forged = copy.deepcopy(stored); forged['losses'][-1] = 'No transcript caveat.'
        (self.run_directory/'plan.json').write_text(json.dumps(forged))
        self.assertIn('effective report plan differs', self.message())

    def retained(self, losses):
        prepared = adaptor.plan(json.loads((self.run_directory/'authored.json').read_text()), retained=True)
        stored = {**prepared, 'losses': losses}
        view = adaptor.transcript_view((self.run_directory/'transcript-0-0.json').read_bytes(), '$')
        return prepared, stored, view

    def test_a_machine_run_with_the_earlier_loss_keeps_its_stored_losses_in_the_report_summary(self):
        prepared, stored, view = self.retained([*adaptor.LOSSES, adaptor.LEGACY_TRANSCRIPT_LOSS])
        self.assertEqual(view['source'], timed_text.SOURCE_VERSION)
        accepted = adaptor.retained_plan(stored, prepared, [view])
        self.assertEqual(accepted['losses'], stored['losses']); self.assertEqual({k: v for k, v in accepted.items() if k != 'losses'}, {k: v for k, v in prepared.items() if k != 'losses'})
        self.assertIs(adaptor.retained_plan(prepared, prepared, [view]), prepared)
        # the very summary `verify` compares against report-summary.json, from the accepted plan, carries the earlier sentence
        for name in ('report.html', 'report.docx'): (self.run_directory/name).write_bytes(b'x')  # the three readers below are stubbed: this checks only the summary
        (self.run_directory/'reopened.json').write_text('{}')
        with patch('schemaxis.adaptors.pandoc.inspection.html_report'), patch('schemaxis.adaptors.pandoc.inspection.docx_report'), patch('schemaxis.adaptors.pandoc.inspection.ast_report'):
            earlier = adaptor.inspect(self.run_directory, accepted); current = adaptor.inspect(self.run_directory, prepared)
        self.assertEqual(earlier['losses'], stored['losses']); self.assertEqual(current['losses'], prepared['losses'])
        self.assertEqual({k: v for k, v in earlier.items() if k != 'losses'}, {k: v for k, v in current.items() if k != 'losses'})
        self.assertEqual((earlier['transcripts'], earlier['blocks'], earlier['tables']), (1, 3, 1))  # heading, provenance paragraph, table

    def test_the_earlier_loss_is_never_accepted_for_a_reviewed_transcript_or_without_a_transcript(self):
        prepared, stored, machine = self.retained([*adaptor.LOSSES, adaptor.LEGACY_TRANSCRIPT_LOSS])
        reviewed = copy.deepcopy(machine); reviewed['source'] = timed_text.REVIEWED_VERSION; reviewed['status'] = 'human-corrected'
        for views in ([reviewed], [machine, reviewed], [reviewed, machine], []):
            with self.subTest(sources=[v['source'] for v in views]), self.assertRaises(SchemaxisError) as caught: adaptor.retained_plan(stored, prepared, views)
            fault = caught.exception.fault
            self.assertEqual((fault.code, fault.location), ('VERIFICATION_FAILED', 'plan.json')); self.assertIn('machine draft', fault.message)
        forged = {**prepared, 'losses': [*adaptor.LOSSES, 'No transcript caveat.']}
        with self.assertRaises(SchemaxisError) as caught: adaptor.retained_plan(forged, prepared, [machine])
        self.assertIn('effective report plan differs', caught.exception.fault.message)

    def test_a_pinned_report_rechecks_the_pin_against_retained_bytes(self):
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        authored = report(self.path, sha256='0' * 64)
        (self.run_directory/'authored.json').write_text(json.dumps(authored)); (self.run_directory/'plan.json').write_text(json.dumps(adaptor.plan(authored)))
        self.assertIn('pin', self.message())
        self.assertNotEqual(digest, '0' * 64)


class Reviewed(unittest.TestCase):
    """A document from the host-only corrections route is published with its author-declared status."""

    def setUp(self):
        from schemaxis.adaptors.whispercpp import corrections
        self.directory = Path(tempfile.mkdtemp(prefix='pandoc-reviewed-'))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.draft = self.directory/'segments.json'; self.draft.write_bytes(source.encode(source.document()))
        self.corrections = corrections
        self.digest = hashlib.sha256(self.draft.read_bytes()).hexdigest()

    def reviewed(self, status='human-corrected', edits=({'index': 1, 'text': 'ask not what your country can do for you.'},), note='Checked against the speech text.'):
        authored = {'version': self.corrections.VERSION, 'draft': {'path': str(self.draft)}, 'basisSha256': self.digest, 'review': {'status': status, 'note': note}}
        if edits: authored['corrections'] = list(edits)
        outputs, _, _ = self.corrections.derive(self.corrections.plan(authored), self.draft.read_bytes())
        path = self.directory/'reviewed-segments.json'; path.write_bytes(outputs['reviewed-segments.json'])
        return path

    def test_corrected_paragraph_states_the_declared_status_basis_and_limits(self):
        view = adaptor.transcript_view(self.reviewed().read_bytes(), '$')
        paragraph, columns, rows = adaptor.transcript_content(view)
        self.assertEqual(rows, [['0', '5410', 'And so, my fellow Americans,'], ['5410', '11000', 'ask not what your country can do for you.']])
        self.assertEqual(columns, adaptor.TRANSCRIPT_COLUMNS)
        for fragment in ('Status: human-corrected, declared by the author of the corrections.', f'machine draft SHA-256 {self.digest}', '1 cue replaced by authored text (cue indexes 1)',
                         'Review note (author\'s words): "Checked against the speech text."', 'not verified or certified', 'Language en; 2 cues; audio duration 11000 ms',
                         view['sha256'], 'a' * 64, 'b' * 64):
            self.assertIn(fragment, paragraph)
        self.assertNotIn('a person has not reviewed it', paragraph)

    def test_unchanged_paragraph_says_no_cue_changed_and_keeps_the_same_table(self):
        view = adaptor.transcript_view(self.reviewed('human-reviewed-unchanged', ()).read_bytes(), '$')
        paragraph, _, rows = adaptor.transcript_content(view)
        self.assertIn('Status: human-reviewed-unchanged, declared by the author', paragraph); self.assertIn('no cue text changed', paragraph)
        self.assertEqual(rows, timed_text.rows(timed_text.parse(self.draft.read_bytes())))

    def test_machine_draft_paragraph_is_unchanged_by_the_reviewed_contract(self):
        paragraph = adaptor.transcript_content(adaptor.transcript_view(self.draft.read_bytes(), '$'))[0]
        self.assertTrue(paragraph.startswith('Status: machine-draft. This transcript is automatic speech recognition output from schemaxis.whispercpp.segments/1; a person has not reviewed it and its accuracy is not certified. Language en; 2 cues;'))

    def test_run_captures_a_reviewed_document_and_binds_its_status(self):
        path = self.reviewed()
        executable = shutil.which('true')
        with patch.object(adaptor, 'launch', side_effect=SchemaxisError(timed_text_fault())):
            with self.assertRaises(SchemaxisError): adaptor.run(report(path, sha256=hashlib.sha256(path.read_bytes()).hexdigest()), self.directory/'run', executable=executable)
        captured = json.loads((self.directory/'run/captures.json').read_text())['transcript-0-0.json']
        self.assertEqual((captured['status'], captured['kind'], captured['cues']), ('human-corrected', 'timed-text', 2))
        self.assertEqual((self.directory/'run/transcript-0-0.json').read_bytes(), path.read_bytes())

    def test_reviewed_documents_that_break_the_contract_are_refused_at_capture(self):
        path = self.reviewed(); good = json.loads(path.read_text())
        for label, mutate, code in (('identity', lambda d: d['review'].update(identityVerified=True), 'TIMED_TEXT_REVIEW_UNSUPPORTED'),
                                    ('status', lambda d: d['review'].update(status='verified'), 'TIMED_TEXT_REVIEW_UNSUPPORTED'),
                                    ('count', lambda d: d['review'].update(correctionCount=0), 'TIMED_TEXT_INVALID'),
                                    ('extra', lambda d: d['review'].update(reviewer='x'), 'TIMED_TEXT_REVIEW_UNSUPPORTED'),
                                    ('timing', lambda d: d['segments'][1].update(startMs=100), 'TIMED_TEXT_TIMING')):
            changed = copy.deepcopy(good); mutate(changed); target = self.directory/(label + '.json'); target.write_bytes(source.encode(changed))
            with patch.object(adaptor, 'launch', side_effect=AssertionError('native stage launched')):
                with self.assertRaises(SchemaxisError) as caught: adaptor.run(report(target), self.directory/('run-' + label), executable=shutil.which('true'))
            self.assertEqual(caught.exception.fault.code, code, label)

    def test_a_note_the_corrections_route_refuses_never_reaches_a_report(self):
        for note in ('word\u2060joiner here', 'no\u00a0break', 'ideographic\u3000space', 'tab\there', 'zero\u200bwidth'):
            with self.subTest(note), self.assertRaises(SchemaxisError) as caught: self.reviewed(note=note)
            self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('CORRECTIONS_NOTE_INVALID', '$.review.note'))

    def test_the_report_route_checks_the_note_at_the_note_location_even_if_the_contract_accepted_it(self):
        for note in ('word\u2060joiner here', 'no\u00a0break'):
            with self.subTest(note):
                with patch.object(timed_text, 'note_problem', return_value=None):
                    path = self.reviewed(note=note)
                    with self.assertRaises(SchemaxisError) as caught: adaptor.transcript_view(path.read_bytes(), '$.sections[0].content[1].segments')
                self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('INVALID_REPORT_TEXT', '$.sections[0].content[1].segments.review.note'))
        # a note both contracts accept is published unchanged, and legitimate Unicode in the note and in a cue stays accepted
        view = adaptor.transcript_view(self.reviewed(note='Vérifié contre le texte; 你好。').read_bytes(), '$')
        self.assertIn('"Vérifié contre le texte; 你好。"', adaptor.transcript_content(view)[0])

    def test_a_reviewed_run_cannot_carry_the_earlier_machine_draft_loss(self):
        path = self.reviewed(); executable = shutil.which('true')
        with patch.object(adaptor, 'launch', side_effect=SchemaxisError(timed_text_fault())):
            with self.assertRaises(SchemaxisError): adaptor.run(report(path, sha256=hashlib.sha256(path.read_bytes()).hexdigest()), self.directory/'run', executable=executable)
        run = self.directory/'run'
        (run/'verification.json').write_text(json.dumps({'executable': executable, 'runtime': 'pandoc 3.12.1', 'artifacts': [], 'evidence': {}}))
        stored = json.loads((run/'plan.json').read_text()); stored['losses'][-1] = adaptor.LEGACY_TRANSCRIPT_LOSS
        (run/'plan.json').write_text(json.dumps(stored))
        with self.assertRaises(SchemaxisError) as caught: adaptor.verify(run, require_result=False)
        fault = caught.exception.fault
        self.assertEqual((fault.code, fault.location), ('VERIFICATION_FAILED', 'plan.json')); self.assertIn('machine draft', fault.message)

    def test_new_plans_carry_the_reviewed_loss_and_retained_plans_keep_the_earlier_text(self):
        document = report('/x/segments.json')
        current = adaptor.plan(document); earlier = {**current, 'losses': [*current['losses'][:-1], adaptor.LEGACY_TRANSCRIPT_LOSS]}
        self.assertEqual(current['losses'][-1], adaptor.TRANSCRIPT_LOSS); self.assertTrue(adaptor.same_plan(earlier, current)); self.assertFalse(adaptor.same_plan({**current, 'losses': [*current['losses'][:-1], 'other']}, current))
        self.assertNotEqual(adaptor.TRANSCRIPT_LOSS, adaptor.LEGACY_TRANSCRIPT_LOSS)
        self.assertIn('machine-draft', adaptor.LEGACY_TRANSCRIPT_LOSS); self.assertIn('human-corrected', adaptor.TRANSCRIPT_LOSS)
        self.assertIn('declaration', adaptor.TRANSCRIPT_LOSS)
        plain = adaptor.plan({'version': adaptor.VERSION, 'operation': 'report', 'title': 'T', 'sections': [{'heading': 'H', 'content': [{'kind': 'paragraph', 'text': 'x'}]}]})
        self.assertEqual(plain['losses'], adaptor.LOSSES)


def timed_text_fault():
    from schemaxis.core.faults import Fault
    return Fault('NATIVE_EXECUTION_FAILED', 'native stage deliberately not run in a host test', 'version', 'pipeline')


if __name__ == '__main__':
    unittest.main()
