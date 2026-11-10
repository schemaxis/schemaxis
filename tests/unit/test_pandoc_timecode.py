"""Pandoc transcript `timeFormat`: exact HH:MM:SS.mmm, an absent field kept absent, and verification of the claimed format."""
import copy
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.pandoc import adaptor
from schemaxis.core import timed_text
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import test_timed_text as source  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
# Fingerprints of what a transcript block WITHOUT the field produced before the field existed (computed from the
# pre-change development adaptor source with the procedure in `fingerprint`); the field must not change a byte of them.
BEFORE = {'plan': '307cc9accdcbbc2152c4c339f3decb27183aaf17179361735d41052d1890296b',
          'content': '14681a4cc9f607375ac0c4412eb1089613818e4e69280c8ed70a0c58ea4554b4',
          'summary': '8e01ddd33039bad555e9b880bbeb092f0dc16ee5c77511817153b646a08bab57',
          'ast': '365fae2b6eab12640fc45dc98b407a8ba27d96e1e144edd47b2c1975f67f9125',
          'model': '64c0c80587526801abc3b637995b89ec373fe383ef2dca03d062fe1ec309aaf0',
          'captured': '05c42bc185c366299b3fae0de5f1d7af193eccc76296a6ded62d82f413330907',
          'result': 'b22a120ee94bd197d09af198928f15d816e590f6a0100f10081ab5e75622e44f'}
MS_COLUMNS = ['Start (ms)', 'End (ms)', 'Text']
TC_COLUMNS = ['Start (HH:MM:SS.mmm)', 'End (HH:MM:SS.mmm)', 'Text']


def block(path='/x/segments.json', fmt=None, sha256=None):
    segments = {'path': str(path), **({'sha256': sha256} if sha256 else {})}
    return {'kind': 'transcript', 'segments': segments, **({'timeFormat': fmt} if fmt is not None else {})}


def report(*blocks, path='/x/segments.json'):
    content = [{'heading': f'Part {i + 1}', 'content': [b]} for i, b in enumerate(blocks or [block(path)])]
    return {'version': adaptor.VERSION, 'operation': 'report', 'title': 'Interview transcript', 'sections': content}


def long_document(cues, language='en'):
    """A valid machine draft whose audio is long enough for every cue; durations are whole seconds."""
    value = source.document(); end = max(end for _, end, _ in cues); seconds = -(-end // 1000)
    value['segments'] = [{'index': i, 'startMs': s, 'endMs': e, 'text': t} for i, (s, e, t) in enumerate(cues)]
    value['segmentCount'] = len(cues); value['language'] = language
    value['audio'].update(frames=16000 * seconds, durationMs=seconds * 1000, bytes=32000 * seconds + 44)
    return value


def fingerprint(module, directory):
    """Digests of the observable output of a transcript block with no `timeFormat`, for the pinned comparison."""
    def sha(value): return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    data = source.encode(source.document()); (directory / 'transcript-0-0.json').write_bytes(data)
    document = report(path='/x/segments.json'); prepared = module.plan(document)
    view = module.transcript_view(data, '$')
    tree = module.ast(prepared, [1, 23], directory)
    with patch('schemaxis.adaptors.pandoc.inspection.html_report'), patch('schemaxis.adaptors.pandoc.inspection.docx_report'), \
            patch('schemaxis.adaptors.pandoc.inspection.ast_report'):
        (directory / 'report.html').write_bytes(b'x'); (directory / 'report.docx').write_bytes(b'x'); (directory / 'reopened.json').write_text('{}')
        summary = module.inspect(directory, prepared)
    model = module.expected({**prepared, '_directory': directory})
    captured = module.transcript_summary(prepared['sections'][0]['content'][0], view)
    return {'plan': sha(prepared), 'content': sha(module.transcript_content(view)), 'summary': sha(summary), 'ast': sha(tree),
            'model': sha(model), 'captured': sha(captured),
            'result': sha({k: summary[k] for k in ('sections', 'blocks', 'tables', 'images', 'transcripts') if k in summary})}


class Formatter(unittest.TestCase):
    def test_boundaries_are_exact_integer_arithmetic(self):
        for ms, text in ((0, '00:00:00.000'), (1, '00:00:00.001'), (999, '00:00:00.999'), (1000, '00:00:01.000'), (1001, '00:00:01.001'),
                         (59999, '00:00:59.999'), (60000, '00:01:00.000'), (60001, '00:01:00.001'), (3599999, '00:59:59.999'),
                         (3600000, '01:00:00.000'), (3600001, '01:00:00.001'), (86399999, '23:59:59.999'), (86400000, '24:00:00.000'),
                         (359999999, '99:59:59.999'), (360000000, '100:00:00.000'), (360000001, '100:00:00.001'),
                         (2 ** 53, '2501999792:59:00.992')):
            with self.subTest(ms=ms): self.assertEqual(adaptor.timecode(ms), text)

    def test_every_value_round_trips_to_the_same_integer(self):
        generator = random.Random(47)
        for ms in [generator.randrange(0, 2 ** 53 + 1) for _ in range(5000)] + [generator.randrange(0, 4000000) for _ in range(5000)]:
            text = adaptor.timecode(ms); clock, fraction = text.split('.')
            hours, minutes, seconds = (int(part) for part in clock.split(':'))
            self.assertEqual((len(fraction), len(clock.split(':')[1]), len(clock.split(':')[2])), (3, 2, 2), text)
            self.assertLess(minutes, 60); self.assertLess(seconds, 60)
            self.assertEqual(((hours * 60 + minutes) * 60 + seconds) * 1000 + int(fraction), ms, text)

    def test_other_values_are_refused_never_coerced(self):
        for value in (-1, 1.0, 1.5, '1', None, True, False, float('nan'), float('inf'), [1]):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError): adaptor.timecode(value)


class Planning(unittest.TestCase):
    def fault(self, document, code='INVALID_ARGUMENT'):
        with self.assertRaises(SchemaxisError) as caught: adaptor.plan(document)
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.message)
        return caught.exception.fault

    def test_an_absent_field_stays_absent_and_the_plan_is_the_old_plan(self):
        planned = adaptor.plan(report())
        self.assertNotIn('timeFormat', planned['sections'][0]['content'][0])
        self.assertEqual(planned['losses'], [*adaptor.LOSSES, adaptor.TRANSCRIPT_LOSS])
        self.assertEqual(planned['sections'][0]['content'][0], {'kind': 'transcript', 'segments': {'path': '/x/segments.json'}})

    def test_the_value_is_planned_exactly_as_authored(self):
        for fmt in ('milliseconds', 'timecode'):
            with self.subTest(fmt):
                self.assertEqual(adaptor.plan(report(block(fmt=fmt)))['sections'][0]['content'][0]['timeFormat'], fmt)
        explicit = adaptor.plan(report(block(fmt='milliseconds')))
        self.assertEqual(explicit['losses'], [*adaptor.LOSSES, adaptor.TRANSCRIPT_LOSS])

    def test_timecode_adds_one_plan_loss_and_only_then(self):
        planned = adaptor.plan(report(block(fmt='timecode')))
        self.assertEqual(planned['losses'], [*adaptor.LOSSES, adaptor.TRANSCRIPT_LOSS, adaptor.TIMECODE_LOSS])
        mixed = adaptor.plan(report(block(fmt='milliseconds'), block(fmt='timecode')))
        self.assertEqual(mixed['losses'].count(adaptor.TIMECODE_LOSS), 1)
        for text in ('HH:MM:SS.mmm', 'without rounding', 'not a wall-clock time', 'accessibility'):
            self.assertIn(text, adaptor.TIMECODE_LOSS)
        for claim in ('certified', 'verified'): self.assertNotIn(claim, adaptor.TIMECODE_LOSS.replace('not ', ''))

    def test_booleans_numbers_and_unknown_names_are_refused_at_the_field(self):
        for value in (True, False, 1, 0, 1.5, None, [], ['timecode'], {}, {'timeFormat': 'timecode'}, '', 'clock', 'Timecode', 'TIMECODE', 'timecode ',
                      'ms', 'millisecond', 'srt', 'hh:mm:ss.mmm', 'HH:MM:SS,mmm', 'seconds'):
            with self.subTest(value=repr(value)):
                entry = block(); entry['timeFormat'] = value; fault = self.fault(report(entry))
                self.assertEqual(fault.location, '$.sections[0].content[0].timeFormat'); self.assertIn('milliseconds or timecode', fault.message)

    def test_the_field_belongs_to_a_transcript_block_only(self):
        for content in ({'kind': 'paragraph', 'text': 'x', 'timeFormat': 'timecode'},
                        {'kind': 'table', 'columns': ['a'], 'rows': [['1']], 'timeFormat': 'timecode'}):
            self.fault({'version': adaptor.VERSION, 'operation': 'report', 'title': 'T', 'sections': [{'heading': 'H', 'content': [content]}]})
        for junk in ({'sections': 5}, {'sections': [5]}, {'sections': [{'content': 7}]}, {'sections': [{'content': [None, 3]}]}):
            with self.subTest(junk=junk), self.assertRaises(SchemaxisError) as caught: adaptor.plan({**report(), **junk})
            self.assertIn(caught.exception.fault.code, ('INVALID_ARGUMENT', 'MISSING_ARGUMENT'))
        self.fault({**report(), 'timeFormat': 'timecode'}, 'UNKNOWN_ARGUMENT')
        bad = report(); bad['sections'][0]['content'][0]['segments']['timeFormat'] = 'timecode'
        self.fault(bad)

    def test_a_refusal_happens_before_any_file_or_native_work(self):
        directory = Path(tempfile.mkdtemp(prefix='pandoc-timecode-')); self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        for value in (True, 'clock', 7):
            with self.subTest(value=repr(value)):
                with patch.object(adaptor, 'read_source', side_effect=AssertionError('source read')), \
                     patch.object(adaptor, 'launch', side_effect=AssertionError('native stage launched')), \
                     patch.object(adaptor, 'bounded', side_effect=AssertionError('file read')):
                    with self.assertRaises(SchemaxisError) as caught:
                        adaptor.run(report(block('/definitely/absent/segments.json', fmt=value)), directory / 'run', executable=shutil.which('true'))
                self.assertEqual(caught.exception.fault.code, 'INVALID_ARGUMENT')
                self.assertFalse((directory / 'run').exists())

    def test_planning_with_the_field_still_reads_no_file(self):
        document = report(block('/definitely/not/there/segments.json', fmt='timecode', sha256='a' * 64))
        with patch('builtins.open', side_effect=AssertionError('planning read a file')), patch('os.open', side_effect=AssertionError('planning opened a file')):
            adaptor.plan(document); self.assertEqual(adaptor.query(document), (['report'], {}))

    def test_a_retained_authored_report_accepts_the_field_under_the_retained_schema(self):
        for fmt in (None, 'milliseconds', 'timecode'):
            with self.subTest(fmt):
                document = report(block(fmt=fmt)); self.assertEqual(adaptor.plan(document, retained=True), adaptor.plan(document))

    def test_the_generated_schema_offers_exactly_the_two_choices(self):
        text = json.dumps(adaptor.schema())
        self.assertIn('"timeFormat"', text)
        found = []
        def walk(node):
            if isinstance(node, dict):
                if 'timeFormat' in node.get('properties', {}): found.append(node['properties']['timeFormat'])
                for value in node.values(): walk(value)
            elif isinstance(node, list):
                for value in node: walk(value)
        walk(adaptor.schema())
        self.assertEqual(len(found), 1); self.assertEqual(sorted(found[0].get('enum', [])), ['milliseconds', 'timecode'])
        self.assertNotIn('timeFormat', json.dumps(adaptor.schema()['required'] if 'required' in adaptor.schema() else []))

    def test_a_workflow_text_handoff_may_supply_the_path_of_a_timecode_block(self):
        from schemaxis import workflow
        document = json.loads((ROOT / 'examples/schemaxis/pandoc-whisper-workflow.json').read_text())
        document['operations'][1]['document']['sections'][0]['content'][0]['timeFormat'] = 'timecode'
        planned = workflow.inspect_plan(document)
        self.assertEqual(planned['operations'][1]['provisionalPlan']['status'], 'deferred')


class Content(unittest.TestCase):
    def view(self, document=None): return timed_text.parse(source.encode(document or source.document()))

    def test_absent_and_explicit_milliseconds_publish_identically_to_the_old_columns(self):
        view = self.view()
        old = adaptor.transcript_content(view)
        self.assertEqual(adaptor.transcript_content(view, 'milliseconds'), old)
        self.assertEqual(adaptor.transcript_content(view, None), old)
        self.assertEqual(old[1], MS_COLUMNS)
        self.assertEqual(old[2], [['0', '5410', 'And so, my fellow Americans,'], ['5410', '11000', 'ask not what your country can do.']])
        self.assertIn('audio duration 11000 ms; times are elapsed milliseconds from the start of the recording.', old[0])

    def test_timecode_renders_every_start_and_end_with_headers_and_unit(self):
        paragraph, columns, rows = adaptor.transcript_content(self.view(), 'timecode')
        self.assertEqual(columns, TC_COLUMNS)
        self.assertEqual(rows, [['00:00:00.000', '00:00:05.410', 'And so, my fellow Americans,'],
                                ['00:00:05.410', '00:00:11.000', 'ask not what your country can do.']])
        self.assertIn('audio duration 00:00:11.000;', paragraph)
        self.assertIn('HH:MM:SS.mmm (hours, minutes, seconds, milliseconds)', paragraph)
        self.assertNotIn('11000', paragraph.replace(self.view()['sha256'], ''))
        self.assertNotIn('elapsed milliseconds', paragraph)
        old = adaptor.transcript_content(self.view())[0]
        self.assertEqual(paragraph.replace('00:00:11.000', '11000 ms').split('; times are')[0], old.split('; times are')[0])
        self.assertIn(f'SHA-256 of the segments file {self.view()["sha256"]}', paragraph)

    def test_only_the_time_cells_headers_and_unit_differ_from_the_millisecond_publication(self):
        cues = [(0, 1, 'Zero'), (999, 1000, 'Edge'), (1000, 59999, 'Minute'), (59999, 60000, 'Rollover'), (3599999, 3600000, 'Hour'),
                (3600000, 3600001, 'Next'), (359999999, 360000000, 'Hundred hours')]
        view = self.view(long_document(cues))
        _, ms_columns, ms_rows = adaptor.transcript_content(view); _, tc_columns, tc_rows = adaptor.transcript_content(view, 'timecode')
        self.assertEqual((len(ms_rows), len(tc_rows)), (7, 7))
        self.assertEqual([row[2] for row in tc_rows], [row[2] for row in ms_rows])
        self.assertEqual([row[:2] for row in tc_rows], [[adaptor.timecode(int(a)), adaptor.timecode(int(b))] for a, b, _ in ms_rows])
        self.assertEqual([row[:2] for row in tc_rows], [['00:00:00.000', '00:00:00.001'], ['00:00:00.999', '00:00:01.000'], ['00:00:01.000', '00:00:59.999'],
            ['00:00:59.999', '00:01:00.000'], ['00:59:59.999', '01:00:00.000'], ['01:00:00.000', '01:00:00.001'], ['99:59:59.999', '100:00:00.000']])
        self.assertEqual((ms_columns, tc_columns), (MS_COLUMNS, TC_COLUMNS))

    def test_a_reviewed_document_keeps_its_declared_status_with_either_format(self):
        view = self.view(); view = {**view, 'source': timed_text.REVIEWED_VERSION, 'status': 'human-corrected',
            'review': {'status': 'human-corrected', 'note': 'Checked.', 'basisSha256': 'd' * 64, 'basisBytes': 9, 'correctionCount': 1, 'correctedIndices': [1],
                       'accuracyCertified': False, 'identityVerified': False}}
        for fmt in (None, 'milliseconds', 'timecode'):
            with self.subTest(fmt):
                paragraph = adaptor.transcript_content(view, fmt)[0]
                self.assertIn('Status: human-corrected, declared by the author of the corrections.', paragraph)
                self.assertIn('not verified or certified', paragraph)

    def test_timecode_text_is_plain_report_text(self):
        for fmt in (None, 'timecode'):
            paragraph, columns, rows = adaptor.transcript_content(self.view(), fmt)
            for text in (paragraph, *columns, *(c for row in rows for c in row)): self.assertEqual(adaptor.plain(text, '$'), text)


class Pinned(unittest.TestCase):
    """Without the field, every artefact the block produced before this change is byte for byte the same."""

    def test_a_block_without_the_field_is_unchanged_from_the_pre_change_development_source(self):
        with tempfile.TemporaryDirectory() as name:
            self.assertEqual(fingerprint(adaptor, Path(name)), BEFORE)


class Run(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pandoc-timecode-run-')); self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.executable = shutil.which('true')
        self.path = self.directory / 'segments.json'; self.path.write_bytes(source.encode(source.document()))
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def captured(self, document, name='run'):
        with patch.object(adaptor, 'launch', side_effect=AssertionError('native stage launched')):
            with self.assertRaises(SchemaxisError): adaptor.run(document, self.directory / name, executable=self.executable)
        return json.loads((self.directory / name / 'captures.json').read_text())

    def test_the_capture_record_binds_the_format_only_when_explicit(self):
        absent = self.captured(report(path=self.path), 'a')['transcript-0-0.json']; self.assertNotIn('timeFormat', absent)
        self.assertEqual(set(absent), {'source', 'kind', 'status', 'sha256', 'bytes', 'cues', 'characters'})
        for fmt in ('milliseconds', 'timecode'):
            record = self.captured(report(block(self.path, fmt=fmt)), fmt)['transcript-0-0.json']
            self.assertEqual(record, {**absent, 'timeFormat': fmt})

    def test_source_rules_and_bounds_are_unchanged_with_timecode(self):
        cases = {'overlap': ('TIMED_TEXT_TIMING', lambda d: d['segments'][1].update(startMs=100)),
                 'beyond audio': ('TIMED_TEXT_TIMING', lambda d: d['segments'][1].update(endMs=11001)),
                 'extra key': ('TIMED_TEXT_UNKNOWN_KEY', lambda d: d.update(title='x')),
                 'review': ('TIMED_TEXT_REVIEW_UNSUPPORTED', lambda d: d['review'].update(accuracyCertified=True)),
                 'control': ('TIMED_TEXT_CUE_TEXT', lambda d: d['segments'][0].update(text='bad\u0007text')),
                 'doubled space': ('INVALID_REPORT_TEXT', lambda d: d['segments'][0].update(text='two  spaces')),
                 'joiner': ('INVALID_REPORT_TEXT', lambda d: d['segments'][0].update(text='word⁠joiner'))}
        for label, (code, change) in cases.items():
            value = source.document(); change(value); path = self.directory / (label.replace(' ', '-') + '.json'); path.write_bytes(source.encode(value))
            for fmt in ('milliseconds', 'timecode'):
                with self.subTest(label, fmt=fmt):
                    with patch.object(adaptor, 'launch', side_effect=AssertionError('native stage launched')):
                        with self.assertRaises(SchemaxisError) as caught: adaptor.run(report(block(path, fmt=fmt)), self.directory / f'{label}-{fmt}'.replace(' ', '-'), executable=self.executable)
                    self.assertEqual(caught.exception.fault.code, code)

    def test_timecode_counts_toward_the_text_budget_so_a_report_that_fits_in_milliseconds_can_be_refused(self):
        many = long_document([(i * 1000 + 3600000, i * 1000 + 3600500, 'x' * 128) for i in range(256)])
        path = self.directory / 'many.json'; path.write_bytes(source.encode(many))
        view = timed_text.parse(path.read_bytes())
        def published(fmt): return adaptor.transcript_content(view, fmt)
        def size(fmt):
            paragraph, columns, rows = published(fmt); return len(paragraph) + sum(map(len, columns)) + sum(len(c) for r in rows for c in r)
        title = 'Interview transcript'; heading = len('Part 1')
        room = 65536 - len(title) - heading - size('milliseconds')
        self.assertTrue(0 < room < size('timecode') - size('milliseconds') + 70000)
        pad = max(0, 65536 - len(title) - heading - size('timecode') + 1)   # one character too many once timecodes are written
        self.assertLess(pad, room, 'a milliseconds report with this padding must still fit')
        document = report(block(path, fmt='milliseconds')); filler = []
        while pad > 0: filler.append({'kind': 'paragraph', 'text': 'y' * min(pad, 2000)}); pad -= min(pad, 2000)
        document['sections'][0]['content'] += filler
        fits = copy.deepcopy(document)
        with patch.object(adaptor, 'launch', side_effect=AssertionError('native stage launched')):
            with self.assertRaises(SchemaxisError) as caught: adaptor.run(fits, self.directory / 'ms', executable=self.executable)
        self.assertIn('native stage launched', caught.exception.fault.message)
        document['sections'][0]['content'][0]['timeFormat'] = 'timecode'
        with patch.object(adaptor, 'launch', side_effect=AssertionError('native stage launched')):
            with self.assertRaises(SchemaxisError) as caught: adaptor.run(document, self.directory / 'tc', executable=self.executable)
        self.assertEqual(caught.exception.fault.code, 'REPORT_RESOURCE_LIMIT')
        self.assertIn('65536', caught.exception.fault.message)


class Retained(unittest.TestCase):
    """`verify` recomputes the format-specific publication from retained bytes and the authored field."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pandoc-timecode-retained-')); self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.path = self.directory / 'segments.json'; self.path.write_bytes(source.encode(source.document()))
        self.executable = shutil.which('true')
        self.run_directory = self.directory / 'run'

    def make(self, *formats):
        document = report(*[block(self.path, fmt=f) for f in formats])
        with patch.object(adaptor, 'launch', side_effect=SchemaxisError(native_fault())):
            with self.assertRaises(SchemaxisError): adaptor.run(document, self.run_directory, executable=self.executable)
        (self.run_directory / 'verification.json').write_text(json.dumps({'executable': self.executable, 'runtime': 'pandoc 3.12.1', 'artifacts': [], 'evidence': {}}))
        return document

    def message(self):
        with self.assertRaises(SchemaxisError) as caught: adaptor.verify(self.run_directory, require_result=False)
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        return caught.exception.fault.message

    def rewrite(self, document, *, plan=True, captures=True, tree=True):
        """Replace the retained claim the way a forger who recomputes every receipt hash would."""
        (self.run_directory / 'authored.json').write_text(json.dumps(document))
        prepared = adaptor.plan(document)
        if plan: (self.run_directory / 'plan.json').write_text(json.dumps(prepared))
        if captures:
            stored = {}
            for i, section in enumerate(prepared['sections']):
                for j, item in enumerate(section['content']):
                    view = adaptor.transcript_view((self.run_directory / f'transcript-{i}-{j}.json').read_bytes(), '$')
                    stored[f'transcript-{i}-{j}.json'] = adaptor.transcript_summary(item, view)
            (self.run_directory / 'captures.json').write_text(json.dumps(stored))
        if tree: (self.run_directory / 'report-input.json').write_text(json.dumps(adaptor.ast(prepared, [1, 23], self.run_directory)))

    def with_native_stand_ins(self):
        (self.run_directory / 'api.json').write_text(json.dumps({'pandoc-api-version': [1, 23]}))
        prepared = adaptor.plan(json.loads((self.run_directory / 'authored.json').read_text()), retained=True)
        (self.run_directory / 'report-input.json').write_text(json.dumps(adaptor.ast(prepared, [1, 23], self.run_directory)))

    def test_the_genuine_retained_claim_reaches_the_native_evidence_check(self):
        for formats in ((None,), ('milliseconds',), ('timecode',), ('timecode', 'milliseconds'), (None, 'timecode')):
            shutil.rmtree(self.run_directory, ignore_errors=True)
            with self.subTest(formats=formats):
                self.make(*formats); self.with_native_stand_ins()
                self.assertNotIn('differs from authored report', self.message()); self.assertNotIn('binding differs', self.message())
                self.assertNotIn('effective report plan differs', self.message())

    def test_a_flipped_authored_format_is_refused_at_the_plan_and_the_capture_and_the_tree(self):
        document = self.make('timecode'); self.with_native_stand_ins()
        flipped = copy.deepcopy(document); flipped['sections'][0]['content'][0]['timeFormat'] = 'milliseconds'
        (self.run_directory / 'authored.json').write_text(json.dumps(flipped))
        self.assertIn('effective report plan differs', self.message())
        self.rewrite(flipped, captures=False, tree=False)
        self.assertIn('captured transcript/source binding differs', self.message())
        self.rewrite(flipped, tree=False)
        self.assertIn('trusted AST differs from authored report', self.message())

    def test_a_removed_or_added_field_is_refused_the_same_way(self):
        for before, after in (('timecode', None), ('milliseconds', None), (None, 'timecode'), (None, 'milliseconds'), ('milliseconds', 'timecode')):
            shutil.rmtree(self.run_directory, ignore_errors=True)
            with self.subTest(before=before, after=after):
                document = self.make(before); self.with_native_stand_ins()
                changed = copy.deepcopy(document); target = changed['sections'][0]['content'][0]
                if after is None: target.pop('timeFormat')
                else: target['timeFormat'] = after
                (self.run_directory / 'authored.json').write_text(json.dumps(changed))
                self.assertIn('effective report plan differs', self.message())
                self.rewrite(changed, captures=False, tree=False); self.assertIn('captured transcript/source binding differs', self.message())
                if 'timecode' in (before, after):
                    self.rewrite(changed, tree=False); self.assertIn('trusted AST differs from authored report', self.message())

    def test_a_forged_capture_format_is_refused(self):
        self.make('timecode'); captures = json.loads((self.run_directory / 'captures.json').read_text())
        self.assertEqual(captures['transcript-0-0.json']['timeFormat'], 'timecode')
        for value in ('milliseconds', 'clock', True, None, 7):
            changed = copy.deepcopy(captures); changed['transcript-0-0.json']['timeFormat'] = value
            (self.run_directory / 'captures.json').write_text(json.dumps(changed))
            self.assertIn('captured transcript/source binding differs', self.message())
        changed = copy.deepcopy(captures); del changed['transcript-0-0.json']['timeFormat']
        (self.run_directory / 'captures.json').write_text(json.dumps(changed))
        self.assertIn('captured transcript/source binding differs', self.message())

    def test_an_added_capture_format_on_a_report_without_the_field_is_refused(self):
        self.make(None); captures = json.loads((self.run_directory / 'captures.json').read_text())
        self.assertNotIn('timeFormat', captures['transcript-0-0.json'])
        for value in ('milliseconds', 'timecode'):
            changed = copy.deepcopy(captures); changed['transcript-0-0.json']['timeFormat'] = value
            (self.run_directory / 'captures.json').write_text(json.dumps(changed))
            self.assertIn('captured transcript/source binding differs', self.message())

    def test_altered_retained_bytes_or_a_forged_plan_loss_are_refused(self):
        self.make('timecode')
        stored = json.loads((self.run_directory / 'plan.json').read_text())
        for label, losses in (('timecode caveat removed', stored['losses'][:-1]), ('caveat replaced', [*stored['losses'][:-1], 'Plain text.']),
                              ('caveat added to a milliseconds plan', [*stored['losses'], adaptor.TIMECODE_LOSS])):
            with self.subTest(label):
                (self.run_directory / 'plan.json').write_text(json.dumps({**stored, 'losses': losses}))
                self.assertIn('effective report plan differs', self.message())
        (self.run_directory / 'plan.json').write_text(json.dumps(stored))
        changed = source.document(); changed['segments'][0]['text'] = 'Altered words.'
        (self.run_directory / 'transcript-0-0.json').write_bytes(source.encode(changed))
        self.assertIn('captured transcript/source binding differs', self.message())

    def test_a_report_without_the_field_cannot_carry_the_timecode_caveat(self):
        self.make(None); stored = json.loads((self.run_directory / 'plan.json').read_text())
        (self.run_directory / 'plan.json').write_text(json.dumps({**stored, 'losses': [*stored['losses'], adaptor.TIMECODE_LOSS]}))
        self.assertIn('effective report plan differs', self.message())

    def test_the_earlier_machine_wording_is_not_a_route_for_a_timecode_report(self):
        self.make('timecode'); stored = json.loads((self.run_directory / 'plan.json').read_text())
        legacy = {**stored, 'losses': [*stored['losses'][:-2], adaptor.LEGACY_TRANSCRIPT_LOSS]}
        (self.run_directory / 'plan.json').write_text(json.dumps(legacy))
        self.assertIn('effective report plan differs', self.message())
        legacy = {**stored, 'losses': [*stored['losses'][:-2], adaptor.LEGACY_TRANSCRIPT_LOSS, adaptor.TIMECODE_LOSS]}
        (self.run_directory / 'plan.json').write_text(json.dumps(legacy))
        self.assertIn('effective report plan differs', self.message())


class Model(unittest.TestCase):
    """AST, expected model and summary for each block use that block's own format."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='pandoc-timecode-model-')); self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        data = source.encode(source.document())
        for i in range(3): (self.directory / f'transcript-{i}-0.json').write_bytes(data)

    def prepared(self, *formats):
        document = {'version': adaptor.VERSION, 'operation': 'report', 'title': 'T', 'sections': [
            {'heading': f'H{i}', 'content': [block(fmt=f)]} for i, f in enumerate(formats)]}
        return adaptor.plan(document)

    def model(self, prepared): return adaptor.expected({**prepared, '_directory': self.directory})

    def tables(self, prepared): return [b['rows'] for b in self.model(prepared) if b['kind'] == 'table']

    def test_mixed_blocks_over_one_pinned_source_publish_independent_tables(self):
        tables = self.tables(self.prepared('timecode', 'milliseconds'))
        self.assertEqual([t[0] for t in tables], [TC_COLUMNS, MS_COLUMNS])
        self.assertEqual(self.tables(self.prepared(None, 'timecode'))[0], tables[1])
        self.assertEqual(tables[0][1:], [['00:00:00.000', '00:00:05.410', 'And so, my fellow Americans,'], ['00:00:05.410', '00:00:11.000', 'ask not what your country can do.']])
        self.assertEqual([r[2] for r in tables[0][1:]], [r[2] for r in tables[1][1:]])
        tables = self.tables(self.prepared('timecode', 'timecode'))
        self.assertEqual(tables[0], tables[1])

    def test_ast_tables_follow_the_model_and_the_existing_table_writer(self):
        prepared = self.prepared('timecode', 'milliseconds'); tree = adaptor.ast(prepared, [1, 23], self.directory)
        self.assertEqual([b['t'] for b in tree['blocks']], ['Header', 'Para', 'Table', 'Header', 'Para', 'Table'])
        for table, rows in zip((tree['blocks'][2], tree['blocks'][5]), self.tables(prepared)):
            self.assertEqual(table, adaptor.table_ast(rows[0], rows[1:]))

    def summary(self, prepared):
        with patch('schemaxis.adaptors.pandoc.inspection.html_report'), patch('schemaxis.adaptors.pandoc.inspection.docx_report'), \
                patch('schemaxis.adaptors.pandoc.inspection.ast_report'):
            for name in ('report.html', 'report.docx'): (self.directory / name).write_bytes(b'x')
            (self.directory / 'reopened.json').write_text('{}')
            return adaptor.inspect(self.directory, prepared)

    def test_the_summary_names_the_formats_only_when_a_block_chose_one(self):
        self.assertNotIn('transcriptTimeFormats', self.summary(self.prepared(None, None)))
        self.assertEqual(self.summary(self.prepared('timecode', None))['transcriptTimeFormats'], ['timecode', 'milliseconds'])
        self.assertEqual(self.summary(self.prepared('milliseconds', 'timecode'))['transcriptTimeFormats'], ['milliseconds', 'timecode'])
        self.assertEqual(self.summary(self.prepared('timecode'))['losses'][-1], adaptor.TIMECODE_LOSS)
        self.assertEqual(self.summary(self.prepared(None))['losses'], [*adaptor.LOSSES, adaptor.TRANSCRIPT_LOSS])

    def test_the_summary_receipt_rejects_a_claimed_format(self):
        prepared = self.prepared('timecode', 'milliseconds'); stored = self.summary(prepared)
        for claim in (['milliseconds', 'milliseconds'], ['timecode', 'timecode'], ['milliseconds', 'timecode'], ['timecode'], []):
            self.assertNotEqual({**stored, 'transcriptTimeFormats': claim}, stored)
        self.assertNotEqual({k: v for k, v in stored.items() if k != 'transcriptTimeFormats'}, stored)


class Declarations(unittest.TestCase):
    def test_examples_plan_and_the_invalid_example_names_the_field(self):
        timecode = adaptor.plan(json.loads((ROOT / 'examples/schemaxis/pandoc-transcript-timecode.json').read_text()))
        self.assertEqual(timecode['sections'][0]['content'][1]['timeFormat'], 'timecode'); self.assertEqual(timecode['losses'][-1], adaptor.TIMECODE_LOSS)
        mixed = adaptor.plan(json.loads((ROOT / 'examples/schemaxis/pandoc-transcript-mixed-formats.json').read_text()))
        self.assertEqual([s['content'][0]['timeFormat'] for s in mixed['sections']], ['timecode', 'milliseconds'])
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.plan(json.loads((ROOT / 'examples/schemaxis/pandoc-transcript-timeformat-invalid.json').read_text()))
        self.assertEqual(caught.exception.fault.code, 'INVALID_ARGUMENT'); self.assertIn('timeFormat', caught.exception.fault.location)

    def test_studio_template_plans_and_the_guidance_record_is_reviewed(self):
        studio = json.loads((ROOT / 'src/schemaxis/adaptors/pandoc/studio.json').read_text())
        template = next(t for t in studio['templates'] if t['id'] == 'transcript-timecode')
        self.assertEqual(adaptor.plan(template['document'])['sections'][0]['content'][1]['timeFormat'], 'timecode')
        guidance = json.loads((ROOT / 'src/schemaxis/adaptors/pandoc/guidance.json').read_text())
        field = guidance['routes']['schemaxis.pandoc/1']['fields']['/properties/sections/items/properties/content/items/anyOf/3/properties/timeFormat']
        self.assertEqual(field['status'], 'reviewed')
        for text in ('HH:MM:SS.mmm', 'milliseconds', 'Omission'): self.assertIn(text, field['explanation'] + field['defaultMeaning'])
        self.assertTrue(field['pitfalls'])

    def test_readiness_links_the_review_and_the_checks(self):
        route = json.loads((ROOT / 'src/schemaxis/adaptors/pandoc/readiness.json').read_text())['routes']['schemaxis.pandoc/1']
        self.assertIn('verification/2026-10-25-pandoc-47.md', route['completion']['review'])
        self.assertIn('tests/unit/test_pandoc_timecode.py', route['conformance']); self.assertIn('tools/qualify_pandoc_timecode.py', route['acceptance'])
        self.assertTrue((ROOT / 'verification/2026-10-25-pandoc-47.md').is_file())
        ids = {e['id']: e for e in route['examples']}
        self.assertEqual(ids['invalid-time-format']['fault'], 'INVALID_ARGUMENT'); self.assertIs(ids['invalid-time-format']['schemaValid'], False)

    def test_discovery_terms_are_declared_and_the_search_cases_are_reviewed(self):
        from schemaxis.adaptors.pandoc import capabilities
        catalogue = capabilities.catalogue()
        operation = catalogue['operations']['report']
        for term in ('timecode', 'HH:MM:SS.mmm'): self.assertIn(term, operation['keywords'])
        cases = {c['id']: c for c in catalogue['searchCases']}
        for name in ('transcript-timecode', 'hh-mm-ss-timestamps'): self.assertEqual(cases[name]['status'], 'reviewed')
        self.assertIn('transcript timecode', json.loads((ROOT / 'src/schemaxis/adaptors/pandoc/adaptor.json').read_text())['keywords'])


def native_fault():
    from schemaxis.core.faults import Fault
    return Fault('NATIVE_EXECUTION_FAILED', 'native stage deliberately not run in a host test', 'version', 'pipeline')


if __name__ == '__main__':
    unittest.main()
