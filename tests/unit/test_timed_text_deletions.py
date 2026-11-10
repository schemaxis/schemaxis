"""Shared timed-text reader: the separately versioned reviewed/2 contract with explicit cue deletion.

reviewed/1 and the machine draft stay closed and refuse an empty cue list. reviewed/2 alone accepts an empty cue list, and only
when its recorded deletions account for every cue of a nonempty pinned draft.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import test_timed_text as base  # noqa: E402

POLICY = {'timing': 'integral milliseconds', 'text': 'UTF-8 plain text'}


def reviewed2(deleted=(), corrected=(), source=3, status=None, note='Checked against the published text.'):
    """A reviewed/2 document over a `source`-cue pinned draft; cues keep their source order and are renumbered from zero."""
    draft = base.document()
    value = copy.deepcopy(draft)
    cues = [{'startMs': i * 1000, 'endMs': i * 1000 + 900, 'text': f'Source cue {i}'} for i in range(source)]
    retained = [i for i in range(source) if i not in deleted]
    value['version'] = timed_text.REVIEWED2_VERSION
    value['segments'] = [{'index': n, **cues[i], 'text': cues[i]['text'] + (' fixed' if i in corrected else '')} for n, i in enumerate(retained)]
    value['segmentCount'] = len(retained)
    value['review'] = {
        'status': status or ('human-corrected' if deleted or corrected else 'human-reviewed-unchanged'), 'accuracyCertified': False, 'identityVerified': False,
        'statement': 'A declaration by the author; not verified.', 'note': note,
        'basis': {'version': timed_text.SOURCE_VERSION, 'sha256': hashlib.sha256(base.encode(draft)).hexdigest(), 'bytes': 1234, 'cueCount': source},
        'correctionCount': len(corrected), 'correctedIndices': list(corrected), 'deletionCount': len(deleted), 'deletedSourceIndices': sorted(deleted),
        'retainedSourceIndices': retained, 'policy': dict(POLICY)}
    return value


class Reviewed2(unittest.TestCase):
    def refused(self, value, code, fragment=None):
        with self.assertRaises(SchemaxisError) as caught: timed_text.validate(value)
        fault = caught.exception.fault
        self.assertEqual(fault.code, code, fault.message)
        self.assertTrue(fault.recovery)
        if fragment: self.assertIn(fragment, fault.location)
        return fault

    def test_partial_deletion_normalises_with_the_source_mapping(self):
        view = timed_text.validate(reviewed2(deleted=(1,), corrected=(2,)))
        self.assertEqual((view['version'], view['source'], view['status']), ('schemaxis.timedtext/1', 'schemaxis.timedtext.reviewed/2', 'human-corrected'))
        self.assertEqual([c['text'] for c in view['cues']], ['Source cue 0', 'Source cue 2 fixed'])
        review = view['review']
        self.assertEqual((review['sourceCueCount'], review['deletionCount'], review['deletedSourceIndices'], review['retainedSourceIndices'], review['correctedIndices']),
                         (3, 1, [1], [0, 2], [2]))
        self.assertIs(review['identityVerified'], False); self.assertIs(review['accuracyCertified'], False)

    def test_unchanged_and_replacement_only_documents_need_no_deletions(self):
        self.assertEqual(timed_text.validate(reviewed2())['status'], 'human-reviewed-unchanged')
        self.assertEqual(timed_text.validate(reviewed2(corrected=(0,)))['review']['deletionCount'], 0)

    def test_every_cue_deleted_is_the_only_accepted_empty_state(self):
        view = timed_text.validate(reviewed2(deleted=(0, 1, 2)))
        self.assertEqual(view['cues'], [])
        self.assertEqual((view['status'], view['review']['retainedSourceIndices'], view['review']['deletedSourceIndices']), ('human-corrected', [], [0, 1, 2]))
        self.assertEqual(timed_text.rows(view), [])
        self.assertEqual((timed_text.plain_text([]), timed_text.srt_text([]), timed_text.vtt_text([])), ('', '', 'WEBVTT\n\n'))
        single = timed_text.validate(reviewed2(deleted=(0,), source=1))
        self.assertEqual(single['cues'], [])

    def test_an_empty_cue_list_is_refused_unless_every_source_cue_is_recorded_as_deleted(self):
        for label, change in (
                ('no deletions recorded', lambda d: d['review'].update(deletionCount=0, deletedSourceIndices=[], retainedSourceIndices=[], status='human-reviewed-unchanged')),
                ('a source cue neither retained nor deleted', lambda d: d['review'].update(deletionCount=2, deletedSourceIndices=[0, 1])),
                ('the pinned draft had no cues', lambda d: d['review']['basis'].update(cueCount=0))):
            value = reviewed2(deleted=(0, 1, 2)); change(value)
            with self.subTest(label): self.refused(value, 'TIMED_TEXT_INVALID')
        # The machine draft and reviewed/1 never accept an empty cue list, whatever else they hold.
        machine = base.document(); machine['segments'] = []; machine['segmentCount'] = 0
        self.refused(machine, 'TIMED_TEXT_INVALID', '.segments')
        first = base.reviewed_document(); first['segments'] = []; first['segmentCount'] = 0; first['review'].update(correctionCount=0, correctedIndices=[], status='human-reviewed-unchanged')
        self.refused(first, 'TIMED_TEXT_INVALID', '.segments')

    def test_deleted_retained_and_corrected_indices_must_agree_with_the_cues_and_the_basis(self):
        def broken(change, fragment=None, code='TIMED_TEXT_INVALID', **kw):
            value = reviewed2(**kw); change(value); return self.refused(value, code, fragment)
        broken(lambda d: d['review'].update(deletedSourceIndices=[2]), '.deletedSourceIndices', deleted=(1,))
        broken(lambda d: d['review'].update(deletionCount=2), '.deletionCount', deleted=(1,))
        broken(lambda d: d['review'].update(retainedSourceIndices=[0, 1]), '.deletedSourceIndices', deleted=(1,))   # overlaps the deletion
        broken(lambda d: d['review'].update(retainedSourceIndices=[2, 0]), '.retainedSourceIndices', deleted=(1,))   # not ascending
        broken(lambda d: d['review'].update(retainedSourceIndices=[0]), '.retainedSourceIndices', deleted=(1,))      # one published cue unmapped
        broken(lambda d: d['review'].update(deletedSourceIndices=[1, 1], deletionCount=2), '.deletedSourceIndices', deleted=(1,))
        broken(lambda d: d['review'].update(deletedSourceIndices=[1, 3], deletionCount=2), '.deletedSourceIndices', deleted=(1,))   # outside the draft
        broken(lambda d: d['review'].update(correctedIndices=[1], correctionCount=1), '.correctedIndices', deleted=(1,))   # a deleted cue is not replaced
        broken(lambda d: d['review'].update(correctionCount=2), '.correctionCount', corrected=(0,))
        broken(lambda d: d['review'].update(status='human-reviewed-unchanged'), '.status', deleted=(1,))
        broken(lambda d: d['review'].update(status='human-corrected'), '.status')
        broken(lambda d: d['review']['basis'].update(cueCount=2), '.retainedSourceIndices', deleted=(1,))
        broken(lambda d: d['review']['basis'].update(cueCount=True), '.basis.cueCount')
        broken(lambda d: d['review']['basis'].update(cueCount=timed_text.MAX_CUES + 1), '.basis.cueCount')
        broken(lambda d: d['segments'][1].update(index=2), '.index', deleted=(1,))   # published indices are contiguous, not source indices
        broken(lambda d: d.update(segmentCount=3), '.segmentCount', deleted=(1,))

    def test_review_object_is_closed_and_the_claims_are_fixed(self):
        broken = lambda change, code, **kw: (lambda v: (change(v), self.refused(v, code)))(reviewed2(**kw))
        broken(lambda d: d['review'].update(reviewer='x'), 'TIMED_TEXT_REVIEW_UNSUPPORTED', deleted=(1,))
        broken(lambda d: d['review'].pop('deletedSourceIndices'), 'TIMED_TEXT_INVALID', deleted=(1,))
        broken(lambda d: d['review'].update(identityVerified=True), 'TIMED_TEXT_REVIEW_UNSUPPORTED', deleted=(1,))
        broken(lambda d: d['review'].update(accuracyCertified=True), 'TIMED_TEXT_REVIEW_UNSUPPORTED', deleted=(1,))
        broken(lambda d: d['review'].update(status='verified'), 'TIMED_TEXT_REVIEW_UNSUPPORTED', deleted=(1,))
        broken(lambda d: d['review']['basis'].update(version='schemaxis.timedtext.reviewed/1'), 'TIMED_TEXT_INVALID', deleted=(1,))
        broken(lambda d: d['review']['basis'].pop('cueCount'), 'TIMED_TEXT_INVALID', deleted=(1,))
        broken(lambda d: d['review'].update(note='two  spaces'), 'TIMED_TEXT_INVALID', deleted=(1,))
        broken(lambda d: d.update(extra=1), 'TIMED_TEXT_UNKNOWN_KEY', deleted=(1,))

    def test_versions_never_borrow_each_others_review_shape(self):
        # reviewed/1 members on reviewed/2 and reviewed/2 members on reviewed/1 or the machine draft are all refused.
        two = reviewed2(deleted=(1,)); two['review'].pop('deletionCount'); self.refused(two, 'TIMED_TEXT_INVALID')
        first = base.reviewed_document(); first['review'].update(deletionCount=0, deletedSourceIndices=[], retainedSourceIndices=[0, 1])
        self.refused(first, 'TIMED_TEXT_REVIEW_UNSUPPORTED')
        first = base.reviewed_document(); first['review']['basis']['cueCount'] = 2
        self.refused(first, 'TIMED_TEXT_UNKNOWN_KEY')
        relabelled = reviewed2(); relabelled['version'] = timed_text.REVIEWED_VERSION
        self.refused(relabelled, 'TIMED_TEXT_REVIEW_UNSUPPORTED')
        machine = reviewed2(); machine['version'] = timed_text.SOURCE_VERSION
        self.refused(machine, 'TIMED_TEXT_REVIEW_UNSUPPORTED')
        self.refused({**reviewed2(), 'version': 'schemaxis.timedtext.reviewed/4'}, 'TIMED_TEXT_UNSUPPORTED_VERSION')
        # reviewed/1 documents still normalise exactly as before, with no deletion members in the view.
        view = timed_text.validate(base.reviewed_document())
        self.assertEqual(view['source'], timed_text.REVIEWED_VERSION); self.assertNotIn('deletionCount', view['review'])

    def test_segmentation_member_is_recounted_on_the_retained_cues(self):
        value = reviewed2(deleted=(0, 1, 2))
        value['segmentation'] = {'maxSegmentLength': 20, 'nativeOptions': ['-ml', '20', '-sow'], 'enforced': False, 'unit': 'code points', 'cueCount': 0,
                                 'cuesOverTarget': 0, 'statement': 'A target.'}
        self.assertEqual(timed_text.validate(value)['segmentation'], {'maxSegmentLength': 20, 'cuesOverTarget': 0, 'enforced': False})
        value['segmentation']['cueCount'] = 3
        self.refused(value, 'TIMED_TEXT_INVALID', '.segmentation.cueCount')
        partial = reviewed2(deleted=(1,)); partial['segmentation'] = {'maxSegmentLength': 20, 'nativeOptions': ['-ml', '20', '-sow'], 'enforced': False,
                                                                       'unit': 'code points', 'cueCount': 2, 'cuesOverTarget': 0, 'statement': 'A target.'}
        self.assertEqual(timed_text.validate(partial)['segmentation']['cuesOverTarget'], 0)
        partial['segmentation']['cuesOverTarget'] = 2
        self.refused(partial, 'TIMED_TEXT_INVALID', '.cuesOverTarget')

    def test_parse_binds_the_empty_document_to_its_bytes(self):
        data = base.encode(reviewed2(deleted=(0, 1, 2)))
        view = timed_text.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual((view['cues'], view['sha256'], view['bytes']), ([], hashlib.sha256(data).hexdigest(), len(data)))
        with self.assertRaises(SchemaxisError) as caught: timed_text.parse(data, expected_sha256='0' * 64)
        self.assertEqual(caught.exception.fault.code, 'TIMED_TEXT_DIGEST_MISMATCH')
        with self.assertRaises(SchemaxisError) as caught: timed_text.parse(data.replace(b'"segmentCount": 0', b'"segmentCount": 1'))
        self.assertEqual(caught.exception.fault.code, 'TIMED_TEXT_INVALID')

    def test_cue_text_and_timing_rules_are_shared_with_the_other_versions(self):
        value = reviewed2(deleted=(1,)); value['segments'][0]['text'] = 'a <b> c'
        self.refused(value, 'TIMED_TEXT_CUE_TEXT')
        value = reviewed2(deleted=(1,)); value['segments'][1]['startMs'] = 1
        self.refused(value, 'TIMED_TEXT_TIMING')


if __name__ == '__main__':
    unittest.main()
