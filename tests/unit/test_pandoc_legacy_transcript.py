"""Pandoc `verify` of a genuine earlier machine-draft report whose provenance paragraph wrote "1 cues".

The earlier grammar is recognised only at verification, only for a one-cue machine draft without timeFormat or segmentation, only beside the
earlier transcript loss wording, and only when the stored AST is exactly that earlier text; every other difference still fails the AST check.
Each synthetic case rewrites the retained AST the way a forger who recomputes the ordinary hashes would.
"""
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

from schemaxis.adaptors.pandoc import adaptor
from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import test_pandoc_timecode as timecode  # noqa: E402
import test_timed_text as source  # noqa: E402

# A genuine report written before the grammar changed, kept outside the repository; the genuine case is skipped when it is not named.
GENUINE = os.environ.get('SCHEMAXIS_GENUINE_PANDOC_REPORT')
ONE_CUE = [(0, 11000, 'And so my fellow Americans, ask what you can do for your country.')]
TWO_CUES = [(0, 5410, 'And so, my fellow Americans,'), (5410, 11000, 'ask not what your country can do.')]
AST_FAULT = 'trusted AST differs from authored report'


def EARLIER(text):
    assert 'Language en; 1 cue;' in text, text
    return text.replace('Language en; 1 cue;', 'Language en; 1 cues;')


def paragraphs(tree):
    return [b for b in tree['blocks'] if b['t'] == 'Para']


def text_of(block):
    return ''.join(' ' if i['t'] == 'Space' else i['c'] for i in block['c'])


class Earlier(unittest.TestCase):
    """A retained report directory with only host-side evidence; `verify` reaches the native checks exactly when the AST check passes."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pandoc-legacy-')); self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.run_directory = self.directory / 'run'

    def make(self, *cue_sets, fmt=None, mutate=None):
        blocks = []
        for n, cues in enumerate(cue_sets):
            value = timecode.long_document(cues)
            if mutate: mutate(value)
            path = self.directory / f'segments-{n}.json'; path.write_bytes(source.encode(value))
            blocks.append(timecode.block(path, fmt=fmt))
        document = timecode.report(*blocks)
        with patch.object(adaptor, 'launch', side_effect=SchemaxisError(timecode.native_fault())):
            with self.assertRaises(SchemaxisError): adaptor.run(document, self.run_directory, executable=shutil.which('true'))
        (self.run_directory / 'verification.json').write_text(json.dumps({'executable': shutil.which('true'), 'runtime': 'pandoc 3.12.1', 'artifacts': [], 'evidence': {}}))
        (self.run_directory / 'api.json').write_text(json.dumps({'pandoc-api-version': [1, 23]}))
        prepared = adaptor.plan(document, retained=True)
        (self.run_directory / 'report-input.json').write_text(json.dumps(adaptor.ast(prepared, [1, 23], self.run_directory)))
        return document

    def tree(self): return json.loads((self.run_directory / 'report-input.json').read_text())

    def edit_paragraph(self, index, change):
        """Rewrite one provenance paragraph's text in the retained AST with the writer's own tokenisation."""
        tree = self.tree(); found = paragraphs(tree)[index]; found['c'] = adaptor.inlines(change(text_of(found)))
        (self.run_directory / 'report-input.json').write_text(json.dumps(tree))

    def earlier_wording(self):
        plan = json.loads((self.run_directory / 'plan.json').read_text()); self.assertEqual(plan['losses'][-1], adaptor.TRANSCRIPT_LOSS)
        plan['losses'][-1] = adaptor.LEGACY_TRANSCRIPT_LOSS; (self.run_directory / 'plan.json').write_text(json.dumps(plan))

    def message(self):
        with self.assertRaises(SchemaxisError) as caught: adaptor.verify(self.run_directory, require_result=False)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        return caught.exception.fault.message

    def accepted(self):
        """True when verify gets past the AST comparison (and then stops, as expected, at the absent native stages)."""
        return AST_FAULT not in self.message()

    def test_the_exact_earlier_grammar_of_a_one_cue_machine_draft_passes_the_ast_check(self):
        self.make(ONE_CUE); self.earlier_wording()
        self.assertTrue(self.accepted(), 'a rewritten run with the earlier loss wording and the current grammar was always accepted')
        self.edit_paragraph(0, EARLIER)
        self.assertTrue(self.accepted())

    def test_the_current_grammar_of_a_current_report_is_unchanged(self):
        document = self.make(ONE_CUE); prepared = adaptor.plan(document, retained=True)
        self.assertIn('Language en; 1 cue;', text_of(paragraphs(self.tree())[0]))
        self.assertTrue(self.accepted())
        views = [adaptor.retained_transcript(self.run_directory, 0, 0)]
        self.assertIs(adaptor.earlier_cue_prepared(prepared, 'current', views, self.tree(), [1, 23], self.run_directory), prepared)
        self.assertNotIn('_earlierCues', adaptor.earlier_cue_prepared(prepared, 'earlier', views, self.tree(), [1, 23], self.run_directory))

    def test_planning_and_the_published_text_never_use_the_earlier_grammar(self):
        view = adaptor.transcript_view(source.encode(timecode.long_document(ONE_CUE)), '$')
        self.assertIn('Language en; 1 cue;', adaptor.transcript_content(view)[0])
        self.assertIn('Language en; 1 cues;', adaptor.transcript_content(view, None, True)[0])
        self.assertNotIn('legacy', json.dumps(adaptor.plan(timecode.report(timecode.block())), default=str).lower())

    def test_each_changed_fact_is_refused_even_in_the_earlier_grammar(self):
        view = adaptor.transcript_view(source.encode(timecode.long_document(ONE_CUE)), '$'); fields = ('SHA-256 of the segments file ' + view['sha256'], 'audio ' + view['audioSha256'])
        changes = {'two cues claimed': lambda t: t.replace('1 cues;', '2 cues;'), 'zero cues claimed': lambda t: t.replace('1 cues;', '0 cues;'),
                   'status changed': lambda t: t.replace('Status: machine-draft', 'Status: human-corrected'),
                   'review sentence removed': lambda t: t.replace('a person has not reviewed it and its accuracy is not certified', 'its accuracy is certified'),
                   'language changed': lambda t: t.replace('Language en', 'Language fr'),
                   'duration changed': lambda t: t.replace('11000 ms', '12000 ms'),
                   'source digest changed': lambda t: t.replace(fields[0], 'SHA-256 of the segments file ' + '0' * 64),
                   'audio digest changed': lambda t: t.replace(fields[1], 'audio ' + '1' * 64),
                   'provenance field added': lambda t: t + ' Reviewed by someone.',
                   'unit sentence changed': lambda t: t.replace('elapsed milliseconds', 'elapsed seconds'),
                   'timecode unit claimed': lambda t: t.replace('times are elapsed milliseconds from the start of the recording', 'times are elapsed time from the start of the recording written as HH:MM:SS.mmm (hours, minutes, seconds, milliseconds)')}
        for label, change in changes.items():
            with self.subTest(label):
                shutil.rmtree(self.run_directory, ignore_errors=True); self.make(ONE_CUE); self.earlier_wording()
                self.edit_paragraph(0, lambda t: change(EARLIER(t)))
                self.assertIn(AST_FAULT, self.message())

    def test_a_changed_table_or_heading_is_refused_beside_the_earlier_paragraph(self):
        self.make(ONE_CUE); self.earlier_wording(); self.edit_paragraph(0, EARLIER)
        self.assertTrue(self.accepted()); good = self.tree()
        for label, change in (('cue text', lambda v: v['blocks'][2]['c'][4][0][3][0][1][2][4][0]['c'].__setitem__(0, {'t': 'Str', 'c': 'changed'})),
                              ('heading', lambda v: v['blocks'][0]['c'][2].__setitem__(0, {'t': 'Str', 'c': 'Changed'})),
                              ('title', lambda v: v['meta']['title']['c'].__setitem__(0, {'t': 'Str', 'c': 'Changed'}))):
            with self.subTest(label):
                value = copy.deepcopy(good); change(value); (self.run_directory / 'report-input.json').write_text(json.dumps(value))
                self.assertIn(AST_FAULT, self.message())

    def test_the_earlier_grammar_needs_the_earlier_loss_wording_and_the_current_wording_refuses_it(self):
        self.make(ONE_CUE); self.edit_paragraph(0, EARLIER)
        self.assertIn(AST_FAULT, self.message())

    def test_other_sources_cannot_use_the_earlier_grammar(self):
        def segmentation(value): value['segmentation'] = {'maxSegmentLength': 20, 'nativeOptions': ['-ml', '20', '-sow'], 'enforced': False, 'unit': 'code points',
                                                       'cueCount': 1, 'cuesOverTarget': 1, 'statement': 'A target, not a guarantee.'}
        view = adaptor.transcript_view(source.encode(timecode.long_document(ONE_CUE)), '$'); block = timecode.block()
        self.assertTrue(adaptor.legacy_cue_grammar(block, view))
        with_target = adaptor.transcript_view(source.encode(self.with_segmentation(segmentation)), '$')
        reviewed = {**view, 'source': timed_text.REVIEWED2_VERSION}; first = {**view, 'source': 'schemaxis.timedtext.reviewed/1'}
        two = adaptor.transcript_view(source.encode(timecode.long_document(TWO_CUES)), '$')
        for label, candidate, item in (('segmentation', with_target, block), ('reviewed/2', reviewed, block), ('reviewed/1', first, block), ('two cues', two, block),
                                       ('timecode', view, timecode.block(fmt='timecode')), ('explicit milliseconds', view, timecode.block(fmt='milliseconds'))):
            with self.subTest(label): self.assertFalse(adaptor.legacy_cue_grammar(item, candidate))
        self.make(ONE_CUE, mutate=segmentation); self.earlier_wording()
        self.edit_paragraph(0, EARLIER)
        self.assertIn(AST_FAULT, self.message())

    def with_segmentation(self, mutate):
        value = timecode.long_document(ONE_CUE); mutate(value); return value

    def test_a_two_cue_draft_has_no_earlier_variant(self):
        self.make(TWO_CUES); self.earlier_wording(); self.assertTrue(self.accepted())
        self.edit_paragraph(0, lambda t: t.replace('Language en; 2 cues;', 'Language en; 2 cue;')); self.assertIn(AST_FAULT, self.message())

    def test_a_mixed_two_transcript_report_changes_only_its_one_cue_draft_and_all_of_them(self):
        self.make(ONE_CUE, TWO_CUES); self.earlier_wording(); earlier = EARLIER
        self.edit_paragraph(0, earlier); self.assertTrue(self.accepted())
        self.edit_paragraph(1, lambda t: t.replace('Language en; 2 cues;', 'Language en; 2 cue;')); self.assertIn(AST_FAULT, self.message())
        shutil.rmtree(self.run_directory, ignore_errors=True); self.make(ONE_CUE, ONE_CUE); self.earlier_wording()
        self.edit_paragraph(0, earlier); self.assertIn(AST_FAULT, self.message())
        self.edit_paragraph(1, earlier); self.assertTrue(self.accepted())

    def test_an_absent_time_format_report_is_unchanged_in_every_fingerprint(self):
        with tempfile.TemporaryDirectory() as scratch:
            self.assertEqual(timecode.fingerprint(adaptor, Path(scratch)), timecode.BEFORE)


@unittest.skipUnless(GENUINE and Path(GENUINE).is_dir(), 'set SCHEMAXIS_GENUINE_PANDOC_REPORT to a genuine earlier machine-draft report directory')
class Genuine(unittest.TestCase):
    def snapshot(self):
        return {str(p.relative_to(GENUINE)): (p.lstat().st_mtime_ns, p.lstat().st_size, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
                for p in sorted(Path(GENUINE).rglob('*'))}

    def test_the_genuine_report_verifies_and_not_one_byte_or_mtime_changes(self):
        before = self.snapshot(); result = adaptor.verify(GENUINE)
        self.assertTrue(result['verified']); self.assertEqual(result['transcripts'], 1)
        self.assertEqual(self.snapshot(), before)
        self.assertIn('Language en; 1 cues;', text_of(paragraphs(json.loads((Path(GENUINE) / 'report-input.json').read_text()))[0]))


if __name__ == '__main__':
    unittest.main()
