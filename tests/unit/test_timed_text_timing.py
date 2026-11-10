"""Shared timed-text reader: the separately versioned reviewed/3 contract with author-edited cue times.

reviewed/1 and reviewed/2 promise the original machine timestamps and stay exactly as they were: they never read a timing member and
refuse a reviewed/3 review. reviewed/3 records the pinned draft's original start and end of every retained cue and proves that the
declared edited indices are exactly the retained cues whose published interval differs from that record.
"""
import copy
import hashlib
from pathlib import Path
import sys
import unittest

from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import test_timed_text as base  # noqa: E402
from test_timed_text_deletions import reviewed2  # noqa: E402

ORIGINALS = [(i * 1000, i * 1000 + 900) for i in range(3)]


def reviewed3(deleted=(), corrected=(), retimed=None, status=None, source=3):
    """A reviewed/3 document over a `source`-cue pinned draft; `retimed` maps a source index to its published (start, end)."""
    retimed = retimed or {}
    value = reviewed2(deleted=deleted, corrected=corrected, source=source)
    retained = value['review']['retainedSourceIndices']
    value['version'] = timed_text.REVIEWED3_VERSION
    for n, i in enumerate(retained):
        if i in retimed: value['segments'][n]['startMs'], value['segments'][n]['endMs'] = retimed[i]
    review = value['review']
    review['status'] = status or ('human-corrected' if deleted or corrected or retimed else 'human-reviewed-unchanged')
    review.update({'synchronizationCertified': False, 'timingEditCount': len(retimed), 'timingEditedIndices': sorted(retimed),
                   'originalTimings': [{'sourceIndex': i, 'startMs': i * 1000, 'endMs': i * 1000 + 900} for i in retained],
                   'timingPolicy': 'Author-edited intervals; not certified as synchronized.'})
    return value


class Reviewed3(unittest.TestCase):
    def refused(self, value, code, fragment=None):
        with self.assertRaises(SchemaxisError) as caught: timed_text.validate(value)
        fault = caught.exception.fault
        self.assertEqual(fault.code, code, fault.message)
        self.assertTrue(fault.recovery)
        if fragment: self.assertIn(fragment, fault.location)
        return fault

    def test_timing_edits_normalise_with_the_original_times_and_the_source_mapping(self):
        view = timed_text.validate(reviewed3(deleted=(1,), retimed={2: (2100, 2950)}))
        self.assertEqual((view['source'], view['status']), ('schemaxis.timedtext.reviewed/3', 'human-corrected'))
        self.assertEqual([(c['startMs'], c['endMs']) for c in view['cues']], [(0, 900), (2100, 2950)])
        review = view['review']
        self.assertEqual((review['timingEditCount'], review['timingEditedIndices'], review['retainedSourceIndices'], review['deletedSourceIndices']), (1, [2], [0, 2], [1]))
        self.assertEqual(review['originalTimings'], [{'sourceIndex': 0, 'startMs': 0, 'endMs': 900}, {'sourceIndex': 2, 'startMs': 2000, 'endMs': 2900}])
        self.assertIs(review['synchronizationCertified'], False)

    def test_timing_only_is_human_corrected_and_unchanged_needs_no_edit(self):
        self.assertEqual(timed_text.validate(reviewed3(retimed={0: (10, 800)}))['status'], 'human-corrected')
        self.assertEqual(timed_text.validate(reviewed3())['status'], 'human-reviewed-unchanged')
        self.refused(reviewed3(retimed={0: (10, 800)}, status='human-reviewed-unchanged'), 'TIMED_TEXT_INVALID', 'status')
        self.refused(reviewed3(status='human-corrected'), 'TIMED_TEXT_INVALID', 'status')

    def test_adjacent_touching_intervals_and_an_end_at_the_audio_duration_are_valid(self):
        value = reviewed3(retimed={0: (0, 1000), 1: (1000, 2000), 2: (2000, 11000)})
        self.assertEqual(timed_text.validate(value)['cues'][2]['endMs'], 11000)

    def test_published_times_are_judged_by_the_shared_rules_never_clamped_or_reordered(self):
        self.refused(reviewed3(retimed={1: (900, 1500), 0: (0, 1200)}), 'TIMED_TEXT_TIMING', 'segments[1]')
        self.refused(reviewed3(retimed={2: (2000, 11001)}), 'TIMED_TEXT_TIMING', 'segments[2]')
        self.refused(reviewed3(retimed={0: (500, 500)}), 'TIMED_TEXT_TIMING', 'segments[0]')

    def test_edited_indices_must_be_exactly_the_cues_that_differ_from_the_recorded_original(self):
        value = reviewed3(corrected=(0,), retimed={1: (1100, 1900)})
        undeclared = copy.deepcopy(value); undeclared['review'].update(timingEditedIndices=[], timingEditCount=0)
        self.refused(undeclared, 'TIMED_TEXT_INVALID', 'timingEditedIndices')
        extra = copy.deepcopy(value); extra['review'].update(timingEditedIndices=[0, 1], timingEditCount=2)
        self.refused(extra, 'TIMED_TEXT_INVALID', 'timingEditedIndices')
        wrong_count = copy.deepcopy(value); wrong_count['review']['timingEditCount'] = 2
        self.refused(wrong_count, 'TIMED_TEXT_INVALID', 'timingEditedIndices')
        deleted = reviewed3(deleted=(1,), retimed={2: (2100, 2900)})
        deleted['review'].update(timingEditedIndices=[1], timingEditCount=1)
        self.refused(deleted, 'TIMED_TEXT_INVALID', 'timingEditedIndices')

    def test_original_timings_follow_the_retained_indices_and_are_integral_ordered_and_inside_the_audio(self):
        for change, fragment in (
                (lambda r: r['originalTimings'].pop(), 'originalTimings'),
                (lambda r: r['originalTimings'][1].update(sourceIndex=2), 'sourceIndex'),
                (lambda r: r['originalTimings'][1].update(startMs=1000.0), 'originalTimings[1]'),
                (lambda r: r['originalTimings'][1].update(startMs=True), 'originalTimings[1]'),
                (lambda r: r['originalTimings'][1].update(startMs=-1), 'originalTimings[1]'),
                (lambda r: r['originalTimings'][1].update(endMs=11001), 'originalTimings[1]'),
                (lambda r: r['originalTimings'][0].update(endMs=1500), 'originalTimings[1]'),
                (lambda r: r['originalTimings'][1].update(extra=1), 'originalTimings[1]')):
            with self.subTest(fragment=fragment):
                value = reviewed3(); change(value['review'])
                with self.assertRaises(SchemaxisError) as caught: timed_text.validate(value)
                self.assertIn(fragment, caught.exception.fault.location)

    def test_the_review_is_closed_and_never_certifies_synchronization_accuracy_or_identity(self):
        for name in ('synchronizationCertified', 'accuracyCertified', 'identityVerified'):
            for bad in (True, 0, None, 'false'):
                value = reviewed3(); value['review'][name] = bad
                with self.subTest(name=name, bad=bad):
                    self.refused(value, 'TIMED_TEXT_REVIEW_UNSUPPORTED')
        for name in ('timingEditCount', 'timingEditedIndices', 'originalTimings', 'timingPolicy', 'synchronizationCertified'):
            value = reviewed3(); del value['review'][name]
            with self.subTest(missing=name): self.refused(value, 'TIMED_TEXT_INVALID')
        value = reviewed3(); value['review']['verified'] = True
        self.refused(value, 'TIMED_TEXT_REVIEW_UNSUPPORTED')
        value = reviewed3(); value['review']['timingPolicy'] = ''
        self.refused(value, 'TIMED_TEXT_INVALID', 'timingPolicy')

    def test_an_empty_document_needs_every_source_cue_explicitly_deleted(self):
        view = timed_text.validate(reviewed3(deleted=(0, 1, 2)))
        self.assertEqual((view['cues'], view['review']['originalTimings'], view['review']['deletionCount']), ([], [], 3))
        value = reviewed3(); value['segments'], value['segmentCount'] = [], 0
        self.refused(value, 'TIMED_TEXT_INVALID')

    def test_older_versions_keep_their_exact_contract_and_do_not_read_timing_members(self):
        self.assertEqual(timed_text.validate(reviewed2(deleted=(1,)))['source'], 'schemaxis.timedtext.reviewed/2')
        value = reviewed2(); value['review']['timingEditCount'] = 0
        self.refused(value, 'TIMED_TEXT_REVIEW_UNSUPPORTED')
        old = reviewed3(); old['version'] = timed_text.REVIEWED2_VERSION
        self.refused(old, 'TIMED_TEXT_REVIEW_UNSUPPORTED')
        # reviewed/3 never reads a reviewed/2 review shape.
        new = reviewed2(); new['version'] = timed_text.REVIEWED3_VERSION
        self.refused(new, 'TIMED_TEXT_INVALID')
        self.refused({**base.document(), 'version': 'schemaxis.timedtext.reviewed/4'}, 'TIMED_TEXT_UNSUPPORTED_VERSION')

    def test_audio_limit_rounds_a_fractional_millisecond_up_exactly_as_the_draft_reader_does(self):
        self.assertEqual(timed_text.audio_limit({'durationMs': 11000, 'durationRemainderFrames': 0}), 11000)
        self.assertEqual(timed_text.audio_limit({'durationMs': 11000, 'durationRemainderFrames': 5}), 11001)

    def test_parse_binds_the_view_to_the_exact_bytes(self):
        data = timed_text.canonical_json(reviewed3(retimed={0: (10, 800)}))
        view = timed_text.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual(view['sha256'], hashlib.sha256(data).hexdigest())
        with self.assertRaises(SchemaxisError) as caught: timed_text.parse(data, expected_sha256='0' * 64)
        self.assertEqual(caught.exception.fault.code, 'TIMED_TEXT_DIGEST_MISMATCH')


if __name__ == '__main__':
    unittest.main()
