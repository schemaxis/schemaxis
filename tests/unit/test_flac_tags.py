"""Optional encodeLossless recording labels (title, artist, description) as native Vorbis comments.

Host-only tests use a deterministic fake ``flac`` that writes a correctly framed FLAC prefix whose VORBIS_COMMENT holds the exact
``--tag`` arguments it was given, and that mimics the one libFLAC 1.5.0 behaviour observed with the real binary under ``LC_ALL=C``
(without ``--no-utf8-convert`` before a tag, non-ASCII bytes become ``#``). They prove host behaviour only: validation, argument
construction, comment parsing, receipts and refused forgeries. Real native evidence is the gated ``RealFlacLabels`` class (set
SCHEMAXIS_FLAC to a FLAC 1.5 ``flac`` with a sibling ``metaflac``) and tools/qualify_flac_tags.py.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator

from schemaxis.adaptors import registry
from schemaxis.adaptors.flac import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_flac_fakes import MARKER, build_flac, frame_header, metadata_stream, streaminfo, vorbis, wav_bytes   # noqa: E402
from test_flac_native_boundary import rebind, refresh   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
FIXTURES = ROOT / 'examples/schemaxis/fixtures/flac'
VENDOR = b'reference libFLAC 1.5.0 20250211'
BASELINE_PLAN_SHA256 = {   # sha256(json.dumps(plan, sort_keys=True)) of the pre-change adaptor for source /data/recording.{wav,flac}
    'encodeLossless': 'b82b00b81bab5c906c1214e925db284972c261cd0501f0212d0a7b542fa32332',
    'decodePCM16': '8738287b252c02f97fc73a51d7d578ba9ac8c1a98651dae97c510f009de8837e'}
LABELS = {'title': 'Café – 日本語', 'artist': 'Zoë Núñez', 'description': 'a=b; c==d = e'}
FAKE = '''#!{python}
import hashlib, json, os, struct, sys
sys.path.insert(0, {tests!r})
from test_flac_fakes import build_flac, parse_fake
args = sys.argv[1:]
if args == ['--version']:
    print('flac 1.5.0'); sys.exit(0)
open({log!r}, 'a').write(json.dumps(args) + '\\n')
if '-d' in args:
    info, pcm = parse_fake(open(args[-1], 'rb').read())
    if hashlib.md5(pcm).hexdigest() != info['md5']:
        sys.stderr.write('ERROR, MD5 signature mismatch\\n'); sys.exit(1)
    open(args[args.index('-o') + 1], 'wb').write(pcm)
else:
    channels = int([a for a in args if a.startswith('--channels=')][0].split('=')[1])
    rate = int([a for a in args if a.startswith('--sample-rate=')][0].split('=')[1])
    pcm = open(args[-1], 'rb').read()
    convert, comments = True, []
    for argument in args:                                    # --no-utf8-convert applies to the tags after it
        if argument == '--no-utf8-convert':
            convert = False
        elif argument.startswith('--tag='):
            raw = os.fsencode(argument[6:])
            comments.append(raw if not convert else bytes(b if b < 128 else 35 for b in raw))
    vendor = {vendor!r}
    block = struct.pack('<I', len(vendor)) + vendor + struct.pack('<I', len(comments)) + b''.join(struct.pack('<I', len(c)) + c for c in comments)
    open(args[args.index('-o') + 1], 'wb').write(build_flac(rate, channels, pcm, vendor=False, extra_blocks=[(4, block)]))
'''


def make_fake(directory, log):
    path = Path(directory) / 'flac'
    path.write_text(FAKE.format(python=sys.executable, tests=str(TESTS), log=str(log), vendor=VENDOR))
    path.chmod(0o700)
    return str(path)


def document(metadata=None, source='/data/recording.wav', **extra):
    result = {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': source, **extra}
    if metadata is not None:
        result['metadata'] = metadata
    return result


def comment_block(lines, vendor=VENDOR, count=None):
    return struct.pack('<I', len(vendor)) + vendor + struct.pack('<I', len(lines) if count is None else count) + b''.join(struct.pack('<I', len(l)) + l for l in lines)


def blocks_of(data):
    """(type, body) of every metadata block and the offset of the audio, from the actual FLAC bytes (an independent reader)."""
    offset, found = 4, []
    while True:
        last, kind, size = data[offset] >> 7, data[offset] & 0x7f, int.from_bytes(data[offset + 1:offset + 4], 'big')
        found.append((kind, data[offset + 4:offset + 4 + size]))
        offset += 4 + size
        if last:
            return found, offset


def replace_comment(data, body):
    found, audio = blocks_of(data)
    return metadata_stream([(kind, body if kind == 4 else content) for kind, content in found]) + data[audio:]


def comments_of(data):
    body = next(body for kind, body in blocks_of(data)[0] if kind == 4)
    length = struct.unpack_from('<I', body, 0)[0]
    count = struct.unpack_from('<I', body, 4 + length)[0]
    offset, lines = 8 + length, []
    for _ in range(count):
        size = struct.unpack_from('<I', body, offset)[0]
        lines.append(body[offset + 4:offset + 4 + size])
        offset += 4 + size
    assert offset == len(body)
    return body[4:4 + length], lines


class LabelContract(unittest.TestCase):
    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def test_absent_metadata_plans_are_the_exact_pre_change_plans(self):
        for operation, suffix in (('encodeLossless', '.wav'), ('decodePCM16', '.flac')):
            prepared = adaptor.plan({'version': 'schemaxis.flac/1', 'operation': operation, 'source': '/data/recording' + suffix})
            self.assertEqual(hashlib.sha256(json.dumps(prepared, sort_keys=True).encode()).hexdigest(), BASELINE_PLAN_SHA256[operation])
            self.assertNotIn('metadata', prepared)
            self.assertEqual(prepared['native']['metadata'], 'none')
        self.assertEqual(adaptor.plan(document())['losses'], adaptor.LOSSES)

    def test_labelled_plan_uses_fixed_names_order_and_one_argument_per_value(self):
        shuffled = {'description': 'a=b', 'title': 'T', 'artist': 'A'}
        prepared = adaptor.plan(document(shuffled))
        self.assertEqual(prepared['native']['arguments'], adaptor.ENCODE_ARGUMENTS + ['--no-utf8-convert', '--tag=TITLE=T', '--tag=ARTIST=A', '--tag=DESCRIPTION=a=b'])
        self.assertEqual(list(prepared['metadata']), ['title', 'artist', 'description'])
        self.assertEqual(prepared['native']['metadata']['mode'], 'authoredLabels')
        self.assertEqual(prepared['native']['metadata']['comments'], ['TITLE=T', 'ARTIST=A', 'DESCRIPTION=a=b'])
        self.assertEqual(prepared, adaptor.plan(document(shuffled)))
        self.assertNotEqual(prepared['losses'], adaptor.LOSSES)
        self.assertIn('author-declared', ' '.join(prepared['losses']))
        only = adaptor.plan(document({'artist': 'Solo'}))
        self.assertEqual(only['native']['arguments'][-2:], ['--no-utf8-convert', '--tag=ARTIST=Solo'])
        argv = adaptor.encode_arguments(prepared['metadata'])
        self.assertLess(argv.index('--no-utf8-convert'), min(i for i, a in enumerate(argv) if a.startswith('--tag=')))

    def test_values_are_preserved_exactly_and_never_normalised_or_cropped(self):
        decomposed, composed = 'Cafe\u0301', 'Café'
        a, b = adaptor.plan(document({'title': decomposed}))['metadata']['title'], adaptor.plan(document({'title': composed}))['metadata']['title']
        self.assertEqual((a, b), (decomposed, composed))
        self.assertNotEqual(a, b)
        padded = '  spaced \u00a0 out  '
        self.assertEqual(adaptor.plan(document({'title': padded}))['metadata']['title'], padded)
        self.assertEqual(adaptor.plan(document({'title': '-x --tag=EVIL=1'}))['native']['arguments'][-1], '--tag=TITLE=-x --tag=EVIL=1')
        for text in ('é', 'x\u200dy', '😀', '=', '"quoted"', 'back\\slash', '�', 'ᚠᛇᚻ'):
            self.assertEqual(adaptor.plan(document({'title': text}))['metadata']['title'], text)

    def test_limits_are_inclusive_in_code_points_and_utf8_bytes(self):
        self.assertEqual(adaptor.plan(document({'title': 'x' * 200, 'artist': 'y' * 200, 'description': 'z' * 1000}))['metadata']['description'], 'z' * 1000)
        self.assertEqual(len(adaptor.plan(document({'title': 'é' * 200}))['metadata']['title'].encode()), 400)
        self.assertEqual(len(adaptor.plan(document({'title': 'あ' * 170}))['metadata']['title'].encode()), 510)
        for field, size in (('title', 200), ('artist', 200), ('description', 1000)):
            self.fault(lambda: adaptor.plan(document({field: 'x' * (size + 1)})), 'INVALID_FLAC_METADATA')
        self.fault(lambda: adaptor.plan(document({'title': 'あ' * 171})), 'INVALID_FLAC_METADATA')            # 513 bytes, 171 code points
        self.fault(lambda: adaptor.plan(document({'title': '😀' * 129})), 'INVALID_FLAC_METADATA')           # 516 bytes
        self.fault(lambda: adaptor.plan(document({'description': '😀' * 751})), 'INVALID_FLAC_METADATA')     # 3004 bytes, 751 code points
        self.assertEqual(adaptor.plan(document({'description': '😀' * 750}))['metadata']['description'], '😀' * 750)

    def test_malformed_metadata_is_refused_with_a_location_and_before_anything_else(self):
        refused = {
            'empty object': {}, 'null': None, 'list': [], 'string': 'title', 'number': 1, 'true': True,
            'empty title': {'title': ''}, 'spaces only': {'title': '   '}, 'joiner only': {'title': '\u200d'}, 'mark only': {'title': '\u0301'},
            'number value': {'title': 1}, 'bool value': {'title': True}, 'null value': {'title': None}, 'list value': {'title': ['x']}, 'object value': {'title': {'a': 1}},
            'newline': {'title': 'a\nb'}, 'carriage return': {'description': 'a\rb'}, 'tab': {'title': 'a\tb'}, 'nul': {'title': 'a\0b'}, 'delete': {'title': 'a\x7fb'},
            'c1 control': {'title': 'a\x85b'}, 'escape': {'title': '\x1b[0m x'},
            'lone surrogate': {'title': 'a\ud800b'}, 'low surrogate': {'artist': '\udfff'},
            'rtl override': {'title': 'a\u202eb'}, 'isolate': {'title': 'a\u2066b'}, 'rtl mark': {'title': 'a\u200fb'}, 'arabic mark': {'title': 'a\u061cb'},
            'line separator': {'title': 'a\u2028b'}, 'paragraph separator': {'title': 'a\u2029b'}, 'private use': {'title': 'a\ue000b'},
            'noncharacter': {'title': 'a\ufffeb'}, 'noncharacter block': {'title': 'a\ufdd0b'}, 'plane noncharacter': {'title': 'a\U0001ffffb'},
            'byte order mark': {'title': '\ufeffx'}, 'zero width space': {'title': 'a\u200bb'}, 'soft hyphen': {'title': 'a\u00adb'}, 'tag character': {'title': 'a\U000e0041b'},
            'word joiner': {'title': 'a\u2060b'}}
        for label, value in refused.items():
            with self.subTest(label):
                fault = self.fault(lambda: adaptor.plan({**document(), 'metadata': value}), 'INVALID_FLAC_METADATA')
                self.assertTrue(fault.location.startswith('$.metadata'), fault.location)
        for label, value in {'unknown key': {'title': 'x', 'album': 'y'}, 'upper case key': {'TITLE': 'x'}, 'tag name': {'tagName': 'x'}, 'picture': {'title': 'x', 'picture': 'a.png'},
                             'tag from file': {'tag-from-file': 'TITLE=/etc/passwd'}, 'flags': {'flags': ['--force']}}.items():
            with self.subTest(label):
                self.assertEqual(self.fault(lambda: adaptor.plan(document(value)), 'UNKNOWN_ARGUMENT').location, '$.metadata')

    def test_visible_unicode_is_accepted_but_not_assumed_to_be_safe_or_normalised(self):
        for text in ('Zoë', '日本語', 'Ελληνικά', 'עברית', '٣ ٤', '😀🎙', 'a\u200cb', 'Ωmega', '©2026', '1/2'):
            adaptor.plan(document({'title': text}))

    def test_decode_has_no_metadata_option_and_other_flac_fields_stay_unknown(self):
        fault = self.fault(lambda: adaptor.plan({'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': '/data/a.flac', 'metadata': {'title': 'x'}}), 'UNKNOWN_ARGUMENT')
        self.assertEqual(fault.location, '$.metadata')
        for key in ('tags', 'tag', 'comments', 'picture', 'flags', 'compression'):
            self.fault(lambda: adaptor.plan(document(None, **{key: {'title': 'x'}})), 'UNKNOWN_ARGUMENT')

    def test_schema_offers_metadata_to_the_encode_branch_only_and_validates_the_closed_object(self):
        schema = adaptor.schema()
        encode, decode = schema['oneOf']
        self.assertIn('metadata', encode['properties'])
        self.assertNotIn('metadata', decode['properties'])
        self.assertNotIn('metadata', encode['required'])
        self.assertEqual(encode['properties']['metadata']['minProperties'], 1)
        validator = Draft202012Validator(schema)
        self.assertTrue(validator.is_valid(document(LABELS)))
        self.assertTrue(validator.is_valid(document()))
        for bad in ({}, {'album': 'x'}, {'title': 1}, {'title': ''}, {'title': 'x' * 201}, {'description': 'x' * 1001}):
            self.assertFalse(validator.is_valid(document(bad)), bad)
        self.assertFalse(validator.is_valid({'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': '/data/a.flac', 'metadata': {'title': 'x'}}))

    def test_registry_plans_labelled_documents_and_declares_the_option(self):
        self.assertEqual(registry.query(document(LABELS))['adaptors'][0]['operations'], ['encodeLossless'])
        self.assertIn('metadata', adaptor.DECLARATIONS['encodeLossless']['options'])
        self.assertNotIn('metadata', adaptor.DECLARATIONS['decodePCM16']['options'])
        native = adaptor.DECLARATIONS['encodeLossless']['native']
        for text in ('--no-utf8-convert', '--tag=TITLE=T', '--tag=ARTIST=A', '--tag=DESCRIPTION=D'):
            self.assertIn(text, native)
        for flag in adaptor.ENCODE_ARGUMENTS:
            self.assertIn(flag, native.split(';')[0].split())

    def test_examples_plan_or_fail_as_documented(self):
        for name in ('archive', 'unicode'):
            example = json.loads((ROOT / f'examples/schemaxis/flac-tag-{name}.json').read_text(encoding='utf-8'))
            example['source'] = '/data/recording.wav'
            prepared = adaptor.plan(example)
            self.assertEqual(prepared['metadata'], example['metadata'])
        bad = json.loads((ROOT / 'examples/schemaxis/flac-tag-invalid-label.json').read_text())
        self.assertEqual(bad['metadata']['title'], 'Meeting\u202erecording')
        self.fault(lambda: adaptor.plan(bad), 'INVALID_FLAC_METADATA')
        raw = (ROOT / 'examples/schemaxis/flac-tag-invalid-label.json').read_bytes()
        self.assertNotIn('\u202e'.encode(), raw)

    def test_comment_reader_is_strict_about_framing(self):
        good = comment_block([b'TITLE=x'])
        self.assertEqual(adaptor.read_comments(good), (VENDOR, [b'TITLE=x']))
        self.assertEqual(adaptor.read_comments(comment_block([])), (VENDOR, []))
        for label, body in {'empty': b'', 'short': b'\x01\0', 'vendor overruns': struct.pack('<I', 999) + b'abc', 'count overruns': comment_block([b'A=1'], count=2),
                            'trailing bytes': good + b'\0', 'entry overruns': comment_block([b'A=1'])[:-1], 'count missing': struct.pack('<I', 3) + b'abc',
                            'huge entry': comment_block([b'A=1'])[:-7] + struct.pack('<I', 2 ** 31) + b'A=1'}.items():
            with self.subTest(label):
                self.assertIsNone(adaptor.read_comments(body))

    def build(self, lines, vendor=VENDOR, count=None, **kwargs):
        return build_flac(16000, 2, bytes(16), vendor=False, extra_blocks=[(4, comment_block(lines, vendor, count))], **kwargs)

    def test_parse_flac_requires_exactly_the_authored_entries_in_fixed_order(self):
        authored = adaptor.plan(document({'title': 'T', 'description': 'D'}))['metadata']
        parsed = adaptor.parse_flac(self.build([b'TITLE=T', b'DESCRIPTION=D']), 'audio.flac', encoder_output=True, authored=authored)
        self.assertEqual((parsed['comments'], parsed['vendor']), (['TITLE=T', 'DESCRIPTION=D'], VENDOR.decode()))
        for label, lines in {'swapped': [b'DESCRIPTION=D', b'TITLE=T'], 'missing': [b'TITLE=T'], 'extra': [b'TITLE=T', b'DESCRIPTION=D', b'ARTIST=A'], 'duplicate': [b'TITLE=T', b'TITLE=T', b'DESCRIPTION=D'],
                             'value changed': [b'TITLE=t', b'DESCRIPTION=D'], 'lower case field': [b'title=T', b'DESCRIPTION=D'], 'empty entry': [b'TITLE=T', b'DESCRIPTION=D', b''],
                             'cropped': [b'TITLE=', b'DESCRIPTION=D'], 'normalised': [b'TITLE=T', b'DESCRIPTION=D\xcc\x81'], 'none': []}.items():
            with self.subTest(label):
                self.fault(lambda: adaptor.parse_flac(self.build(lines), 'audio.flac', encoder_output=True, authored=authored), 'INVALID_FLAC_STREAM')
        self.fault(lambda: adaptor.parse_flac(self.build([b'TITLE=T', b'DESCRIPTION=D'], vendor=b'reference libFLAC 1.4.3 20230623'), 'audio.flac', encoder_output=True, authored=authored), 'INVALID_FLAC_STREAM')
        self.fault(lambda: adaptor.parse_flac(self.build([b'TITLE=T', b'DESCRIPTION=D'], count=3), 'audio.flac', encoder_output=True, authored=authored), 'INVALID_FLAC_STREAM')
        # an untagged request still demands the original empty comment, and decode-side parsing never needs labels
        self.assertEqual(adaptor.parse_flac(self.build([]), 'audio.flac', encoder_output=True)['comments'], [])
        fault = self.fault(lambda: adaptor.parse_flac(self.build([b'TITLE=T']), 'audio.flac', encoder_output=True), 'INVALID_FLAC_STREAM')
        self.assertIn('not empty', fault.message)
        self.assertEqual(adaptor.parse_flac(self.build([b'TITLE=T']), 'x.flac')['comments'], [])

    def test_the_original_empty_comment_guard_message_is_unchanged(self):
        message = 'not a well-formed native FLAC stream: published FLAC metadata is not STREAMINFO plus an empty libFLAC VORBIS_COMMENT'
        for data in (build_flac(16000, 2, bytes(16), vendor=False), build_flac(16000, 2, bytes(16), extra_blocks=[(1, bytes(8))])):
            self.assertEqual(self.fault(lambda: adaptor.parse_flac(data, 'audio.flac', encoder_output=True), 'INVALID_FLAC_STREAM').message, message)


class LabelledRunWithFake(unittest.TestCase):
    """One labelled, one ASCII-labelled and one untagged run are published once; each test mutates a private copy."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.log = cls.root / 'argv.log'
        cls.flac = make_fake(cls.root, cls.log)
        cls.wav_data = (FIXTURES / 'stereo-16000.wav').read_bytes()
        cls.pcm = cls.wav_data[44:]
        cls.wav = cls.root / 'a.wav'
        cls.wav.write_bytes(cls.wav_data)
        cls.base = {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': str(cls.wav)}
        cls.runs = {}
        for name, metadata in (('labelled', LABELS), ('ascii', {'title': 'Plain', 'artist': 'Ann', 'description': 'x=y'}), ('plain', None)):
            cls.log.write_text('')
            doc = {**cls.base, **({'metadata': metadata} if metadata else {})}
            directory = cls.root / ('run-' + name)
            result = adaptor.run(doc, directory, executable=cls.flac, timeout=60)
            cls.runs[name] = (directory, doc, result, [json.loads(line) for line in cls.log.read_text().splitlines()])
        (cls.root / 'empty.json').write_text('{"version": 1, "locations": {}}')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='copy-', dir=self.root))
        self.addCleanup(shutil.rmtree, self.work, True)

    def fault(self, action, code='VERIFICATION_FAILED'):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def copy(self, name='labelled'):
        parent = Path(tempfile.mkdtemp(dir=self.work))
        if (self.root / 'schemas').exists():
            shutil.copytree(self.root / 'schemas', parent / 'schemas')          # the shared schema store sits beside the run
        directory = parent / name
        shutil.copytree(self.runs[name][0], directory)
        rebind(directory)     # receipt artifact paths are absolute provenance of the original location
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])
        return directory

    def verify(self, directory):
        return self.fault(lambda: adaptor.verify(directory, executable=self.flac))

    def rewrite_json(self, directory, name, change):
        value = adaptor.read_json(directory, name)
        change(value)
        atomic_json(directory / name, value)
        rebind(directory)

    # ------------------------------------------------------------ published behaviour
    def test_labelled_run_passes_exact_native_arguments_and_publishes_exact_comments(self):
        directory, doc, result, argv = self.runs['labelled']
        encode = next(call for call in argv if '--channels=2' in call)
        self.assertEqual(encode, adaptor.ENCODE_ARGUMENTS + ['--no-utf8-convert', '--tag=TITLE=Café – 日本語', '--tag=ARTIST=Zoë Núñez', '--tag=DESCRIPTION=a=b; c==d = e',
                                                           '--channels=2', '--sample-rate=16000', '-o', 'audio.flac', 'source.pcm'])
        decode = [*adaptor.DECODE_ARGUMENTS, '-o', 'reopened.pcm', 'audio.flac']
        others = [call for call in argv if '--channels=2' not in call]
        self.assertGreaterEqual(len(others), 2)                        # the run readback and the fresh verification decodes
        self.assertEqual(others, [decode] * len(others))
        vendor, lines = comments_of((directory / 'audio.flac').read_bytes())
        self.assertEqual(vendor, VENDOR)
        self.assertEqual(lines, ['TITLE=Café – 日本語'.encode(), 'ARTIST=Zoë Núñez'.encode(), 'DESCRIPTION=a=b; c==d = e'.encode()])
        self.assertTrue(result['verified'])
        self.assertEqual(result['metadata'], {'mode': 'authoredLabels', 'labels': {'TITLE': 'Café – 日本語', 'ARTIST': 'Zoë Núñez', 'DESCRIPTION': 'a=b; c==d = e'},
                                              'vorbisCommentBytes': 8 + len(VENDOR) + sum(4 + len(line) for line in lines)})
        summary = adaptor.read_json(directory, 'flac-summary.json')
        self.assertEqual(summary['metadata']['mode'], 'authoredLabels')
        self.assertEqual(summary['metadata']['declaredBy'], 'author')
        self.assertEqual([(c['field'], c['value'], c['utf8Bytes']) for c in summary['metadata']['comments']],
                         [('TITLE', 'Café – 日本語', len('Café – 日本語'.encode())), ('ARTIST', 'Zoë Núñez', len('Zoë Núñez'.encode())), ('DESCRIPTION', 'a=b; c==d = e', len('a=b; c==d = e'.encode()))])
        self.assertIn('not an identity', summary['metadata']['meaning'])
        self.assertEqual(summary['flac']['metadataBlocks'], [{'type': 'STREAMINFO', 'bytes': 34}, {'type': 'VORBIS_COMMENT', 'bytes': result['metadata']['vorbisCommentBytes']}])
        self.assertEqual(adaptor.read_json(directory, 'captures.json')['metadata'], doc['metadata'])
        self.assertEqual(adaptor.read_json(directory, 'plan.json')['metadata'], doc['metadata'])
        self.assertTrue(summary['readback']['exactPcm'])
        self.assertEqual(summary['pcm']['sha256'], hashlib.sha256(self.pcm).hexdigest())
        self.assertEqual(adaptor.verify(directory, executable=self.flac)['metadata'], result['metadata'])

    def test_labelled_launcher_keeps_utf8_labels_and_compiles(self):
        directory = self.runs['labelled'][0]
        text = (directory / 'encode-launcher.py').read_bytes().decode('utf-8')
        self.assertIn('--tag=TITLE=Café – 日本語', text)
        compile(text, 'launcher', 'exec')

    def test_the_fake_reproduces_the_observed_conversion_so_the_flag_is_load_bearing(self):
        source = self.work / 'source.pcm'
        source.write_bytes(bytes(8))
        base = [self.flac, '--channels=1', '--sample-rate=8000', '-o']
        for label, before, after, expected in (('no flag', [], [], b'TITLE=Caf##'), ('flag before the tag', ['--no-utf8-convert'], [], 'TITLE=Café'.encode()),
                                               ('flag after the tag', [], ['--no-utf8-convert'], b'TITLE=Caf##')):
            with self.subTest(label):
                out = self.work / (label.replace(' ', '-') + '.flac')
                subprocess.run([*base, str(out), *before, '--tag=TITLE=Café', *after, str(source)], check=True, cwd=self.work)
                self.assertEqual(comments_of(out.read_bytes())[1], [expected])

    def test_untagged_run_is_exactly_the_pre_change_behaviour(self):
        directory, doc, result, argv = self.runs['plain']
        encode = next(call for call in argv if '--channels=2' in call)
        self.assertEqual(encode, adaptor.ENCODE_ARGUMENTS + ['--channels=2', '--sample-rate=16000', '-o', 'audio.flac', 'source.pcm'])
        self.assertFalse([a for call in argv for a in call if a.startswith('--tag') or a == '--no-utf8-convert'])
        self.assertEqual(comments_of((directory / 'audio.flac').read_bytes()), (VENDOR, []))
        self.assertNotIn('metadata', result)
        summary = adaptor.read_json(directory, 'flac-summary.json')
        self.assertNotIn('metadata', summary)
        self.assertEqual(set(adaptor.read_json(directory, 'captures.json')), {'source', 'bytes', 'sha256'})
        plan = adaptor.read_json(directory, 'plan.json')
        self.assertEqual(hashlib.sha256(json.dumps({**plan, 'source': '/data/recording.wav'}, sort_keys=True).encode()).hexdigest(), BASELINE_PLAN_SHA256['encodeLossless'])
        self.assertEqual(summary['verification'], 'Every PCM byte of a fresh native flac decode of the published FLAC equals the PCM of the captured WAV, and the decoded samples '
                                                  'reproduce the STREAMINFO MD5 and sample count. No independent host FLAC decoder.')
        self.assertEqual(set(result), {'status', 'verified', 'operation', 'artifacts', 'audio', 'bytes', 'pcmSha256', 'runtime'})

    def test_labels_do_not_change_the_audio_identity(self):
        pcm = {name: adaptor.read_json(run[0], 'flac-summary.json')['pcm'] for name, run in self.runs.items()}
        self.assertEqual(pcm['labelled'], pcm['plain'])
        self.assertEqual(self.runs['labelled'][2]['pcmSha256'], self.runs['plain'][2]['pcmSha256'])
        self.assertNotEqual((self.runs['labelled'][0] / 'audio.flac').read_bytes(), (self.runs['plain'][0] / 'audio.flac').read_bytes())

    def test_decode_of_a_labelled_archive_reuses_the_pcm_and_drops_the_labels(self):
        archive = self.runs['labelled'][0] / 'audio.flac'
        directory = self.work / 'reuse'
        result = adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': str(archive)}, directory, executable=self.flac, timeout=60)
        self.assertTrue(result['verified'])
        self.assertNotIn('metadata', result)
        self.assertEqual((directory / 'audio.wav').read_bytes(), self.wav_data)
        summary = adaptor.read_json(directory, 'flac-summary.json')
        self.assertEqual(summary['source']['droppedMetadataBlocks'], ['VORBIS_COMMENT'])
        self.assertNotIn('metadata', summary)
        self.assertNotIn('Café'.encode(), (directory / 'audio.wav').read_bytes())

    def test_invalid_labels_are_refused_before_any_native_launch_or_output_directory(self):
        target = self.work / 'never'
        with mock.patch.object(adaptor, 'execute', side_effect=AssertionError('native launch')) as launch, mock.patch.object(adaptor, 'runtime', side_effect=AssertionError('runtime lookup')):
            for value in ({}, {'title': 'a\nb'}, {'title': 'x', 'album': 'y'}, {'title': 'a\u202eb'}, {'title': 'x' * 201}, {'title': 7}):
                self.fault(lambda: adaptor.run({**self.base, 'metadata': value}, target, executable=self.flac), 'INVALID_FLAC_METADATA' if 'album' not in value else 'UNKNOWN_ARGUMENT')
                self.assertFalse(target.exists())
            self.fault(lambda: adaptor.run({'version': 'schemaxis.flac/1', 'operation': 'decodePCM16', 'source': '/x.flac', 'metadata': {'title': 'x'}}, target, executable=self.flac), 'UNKNOWN_ARGUMENT')
            self.assertFalse(target.exists())
            launch.assert_not_called()

    # ------------------------------------------------------------ forgeries with every hash refreshed
    def forge_comments(self, name, change):
        directory = self.copy(name)
        data = (directory / 'audio.flac').read_bytes()
        vendor, lines = comments_of(data)
        vendor, lines, count = change(vendor, list(lines))
        (directory / 'audio.flac').write_bytes(replace_comment(data, comment_block(lines, vendor, count)))
        refresh(directory)
        return directory

    def test_forged_vorbis_comments_are_refused_with_every_hash_refreshed(self):
        title = 'TITLE=Café – 日本語'.encode()
        cases = {
            'value changed, same size': lambda v, l: (v, [l[0].replace('日本語'.encode(), '日本誤'.encode())] + l[1:], None),
            'value cropped': lambda v, l: (v, [l[0][:-3]] + l[1:], None),
            'value lengthened': lambda v, l: (v, [l[0] + b'!'] + l[1:], None),
            'title normalised': lambda v, l: (v, [b'TITLE=Cafe\xcc\x81 \xe2\x80\x93 \xe6\x97\xa5\xe6\x9c\xac\xe8\xaa\x9e'] + l[1:], None),
            'order swapped': lambda v, l: (v, [l[1], l[0], l[2]], None),
            'artist dropped': lambda v, l: (v, [l[0], l[2]], None),
            'all dropped': lambda v, l: (v, [], None),
            'title duplicated': lambda v, l: (v, [l[0], l[0], l[1], l[2]], None),
            'extra tag added': lambda v, l: (v, l + [b'COMMENT=injected'], None),
            'empty entry added': lambda v, l: (v, l + [b''], None),
            'field lower case': lambda v, l: (v, [b'title' + l[0][5:]] + l[1:], None),
            'separator missing': lambda v, l: (v, [l[0].replace(b'=', b':', 1)] + l[1:], None),
            'vendor changed': lambda v, l: (b'reference libFLAC 1.4.3 20230623', l, None),
            'vendor foreign': lambda v, l: (b'my encoder', l, None),
            'count too large': lambda v, l: (v, l, 4),
            'count too small': lambda v, l: (v, l, 2)}
        for label, change in cases.items():
            with self.subTest(label):
                directory = self.forge_comments('labelled', change)
                self.verify(directory)
        self.assertEqual(title, comments_of((self.runs['labelled'][0] / 'audio.flac').read_bytes())[1][0])

    def test_trailing_bytes_inside_the_comment_block_are_refused(self):
        directory = self.copy()
        data = (directory / 'audio.flac').read_bytes()
        vendor, lines = comments_of(data)
        (directory / 'audio.flac').write_bytes(replace_comment(data, comment_block(lines, vendor) + b'\0\0'))
        refresh(directory)
        self.verify(directory)

    def test_labels_added_to_or_removed_from_the_request_without_the_flac_are_refused(self):
        plain = self.copy('plain')
        doc = {**self.runs['plain'][1], 'metadata': {'title': 'Smuggled'}}
        for name, value in (('authored.json', doc), ('plan.json', adaptor.plan(doc)), ('captures.json', {**adaptor.read_json(plain, 'captures.json'), 'metadata': doc['metadata']})):
            atomic_json(plain / name, value)
        rebind(plain)
        self.assertIn('VORBIS_COMMENT', self.verify(plain).message)      # the capture record is consistent: only the published comment can refuse it
        labelled = self.copy()
        bare = self.runs['plain'][1]
        captures = {k: v for k, v in adaptor.read_json(labelled, 'captures.json').items() if k != 'metadata'}
        for name, value in (('authored.json', bare), ('plan.json', adaptor.plan(bare)), ('captures.json', captures)):
            atomic_json(labelled / name, value)
        rebind(labelled)
        self.assertIn('VORBIS_COMMENT', self.verify(labelled).message)

    def test_request_labels_must_agree_with_the_published_comment_values(self):
        directory = self.copy()
        doc = copy.deepcopy(self.runs['labelled'][1])
        doc['metadata']['title'] = 'Another title'
        atomic_json(directory / 'authored.json', doc)
        atomic_json(directory / 'plan.json', adaptor.plan(doc))
        atomic_json(directory / 'captures.json', {**adaptor.read_json(directory, 'captures.json'), 'metadata': doc['metadata']})
        rebind(directory)
        self.assertIn('VORBIS_COMMENT', self.verify(directory).message)

    def test_pcm_forgery_with_intact_labels_is_refused(self):
        directory = self.copy()
        data = (directory / 'audio.flac').read_bytes()
        _, lines = comments_of(data)
        (directory / 'audio.flac').write_bytes(build_flac(16000, 2, bytes(range(256)) * 32 + bytes(4), vendor=False, extra_blocks=[(4, comment_block(lines))]))
        refresh(directory)
        self.verify(directory)

    def test_capture_summary_and_result_forgeries_are_refused(self):
        def alter(name, change):
            directory = self.copy()
            self.rewrite_json(directory, name, change)
            self.verify(directory)
        alter('captures.json', lambda v: v.pop('metadata'))
        alter('captures.json', lambda v: v['metadata'].update(title='Other'))
        alter('captures.json', lambda v: v['metadata'].update(album='x'))
        alter('flac-summary.json', lambda v: v.pop('metadata'))
        alter('flac-summary.json', lambda v: v['metadata']['comments'][0].update(value='Other'))
        alter('flac-summary.json', lambda v: v['metadata'].update(mode='otherMode'))
        alter('flac-summary.json', lambda v: v['metadata'].update(declaredBy='verified'))
        alter('flac-summary.json', lambda v: v['metadata']['comments'].reverse())
        alter('flac-summary.json', lambda v: v['metadata']['comments'][0].update(utf8Bytes=float(v['metadata']['comments'][0]['utf8Bytes'])))
        alter('result.json', lambda v: v.pop('metadata'))
        alter('result.json', lambda v: v['metadata']['labels'].update(TITLE='Other'))
        alter('result.json', lambda v: v['metadata']['labels'].pop('ARTIST'))
        alter('result.json', lambda v: v['metadata'].update(vorbisCommentBytes=float(v['metadata']['vorbisCommentBytes'])))
        alter('result.json', lambda v: v['metadata'].update(mode='verifiedIdentity'))
        alter('result.json', lambda v: v['metadata'].update(extra=True))

    def test_labels_cannot_be_promoted_into_an_untagged_publication(self):
        def alter(name, change):
            directory = self.copy('plain')
            self.rewrite_json(directory, name, change)
            self.verify(directory)
        alter('result.json', lambda v: v.update(metadata={'mode': 'authoredLabels', 'labels': {'TITLE': 'x'}, 'vorbisCommentBytes': 59}))
        alter('flac-summary.json', lambda v: v.update(metadata={'mode': 'authoredLabels', 'declaredBy': 'author', 'comments': []}))
        alter('captures.json', lambda v: v.update(metadata={'title': 'x'}))

    def test_a_changed_launcher_tag_or_missing_flag_is_refused(self):
        directory = self.copy()
        launcher = (directory / 'encode-launcher.py').read_text(encoding='utf-8')
        for old, new in (('--tag=TITLE=Café', '--tag=TITLE=Cafe'), ("'--no-utf8-convert', ", ''), ("'--tag=ARTIST=Zoë Núñez', ", '')):
            self.assertIn(old, launcher)
            (directory / 'encode-launcher.py').write_text(launcher.replace(old, new), encoding='utf-8')
            refresh(directory)
            self.fault(lambda: adaptor.verify(directory, executable=self.flac))
            (directory / 'encode-launcher.py').write_text(launcher, encoding='utf-8')
        refresh(directory)
        self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])

    def test_unreferenced_files_and_receipt_membership_still_apply(self):
        directory = self.copy()
        (directory / 'labels.txt').write_text('TITLE=x')
        self.assertIn('unreferenced', self.verify(directory).message)

    def test_old_plan_without_labels_verifies_with_the_new_code(self):
        directory = self.copy('plain')
        self.assertNotIn('metadata', adaptor.verify(directory, executable=self.flac))

    def test_ascii_labels_round_trip_without_conversion(self):
        directory, _, result, _ = self.runs['ascii']
        self.assertEqual(comments_of((directory / 'audio.flac').read_bytes())[1], [b'TITLE=Plain', b'ARTIST=Ann', b'DESCRIPTION=x=y'])
        self.assertEqual(result['metadata']['labels']['DESCRIPTION'], 'x=y')


def tool(name):
    configured = os.environ.get('SCHEMAXIS_FLAC')
    path = Path(configured).with_name(name) if configured else None
    return str(path) if path and path.is_file() and os.access(path, os.X_OK) else None


@unittest.skipUnless(os.environ.get('SCHEMAXIS_FLAC') and tool('metaflac'), 'real flac and a sibling metaflac are not configured: see tools/qualify_flac_tags.py')
class RealFlacLabels(unittest.TestCase):
    """Real FLAC 1.5 ``flac``: tagged ASCII and Unicode archives, read back by independent ``metaflac`` and a literal binary reader."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.flac, self.metaflac = os.environ['SCHEMAXIS_FLAC'], tool('metaflac')
        self.wav = FIXTURES / 'stereo-16000.wav'

    def metaflac_value(self, path, field):
        done = subprocess.run([self.metaflac, '--no-utf8-convert', '--show-tag=' + field, str(path)], capture_output=True, env={'LC_ALL': 'C', 'LANG': 'C'}, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_ascii_unicode_and_equals_labels_are_read_back_exactly_and_the_pcm_survives(self):
        cases = {'ascii': LABELS_ASCII, 'unicode': LABELS, 'equals': {'title': '=', 'description': 'k=v=w'}}
        for name, labels in cases.items():
            with self.subTest(name):
                directory = self.root / name
                result = adaptor.run(document(labels, source=str(self.wav)), directory, executable=self.flac, timeout=120)
                self.assertTrue(result['verified'])
                data = (directory / 'audio.flac').read_bytes()
                expected = [('%s=%s' % (key.upper(), value)).encode() for key, value in labels.items() if key in ('title', 'artist', 'description')]
                self.assertEqual(comments_of(data)[1], sorted(expected, key=lambda line: ['TITLE', 'ARTIST', 'DESCRIPTION'].index(line.split(b'=')[0].decode())))
                for key, value in labels.items():
                    self.assertEqual(self.metaflac_value(directory / 'audio.flac', key.upper()), ('%s=%s\n' % (key.upper(), value)).encode())
                decoded = self.root / (name + '.pcm')
                subprocess.run([self.flac, '-d', '-s', '--force-raw-format', '--endian=little', '--sign=signed', '-o', str(decoded), str(directory / 'audio.flac')], check=True, timeout=60)
                self.assertEqual(decoded.read_bytes(), self.wav.read_bytes()[44:])
                self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])

    def test_unicode_labels_survive_an_inherited_ascii_python_locale(self):
        directory = self.root / 'ascii-locale'
        with mock.patch.dict(os.environ, {'LC_ALL': 'C', 'LC_CTYPE': 'C',
                                         'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0'}):
            result = adaptor.run(document(LABELS, source=str(self.wav)), directory,
                                 executable=self.flac, timeout=120)
            self.assertTrue(result['verified'])
            self.assertTrue(adaptor.verify(directory, executable=self.flac)['verified'])
        for field, value in LABELS.items():
            self.assertEqual(self.metaflac_value(directory / 'audio.flac', field.upper()),
                             ('%s=%s\n' % (field.upper(), value)).encode('utf-8'))

    def test_refused_labels_never_reach_the_real_flac(self):
        with mock.patch.object(adaptor, 'execute', side_effect=AssertionError('native launch')):
            for value in ({'title': 'a\nb'}, {'title': 'a\u202eb'}, {}, {'x': 'y'}):
                with self.assertRaises(SchemaxisError):
                    adaptor.run(document(value, source=str(self.wav)), self.root / 'refused', executable=self.flac)
            self.assertFalse((self.root / 'refused').exists())


LABELS_ASCII = {'title': 'Plain title', 'artist': 'Ann Artist', 'description': 'A note'}


if __name__ == '__main__':
    unittest.main()
