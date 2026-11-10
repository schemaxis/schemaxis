"""Closed machine-draft timed-text contract: acceptance, closed keys, timing, text, budgets and drift."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

SHA = 'a' * 64


def document():
    return {'version': 'schemaxis.whispercpp.segments/1', 'language': 'en', 'timeUnit': 'millisecond',
            'audio': {'sha256': SHA, 'bytes': 352044, 'frames': 176000, 'rate': 16000, 'channels': 1,
                      'durationMs': 11000, 'durationRemainderFrames': 0},
            'model': {'sha256': 'b' * 64, 'bytes': 147951465}, 'nativeJsonSha256': 'c' * 64, 'segmentCount': 2,
            'segments': [{'index': 0, 'startMs': 0, 'endMs': 5410, 'text': 'And so, my fellow Americans,'},
                         {'index': 1, 'startMs': 5410, 'endMs': 11000, 'text': 'ask not what your country can do.'}],
            'review': {'accuracyCertified': False, 'humanReviewRequired': True, 'statement': 'Review before use.',
                       'policy': {'timing': 'integral milliseconds', 'text': 'UTF-8 plain text'}}}


def encode(value): return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')


class Contract(unittest.TestCase):
    def refused(self, value, code, fragment=None):
        with self.assertRaises(SchemaxisError) as caught:
            timed_text.validate(value)
        fault = caught.exception.fault
        self.assertEqual(fault.code, code, fault.message)
        self.assertTrue(fault.recovery)
        if fragment: self.assertIn(fragment, fault.location)
        return fault

    def test_current_document_normalises_to_a_machine_draft(self):
        view = timed_text.validate(document())
        self.assertEqual(view['status'], 'machine-draft')
        self.assertEqual(view['version'], 'schemaxis.timedtext/1')
        self.assertEqual([(c['startMs'], c['endMs']) for c in view['cues']], [(0, 5410), (5410, 11000)])
        self.assertEqual(timed_text.rows(view)[1], ['5410', '11000', 'ask not what your country can do.'])
        self.assertEqual((view['language'], view['durationMs'], view['audioSha256']), ('en', 11000, SHA))

    def test_parse_binds_the_view_to_exact_bytes_and_pin(self):
        data = encode(document())
        view = timed_text.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual((view['sha256'], view['bytes']), (hashlib.sha256(data).hexdigest(), len(data)))
        with self.assertRaises(SchemaxisError) as caught: timed_text.parse(data, expected_sha256='0' * 64)
        self.assertEqual(caught.exception.fault.code, 'TIMED_TEXT_DIGEST_MISMATCH')

    def test_the_real_whisper_serialiser_stays_inside_the_contract(self):
        from schemaxis.adaptors.whispercpp import adaptor
        segments = [{'index': 0, 'startMs': 0, 'endMs': 1500, 'text': 'Hello there.', '_raw': ' Hello there.'}]
        info = {'bytes': 64044, 'frames': 32000, 'rate': 16000, 'channels': 1}
        built = adaptor.segment_document({'language': 'en'}, segments, SHA, info, 'b' * 64, 1000, 'c' * 64)
        view = timed_text.parse(adaptor.encode_json(built))
        self.assertEqual(view['cues'], [{'startMs': 0, 'endMs': 1500, 'text': 'Hello there.'}])
        self.assertEqual(view['durationMs'], 2000)

    def test_unsupported_versions_and_unknown_members_are_refused(self):
        for version in ('schemaxis.whispercpp.segments/2', 'schemaxis.timedtext/1', 7, None):
            value = document(); value['version'] = version
            self.refused(value, 'TIMED_TEXT_UNSUPPORTED_VERSION', '.version')
        for path in ((), ('audio',), ('model',), ('segments', 0), ('review',), ('review', 'policy')):
            value = document(); target = value
            for step in path: target = target[step]
            target['extra'] = 1
            fault = self.refused(value, 'TIMED_TEXT_REVIEW_UNSUPPORTED' if path == ('review',) else 'TIMED_TEXT_UNKNOWN_KEY')
            self.assertIn('extra', fault.observed.get('extra') or fault.observed.get('members'))

    def test_missing_members_and_non_objects_are_invalid(self):
        for key in ('language', 'audio', 'model', 'segments', 'nativeJsonSha256', 'segmentCount', 'timeUnit', 'review'):
            value = document(); del value[key]
            self.refused(value, 'TIMED_TEXT_INVALID')
        for value in ([], 'text', 3, None):
            self.refused(value, 'TIMED_TEXT_INVALID')

    def test_a_human_review_status_is_never_read(self):
        reviewed = document(); reviewed['review'] = {'status': 'human-reviewed', 'reviewer': 'someone'}
        self.refused(reviewed, 'TIMED_TEXT_REVIEW_UNSUPPORTED', '.review')
        for field, value in (('accuracyCertified', True), ('humanReviewRequired', False), ('accuracyCertified', 0), ('humanReviewRequired', 1)):
            changed = document(); changed['review'][field] = value
            self.refused(changed, 'TIMED_TEXT_REVIEW_UNSUPPORTED', '.review')
        added = document(); added['review']['status'] = 'human-corrected'
        self.refused(added, 'TIMED_TEXT_REVIEW_UNSUPPORTED', '.review')

    def test_timing_is_integral_ordered_and_inside_the_audio(self):
        for field, value in (('startMs', -1), ('startMs', '0'), ('startMs', 0.5), ('endMs', True), ('endMs', None), ('endMs', 2**60)):
            changed = document(); changed['segments'][0][field] = value
            self.refused(changed, 'TIMED_TEXT_TIMING', '.segments[0]')
        zero = document(); zero['segments'][0]['endMs'] = 0
        self.refused(zero, 'TIMED_TEXT_TIMING', '.segments[0]')
        overlap = document(); overlap['segments'][1]['startMs'] = 5409
        fault = self.refused(overlap, 'TIMED_TEXT_TIMING', '.segments[1]')
        self.assertEqual(fault.observed['previousEndMs'], 5410)
        late = document(); late['segments'][1]['endMs'] = 11001
        self.refused(late, 'TIMED_TEXT_TIMING', '.segments[1]')
        remainder = document(); remainder['audio'].update(frames=176001, durationRemainderFrames=1000, bytes=352046)
        remainder['segments'][1]['endMs'] = 11001
        self.assertEqual(timed_text.validate(remainder)['cues'][1]['endMs'], 11001)

    def test_cue_indexes_counts_and_audio_arithmetic_are_checked(self):
        for mutate in (lambda d: d['segments'][1].update(index=2), lambda d: d['segments'][0].update(index=True),
                       lambda d: d.update(segmentCount=3), lambda d: d.update(segmentCount=True), lambda d: d['segments'].clear(),
                       lambda d: d['audio'].update(durationMs=10999), lambda d: d['audio'].update(rate=0),
                       lambda d: d['audio'].update(channels=True), lambda d: d.update(language='EN'), lambda d: d.update(timeUnit='second'),
                       lambda d: d['audio'].update(sha256='A' * 64), lambda d: d['model'].update(sha256='b' * 63),
                       lambda d: d.update(nativeJsonSha256=None)):
            value = document(); mutate(value)
            self.refused(value, 'TIMED_TEXT_INVALID')

    def test_cue_text_must_be_nonblank_plain_text(self):
        bad = ['', ' ', ' leading', 'trailing ', 'line\nbreak', 'tab\there', 'nul\x00', 'a b', 'a\ud800b', 'broken �',
               'a < b', 'a > b', 'a { b', 'one --> two', '‮evil', 'a⁧b', '​‍', 'ㅤ', '́', '⠀', '﷐', '', 7, None, ['x']]
        for text in bad:
            value = document(); value['segments'][0]['text'] = text
            self.refused(value, 'TIMED_TEXT_CUE_TEXT', '.segments[0].text')

    def test_multilingual_and_emoji_text_is_accepted_unchanged(self):
        for text in ('Bonjour, ça va ? 你好。', 'שלום עולם', 'مرحبا بالعالم', 'नमस्ते', 'สวัสดี', '👩‍🚀 ok', 'a&b "quoted"', 'a  b'):
            value = document(); value['segments'][0]['text'] = text
            self.assertEqual(timed_text.validate(value)['cues'][0]['text'], text)

    def test_budgets_refuse_rather_than_truncate(self):
        many = document(); many['segments'] = [{'index': i, 'startMs': i, 'endMs': i + 1, 'text': 'x'} for i in range(513)]
        many['segmentCount'] = 513; many['audio'].update(frames=16000 * 1000, durationMs=1000000, bytes=32000044)
        self.refused(many, 'TIMED_TEXT_RESOURCE_LIMIT', '.segments')
        exact = copy.deepcopy(many); exact['segments'] = exact['segments'][:512]; exact['segmentCount'] = 512
        self.assertEqual(len(timed_text.validate(exact)['cues']), 512)
        long = document(); long['segments'][0]['text'] = 'x' * 257
        self.refused(long, 'TIMED_TEXT_RESOURCE_LIMIT', '.segments[0].text')
        edge = document(); edge['segments'][0]['text'] = 'x' * 256
        self.assertEqual(len(timed_text.validate(edge)['cues'][0]['text']), 256)
        total = document(); total['segments'] = [{'index': i, 'startMs': i, 'endMs': i + 1, 'text': 'x' * 256} for i in range(129)]
        total['segmentCount'] = 129; total['audio'].update(frames=16000 * 100, durationMs=100000, bytes=3200044)
        self.refused(total, 'TIMED_TEXT_RESOURCE_LIMIT', '.segments[128].text')
        with self.assertRaises(SchemaxisError) as caught: timed_text.parse(b' ' * (timed_text.MAX_DOCUMENT_BYTES + 1))
        self.assertEqual(caught.exception.fault.code, 'TIMED_TEXT_RESOURCE_LIMIT')

    def test_json_bytes_must_be_strict(self):
        good = encode(document()).decode()
        for data in (b'\xef\xbb\xbf' + good.encode(), good.encode('utf-16'), b'\xff\xfe', b'', b'{', b'[]'[:1] * 2000 + b']' * 2000,
                     '{"a":1,"a":2}'.encode(), good.replace('11000', 'NaN').encode(), good.replace('"language"', '"language" ,"language"').encode(),
                     good.replace('"en"', '"\\ud800"').encode()):
            with self.assertRaises(SchemaxisError) as caught: timed_text.parse(data)
            self.assertIn(caught.exception.fault.code, ('TIMED_TEXT_INVALID_JSON', 'TIMED_TEXT_INVALID'), data[:20])
        with self.assertRaises(SchemaxisError) as caught: timed_text.parse(None)
        self.assertEqual(caught.exception.fault.code, 'TIMED_TEXT_INVALID_JSON')

    def test_a_number_that_overflows_to_infinity_is_refused_when_parsed(self):
        for literal in ('1e400', '-1e400', '1E999', '1.5e4000'):
            with self.subTest(literal):
                with self.assertRaises(SchemaxisError) as caught: timed_text.strict_json(('{"a": %s}' % literal).encode(), '$.draft')
                fault = caught.exception.fault
                self.assertEqual((fault.code, fault.location), ('TIMED_TEXT_INVALID_JSON', '$.draft'))
                self.assertIn('non-finite', fault.message); self.assertIn('infinity', fault.message)
        # refused at parse time, so the document never reaches the later integer checks that would hide the real cause
        with self.assertRaises(SchemaxisError) as caught: timed_text.parse(encode(document()).decode().replace('11000', '1e400').encode())
        self.assertEqual(caught.exception.fault.code, 'TIMED_TEXT_INVALID_JSON')
        # finite fractions and exponents still parse (and are later refused as non-integers where an integer is required)
        self.assertEqual(timed_text.strict_json(b'{"a": 1.5e3, "b": 1e-400}'), {'a': 1500.0, 'b': 0.0})

    def test_the_optional_cue_length_target_is_a_closed_member(self):
        value = document(); value['segmentation'] = {'maxSegmentLength': 20, 'nativeOptions': ['-ml', '20', '-sow'], 'enforced': False,
            'unit': 'code points', 'cueCount': 2, 'cuesOverTarget': 2, 'statement': 'A target, not a guarantee.'}
        self.assertEqual(timed_text.validate(value)['segmentation'], {'maxSegmentLength': 20, 'cuesOverTarget': 2, 'enforced': False})
        self.assertIsNone(timed_text.validate(document())['segmentation'])
        for mutate in (lambda m: m.update(extra=1), lambda m: m.pop('statement'), lambda m: m.update(enforced=True), lambda m: m.update(maxSegmentLength=15),
                       lambda m: m.update(maxSegmentLength=True), lambda m: m.update(nativeOptions=['-ml', '21', '-sow']), lambda m: m.update(cueCount=3),
                       lambda m: m.update(cuesOverTarget=1), lambda m: m.update(unit=''), lambda m: m.update(cuesOverTarget=False)):
            changed = copy.deepcopy(value); mutate(changed['segmentation'])
            fault = self.refused(changed, 'TIMED_TEXT_UNKNOWN_KEY' if 'extra' in changed['segmentation'] else 'TIMED_TEXT_INVALID', '.segmentation')
            self.assertTrue(fault.message)
        value['segmentation'] = None
        self.refused(value, 'TIMED_TEXT_INVALID', '.segmentation')

    def test_the_real_whisper_serialiser_with_a_cue_length_target_stays_inside_the_contract(self):
        from schemaxis.adaptors.whispercpp import adaptor
        segments = [{'index': 0, 'startMs': 0, 'endMs': 1500, 'text': 'Hello there, my friend.', '_raw': ' Hello there, my friend.'}]
        info = {'bytes': 64044, 'frames': 32000, 'rate': 16000, 'channels': 1}
        built = adaptor.segment_document({'language': 'en', 'maxSegmentLength': 16}, segments, SHA, info, 'b' * 64, 1000, 'c' * 64)
        view = timed_text.parse(adaptor.encode_json(built))
        self.assertEqual(view['segmentation'], {'maxSegmentLength': 16, 'cuesOverTarget': 1, 'enforced': False})

    def test_no_adaptor_or_native_import_in_the_core_module(self):
        text = Path(timed_text.__file__).read_text(encoding='utf-8')
        self.assertNotIn('schemaxis.adaptors', text)
        self.assertNotIn('open(', text)


def reviewed_document(status='human-corrected', indices=(0,), note='Checked against the published text.'):
    value = document()
    draft = encode(document())
    value['version'] = 'schemaxis.timedtext.reviewed/1'
    for i in indices: value['segments'][i]['text'] = value['segments'][i]['text'] + ' (fixed)'
    value['review'] = {'status': status, 'accuracyCertified': False, 'identityVerified': False, 'statement': 'A declaration by the author; not verified.',
                       'note': note, 'basis': {'version': 'schemaxis.whispercpp.segments/1', 'sha256': hashlib.sha256(draft).hexdigest(), 'bytes': len(draft)},
                       'correctionCount': len(indices), 'correctedIndices': list(indices), 'policy': {'timing': 'integral milliseconds', 'text': 'UTF-8 plain text'}}
    return value


class ReviewedContract(unittest.TestCase):
    def refused(self, value, code, fragment=None):
        with self.assertRaises(SchemaxisError) as caught: timed_text.validate(value)
        fault = caught.exception.fault
        self.assertEqual(fault.code, code, fault.message)
        self.assertTrue(fault.recovery)
        if fragment: self.assertIn(fragment, fault.location)
        return fault

    def test_both_declared_statuses_normalise_with_their_review(self):
        corrected = timed_text.validate(reviewed_document())
        self.assertEqual((corrected['version'], corrected['source'], corrected['status']), ('schemaxis.timedtext/1', 'schemaxis.timedtext.reviewed/1', 'human-corrected'))
        self.assertEqual(corrected['review']['correctedIndices'], [0]); self.assertIs(corrected['review']['identityVerified'], False)
        self.assertEqual(corrected['cues'][0]['text'], 'And so, my fellow Americans, (fixed)')
        unchanged = timed_text.validate(reviewed_document('human-reviewed-unchanged', ()))
        self.assertEqual((unchanged['status'], unchanged['review']['correctionCount']), ('human-reviewed-unchanged', 0))
        self.assertEqual(timed_text.validate(document())['status'], 'machine-draft')
        self.assertNotIn('review', timed_text.validate(document()))

    def test_review_object_is_closed_and_the_claims_are_fixed(self):
        for mutate in (lambda r: r.update(reviewer='someone'), lambda r: r.update(humanReviewRequired=True)):
            value = reviewed_document(); mutate(value['review'])
            self.refused(value, 'TIMED_TEXT_REVIEW_UNSUPPORTED', '.review')
        for key in ('note', 'basis', 'status', 'policy', 'statement', 'correctedIndices'):
            value = reviewed_document(); del value['review'][key]
            self.refused(value, 'TIMED_TEXT_INVALID', '.review')
        for field in ('accuracyCertified', 'identityVerified'):
            for forged in (True, 0, 1, None, 'false'):
                value = reviewed_document(); value['review'][field] = forged
                self.refused(value, 'TIMED_TEXT_REVIEW_UNSUPPORTED', '.review')
        for status in ('machine-draft', 'human-reviewed', 'verified', '', None, 7):
            value = reviewed_document(); value['review']['status'] = status
            self.refused(value, 'TIMED_TEXT_REVIEW_UNSUPPORTED', '.review.status')

    def test_status_counts_and_indices_must_agree(self):
        for mutate in (lambda r: r.update(status='human-reviewed-unchanged'), lambda r: r.update(correctionCount=2), lambda r: r.update(correctionCount=True),
                       lambda r: r.update(correctedIndices=[2]), lambda r: r.update(correctedIndices=[-1]), lambda r: r.update(correctedIndices=[True]),
                       lambda r: r.update(correctedIndices=[0, 0], correctionCount=2), lambda r: r.update(correctedIndices=[1, 0], correctionCount=2),
                       lambda r: r.update(correctedIndices='0'), lambda r: r.update(correctedIndices=[], correctionCount=0)):
            value = reviewed_document(); mutate(value['review'])
            self.refused(value, 'TIMED_TEXT_INVALID', '.review')
        value = reviewed_document('human-reviewed-unchanged', ()); value['review'].update(status='human-corrected')
        self.refused(value, 'TIMED_TEXT_INVALID', '.review.status')

    def test_basis_is_the_pinned_machine_draft(self):
        for mutate in (lambda b: b.update(version='schemaxis.timedtext.reviewed/1'), lambda b: b.update(sha256='A' * 64), lambda b: b.update(sha256='a' * 63),
                       lambda b: b.update(bytes=0), lambda b: b.update(bytes=True), lambda b: b.update(extra=1), lambda b: b.pop('bytes')):
            value = reviewed_document(); mutate(value['review']['basis'])
            self.refused(value, 'TIMED_TEXT_INVALID' if 'extra' not in value['review']['basis'] else 'TIMED_TEXT_UNKNOWN_KEY', '.review.basis')

    def test_note_is_bounded_plain_text(self):
        for note in ('', ' lead', 'trail ', 'two  spaces', 'a <b> c', 'a --> b', 'new\nline', '\u202eevil', 'x' * 501, 7, None, '\u200b'):
            value = reviewed_document(note=note)
            self.refused(value, 'TIMED_TEXT_INVALID', '.review.note')
        self.assertEqual(timed_text.validate(reviewed_document(note='x' * 500))['review']['note'], 'x' * 500)
        self.assertEqual(timed_text.validate(reviewed_document(note='Vérifié contre le texte; 你好。'))['review']['note'], 'Vérifié contre le texte; 你好。')

    def test_a_note_is_plain_space_text_that_pandoc_can_publish_while_cues_keep_their_unicode(self):
        for label, note in (('no-break space', 'a\u00a0b'), ('ideographic space', 'a\u3000b'), ('tab', 'a\tb'), ('word joiner', 'a\u2060b'), ('byte order mark', 'a\ufeffb'),
                            ('zero-width space', 'a\u200bb'), ('zero-width joiner', 'a\u200db'), ('zero-width non-joiner', 'a\u200cb'), ('left-to-right mark', 'a\u200eb'),
                            ('unassigned tag', 'a\U000e0002b'), ('tag base', 'a\U000e0000b'), ('private use', 'a\ue000b'), ('noncharacter', 'a\ufdd0b'), ('en space', 'a\u2002b')):
            with self.subTest(label):
                self.assertTrue(timed_text.note_problem(note), label)
                self.refused(reviewed_document(note=note), 'TIMED_TEXT_INVALID', '.review.note')
        # cue text is not narrowed: the same characters stay legitimate caption text
        for text in ('a\u00a0b', 'می\u200cخواهم', 'a\u200eb'):
            self.assertIsNone(timed_text.cue_text_problem(text), text)

    def test_document_members_stay_closed_and_cue_rules_are_shared(self):
        for path in ((), ('audio',), ('model',), ('segments', 0), ('review', 'policy')):
            value = reviewed_document(); target = value
            for step in path: target = target[step]
            target['extra'] = 1
            self.refused(value, 'TIMED_TEXT_UNKNOWN_KEY')
        value = reviewed_document(); value['segments'][1]['startMs'] = 5409
        self.refused(value, 'TIMED_TEXT_TIMING', '.segments[1]')
        value = reviewed_document(); value['segments'][0]['text'] = 'a <b> c'
        self.refused(value, 'TIMED_TEXT_CUE_TEXT', '.segments[0].text')
        value = reviewed_document(); value['segmentCount'] = 3
        self.refused(value, 'TIMED_TEXT_INVALID', '.segmentCount')

    def test_the_reviewed_shape_is_never_accepted_on_the_machine_version_and_the_reverse(self):
        value = reviewed_document(); value['version'] = 'schemaxis.whispercpp.segments/1'
        self.refused(value, 'TIMED_TEXT_REVIEW_UNSUPPORTED', '.review')
        value = document(); value['version'] = 'schemaxis.timedtext.reviewed/1'
        self.refused(value, 'TIMED_TEXT_REVIEW_UNSUPPORTED', '.review')
        for version in ('schemaxis.timedtext.reviewed/4', 'schemaxis.timedtext.reviewed', 'schemaxis.whispercpp.reviewed/1'):
            value = reviewed_document(); value['version'] = version
            self.refused(value, 'TIMED_TEXT_UNSUPPORTED_VERSION', '.version')

    def test_segmentation_is_carried_and_recounted_for_the_reviewed_text(self):
        value = reviewed_document()
        value['segmentation'] = {'maxSegmentLength': 20, 'nativeOptions': ['-ml', '20', '-sow'], 'enforced': False, 'unit': 'code points', 'cueCount': 2,
                                 'cuesOverTarget': 2, 'statement': 'A target, not a guarantee.'}
        self.assertEqual(timed_text.validate(value)['segmentation'], {'maxSegmentLength': 20, 'cuesOverTarget': 2, 'enforced': False})
        value['segmentation']['cuesOverTarget'] = 1
        self.refused(value, 'TIMED_TEXT_INVALID', '.segmentation.cuesOverTarget')

    def test_parse_binds_bytes_and_serialisers_are_exact(self):
        data = timed_text.canonical_json(reviewed_document())
        view = timed_text.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual((view['status'], view['sha256'], view['bytes']), ('human-corrected', hashlib.sha256(data).hexdigest(), len(data)))
        self.assertEqual(timed_text.canonical_json(document()), encode(document()))
        cues = [{'startMs': 3723004, 'endMs': 3723999, 'text': 'A & B'}]
        self.assertEqual(timed_text.srt_text(cues), '1\n01:02:03,004 --> 01:02:03,999\nA & B\n\n')
        self.assertEqual(timed_text.vtt_text(cues), 'WEBVTT\n\n01:02:03.004 --> 01:02:03.999\nA &amp; B\n\n')
        self.assertEqual(timed_text.plain_text(cues), 'A & B\n')

    def test_the_serialisers_agree_with_the_whisper_adaptor_on_the_same_cues(self):
        from schemaxis.adaptors.whispercpp import adaptor
        segments = [{'index': 0, 'startMs': 0, 'endMs': 1500, 'text': 'Tom & Jerry'}, {'index': 1, 'startMs': 1500, 'endMs': 3723004, 'text': 'second'}]
        cues = [{k: s[k] for k in ('startMs', 'endMs', 'text')} for s in segments]
        self.assertEqual((timed_text.srt_text(cues), timed_text.vtt_text(cues), timed_text.plain_text(cues)),
                         (adaptor.srt(segments), adaptor.vtt(segments), adaptor.transcript(segments)))


if __name__ == '__main__':
    unittest.main()
