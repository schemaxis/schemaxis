"""Host-only explicit caption line layout: schemaxis.whispercpp.captions/1.

Nothing here launches a native executable, reads audio or runs speech recognition. Sources are tiny illustrative timed-text documents built
from the retained genuine public-sample draft (three cues, 0/5410/9040/11000 ms) or from invented texts; no person reviewed any of them.
Expected line breaks are written out by hand, and an exhaustive search over every breakpoint choice, which tokenises the text by its own
character scan, is a second, independent oracle for the dynamic program. These tests never count as native qualification of any route.
"""
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.adaptors.whispercpp import adaptor as transcription
from schemaxis.adaptors.whispercpp import caption_layout as c
from schemaxis.adaptors.whispercpp import corrections as first
from schemaxis.adaptors.whispercpp import corrections_deletion as second
from schemaxis.adaptors.whispercpp import corrections_timing as third
from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
JFK = ROOT / 'examples/schemaxis/whispercpp-corrections-fixtures/jfk-short-cues-segments.json'
JFK_SHA = '0fb466aec743b3a236655d7b29e4d3a1003bcd5230abcd4276af56b08cb4ba04'
NOTE = 'Illustrative automated declaration; no person listened to or reviewed this recording.'
SENTINEL = 'SENTINEL-whisper-cli-was-launched'
TEXTS = ['And so my fellow Americans, ask not what', 'your country can do for you, ask what you', 'can do for your country.']

SRT_24 = ('1\n00:00:00,000 --> 00:00:05,410\nAnd so my fellow\nAmericans, ask not what\n\n'
          '2\n00:00:05,410 --> 00:00:09,040\nyour country can do\nfor you, ask what you\n\n'
          '3\n00:00:09,040 --> 00:00:11,000\ncan do for your country.\n\n')
VTT_24 = ('WEBVTT\n\n00:00:00.000 --> 00:00:05.410\nAnd so my fellow\nAmericans, ask not what\n\n'
          '00:00:05.410 --> 00:00:09.040\nyour country can do\nfor you, ask what you\n\n'
          '00:00:09.040 --> 00:00:11.000\ncan do for your country.\n\n')


def machine(texts, duration=11000):
    """A valid machine draft with the given cue texts, evenly spaced inside the retained sample's 11000 ms audio."""
    document = json.loads(JFK.read_text()); document.pop('segmentation')
    step = duration // len(texts)
    document['segments'] = [{'index': i, 'startMs': i * step, 'endMs': (i + 1) * step, 'text': text} for i, text in enumerate(texts)]
    document['segmentCount'] = len(texts)
    return document


def lcg(seed):
    state = seed
    while True:
        state = (state * 6364136223846793005 + 1442695040888963407) % 2 ** 64
        yield state >> 33


def tokens(text):
    """Unbreakable runs by a plain character scan: a space separates only when neither neighbour is an ordinary space."""
    found, start = [], 0
    for at, character in enumerate(text):
        if character == ' ' and 0 < at < len(text) - 1 and text[at - 1] != ' ' and text[at + 1] != ' ':
            found.append(text[start:at]); start = at + 1
    found.append(text[start:])
    return found


def oracle(text, width, lines):
    """Exhaustive search over every breakpoint choice: fewest lines, then least sum of squares, then earliest breaks. None when infeasible."""
    if len(text) <= width: return [text]
    words = tokens(text)
    for k in range(1, min(lines, len(words)) + 1):
        best = None
        for cuts in itertools.combinations(range(1, len(words)), k - 1):
            bounds = (0, *cuts, len(words))
            parts = [' '.join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
            if any(len(part) > width for part in parts): continue
            key = (sum(len(part) ** 2 for part in parts), cuts)
            if best is None or key < best[0]: best = (key, parts)
        if best: return best[1]
    return None


class Base(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.dir = Path(self.temporary.name)
        self.source = self.dir / 'source.json'; shutil.copyfile(JFK, self.source)

    def fault(self, action, code=None, location=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        fault = caught.exception.fault
        if code: self.assertEqual(fault.code, code, fault.to_dict())
        if location: self.assertEqual(fault.location, location)
        self.assertTrue(fault.recovery or fault.code == 'VERIFICATION_FAILED', fault.to_dict())
        return fault

    def write(self, document, name='source.json'):
        path = self.dir / name
        path.write_bytes(document if isinstance(document, bytes) else json.dumps(document).encode('utf-8'))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def doc(self, path=None, sha=None, width=24, lines=3, **change):
        path = path or self.source
        document = {'version': c.VERSION, 'operation': 'layout', 'source': {'path': str(path)}, 'sourceSha256': sha or hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                    'maxLineCodePoints': width, 'maxLines': lines}
        document.update(change); return document

    def job(self, texts, width=24, lines=3, name='job'):
        path, sha = self.write(machine(texts), name + '-source.json')
        result = c.run(self.doc(path, sha, width, lines), self.dir / name, timeout=30)
        return result, self.dir / name

    def laid(self, texts, width, lines=3):
        _, directory = self.job(texts, width, lines, name=f'laid-{abs(hash((tuple(texts), width, lines)))}')
        return [cue['lines'] for cue in json.loads((directory / 'caption-layout.json').read_text())['cues']]

    def refresh(self, directory):
        receipt = c.read_json(directory, 'verification.json')
        receipt['artifacts'] = c.artifacts(directory)
        receipt['evidence'] = {n: c.digest(directory, n) for n in receipt['evidence']}
        c.atomic_json(directory / 'verification.json', receipt)
        from schemaxis.publication_metadata import finalise
        finalise(directory)


class Planning(Base):
    def test_plan_reads_no_file_and_keeps_the_authored_members(self):
        document = self.doc(Path('/definitely/not/there/segments.json'), JFK_SHA)
        with patch('builtins.open', side_effect=AssertionError('read')), patch('os.open', side_effect=AssertionError('opened')):
            planned = c.plan(document); self.assertEqual(c.query(document), (['layout'], {}))
        self.assertEqual((planned['version'], planned['operation'], planned['maxLineCodePoints'], planned['maxLines'], planned['sourceSha256']),
                         (c.PLAN_VERSION, 'layout', 24, 3, JFK_SHA))
        self.assertEqual(planned['losses'], c.LOSSES); self.assertEqual(planned['source'], {'path': '/definitely/not/there/segments.json'})

    def test_the_document_is_closed_and_every_member_is_required(self):
        base = self.doc()
        for name in ('version', 'operation', 'source', 'sourceSha256', 'maxLineCodePoints', 'maxLines'):
            document = {k: v for k, v in base.items() if k != name}
            if name == 'version':
                with self.assertRaises(SchemaxisError) as caught: c.plan(document)
                self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_VERSION')
            elif name == 'operation': self.fault(lambda: c.plan(document), 'UNKNOWN_OPERATION')
            else: self.fault(lambda: c.plan(document), 'MISSING_ARGUMENT')
        self.fault(lambda: c.plan({**base, 'maxColumns': 3}), 'UNKNOWN_ARGUMENT', '$')
        self.fault(lambda: c.plan({**base, 'captionReview': True}), 'UNKNOWN_ARGUMENT', '$')
        self.fault(lambda: c.plan({**base, 'source': {'path': base['source']['path'], 'sha256': JFK_SHA}}), 'UNKNOWN_ARGUMENT', '$.source')
        self.fault(lambda: c.plan({**base, 'operation': 'correct'}), 'UNKNOWN_OPERATION')
        with self.assertRaises(SchemaxisError) as caught: c.plan({**base, 'version': 'schemaxis.whispercpp.captions/2'})
        self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_VERSION')
        self.fault(lambda: c.plan([base]), 'INVALID_DOCUMENT')

    def test_the_bounds_have_exact_inclusive_limits_and_no_loose_types(self):
        for width in (8, 9, 79, 80): self.assertEqual(c.plan(self.doc(maxLineCodePoints=width))['maxLineCodePoints'], width)
        for lines in (1, 2, 3): self.assertEqual(c.plan(self.doc(maxLines=lines))['maxLines'], lines)
        for width in (7, 81, 0, -8): self.fault(lambda: c.plan(self.doc(maxLineCodePoints=width)), 'INVALID_ARGUMENT', '$.maxLineCodePoints')
        for lines in (0, 4, -1): self.fault(lambda: c.plan(self.doc(maxLines=lines)), 'INVALID_ARGUMENT', '$.maxLines')
        for value in (True, False, 8.0, 24.5, '24', None, [24]):
            self.fault(lambda: c.plan(self.doc(maxLineCodePoints=value)), 'INVALID_ARGUMENT', '$.maxLineCodePoints')
            self.fault(lambda: c.plan(self.doc(maxLines=value)), 'INVALID_ARGUMENT', '$.maxLines')

    def test_the_source_path_and_pin_are_checked_before_any_file_is_read(self):
        for path in ('relative/segments.json', '/tmp/../etc/segments.json', '/tmp/segments.txt', '/tmp/segments', '/tmp/a\0b.json'):
            self.fault(lambda: c.plan(self.doc(Path(path), JFK_SHA)), 'INVALID_SOURCE', '$.source.path')
        for sha in ('A' * 64, 'a' * 63, 'a' * 65, 'g' * 64, ''):
            self.fault(lambda: c.plan(self.doc(sourceSha256=sha)), None)
        self.fault(lambda: c.plan(self.doc(sourceSha256='A' * 64)), 'INVALID_SHA256', '$.sourceSha256')
        self.fault(lambda: c.plan(self.doc(sourceSha256=123)), 'INVALID_ARGUMENT', '$.sourceSha256')

    def test_the_hooks_hash_the_source_bytes_and_the_run_is_serial(self):
        document = self.doc(); before = c.reusableInputs(document)
        self.assertEqual(before, {'source': JFK_SHA})
        self.source.write_bytes(self.source.read_bytes() + b'\n'); self.assertNotEqual(c.reusableInputs(document), before)
        self.fault(lambda: c.reusableInputs(self.doc(Path('/nonexistent-dir/x.json'), JFK_SHA)), 'SOURCE_MISSING')
        self.assertEqual(c.resources(document, {}, 'x'), {'threads': 1}); self.assertEqual(c.resources(document, {'threads': 1}, 'x'), {'threads': 1})
        self.fault(lambda: c.resources(document, {'threads': 2}, 'x'), 'INVALID_EXECUTION')


class Registration(Base):
    def test_the_route_is_registered_separately_and_the_old_routes_do_not_know_it(self):
        route = registry.resolve(self.doc(), legacy=True)[1]
        self.assertEqual((route['module'], route['acceptedArtifacts']), ('schemaxis.adaptors.whispercpp.caption_layout', ['text']))
        for old, module in ((first, 'corrections'), (second, 'corrections_deletion'), (third, 'corrections_timing')):
            self.assertEqual(registry.resolve({'version': old.VERSION}, legacy=True)[1]['module'], 'schemaxis.adaptors.whispercpp.' + module)
            self.fault(lambda: old.plan(self.doc()), None)
        with self.assertRaises(SchemaxisError): transcription.plan(self.doc())
        self.assertEqual((first.VERSION, second.VERSION, third.VERSION, transcription.VERSION),
                         ('schemaxis.whispercpp.correct/1', 'schemaxis.whispercpp.correct/2', 'schemaxis.whispercpp.correct/3', 'schemaxis.whispercpp/1'))
        qualification = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/qualification.json').read_text())
        self.assertNotIn(c.VERSION, qualification['routes'])

    def test_a_layout_with_room_to_spare_is_byte_identical_to_the_one_line_publications_of_every_older_route(self):
        """Wide bounds change nothing, so the older routes' own SRT and WebVTT are the literal expected bytes."""
        _, mine = self.job(TEXTS, **{'width': 80, 'lines': 1}, name='machine')
        draft = machine(TEXTS); path, sha = self.write(draft, 'draft.json')
        edited = {'version': third.VERSION, 'draft': {'path': str(path)}, 'basisSha256': sha, 'review': {'status': 'human-corrected', 'note': NOTE},
                  'timings': [{'index': 0, 'startMs': 10, 'endMs': 20}]}
        third.run(edited, self.dir / 'old3', timeout=30)
        reviewed = self.dir / 'old3' / 'reviewed-segments.json'
        reviewed_sha = hashlib.sha256(reviewed.read_bytes()).hexdigest()
        c.run(self.doc(reviewed, reviewed_sha, **{'width': 80, 'lines': 1}), self.dir / 'layout3', timeout=30)
        for name in ('captions.srt', 'captions.vtt'):
            self.assertEqual((self.dir / 'layout3' / name).read_bytes(), (self.dir / 'old3' / name).read_bytes(), name)
        self.assertEqual((mine / 'captions.srt').read_text(), timed_text.srt_text(machine(TEXTS)['segments']))
        self.assertEqual((mine / 'captions.vtt').read_text(), timed_text.vtt_text(machine(TEXTS)['segments']))


class Layout(Base):
    def lines(self, text, width, count=3): return c.break_cue(text, width, count, 0)

    def test_literal_layouts_choose_the_fewest_lines_then_balance_then_the_earliest_break(self):
        self.assertEqual(self.lines('Hello world', 42), ['Hello world'])
        self.assertEqual(self.lines('The quick brown fox jumps', 16), ['The quick', 'brown fox jumps'])  # 9|15 and 15|9 tie: earliest first break
        self.assertEqual(self.lines('one two three four', 14), ['one two', 'three four'])  # balanced 7|10 beats greedy 13|4
        self.assertEqual(self.lines('one two three four five six', 10), ['one two', 'three four', 'five six'])
        self.assertEqual(self.lines('aa bb cc dd ee ff gg hh', 8), ['aa bb', 'cc dd ee', 'ff gg hh'])  # (3,3,2), (3,2,3), (2,3,3) tie
        self.assertEqual(self.lines('aa bb cc dd ee ff gg', 8), ['aa bb', 'cc dd', 'ee ff gg'])
        self.assertEqual(self.lines('Fish & chips & peas', 12), ['Fish &', 'chips & peas'])
        self.assertEqual(self.lines('one', 8), ['one'])

    def test_a_cue_is_never_broken_when_it_fits_and_the_width_boundary_is_exact(self):
        text = 'can do for your country.'; self.assertEqual(len(text), 24)
        self.assertEqual(self.lines(text, 24), [text])
        self.assertEqual(self.lines(text, 23), ['can do for', 'your country.'])  # 10|13 beats 15|8 and 6|17
        self.assertEqual(self.lines('a' * 8, 8), ['aaaaaaaa'])
        self.assertEqual(self.lines('a' * 8 + ' b', 8), ['aaaaaaaa', 'b'])
        self.assertEqual(self.lines('a' * 7 + ' b', 8), ['aaaaaaa', 'b'])  # eight code points fit, the nine of 'aaaaaaa b' do not

    def test_maxlines_is_an_exact_boundary_and_the_fault_names_the_cue(self):
        three = 'aa bb cc dd ee ff gg'
        self.assertEqual(len(self.lines(three, 8, 3)), 3)
        fault = self.fault(lambda: c.break_cue(three, 8, 2, 4), 'LAYOUT_TOO_MANY_LINES', '$.source.segments[4].text')
        self.assertEqual((fault.observed['cue'], fault.observed['linesNeeded'], fault.observed['maxLines'], fault.observed['maxLineCodePoints']), (4, 3, 2, 8))
        self.fault(lambda: c.break_cue('aa bb cc dd', 8, 1, 0), 'LAYOUT_TOO_MANY_LINES')
        self.assertEqual(self.lines('aa bb cc dd', 8, 2), ['aa bb', 'cc dd'])
        four = ' '.join(['aa'] * 10); self.assertEqual(self.fault(lambda: c.break_cue(four, 8, 3, 0), 'LAYOUT_TOO_MANY_LINES').observed['linesNeeded'], 4)

    def test_a_long_word_is_refused_never_split_truncated_or_given_a_wider_line(self):
        fault = self.fault(lambda: c.break_cue('short supercalifragilistic short', 12, 3, 2), 'LAYOUT_WORD_TOO_LONG', '$.source.segments[2].text')
        self.assertEqual((fault.observed['word'], fault.observed['wordCodePoints'], fault.observed['maxLineCodePoints']), (1, 20, 12))
        self.assertEqual(self.lines('short abcdefghijkl short', 12), ['short', 'abcdefghijkl', 'short'])  # exactly the bound is allowed
        self.fault(lambda: c.break_cue('short abcdefghijklm short', 12, 3, 0), 'LAYOUT_WORD_TOO_LONG')
        # A word longer than the bound wins over a line-count refusal in the same cue.
        self.fault(lambda: c.break_cue('aa bb cc dd ee ff gg hh ii jj abcdefghij', 8, 1, 0), 'LAYOUT_WORD_TOO_LONG')
        # No-break space and ideographic space are not break opportunities, so they glue words together.
        self.fault(lambda: c.break_cue('aaaa\u00a0bbbb cc', 8, 3, 0), 'LAYOUT_WORD_TOO_LONG')
        self.assertEqual(self.lines('aaa\u00a0bbb cc', 8), ['aaa\u00a0bbb', 'cc'])
        self.fault(lambda: c.break_cue('\u4f60\u597d\u4e16\u754c\u5f88\u597d\u7684\u671f\u5f85\u5f88\u597d', 8, 3, 0), 'LAYOUT_WORD_TOO_LONG')  # unspaced script, visually narrow

    def test_adjacent_ordinary_spaces_stay_inside_one_unbreakable_run_and_are_never_normalised(self):
        self.assertEqual(self.lines('a  b', 8, 1), ['a  b'])  # fits: published exactly as it is
        self.assertEqual(self.lines('two  spaces', 80, 3), ['two  spaces'])  # the cue the old route refused although nothing had to break
        self.assertEqual(self.lines('aaaa  bb cc dd', 8, 3), ['aaaa  bb', 'cc dd'])  # 8 and 5: the only two-line choice
        self.assertEqual(self.lines('aa  b cc  d', 8, 2), ['aa  b', 'cc  d'])
        self.assertEqual(self.lines('two  spaces here', 12, 3), ['two  spaces', 'here'])
        self.assertEqual(self.lines('a   b c', 8, 3), ['a   b c'])  # three spaces are one run too
        self.assertEqual(self.lines('aaa   b cc', 8, 3), ['aaa   b', 'cc'])
        for text, width, count in (('aaaa  bb cc dd', 8, 3), ('aa  b cc  d', 8, 2), ('two  spaces here', 12, 3), ('aaa   b cc', 8, 3)):
            self.assertEqual(' '.join(self.lines(text, width, count)), text)  # joining with one space restores every character
        fault = self.fault(lambda: c.break_cue('aaaa  bbbb cc', 8, 3, 3), 'LAYOUT_WORD_TOO_LONG', '$.source.segments[3].text')
        self.assertEqual((fault.observed['cue'], fault.observed['word'], fault.observed['wordCodePoints'], fault.observed['maxLineCodePoints']), (3, 0, 10, 8))
        self.assertIn('cue 3', fault.message); self.assertIn('unbreakable run of 10 code points', fault.message)
        self.assertIn('adjacent ordinary spaces', fault.recovery)
        self.assertNotIn('LAYOUT_SPACING_UNSUPPORTED', Path(c.__file__).read_text(encoding='utf-8'))  # the refusal no longer exists

    def test_a_run_level_cue_with_adjacent_spaces_publishes_exact_literal_srt_and_webvtt_bytes(self):
        result, directory = self.job(['fine words', 'two  spaces here'], 12, 3, name='spaced')
        self.assertEqual((result['verified'], result['cues'], result['reflowedCues'], result['lines']), (True, 2, 1, 3))
        self.assertEqual((directory / 'captions.srt').read_bytes(),
                         b'1\n00:00:00,000 --> 00:00:05,500\nfine words\n\n2\n00:00:05,500 --> 00:00:11,000\ntwo  spaces\nhere\n\n')
        self.assertEqual((directory / 'captions.vtt').read_bytes(),
                         b'WEBVTT\n\n00:00:00.000 --> 00:00:05.500\nfine words\n\n00:00:05.500 --> 00:00:11.000\ntwo  spaces\nhere\n\n')
        cues = json.loads((directory / 'caption-layout.json').read_text())['cues']
        self.assertEqual([(cue['text'], cue['lines'], cue['lineCodePoints'], cue['reflowed']) for cue in cues],
                         [('fine words', ['fine words'], [10], False), ('two  spaces here', ['two  spaces', 'here'], [11, 4], True)])
        self.assertTrue(c.verify(directory)['verified'])
        # A cue that only fits on one line is still published untouched, including its adjacent spaces.
        _, fits = self.job(['two  spaces'], 80, 1, name='fits')
        self.assertEqual((fits / 'captions.srt').read_bytes(), b'1\n00:00:00,000 --> 00:00:11,000\ntwo  spaces\n\n')

    def test_code_points_are_counted_not_graphemes_display_width_or_utf16_units(self):
        decomposed = 'cafe\u0301 aux'  # nine code points, eight grapheme clusters: a grapheme count would leave it on one line of eight
        self.assertEqual(len(decomposed), 9)
        self.assertEqual(self.laid([decomposed], 8)[0], ['cafe\u0301', 'aux'])
        _, directory = self.job([decomposed], 8, 3, name='combining')
        self.assertEqual(json.loads((directory / 'caption-layout.json').read_text())['cues'][0]['lineCodePoints'], [5, 3])
        self.assertEqual(self.lines('e\u0301' * 4, 8), ['e\u0301' * 4])  # four graphemes, eight code points: exactly the bound
        self.fault(lambda: c.break_cue('e\u0301' * 4 + 'e', 8, 3, 0), 'LAYOUT_WORD_TOO_LONG')  # nine code points: one over
        self.assertEqual(self.lines('\U0001F600' * 8, 8), ['\U0001F600' * 8])  # astral code points are one each (sixteen UTF-16 units)
        family = '\U0001F468\u200d\U0001F469\u200d\U0001F467'
        self.assertEqual(len(family), 5)
        self.assertEqual(self.lines(family + ' okay', 8), [family, 'okay'])  # ten code points; as grapheme clusters it would be six and fit
        self.assertEqual(self.lines('\u4f60\u597d \u4e16\u754c \u5f88\u597d', 5), ['\u4f60\u597d', '\u4e16\u754c \u5f88\u597d'])  # 2|5 and 5|2 tie: earliest first break

    def test_the_dynamic_program_agrees_with_an_exhaustive_search_on_pseudorandom_cues(self):
        draw = lcg(59); checked = refused = doubled = 0
        for _ in range(900):
            words = [''.join(chr(97 + next(draw) % 26) for _ in range(1 + next(draw) % 12)) for _ in range(1 + next(draw) % 16)]
            # About one separator in four is two or three ordinary spaces, so the unbreakable runs are not the space-delimited words.
            text = words[0]
            for word in words[1:]: text += ' ' * (1 if next(draw) % 4 else 2 + next(draw) % 2) + word
            width, lines = 8 + next(draw) % 40, 1 + next(draw) % 3
            doubled += '  ' in text
            expected = oracle(text, width, lines)
            if expected is None:
                code = 'LAYOUT_WORD_TOO_LONG' if max(map(len, tokens(text))) > width else 'LAYOUT_TOO_MANY_LINES'
                self.fault(lambda: c.break_cue(text, width, lines, 0), code); refused += 1; continue
            actual = c.break_cue(text, width, lines, 0)
            self.assertEqual(actual, expected, (text, width, lines)); self.assertEqual(' '.join(actual), text); checked += 1
        self.assertGreater(checked, 300); self.assertGreater(refused, 40); self.assertGreater(doubled, 300)
        self.assertEqual(tokens('a  b c   d e'), ['a  b', 'c   d', 'e']); self.assertEqual(tokens('abc'), ['abc']); self.assertEqual(tokens('a b'), ['a', 'b'])

    def test_the_largest_cue_and_the_largest_document_stay_bounded(self):
        longest = ' '.join(['a'] * 128)  # 255 code points, 128 words: the most the shared cue budget allows
        self.assertEqual(len(longest), 255)
        self.fault(lambda: c.break_cue(longest, 80, 3, 0), 'LAYOUT_TOO_MANY_LINES')
        packed = ' '.join(['a'] * 120)  # 239 code points: three full lines of forty words
        self.assertEqual([len(line) for line in c.break_cue(packed, 80, 3, 0)], [79, 79, 79])
        texts = [' '.join(['a'] * 120)] * 128  # 128 cues of 239 code points: within the 32768-character document budget
        self.assertLessEqual(sum(map(len, texts)), timed_text.MAX_TOTAL_CHARACTERS)
        started = time.monotonic(); result, _ = self.job(texts, 80, 3, name='largest')
        self.assertEqual((result['cues'], result['lines']), (128, 384)); self.assertLess(time.monotonic() - started, 60)


class Publications(Base):
    def test_the_jfk_sample_publishes_exact_srt_and_webvtt_bytes_and_unchanged_cue_numbers_and_times(self):
        result, directory = c.run(self.doc(), self.dir / 'jfk', timeout=30), self.dir / 'jfk'
        self.assertEqual((directory / 'captions.srt').read_text(), SRT_24); self.assertEqual((directory / 'captions.vtt').read_text(), VTT_24)
        self.assertEqual((result['cues'], result['reflowedCues'], result['lines'], result['nativeProcesses']), (3, 2, 5, 0))
        summary = json.loads((directory / 'caption-layout.json').read_text())
        self.assertEqual([(q['index'], q['startMs'], q['endMs'], q['text']) for q in summary['cues']], [(i, s, e, TEXTS[i]) for i, (s, e) in enumerate(((0, 5410), (5410, 9040), (9040, 11000)))])
        self.assertEqual([q['lines'] for q in summary['cues']], [['And so my fellow', 'Americans, ask not what'], ['your country can do', 'for you, ask what you'], ['can do for your country.']])
        self.assertEqual([q['lineCodePoints'] for q in summary['cues']], [[16, 23], [19, 21], [24]])
        self.assertEqual([q['reflowed'] for q in summary['cues']], [True, True, False])
        for cue in summary['cues']: self.assertEqual(' '.join(cue['lines']), cue['text'])

    def test_the_artifacts_are_the_srt_the_webvtt_and_the_summary_in_that_order_and_kind(self):
        _, directory = self.job(TEXTS, name='order')
        receipt = json.loads((directory / 'verification.json').read_text())
        self.assertEqual([(Path(a['file']).name, a['kind']) for a in receipt['artifacts']], [('captions.srt', 'file'), ('captions.vtt', 'file'), ('caption-layout.json', 'text')])
        self.assertEqual(receipt['runtime'], 'host-only'); self.assertEqual(set(receipt), {'runtime', 'artifacts', 'evidence'})
        self.assertEqual(sorted(p.name for p in directory.iterdir() if not p.name.endswith('.metadata.json')),
                         ['authored.json', 'caption-layout.json', 'captions.srt', 'captions.vtt', 'captured-source.json', 'captures.json', 'plan.json',
                          'publication-metadata.json', 'result.json', 'schema.snapshot.json', 'verification.json'])

    def test_the_summary_is_closed_carries_the_source_identity_and_certifies_nothing(self):
        _, directory = self.job(TEXTS, name='summary')
        summary = json.loads((directory / 'caption-layout.json').read_text()); source = json.loads((directory / 'captured-source.json').read_text())
        self.assertEqual(set(summary), {'version', 'source', 'status', 'language', 'audioSha256', 'modelSha256', 'durationMs', 'bounds', 'policy', 'cueCount',
                                        'reflowedCueCount', 'lineCount', 'cues', 'review'})
        self.assertEqual(summary['source'], {'version': 'schemaxis.whispercpp.segments/1', 'bytes': len((directory / 'captured-source.json').read_bytes()),
                                              'sha256': hashlib.sha256((directory / 'captured-source.json').read_bytes()).hexdigest(), 'basisSha256': None})
        self.assertEqual((summary['status'], summary['language'], summary['audioSha256'], summary['modelSha256'], summary['durationMs']),
                         ('machine-draft', source['language'], source['audio']['sha256'], source['model']['sha256'], 11000))
        self.assertEqual(summary['bounds'], {'maxLineCodePoints': 24, 'maxLines': 3})
        self.assertEqual(summary['review'], {'humanReviewRequired': True, 'accuracyCertified': False, 'readabilityCertified': False, 'accessibilityCertified': False,
                                             'synchronizationCertified': False, 'identityVerified': False, 'statement': c.STATEMENT})
        self.assertNotIn(str(self.dir), json.dumps(summary), 'no source path may be published')
        for name in ('captions.srt', 'captions.vtt', 'caption-layout.json'): self.assertNotIn(str(self.dir), (directory / name).read_text())
        for cue in summary['cues']: self.assertEqual(set(cue), {'index', 'startMs', 'endMs', 'text', 'lines', 'lineCodePoints', 'reflowed'})
        self.assertEqual(summary['policy'], c.POLICY)
        self.assertIn('not a standard', summary['policy']['kind']); self.assertIn('not grapheme clusters', summary['policy']['textLength'])
        self.assertEqual((directory / 'caption-layout.json').read_bytes(), timed_text.canonical_json(summary))

    def test_srt_keeps_the_payload_plain_and_webvtt_escapes_once_per_line(self):
        _, directory = self.job(['Fish & chips & peas', 'AT&amp;T rocks'], 12, 2, name='entities')
        self.assertEqual((directory / 'captions.srt').read_text(), '1\n00:00:00,000 --> 00:00:05,500\nFish &\nchips & peas\n\n2\n00:00:05,500 --> 00:00:11,000\nAT&amp;T\nrocks\n\n')
        self.assertEqual((directory / 'captions.vtt').read_text(),
                         'WEBVTT\n\n00:00:00.000 --> 00:00:05.500\nFish &amp;\nchips &amp; peas\n\n00:00:05.500 --> 00:00:11.000\nAT&amp;amp;T\nrocks\n\n')
        summary = json.loads((directory / 'caption-layout.json').read_text())
        self.assertEqual(summary['cues'][1]['text'], 'AT&amp;T rocks'); self.assertEqual(summary['cues'][0]['lines'], ['Fish &', 'chips & peas'])
        # The bound counts the source text, never the escaped text: 'chips & peas' is twelve code points although its escape is sixteen.
        self.assertEqual(summary['cues'][0]['lineCodePoints'], [6, 12])
        # The shared renderer escapes angle brackets exactly once too (the validator refuses them in source text, so the check is direct).
        self.assertEqual(timed_text.vtt_text([{'startMs': 0, 'endMs': 1, 'text': 'a <b>\nc & d'}]), 'WEBVTT\n\n00:00:00.000 --> 00:00:00.001\na &lt;b&gt;\nc &amp; d\n\n')

    def test_a_source_that_markup_or_arrows_would_break_is_refused_by_the_shared_validator(self):
        for text in ('bold <b>text</b>', 'curly {braces}', 'a --> b', 'tab\there', 'line\nbreak', ' leading', 'trailing '):
            path, sha = self.write(machine(['fine words', text]))
            self.fault(lambda: c.run(self.doc(path, sha), self.dir / ('refused-' + str(abs(hash(text)))), timeout=30), 'TIMED_TEXT_CUE_TEXT')


class Sources(Base):
    def reviewed(self, kind):
        """A genuine reviewed/1, /2 or /3 document published by the corresponding older route from the retained draft."""
        base = {'draft': {'path': str(self.source)}, 'basisSha256': JFK_SHA}
        documents = {
            'unchanged': (first, {**base, 'version': first.VERSION, 'review': {'status': 'human-reviewed-unchanged', 'note': NOTE}}),
            'reviewed1': (first, {**base, 'version': first.VERSION, 'review': {'status': 'human-corrected', 'note': NOTE}, 'corrections': [{'index': 0, 'text': 'And so, my fellow Americans: ask not what'}]}),
            'reviewed2': (second, {**base, 'version': second.VERSION, 'review': {'status': 'human-corrected', 'note': NOTE}, 'deletions': [1]}),
            'reviewed3': (third, {**base, 'version': third.VERSION, 'review': {'status': 'human-corrected', 'note': NOTE}, 'timings': [{'index': 0, 'startMs': 120, 'endMs': 5300}]}),
            'empty2': (second, {**base, 'version': second.VERSION, 'review': {'status': 'human-corrected', 'note': NOTE}, 'deletions': [0, 1, 2]}),
            'empty3': (third, {**base, 'version': third.VERSION, 'review': {'status': 'human-corrected', 'note': NOTE}, 'deletions': [0, 1, 2]})}
        route, document = documents[kind]
        route.run(document, self.dir / ('old-' + kind), timeout=30)
        path = self.dir / ('old-' + kind) / 'reviewed-segments.json'
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_every_reviewed_version_is_laid_out_with_its_declared_status_unchanged(self):
        expected = {'unchanged': ('schemaxis.timedtext.reviewed/1', 'human-reviewed-unchanged'), 'reviewed1': ('schemaxis.timedtext.reviewed/1', 'human-corrected'),
                    'reviewed2': ('schemaxis.timedtext.reviewed/2', 'human-corrected'), 'reviewed3': ('schemaxis.timedtext.reviewed/3', 'human-corrected')}
        for kind, (version, status) in expected.items():
            path, sha = self.reviewed(kind)
            result = c.run(self.doc(path, sha), self.dir / ('layout-' + kind), timeout=30)
            summary = json.loads((self.dir / ('layout-' + kind) / 'caption-layout.json').read_text()); original = json.loads(path.read_text())
            self.assertEqual((summary['source']['version'], summary['status'], result['reviewStatus'], result['sourceVersion']), (version, status, status, version), kind)
            self.assertEqual(summary['source']['basisSha256'], original['review']['basis']['sha256'], kind)
            self.assertEqual([(q['startMs'], q['endMs'], q['text']) for q in summary['cues']], [(s['startMs'], s['endMs'], s['text']) for s in original['segments']], kind)
            self.assertEqual((summary['review']['humanReviewRequired'], summary['review']['identityVerified'], summary['review']['accuracyCertified']), (True, False, False))
            self.assertEqual(c.verify(self.dir / ('layout-' + kind))['reviewStatus'], status)

    def test_a_retimed_source_keeps_its_edited_times_exactly(self):
        path, sha = self.reviewed('reviewed3')
        c.run(self.doc(path, sha), self.dir / 'retimed', timeout=30)
        self.assertTrue((self.dir / 'retimed' / 'captions.srt').read_text().startswith('1\n00:00:00,120 --> 00:00:05,300\nAnd so my fellow\nAmericans, ask not what\n\n2\n00:00:05,410'))
        self.assertTrue((self.dir / 'retimed' / 'captions.vtt').read_text().startswith('WEBVTT\n\n00:00:00.120 --> 00:00:05.300\nAnd so my fellow\n'))

    def test_a_source_with_every_cue_deleted_publishes_an_empty_srt_a_webvtt_header_and_no_invented_cue(self):
        for kind in ('empty2', 'empty3'):
            path, sha = self.reviewed(kind)
            result = c.run(self.doc(path, sha), self.dir / ('layout-' + kind), timeout=30); directory = self.dir / ('layout-' + kind)
            self.assertEqual((directory / 'captions.srt').read_bytes(), b''); self.assertEqual((directory / 'captions.vtt').read_bytes(), b'WEBVTT\n\n')
            summary = json.loads((directory / 'caption-layout.json').read_text())
            self.assertEqual((summary['cues'], summary['cueCount'], summary['reflowedCueCount'], summary['lineCount']), ([], 0, 0, 0))
            self.assertEqual((result['cues'], result['lines'], result['reviewStatus'], result['verified']), (0, 0, 'human-corrected', True))
            self.assertTrue(c.verify(directory)['verified'])

    def test_the_older_routes_still_publish_their_literal_single_line_captions(self):
        self.reviewed('reviewed2')
        self.assertEqual((self.dir / 'old-reviewed2' / 'captions.srt').read_text(),
                         '1\n00:00:00,000 --> 00:00:05,410\n' + TEXTS[0] + '\n\n2\n00:00:09,040 --> 00:00:11,000\n' + TEXTS[2] + '\n\n')
        self.assertEqual(second.verify(self.dir / 'old-reviewed2')['deletions'], 1)

    def test_a_machine_draft_status_is_never_promoted(self):
        result = c.run(self.doc(), self.dir / 'machine', timeout=30)
        self.assertEqual((result['reviewStatus'], result['humanReviewRequired'], result['accuracyCertified'], result['readabilityCertified'], result['accessibilityCertified'],
                          result['synchronizationCertified'], result['identityVerified']), ('machine-draft', True, False, False, False, False, False))

    def test_unreadable_unpinned_or_invalid_sources_are_refused_with_distinct_faults(self):
        self.fault(lambda: c.run(self.doc(sha='0' * 64), self.dir / 'stale', timeout=30), 'LAYOUT_SOURCE_STALE', '$.sourceSha256')
        self.assertFalse((self.dir / 'stale' / 'captured-source.json').exists() and (self.dir / 'stale' / 'captions.srt').exists())
        self.fault(lambda: c.run(self.doc(self.dir / 'absent.json', JFK_SHA), self.dir / 'absent', timeout=30), 'SOURCE_MISSING')
        (self.dir / 'file.txt').write_text('x')
        self.fault(lambda: c.run(self.doc(self.dir / 'file.txt' / 'inner.json', JFK_SHA), self.dir / 'notdir', timeout=30), 'SOURCE_MISSING')
        os.symlink(self.source, self.dir / 'link.json')
        self.fault(lambda: c.run(self.doc(self.dir / 'link.json', JFK_SHA), self.dir / 'linked', timeout=30), 'INVALID_SOURCE')
        (self.dir / 'folder.json').mkdir()
        self.fault(lambda: c.run(self.doc(self.dir / 'folder.json', JFK_SHA), self.dir / 'folded', timeout=30), 'INVALID_SOURCE')
        os.mkfifo(self.dir / 'fifo.json')
        self.fault(lambda: c.run(self.doc(self.dir / 'fifo.json', JFK_SHA), self.dir / 'fifoed', timeout=30), 'INVALID_SOURCE')
        self.fault(lambda: c.bounded('/dev/null', 'INVALID_SOURCE', 'SOURCE_MISSING'), 'INVALID_SOURCE')
        huge = self.dir / 'huge.json'
        with open(huge, 'wb') as stream: stream.truncate(timed_text.MAX_DOCUMENT_BYTES + 1)
        self.fault(lambda: c.run(self.doc(huge, JFK_SHA), self.dir / 'hugeout', timeout=30), 'INVALID_SOURCE')

    def test_documents_the_shared_validator_refuses_stay_refused_with_the_validators_codes(self):
        document = machine(TEXTS)
        cases = {
            'duplicate-key': (self.source.read_bytes().replace(b'"language"', b'"timeUnit": "millisecond", "language"', 1), 'TIMED_TEXT_INVALID_JSON'),
            'extra-key': ({**document, 'extra': 1}, 'TIMED_TEXT_UNKNOWN_KEY'),
            'version': ({**document, 'version': 'schemaxis.whispercpp.segments/2'}, 'TIMED_TEXT_UNSUPPORTED_VERSION'),
            'no-cues': ({**document, 'segments': [], 'segmentCount': 0}, 'TIMED_TEXT_INVALID'),
            'overlap': ({**document, 'segments': [dict(document['segments'][0], endMs=6000), dict(document['segments'][1], startMs=5410)] + document['segments'][2:]}, 'TIMED_TEXT_TIMING'),
            'review-status': ({**document, 'review': {**document['review'], 'humanReviewRequired': False}}, 'TIMED_TEXT_REVIEW_UNSUPPORTED'),
            'too-long-cue': (machine(['a ' * 128 + 'a']), 'TIMED_TEXT_RESOURCE_LIMIT'),
            'not-json': (b'\xff\xfe', 'TIMED_TEXT_INVALID_JSON')}
        for label, (content, code) in cases.items():
            path, sha = self.write(content, label + '.json')
            self.fault(lambda: c.run(self.doc(path, sha), self.dir / ('out-' + label), timeout=30), code, None)
            self.assertEqual(json.loads((self.dir / ('out-' + label) / 'result.json').read_text())['status'], 'failed', label)


class Lifecycle(Base):
    def test_a_changed_source_is_refused_before_and_during_the_run(self):
        self.source.write_bytes(self.source.read_bytes().replace(b'country', b'countrx', 1))
        self.fault(lambda: c.run(self.doc(sha=JFK_SHA), self.dir / 'before', timeout=30), 'LAYOUT_SOURCE_STALE')
        shutil.copyfile(JFK, self.source); real = c.bounded; calls = []
        def changing(path, *arguments, **keywords):
            data = real(path, *arguments, **keywords); calls.append(path)
            if len(calls) == 1: Path(path).write_bytes(data.replace(b'country', b'countrx', 1))
            return data
        with patch.object(c, 'bounded', side_effect=changing):
            self.fault(lambda: c.run(self.doc(), self.dir / 'during', timeout=30), 'LAYOUT_SOURCE_CHANGED', '$.source.path')
        # Files written before the second read may remain; they are unverified and `verify` refuses the directory.
        self.assertFalse((self.dir / 'during' / 'verification.json').exists())
        self.assertEqual(json.loads((self.dir / 'during' / 'result.json').read_text())['status'], 'failed')
        self.fault(lambda: c.verify(self.dir / 'during'), 'VERIFICATION_FAILED')
        shutil.copyfile(JFK, self.source)

    def test_a_source_removed_during_the_run_is_a_changed_source(self):
        real = c.bounded; calls = []
        def vanishing(path, *arguments, **keywords):
            calls.append(path)
            if len(calls) == 2: os.unlink(path)
            return real(path, *arguments, **keywords)
        with patch.object(c, 'bounded', side_effect=vanishing):
            fault = self.fault(lambda: c.run(self.doc(), self.dir / 'vanished', timeout=30), 'LAYOUT_SOURCE_CHANGED')
        self.assertEqual(fault.observed['cause']['code'], 'SOURCE_MISSING')

    def test_the_output_directory_must_be_fresh_and_a_bad_timeout_starts_nothing(self):
        c.run(self.doc(), self.dir / 'one', timeout=30)
        self.fault(lambda: c.run(self.doc(), self.dir / 'one', timeout=30), 'OUTPUT_EXISTS')
        os.symlink(self.dir / 'one', self.dir / 'linked-out')
        self.fault(lambda: c.run(self.doc(), self.dir / 'linked-out', timeout=30), 'OUTPUT_EXISTS')
        for timeout in (0, -1, 3601, float('nan'), float('inf'), True, '30', None):
            self.fault(lambda: c.run(self.doc(), self.dir / 'never', timeout=timeout), 'INVALID_ARGUMENT'); self.assertFalse((self.dir / 'never').exists())

    def test_cancellation_and_the_deadline_before_any_write_stop_the_run_with_a_failed_result_and_no_verification(self):
        with patch.object(c, 'cancellation_requested', return_value=True):
            self.fault(lambda: c.run(self.doc(), self.dir / 'cancelled', timeout=30), 'RUNNER_CANCELLED')
        flags = iter([False, False, False, True]); texts = machine(TEXTS)
        path, sha = self.write(texts)
        with patch.object(c, 'cancellation_requested', side_effect=lambda: next(flags, True)):
            self.fault(lambda: c.run(self.doc(path, sha), self.dir / 'midway', timeout=30), 'RUNNER_CANCELLED')
        ticks = iter([0.0, 0.0, 0.0, 100.0, 100.0, 100.0, 100.0, 100.0])
        with patch.object(c.time, 'monotonic', side_effect=lambda: next(ticks, 1000.0)):
            self.fault(lambda: c.run(self.doc(), self.dir / 'timed-out', timeout=5), 'RUNNER_TIMED_OUT')
        for name in ('cancelled', 'midway', 'timed-out'):  # these stop before any publication is written; a later failure may leave unverified files
            directory = self.dir / name
            self.assertEqual(json.loads((directory / 'result.json').read_text())['status'], 'failed', name)
            self.assertEqual(sorted(p.name for p in directory.iterdir() if p.name.startswith('captions') or p.name == 'caption-layout.json'), [], name)
            self.assertFalse((directory / 'verification.json').exists(), name)
            self.fault(lambda: c.verify(directory), 'VERIFICATION_FAILED')

    def test_a_native_executable_is_never_launched_or_needed(self):
        fake = self.dir / 'bin' / 'whisper-cli'; fake.parent.mkdir(); marker = self.dir / 'sentinel.marker'
        fake.write_text(f'#!/bin/sh\necho {SENTINEL} > {marker}\nexit 0\n'); fake.chmod(0o755)
        with patch('subprocess.Popen', side_effect=AssertionError('process')), patch('subprocess.run', side_effect=AssertionError('process')), patch('os.execv', side_effect=AssertionError('exec')):
            result = c.run(self.doc(), self.dir / 'hosted', executable=str(fake), timeout=30); c.verify(self.dir / 'hosted')
        self.assertEqual((result['runtime'], result['nativeProcesses']), ('host-only', 0)); self.assertFalse(marker.exists())
        self.assertEqual(c.verify(self.dir / 'hosted')['artifacts'], 3)


class Verification(Base):
    """Every probe refreshes all ordinary hashes and publication metadata, so only independent replay can notice the change."""

    def setUp(self):
        super().setUp()
        c.run(self.doc(), self.dir / 'run', timeout=30); self.directory = self.dir / 'run'
        self.saved = {p: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}
        self.assertTrue(c.verify(self.directory)['verified'])

    def restore(self):
        for path in sorted((p for p in self.directory.rglob('*') if p not in self.saved), key=lambda q: len(q.parts), reverse=True):
            if path.is_symlink() or path.is_file(): path.unlink()
            elif path.is_dir(): shutil.rmtree(path)
        for path, data in self.saved.items(): path.write_bytes(data)

    def forge(self, name, mutate, refresh=True, code='VERIFICATION_FAILED'):
        path = self.directory / name; original = path.read_bytes(); changed = mutate(original)
        self.assertNotEqual(changed, original, 'vacuous probe ' + name); path.write_bytes(changed)
        if refresh: self.refresh(self.directory)
        try: self.fault(lambda: c.verify(self.directory), code)
        finally: self.restore()
        self.assertTrue(c.verify(self.directory)['verified'])

    def edit(self, name, change):
        def mutate(data):
            value = json.loads(data); change(value); return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode('utf-8') + b'\n'
        return mutate

    def test_a_clean_run_verifies_from_the_retained_bytes_alone(self):
        result = c.verify(self.directory)
        self.assertEqual((result['verified'], result['artifacts'], result['cues'], result['reflowedCues'], result['lines']), (True, 3, 3, 2, 5))
        self.source.unlink()  # the original source may be gone: nothing outside the run directory is consulted
        self.assertTrue(c.verify(self.directory)['verified'])

    def test_altered_publications_are_found_by_replay_even_with_every_hash_refreshed(self):
        self.forge('captions.srt', lambda b: b.replace(b'And so my fellow\nAmericans,', b'And so my\nfellow Americans,'))
        self.forge('captions.srt', lambda b: b.replace(b'00:00:09,040 --> 00:00:11,000', b'00:00:09,041 --> 00:00:11,000'))
        self.forge('captions.srt', lambda b: b.replace(b'fellow', b'fellows'))
        self.forge('captions.srt', lambda b: b + b'\n')
        self.forge('captions.vtt', lambda b: b.replace(b'WEBVTT\n\n', b'WEBVTT\n\nNOTE x\n\n'))
        self.forge('captions.vtt', lambda b: b.replace(b'for you, ask what you', b'for you, ask what\nyou'))
        self.forge('captions.vtt', lambda b: b.replace(b'--> 00:00:05.410', b'--> 00:00:05.411', 1))

    def test_adjacent_spaces_collapsed_or_broken_in_a_publication_are_found_even_with_every_hash_refreshed(self):
        path, sha = self.write(machine(['fine words', 'two  spaces here']), 'spaced-source.json')
        c.run(self.doc(path, sha, 12, 3), self.dir / 'spaced', timeout=30)
        self.directory = self.dir / 'spaced'; self.saved = {p: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}
        self.assertTrue(c.verify(self.directory)['verified'])
        self.forge('captions.srt', lambda b: b.replace(b'two  spaces', b'two spaces'))
        self.forge('captions.vtt', lambda b: b.replace(b'two  spaces', b'two spaces'))
        self.forge('captions.srt', lambda b: b.replace(b'two  spaces\nhere', b'two\nspaces here'))
        self.forge('captions.srt', lambda b: b.replace(b'two  spaces', b'two \n spaces'))
        self.forge('caption-layout.json', self.edit('caption-layout.json', lambda d: d['cues'][1].update(text='two spaces here')))

    def test_altered_summaries_are_found_even_when_they_stay_valid_json_and_hashes_are_refreshed(self):
        for label, change in (
                ('source-sha', lambda v: v['source'].update(sha256='0' * 64)),
                ('source-bytes', lambda v: v['source'].update(bytes=v['source']['bytes'] + 1)),
                ('source-version', lambda v: v['source'].update(version='schemaxis.timedtext.reviewed/1')),
                ('status-promoted', lambda v: v.update(status='human-reviewed-unchanged')),
                ('accuracy', lambda v: v['review'].update(accuracyCertified=True)),
                ('readability', lambda v: v['review'].update(readabilityCertified=True)),
                ('accessibility', lambda v: v['review'].update(accessibilityCertified=True)),
                ('synchronization', lambda v: v['review'].update(synchronizationCertified=True)),
                ('identity', lambda v: v['review'].update(identityVerified=True)),
                ('human-review-waived', lambda v: v['review'].update(humanReviewRequired=False)),
                ('statement', lambda v: v['review'].update(statement='fine')),
                ('bounds', lambda v: v['bounds'].update(maxLines=2)),
                ('policy', lambda v: v['policy'].update(kind='certified')),
                ('word', lambda v: v['cues'][0].update(text=v['cues'][0]['text'].replace('fellow', 'fellows'))),
                ('lines', lambda v: v['cues'][0].update(lines=['And so my', 'fellow Americans, ask not what'])),
                ('lengths', lambda v: v['cues'][0].update(lineCodePoints=[16, 24])),
                ('reflowed', lambda v: v['cues'][2].update(reflowed=True)),
                ('time', lambda v: v['cues'][1].update(startMs=5411)),
                ('index', lambda v: v['cues'][1].update(index=7)),
                ('count', lambda v: v.update(cueCount=2)),
                ('extra-member', lambda v: v.update(note='x')),
                ('dropped-cue', lambda v: v['cues'].pop()),
                ('audio-digest', lambda v: v.update(audioSha256='f' * 64)),
                ('language', lambda v: v.update(language='fr'))):
            with self.subTest(label): self.forge('caption-layout.json', self.edit('caption-layout.json', change))

    def test_altered_receipts_results_plans_and_evidence_are_refused(self):
        self.forge('result.json', self.edit('result.json', lambda v: v.update(cues=2)), refresh=False)
        self.forge('result.json', self.edit('result.json', lambda v: v.update(cues=3.0)), refresh=False)
        self.forge('result.json', self.edit('result.json', lambda v: v.update(accuracyCertified=True)), refresh=False)
        self.forge('result.json', self.edit('result.json', lambda v: v.update(verified=1)), refresh=False)
        self.forge('result.json', self.edit('result.json', lambda v: v.update(status='failed')), refresh=False, code='INCOMPLETE_EXECUTION')
        self.forge('result.json', self.edit('result.json', lambda v: v.update(reviewStatus='human-corrected')), refresh=False)
        self.forge('result.json', self.edit('result.json', lambda v: v.update(extra=True)), refresh=False)
        self.forge('verification.json', self.edit('verification.json', lambda v: v.update(runtime='whisper.cpp 1.9.5')), refresh=False)
        self.forge('verification.json', self.edit('verification.json', lambda v: v.update(executable='/usr/bin/whisper-cli')), refresh=False)
        self.forge('verification.json', self.edit('verification.json', lambda v: v.update(profile={'native': True})), refresh=False)
        self.forge('verification.json', self.edit('verification.json', lambda v: v['artifacts'].reverse()), refresh=False)
        self.forge('verification.json', self.edit('verification.json', lambda v: v['artifacts'].pop()), refresh=False)
        self.forge('verification.json', self.edit('verification.json', lambda v: v['artifacts'][0].update(kind='text')), refresh=False)
        self.forge('verification.json', self.edit('verification.json', lambda v: v['evidence'].update({'plan.json': '0' * 64})), refresh=False)
        self.forge('plan.json', self.edit('plan.json', lambda v: v.update(maxLines=2)))
        self.forge('plan.json', self.edit('plan.json', lambda v: v['losses'].pop()))
        self.forge('authored.json', self.edit('authored.json', lambda v: v.update(maxLineCodePoints=30)))
        self.forge('authored.json', self.edit('authored.json', lambda v: v.update(extra=1)))
        self.forge('captures.json', self.edit('captures.json', lambda v: v.update(bytes=v['bytes'] + 1)))
        self.forge('captures.json', self.edit('captures.json', lambda v: v.update(source='/elsewhere/source.json')))
        self.forge('captured-source.json', lambda b: b.replace(b'country', b'countrx', 1))

    def test_a_replaced_source_with_the_pin_unchanged_is_refused_but_a_coherent_rewrite_is_only_new_consistent_data(self):
        other = machine(['Another invented line of speech', 'and one more']); other_path, other_sha = self.write(other, 'other.json')
        self.forge('captured-source.json', lambda b: other_path.read_bytes())
        # A complete, coherent rewrite (new source, new pin, republished files, refreshed receipt) verifies: verification is replay, not authentication.
        authored = self.doc(other_path, other_sha); c.run(authored, self.dir / 'rewrite', timeout=30)
        for name in ('authored.json', 'plan.json', 'captures.json', 'captured-source.json', 'captions.srt', 'captions.vtt', 'caption-layout.json', 'result.json'):
            (self.directory / name).write_bytes((self.dir / 'rewrite' / name).read_bytes())
        self.refresh(self.directory)
        try:
            self.assertEqual(c.verify(self.directory)['sourceSha256'], other_sha)
            self.assertIn('Another invented', (self.directory / 'captions.srt').read_text())
        finally: self.restore()

    def test_foreign_members_links_and_native_leftovers_break_membership(self):
        for name in ('transcribe-launcher.py', 'transcribe-submission.json', 'model.json', 'native.json', 'runtime.json', 'captured-audio.wav', 'extra.txt', 'caption-review.json'):
            (self.directory / name).write_text('x'); self.assertTrue(self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED').location == name, name); self.restore()
        os.symlink(self.directory / 'captions.srt', self.directory / 'linked.srt')
        self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED'); self.restore()
        (self.directory / 'subdirectory').mkdir(); self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED'); self.restore()
        planted = self.directory / '.dispatch'; planted.mkdir(); marker = self.dir / 'ran.marker'
        (planted / 'replay-x.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("ran")\n')
        self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED'); self.assertFalse(marker.exists())
        self.restore(); self.assertTrue(c.verify(self.directory)['verified'])
        (self.directory / 'captions.srt').unlink(); self.fault(lambda: c.verify(self.directory), 'VERIFICATION_FAILED'); self.restore()
        os.symlink(self.dir / 'run' / 'captions.vtt', self.dir / 'run' / 'swap'); (self.directory / 'swap').unlink()
        (self.directory / 'result.json').write_text('{"status": "incomplete", "verified": false}')
        self.fault(lambda: c.verify(self.directory), 'INCOMPLETE_EXECUTION'); self.restore()
        self.assertEqual(c.verify(self.directory, require_result=False)['verified'], True)


class Interfaces(Base):
    def cli(self, *arguments):
        if arguments and arguments[0] == 'run':
            arguments = (*arguments, '--backend', 'native')
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), 'SCHEMAXIS_WHISPERCPP': '/nonexistent/whisper-cli', 'PATH': '/nonexistent'}
        return subprocess.run([sys.executable, '-m', 'schemaxis', *arguments], capture_output=True, text=True, env=environment, cwd=self.dir, timeout=120)

    def test_cli_plan_run_and_verify_without_any_whisper_executable(self):
        document = self.dir / 'document.json'; document.write_text(json.dumps(self.doc()))
        planned = self.cli('plan', str(document)); self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual((json.loads(planned.stdout)['maxLineCodePoints'], json.loads(planned.stdout)['operation']), (24, 'layout'))
        ran = self.cli('run', str(document), '--output-directory', str(self.dir / 'cli-run')); self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertEqual((json.loads(ran.stdout)['runtime'], json.loads(ran.stdout)['reflowedCues']), ('host-only', 2))
        self.assertEqual((self.dir / 'cli-run' / 'captions.srt').read_text(), SRT_24)
        checked = self.cli('verify', str(self.dir / 'cli-run')); self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertTrue(json.loads(checked.stdout)['verified'])
        bad = self.dir / 'bad.json'; bad.write_text(json.dumps(self.doc(width=8)))
        failed = self.cli('run', str(bad), '--output-directory', str(self.dir / 'cli-bad')); self.assertNotEqual(failed.returncode, 0)
        self.assertIn('LAYOUT_WORD_TOO_LONG', failed.stdout + failed.stderr)

    def test_discovery_and_guidance_cover_every_field_of_the_route(self):
        guidance = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/guidance.json').read_text())
        fields = guidance['routes'][c.VERSION]['fields']
        for pointer in ('', '/properties/version', '/properties/operation', '/properties/source', '/properties/source/properties/path', '/properties/sourceSha256',
                        '/properties/maxLineCodePoints', '/properties/maxLines'):
            self.assertEqual(fields[pointer]['status'], 'reviewed', pointer)
        from schemaxis.adaptors.whispercpp import capabilities
        catalogue = capabilities.catalogue()
        self.assertIn('captions/1', ' '.join(catalogue['requirements']))
        self.assertIn('caption line layout', catalogue['application']['keywords'])
        readiness = json.loads((ROOT / 'src/schemaxis/adaptors/whispercpp/readiness.json').read_text())['routes'][c.VERSION]
        self.assertIn('tests/unit/test_whispercpp_caption_layout.py', readiness['conformance'])
        self.assertIn('tools/qualify_whispercpp_caption_layout.py', readiness['acceptance'])

    def test_shipped_examples_plan_and_the_invalid_ones_refuse_for_their_stated_reason(self):
        for name in ('whispercpp-caption-layout', 'whispercpp-caption-layout-two-lines'):
            document = json.loads((ROOT / f'examples/schemaxis/{name}.json').read_text())
            self.assertEqual(document['sourceSha256'], JFK_SHA); c.plan(document)
        invalid = {'whispercpp-caption-layout-word-invalid': 'LAYOUT_WORD_TOO_LONG', 'whispercpp-caption-layout-lines-invalid': 'LAYOUT_TOO_MANY_LINES'}
        for name, code in invalid.items():
            document = json.loads((ROOT / f'examples/schemaxis/{name}.json').read_text()); c.plan(document)  # schema-valid; refused only against the source
            document['source']['path'] = str(self.source)
            self.fault(lambda: c.run(document, self.dir / name, timeout=30), code, '$.source.segments[0].text')
        self.fault(lambda: c.plan(json.loads((ROOT / 'examples/schemaxis/whispercpp-caption-layout-relative-invalid.json').read_text())), 'INVALID_SOURCE', '$.source.path')
        self.fault(lambda: c.plan(json.loads((ROOT / 'examples/schemaxis/whispercpp-caption-layout-bounds-invalid.json').read_text())), 'INVALID_ARGUMENT', '$.maxLines')
        graph = json.loads((ROOT / 'examples/schemaxis/whispercpp-caption-layout-workflow.json').read_text())
        self.assertEqual([o['id'] for o in graph['operations']], ['correct', 'layout'])
        self.assertEqual(graph['operations'][1]['document']['source']['path'], {'$artifact': 'correct', 'index': 0})
        correction = copy.deepcopy(graph['operations'][0]['document']); correction['draft']['path'] = str(self.source)
        first.run(correction, self.dir / 'chained', timeout=30)  # the literal pin in the example is the digest of this correction's reviewed-segments.json
        self.assertEqual(graph['operations'][1]['document']['sourceSha256'], hashlib.sha256((self.dir / 'chained' / 'reviewed-segments.json').read_bytes()).hexdigest())
        self.assertTrue(graph['operations'][0]['document']['review']['note'].startswith('Illustrative')); self.assertIn('no person', graph['operations'][0]['document']['review']['note'])


class Qualifier(Base):
    TOOL = ROOT / 'tools/qualify_whispercpp_caption_layout.py'

    def load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('qualify_whispercpp_caption_layout_under_test', self.TOOL)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

    def test_optimized_python_is_refused_before_any_work_or_output(self):
        for flags, extra in ((['-O'], {}), (['-OO'], {}), ([], {'PYTHONOPTIMIZE': '1'})):
            out = self.dir / ('never-created-' + str(len(flags)) + str(sorted(extra)))
            environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src'), **extra}
            done = subprocess.run([sys.executable, *flags, str(self.TOOL), '--ffmpeg', '/nonexistent/ffmpeg', '--output-directory', str(out)],
                                  capture_output=True, text=True, timeout=60, env=environment, cwd=self.dir)
            self.assertNotEqual(done.returncode, 0); self.assertIn('refused', done.stderr + done.stdout); self.assertIn('-O', done.stderr + done.stdout)
            self.assertFalse(out.exists(), 'no output directory may be created before the refusal')

    def test_the_hand_written_native_expectations_are_what_the_route_publishes_on_the_host(self):
        """The qualifier's literals are checked here without any native process, so a native pass cannot rest on a wrong expectation."""
        q = self.load()
        audio = q.write_wav(self.dir / 'speech.wav', q.samples(q.SAMPLES))
        source = self.dir / 'timed-text.json'; source.write_bytes(q.source_document(q.CUES, audio)); pin = hashlib.sha256(source.read_bytes()).hexdigest()
        c.run(q.layout_document(str(source), pin), self.dir / 'qualifier-fixture', timeout=30)
        counts = q.check_publications(self.dir / 'qualifier-fixture', q.LINES, q.EXPECTED_SRT, q.EXPECTED_VTT, q.CUES)
        self.assertEqual(counts['cues'], 2)
        self.assertEqual(self.laid([cue[2] for cue in q.CUES], 20), q.LINES)
        for text, lines in zip((cue[2] for cue in q.CUES), q.LINES): self.assertEqual(oracle(text, 20, 3), lines)
        second = self.dir / 'second.json'; second.write_bytes(q.source_document(q.SECOND, audio)); second_pin = hashlib.sha256(second.read_bytes()).hexdigest()
        c.run(q.layout_document(str(second), second_pin), self.dir / 'second-fixture', timeout=30)
        self.assertEqual((self.dir / 'second-fixture' / 'captions.srt').read_text(encoding='utf-8'), q.SECOND_SRT)
        self.assertEqual(audio.stat().st_size, 44 + 2 * q.SAMPLES); self.assertEqual(q.SAMPLES / q.RATE, q.FRAMES / q.FPS)
        # The two-second fixtures meet the FFmpeg review consumer limits, which this work does not loosen: at most four lines, no markup characters.
        for cue in q.LINES: self.assertLessEqual(len(cue), 4); self.assertFalse(any(ch in line for line in cue for ch in '<>{}\\'))
        self.assertEqual(q.vtt_cues(q.EXPECTED_VTT)[1][2][0], 'Fish & chips')


if __name__ == '__main__':
    unittest.main()
