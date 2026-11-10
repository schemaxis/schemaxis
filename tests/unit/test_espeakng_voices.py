"""eSpeak NG explicit narration voices: closed enum, exact listings, per-voice fingerprints and voice-bound verification.

Everything here uses a deterministic HOST FAKE ``espeak-ng`` that makes no speech: its tone depends on the selected ``-v`` voice,
the captured text and the rate, so it proves host behaviour only (planning, fixed argv, exact listing checks, data fingerprints,
conditional voice bindings, forged evidence with every ordinary hash refreshed and legacy compatibility of an absent voice).
Native proof with the real runtime is tools/qualify_espeakng_voices.py. A test that needs the real binary runs only when
SCHEMAXIS_ESPEAKNG is set and is reported skipped otherwise.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from schemaxis.adaptors.espeakng import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_espeakng_fakes import DATA_FILES, EN_GB, EN_US, HEADER, SCOTLAND, VERSION_TEXT, tone_pcm, wav_bytes   # noqa: E402
from test_espeakng_native_boundary import rebind, refresh   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'src'
TESTS = Path(__file__).resolve().parent
EXAMPLES = ROOT / 'examples/schemaxis'
FRENCH = "Bienvenue à la visite de l'usine. Veuillez porter vos lunettes de protection."
SPANISH = '¿Cómo estás? El niño comió mañana, detrás de la línea amarilla.'
ENGLISH = 'Welcome to the plant tour. Please wear your safety glasses.'
TEXTS = {'en-us': ENGLISH, 'en-gb': ENGLISH, 'fr-fr': FRENCH, 'es': SPANISH}

# Listings copied from the 1.52.0 runtime queries (private qualification evidence); the fake serves them by query.
LISTINGS = {
    'en': HEADER + EN_GB + EN_US + SCOTLAND,
    'en-us': HEADER + EN_US + ' 5  variant         --/M      Storm              !v/Storm             (en-us 5)\n',
    'en-gb': HEADER + ' 2  en-gb           --/M      English_(Great_Britain) gmw/en               (en 2)\n'
                      ' 5  en-gb-x-gbclan  --/M      English_(Lancaster) gmw/en-GB-x-gbclan   (en-gb 3)(en 5)\n'
                      ' 5  en-gb-x-rp      --/M      English_(Received_Pronunciation) gmw/en-GB-x-rp       (en-gb 4)(en 5)\n'
                      ' 2  en-us           --/M      English_(America)  gmw/en-US            (en 3)\n',
    'fr-fr': HEADER + ' 5  fr-fr           --/M      French_(France)    roa/fr               (fr 5)\n'
                      ' 5  fr-be           --/M      French_(Belgium)   roa/fr-BE            (fr 8)\n'
                      ' 5  fr-ch           --/M      French_(Switzerland) roa/fr-CH            (fr 8)\n',
    'es': HEADER + ' 5  es              --/M      Spanish_(Spain)    roa/es               \n'
                   ' 5  es-419          --/M      Spanish_(Latin_America) roa/es-419           (es-mx 6)\n'}
# Byte hashes recorded from the adaptor before the voice option existed: plan JSON (indent 2, sorted keys), the three launchers of three legacy
# documents (default rate 175, 240 and 120), the legacy review and losses texts and the legacy fingerprinted file list.
LEGACY = {
    'data_files': ['phontab', 'phonindex', 'phondata', 'intonations', 'en_dict', 'lang/gmw/en-US'],
    'launcher0-narrate': '178f8282b98bc8d78a8b965f1c4055047f06ae515a9ff90ba311c80eac895077',
    'launcher0-version': 'ea1b83f280e0d50508aecc9ffbc989782e931c6367857ab133f77899f228074d',
    'launcher0-voices': 'c526a8827f85f0ed2a2345856a960db729bc458b0a39233d976e798b53b6f363',
    'launcher1-narrate': '2600ca761fae0372d385dc9272c1a3f72ccdf02af9c1997a50608e15c52965eb',
    'launcher1-version': 'ea1b83f280e0d50508aecc9ffbc989782e931c6367857ab133f77899f228074d',
    'launcher1-voices': 'c526a8827f85f0ed2a2345856a960db729bc458b0a39233d976e798b53b6f363',
    'launcher2-narrate': '48988edf65671a9c2d665de9f0e401b841924a5f4706c5f29eab0235c7b72134',
    'launcher2-version': 'ea1b83f280e0d50508aecc9ffbc989782e931c6367857ab133f77899f228074d',
    'launcher2-voices': 'c526a8827f85f0ed2a2345856a960db729bc458b0a39233d976e798b53b6f363',
    'losses': '1c94e1f2735770ecda432539d49bc73d07f3f3bd6cd5d45e008e9d1a028cb5ae',
    'plan0': '7d455c645ad46413b6288954c9ba83e718897c7e92a2e53068184c5b01db0a97',
    'plan1': '96f6e6c0ac71c0ff1b295b34afda802a2fc888020439bdc7511ad8641471a6e7',
    'plan2': '27360c52bb686b86d21d35100b8101b2fa6baa5e6a6225a3e41a7d28a015be94',
    'review': 'c1c0f832b8685edb5852d076cea2de09d881fde9869c2a3a179e59e491210a4a',
}
VOICE_DATA = {'en-us': DATA_FILES, 'en-gb': ('phontab', 'phonindex', 'phondata', 'intonations', 'en_dict', 'lang/gmw/en'),
              'fr-fr': ('phontab', 'phonindex', 'phondata', 'intonations', 'fr_dict', 'en_dict', 'lang/roa/fr'),
              'es': ('phontab', 'phonindex', 'phondata', 'intonations', 'es_dict', 'en_dict', 'lang/roa/es')}
# SHA-256 of the original six-file fingerprint over this fixture (every file is b'fake native data ' + name), computed by the adaptor before the voice-file check existed.
LEGACY_FINGERPRINT_OF_FIXTURE = '2e985afef0107d104a0991447a842ef7cefa2be33d002971ea87a97d7c5c78cd'
ALL_DATA = sorted({name for names in VOICE_DATA.values() for name in names})
# The three voice files of the 1.52.0 runtime data, byte for byte (private qualification evidence; the same bytes the official 1.52.0 tag ships in
# espeak-ng-data/lang). Their first ``language`` lines are en-gb, fr-fr and es and none declares a ``dictionary``. gmw/en-US is the legacy file: hashed, never parsed.
VOICE_FILES = {
    'lang/gmw/en': b'name English (Great Britain)\nlanguage en-gb  2\nlanguage en 2\n\nmaintainer Reece H. Dunn <msclrhd@gmail.com>\nstatus mature\n\ntunes s1 c1 q1 e1\n',
    'lang/roa/fr': b'name French (France)\nlanguage fr-fr\nlanguage fr\n\ndictrules 1\ntunes s3 c3 q3 e3\n',
    'lang/roa/es': b'name Spanish (Spain)\nlanguage es\ndictrules 1\ntunes s6 c6 q6 e6\n'}
VOICE_FILE_OF = {'en-gb': 'lang/gmw/en', 'fr-fr': 'lang/roa/fr', 'es': 'lang/roa/es'}
# The ``-v`` value of each voice. The three NEW voices are selected by the fixed identifier of the native voice file (``data/lang/<identifier>``), never by the
# language name: espeak-ng resolves a name through data/voices/<name>, data/lang/<name>, a name or identifier-suffix match and a language score, any of which a
# modified data directory can redirect. The legacy en-us keeps its name.
VOICE_ARGUMENT = {'en-us': 'en-us', 'en-gb': 'gmw/en', 'fr-fr': 'roa/fr', 'es': 'roa/es'}

FAKE = '''#!{python}
import json, sys
sys.path.insert(0, {tests!r})
from test_espeakng_fakes import tone_pcm, wav_bytes
LISTINGS = {listings!r}
args = sys.argv[1:]
if {log!r}:
    open({log!r}, 'a').write(json.dumps(args) + '\\n')
if args == ['--version']:
    sys.stdout.write({version!r}); sys.exit(0)
if len(args) == 1 and args[0].startswith('--voices='):
    sys.stdout.write(LISTINGS.get(args[0][9:], '')); sys.exit(0)
voice = [a for a in args if a.startswith('-v')][0][2:]
text = open(args[args.index('-f') + 1], 'rb').read()
rate = int([a for a in args if a.startswith('-s')][0][2:])
wav = wav_bytes(tone_pcm(voice.encode() + b'|' + text, rate))
wav = {transform}
if wav is not None:
    open(args[args.index('-w') + 1], 'wb').write(wav)
'''


def make_voice_data(directory, tag=b''):
    """A fake data directory with every file any voice fingerprints (realistic voice files for en-gb, fr-fr and es); ``tag`` changes all of them."""
    directory = Path(directory)
    for name in ALL_DATA:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # a voice file is a realistic one; ``tag`` is appended as a native ``//`` comment line so every file still changes
        path.write_bytes(VOICE_FILES[name] + (b'// ' + tag + b'\n' if tag else b'') if name in VOICE_FILES else b'fake native data ' + name.encode() + tag)
    return str(directory)


def fake_tone(voice, text, rate=175):
    return tone_pcm(VOICE_ARGUMENT[voice].encode() + b'|' + text.encode('utf-8'), rate)    # the fake's tone follows the actual -v argument


def document(voice=None, text=None, **extra):
    base = {'version': 'schemaxis.espeakng/1', 'operation': 'narrate', 'text': text if text is not None else TEXTS[voice or 'en-us']}
    if voice is not None:
        base['voice'] = voice
    return {**base, **extra}


class VoiceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_voice_data(self.root / 'data')
        self.log = self.root / 'argv.log'
        self.espeak = self.program('espeak-ng', log=str(self.log))

    def program(self, name, *, listings=None, transform='wav', log='', data=None):
        path = self.root / name
        path.write_text(FAKE.format(python=sys.executable, tests=str(TESTS), listings={**LISTINGS, **(listings or {})}, marker='', transform=transform, log=log,
                                    version=VERSION_TEXT % (data or self.data)))
        path.chmod(0o700)
        return str(path)

    def fault(self, action, code):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code, caught.exception.fault.to_dict())
        return caught.exception.fault

    def publish(self, doc, name='run', executable=None):
        directory = self.root / name
        return directory, adaptor.run(doc, directory, executable=executable or self.espeak, timeout=60)

    def verify_fault(self, directory, code='VERIFICATION_FAILED', executable=None):
        return self.fault(lambda: adaptor.verify(directory, executable=executable or self.espeak), code)

    def invocations(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def write(self, directory, name, value):
        atomic_json(Path(directory) / name, value)


class VoicePlanning(VoiceCase):
    def test_absent_voice_is_the_unchanged_legacy_plan(self):
        planned = adaptor.plan(document())
        self.assertNotIn('voice', planned)
        self.assertEqual((planned['native']['voice'], planned['native']['voicesQuery']), ('en-us', ['--voices=en']))
        self.assertIs(planned['losses'], adaptor.LOSSES)
        digests = {}
        for index, doc in enumerate((document(text='Welcome to the plant tour.'), document(text='Digits 1 2 3', rateWpm=240),
                                     {'version': 'schemaxis.espeakng/1', 'operation': 'narrate', 'source': '/tmp/x.txt', 'rateWpm': 120})):
            digests['plan%d' % index] = hashlib.sha256(json.dumps(adaptor.plan(doc), indent=2, sort_keys=True).encode()).hexdigest()
        self.assertEqual({k: v for k, v in LEGACY.items() if k.startswith('plan')}, digests)

    def test_absent_voice_launchers_and_texts_are_byte_identical_to_the_legacy_ones(self):
        observed = {}
        for index, doc in enumerate((document(text='x y'), document(text='Digits 1 2 3', rateWpm=240),
                                     {'version': 'schemaxis.espeakng/1', 'operation': 'narrate', 'source': '/tmp/x.txt', 'rateWpm': 120})):
            prepared = adaptor.plan(doc)
            for stage, (command, names, limit) in adaptor.stage_commands(prepared['rateWpm'], '/x/espeak-ng').items():
                observed['launcher%d-%s' % (index, stage)] = hashlib.sha256(adaptor.launcher(stage, names, command, limit).encode()).hexdigest()
        self.assertEqual({k: v for k, v in LEGACY.items() if k.startswith('launcher')}, observed)
        self.assertEqual(hashlib.sha256(adaptor.REVIEW.encode()).hexdigest(), LEGACY['review'])
        self.assertEqual(hashlib.sha256(json.dumps(adaptor.LOSSES).encode()).hexdigest(), LEGACY['losses'])
        self.assertEqual(list(adaptor.DATA_FILES), LEGACY['data_files'])

    def test_explicit_voices_select_fixed_arguments_and_listing_queries(self):
        queries = {'en-us': '--voices=en', 'en-gb': '--voices=en-gb', 'fr-fr': '--voices=fr-fr', 'es': '--voices=es'}
        for voice, query in queries.items():
            with self.subTest(voice):
                planned = adaptor.plan(document(voice, rateWpm=150))
                self.assertEqual(planned['voice'], voice)
                self.assertEqual((planned['native']['voice'], planned['native']['voicesQuery']), (voice, [query]))
                self.assertEqual(planned['native']['arguments'], ['-v' + VOICE_ARGUMENT[voice], '-s150', '-p50', '-a100', '-b1', '-w', 'native.wav', '-f', 'captured.txt'])
                self.assertEqual(planned, adaptor.plan(document(voice, rateWpm=150)))
                self.assertIs(planned['losses'], adaptor.LOSSES_VOICE)
                commands = adaptor.stage_commands(150, '/x/espeak-ng', voice)
                self.assertEqual(commands['voices'][0], ['/x/espeak-ng', query])
                self.assertEqual(commands['narrate'][0], ['/x/espeak-ng', *planned['native']['arguments']])
        self.assertEqual(list(adaptor.VOICE_CHOICES), ['en-us', 'en-gb', 'fr-fr', 'es'])

    def test_new_voices_are_selected_by_the_fixed_voice_file_identifier_never_by_the_language_name_or_an_authored_path(self):
        expected = {'en-gb': 'gmw/en', 'fr-fr': 'roa/fr', 'es': 'roa/es'}
        for voice, identifier in expected.items():
            with self.subTest(voice):
                profile = adaptor.VOICE_PROFILES[voice]
                self.assertEqual(profile['argument'], identifier)
                # one fixed identifier: the one exact listing row, the inspected and hashed voice file and the -v value all name the same native file
                self.assertEqual((profile['listing']['file'], profile['voiceFile']), (identifier, 'lang/' + identifier))
                self.assertEqual(adaptor.narrate_arguments(150, voice)[0], '-v' + identifier)
                self.assertNotIn('-v' + voice, adaptor.narrate_arguments(150, voice))
                for rate in (adaptor.RATE_MIN, 175, adaptor.RATE_MAX):
                    self.assertEqual(adaptor.plan(document(voice, rateWpm=rate))['native']['arguments'][0], '-v' + identifier)
                self.assertEqual(adaptor.stage_commands(150, '/x/espeak-ng', voice)['narrate'][0][1], '-v' + identifier)
                self.assertEqual(adaptor.stage_commands(150, '/x/espeak-ng', voice)['voices'][0], ['/x/espeak-ng', profile['query']])
        # the legacy en-us profile has no fixed file argument: absent and explicit en-us keep the language name
        self.assertNotIn('argument', adaptor.VOICE_PROFILES['en-us'])
        for voice in (None, 'en-us'):
            self.assertEqual(adaptor.plan(document(voice, rateWpm=175))['native']['arguments'][0], '-ven-us')
        # the mapping is host code: the authored closed enum is unchanged and no authored path or identifier selects a voice
        self.assertEqual(list(adaptor.VOICE_CHOICES), ['en-us', 'en-gb', 'fr-fr', 'es'])
        self.assertEqual(adaptor.OPTIONS['voice'], {'type': 'enum', 'values': ['en-us', 'en-gb', 'fr-fr', 'es']})
        for identifier in expected.values():
            bad = document(text=ENGLISH)
            bad['voice'] = identifier
            self.fault(lambda: adaptor.plan(bad), 'INVALID_ARGUMENT')

    def test_invalid_voices_are_refused_by_plan_before_any_native_or_output_work(self):
        bad_values = ['de', 'fr-be', 'fr-FR', 'es-419', 'en-gb-x-rp', 'EN-GB', 'en', 'fr', 'fr-fr+m1', 'fr-fr ', ' fr-fr', '', 'variant', 'gmw/en', 'roa/fr', 'roa/es',
                      'lang/roa/fr', 'voices/roa/fr', 'gmw/en-US', '/usr/share/espeak-ng-data/voices/fr', '../fr-fr', 'fr-fr\0', '!v/Storm', 'auto', 'Storm', None, 1, 1.5, True, ['fr-fr'], {'voice': 'fr-fr'}]
        for value in bad_values:
            with self.subTest(repr(value)):
                directory = self.root / ('bad-%d' % abs(hash(repr(value))))
                bad = document(text=ENGLISH)
                bad['voice'] = value
                self.fault(lambda: adaptor.plan(bad), 'INVALID_ARGUMENT')
                self.fault(lambda: adaptor.run(bad, directory, executable=self.espeak, timeout=60), 'INVALID_ARGUMENT')
                self.assertFalse(directory.exists())
        self.assertEqual(self.invocations(), [])

    def test_unknown_voice_related_names_are_unknown_arguments(self):
        for key in ('voices', 'voiceName', 'voiceFile', 'voicePath', 'variant', 'language', 'lang', 'translate', 'detect', 'autodetect', 'ssml', 'phonemes', 'flags', 'arguments',
                    'pitch', 'espeakVoice', 'locale'):
            with self.subTest(key):
                bad = document('fr-fr')
                bad[key] = 'fr-fr'
                self.fault(lambda: adaptor.plan(bad), 'UNKNOWN_ARGUMENT')
        self.assertEqual(self.invocations(), [])

    def test_voice_does_not_change_the_text_profile_or_budgets(self):
        for voice in adaptor.VOICE_CHOICES:
            for text, code in (('[[h@l\'oU]]', 'INVALID_ESPEAKNG_TEXT'), ('<b>bonjour</b>', 'INVALID_ESPEAKNG_TEXT'), ('a\tb', 'INVALID_ESPEAKNG_TEXT'), ('x' * 1025, 'ESPEAKNG_BUDGET')):
                with self.subTest(voice, text=text[:6]):
                    self.fault(lambda: adaptor.plan(document(voice, text=text)), code)
        for voice in ('fr-fr', 'es'):
            adaptor.plan(document(voice, text='¿Qué? ¡Sí! À bientôt, déjà vu — «très bien» ñandú'))    # accented letters and ¿ ¡ « » — are plain text

    def test_schema_offers_the_closed_optional_voice_in_every_alternative_without_a_default(self):
        schema = adaptor.schema()
        literal, file = schema['oneOf']
        for item in (schema, literal, file):
            self.assertEqual(item['properties']['voice'], {'enum': ['en-us', 'en-gb', 'fr-fr', 'es']})
            self.assertNotIn('voice', item['required'])
        self.assertFalse(schema['additionalProperties'])
        json.dumps(schema, allow_nan=False)

    def test_examples_plan_and_the_invalid_example_is_refused(self):
        from schemaxis import workflow
        for name, voice in (('en-gb', 'en-gb'), ('fr-fr', 'fr-fr'), ('es', 'es')):
            example = json.loads((EXAMPLES / ('espeakng-voice-%s.json' % name)).read_text())
            self.assertEqual(adaptor.plan(example)['voice'], voice)
        self.fault(lambda: adaptor.plan(json.loads((EXAMPLES / 'espeakng-voice-invalid.json').read_text())), 'INVALID_ARGUMENT')
        planned = workflow.inspect_plan(json.loads((EXAMPLES / 'espeakng-voice-archive-workflow.json').read_text()))
        self.assertEqual([entry['id'] for entry in planned['operations']], ['narration', 'speech', 'archive'])
        self.assertEqual([planned['operations'][i]['provisionalPlan']['status'] for i in (1, 2)], ['deferred', 'deferred'])


class VoiceListing(unittest.TestCase):
    def test_each_voice_is_accepted_only_by_its_exact_listing(self):
        for voice, profile in adaptor.VOICE_PROFILES.items():
            with self.subTest(voice):
                query = profile['query'][len('--voices='):]
                self.assertEqual(adaptor.check_voice(LISTINGS[query], voice), profile['listing'])
        self.assertEqual(adaptor.check_voice(LISTINGS['fr-fr'], 'fr-fr'), {'language': 'fr-fr', 'name': 'French_(France)', 'file': 'roa/fr'})
        self.assertEqual(adaptor.check_voice(LISTINGS['en'], 'en-us')['file'], 'gmw/en-US')

    def refused(self, table, voice):
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.check_voice(table, voice)
        self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('UNSUPPORTED_RUNTIME', 'voices'))

    def test_a_listing_must_name_the_selected_language_in_the_first_column_with_the_expected_name_and_file(self):
        row = ' 5  %-14s --/M      %s %s (x)\n'
        cases = {
            'fr-fr': (HEADER, HEADER + row % ('fr-be', 'French_(Belgium)', 'roa/fr-BE'),
                      HEADER + ' 5  fr-be           --/M      French_(Belgium)   roa/fr-BE            (fr-fr 5)\n',           # only in Other Languages
                      HEADER + row % ('fr-fr', 'French_(Belgium)', 'roa/fr'), HEADER + row % ('fr-fr', 'French_(France)', 'roa/fr-BE'),
                      HEADER + row % ('fr-fr', 'French_(France)', 'roa/es'), LISTINGS['es'], LISTINGS['en'], '', 'fr-fr\n'),
            'es': (HEADER + row % ('es-419', 'Spanish_(Latin_America)', 'roa/es-419'), HEADER + row % ('es', 'Spanish_(Latin_America)', 'roa/es'),
                   HEADER + row % ('es', 'Spanish_(Spain)', 'roa/es-419'), LISTINGS['fr-fr']),
            'en-gb': (HEADER + EN_US, HEADER + ' 5  en-gb-x-rp      --/M      English_(Received_Pronunciation) gmw/en-GB-x-rp       (en-gb 4)(en 5)\n',
                      HEADER + row % ('en-gb', 'English_(Great_Britain)', 'gmw/en-US'), HEADER + row % ('en-gb', 'English_(America)', 'gmw/en'), LISTINGS['fr-fr']),
            'en-us': (HEADER + EN_GB, HEADER + row % ('en-us', 'English_(America)', 'gmw/en'), '')}
        for voice, tables in cases.items():
            for index, table in enumerate(tables):
                with self.subTest(voice, case=index):
                    self.refused(table, voice)

    def row_of(self, voice):
        query = adaptor.VOICE_PROFILES[voice]['query'][len('--voices='):]
        return next(line + '\n' for line in LISTINGS[query].splitlines() if adaptor.VOICE_ROW.fullmatch(line) and line.split()[1] == voice)

    def refusal(self, table, voice):
        with self.assertRaises(SchemaxisError) as caught:
            adaptor.check_voice(table, voice)
        self.assertEqual((caught.exception.fault.code, caught.exception.fault.location), ('UNSUPPORTED_RUNTIME', 'voices'))
        return caught.exception.fault.message

    def test_a_selected_voice_listed_twice_is_refused_whether_the_rows_are_identical_or_conflict(self):
        wrong = {'fr-fr': ' 5  fr-fr           --/M      French_(Belgium)   roa/fr-BE            (fr 8)\n',
                 'es': ' 5  es              --/M      Spanish_(Latin_America) roa/es-419           (es-mx 6)\n',
                 'en-gb': ' 5  en-gb           --/M      English_(Scotland) gmw/en-GB-scotland   (en 4)\n',
                 'en-us': ' 5  en-us           --/M      English_(Canada)   gmw/en-CA            (en 3)\n'}
        for voice, profile in adaptor.VOICE_PROFILES.items():
            query = profile['query'][len('--voices='):]
            table, row = LISTINGS[query], self.row_of(voice)
            with self.subTest(voice, case='identical'):
                message = self.refusal(table + row, voice)
                self.assertIn('2 times', message)
                self.assertIn('identical', message)
                self.assertNotIn('conflicting', message)
            with self.subTest(voice, case='identical three times'):
                self.assertIn('3 times', self.refusal(table + row + row, voice))
            with self.subTest(voice, case='identical with another other-languages column'):
                self.assertIn('2 times', self.refusal(table + row.rstrip('\n') + ' (xx 9)\n', voice))
            with self.subTest(voice, case='conflicting, expected row first'):
                message = self.refusal(table + wrong[voice], voice)
                self.assertIn('2 times', message)
                self.assertIn('conflicting', message)
            with self.subTest(voice, case='conflicting, expected row last'):
                self.assertIn('conflicting', self.refusal(HEADER + wrong[voice] + row, voice))

    def test_the_duplicate_refusal_is_distinct_from_the_missing_and_wrong_row_refusals(self):
        messages = {'missing': self.refusal(HEADER, 'fr-fr'), 'wrong': self.refusal(HEADER + ' 5  fr-fr           --/M      French_(Belgium)   roa/fr-BE            (fr 8)\n', 'fr-fr'),
                    'duplicate': self.refusal(LISTINGS['fr-fr'] + self.row_of('fr-fr'), 'fr-fr')}
        self.assertEqual(len(set(messages.values())), 3, messages)
        self.assertIn('does not list', messages['missing'])
        self.assertIn('not the expected', messages['wrong'])
        self.assertIn('times', messages['duplicate'])
        # the single exact row of every voice is still the only accepted shape
        for voice, profile in adaptor.VOICE_PROFILES.items():
            self.assertEqual(adaptor.check_voice(LISTINGS[profile['query'][len('--voices='):]], voice), profile['listing'])

    def test_fallback_voice_listing_for_another_query_is_not_accepted(self):
        for voice in ('en-gb', 'fr-fr', 'es'):
            self.refused(LISTINGS['en'] if voice != 'en-gb' else LISTINGS['en-us'], voice)


class VoiceFingerprints(VoiceCase):
    def legacy_fingerprint(self, root):
        hashes = {name: hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() for name in DATA_FILES}
        return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()

    def test_en_us_fingerprint_is_the_legacy_one_and_other_voices_differ(self):
        self.assertEqual(adaptor.data_fingerprint(self.data), self.legacy_fingerprint(self.data))
        self.assertEqual(adaptor.data_fingerprint(self.data, 'en-us'), self.legacy_fingerprint(self.data))
        prints = {voice: adaptor.data_fingerprint(self.data, voice) for voice in adaptor.VOICE_CHOICES}
        self.assertEqual(len(set(prints.values())), 4)
        for voice, names in VOICE_DATA.items():
            self.assertEqual(tuple(adaptor.VOICE_PROFILES[voice]['data']), names)

    def test_each_voice_fingerprints_its_own_dictionary_and_voice_file_and_nothing_else(self):
        for voice, names in VOICE_DATA.items():
            first = adaptor.data_fingerprint(self.data, voice)
            for name in ALL_DATA:
                path = Path(self.data) / name
                saved = path.read_bytes()
                path.write_bytes(saved + b'!')
                with self.subTest(voice, name=name):
                    if name in names:
                        self.assertNotEqual(adaptor.data_fingerprint(self.data, voice), first)
                    else:
                        self.assertEqual(adaptor.data_fingerprint(self.data, voice), first)
                path.write_bytes(saved)
        # French and Spanish are never fingerprinted with the English dictionary alone.
        self.assertIn('fr_dict', VOICE_DATA['fr-fr'])
        self.assertIn('es_dict', VOICE_DATA['es'])
        self.assertNotIn('fr_dict', VOICE_DATA['es'])

    def test_missing_selected_voice_or_dictionary_is_an_incomplete_runtime(self):
        for voice, names in VOICE_DATA.items():
            for name in names:
                path = Path(self.data) / name
                saved = path.read_bytes()
                path.unlink()
                with self.subTest(voice, name=name):
                    self.assertEqual(self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME').location, 'version')
                path.write_bytes(saved)


class VoiceFileResolution(VoiceCase):
    """The bounded check of the selected voice file of the NEW profiles (en-gb, fr-fr, es), after the native LoadVoice/fgets_strip of eSpeak NG 1.52.0.

    Read from the 1.52.0 source: a line starting with ``#`` is blank; trailing whitespace is dropped; ``//`` truncates the line; the attribute is
    the text before the first whitespace, matched case-sensitively, so a line that starts with whitespace is ignored; only the FIRST ``language`` line
    sets the translator and dictionary (its text before the first ``-``); a ``dictionary`` line overrides the dictionary name; a keyword without an
    argument reads past the end of the line in the native code. Nothing else in the file is interpreted here.
    """
    legacy_name = 'lang/gmw/en-US'

    def put(self, voice, data):
        (Path(self.data) / VOICE_FILE_OF[voice]).write_bytes(data)

    def refused(self, voice, data, fragment):
        self.put(voice, data)
        fault = self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME')
        self.assertEqual(fault.location, 'version')
        self.assertIn(fragment, fault.message, fault.message)
        self.assertIn(VOICE_FILE_OF[voice], fault.message)
        self.assertTrue(fault.observed.get('recovery'), fault.to_dict())
        return fault

    def expected_fingerprint(self, voice):
        hashes = {name: hashlib.sha256((Path(self.data) / name).read_bytes()).hexdigest() for name in VOICE_DATA[voice]}
        return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()

    def test_the_genuine_1_52_0_voice_files_are_accepted_and_hashed_exactly(self):
        for voice in VOICE_FILE_OF:
            with self.subTest(voice):
                self.assertEqual((Path(self.data) / VOICE_FILE_OF[voice]).read_bytes(), VOICE_FILES[VOICE_FILE_OF[voice]])
                self.assertEqual(adaptor.data_fingerprint(self.data, voice), self.expected_fingerprint(voice))

    def test_native_comment_whitespace_secondary_language_and_line_ending_forms_are_accepted(self):
        accepted = {
            'fr-fr': (b'language fr-fr', b'language fr-fr\r\nlanguage fr\r\n', b'language\tfr-fr\t5\n', b'language   fr-fr   \n', b'language fr-fr 2 extra words\n',
                      b'# comment\n// full line comment\nname Fran\xc3\xa7ais\nlanguage fr-fr // primary\nlanguage fr 5\n', b'\n\n  \nlanguage fr-fr\n',
                      b'language fr-fr\nlanguage en 2\nlanguage de 3\n',                 # secondary languages never select the dictionary
                      b'language fr-fr\ndictionary fr\n', b'dictionary fr\nlanguage fr-fr\n',        # a repeat of the expected dictionary changes nothing
                      b'language fr-fr\n language de-de\n  dictionary de\n',                 # a line starting with whitespace has an empty attribute and is ignored
                      b'language fr-fr\n// dictionary de\n# dictionary de\n',
                      b'language fr-fr\nDictionary de\nLanguage de-de\nphonemes fr\nunknown thing\n'),    # keywords are case-sensitive: other names are not these declarations
            'es': (b'language es\n', b'language es 5\nlanguage es-419\n', b'name x\r\nlanguage es\r\n'),
            'en-gb': (b'language en-gb  2\nlanguage en 2\n', b'language en-gb\nlanguage en-us 3\nlanguage en 5\n', b'language en-gb\ndictionary en\n')}
        for voice, files in accepted.items():
            for index, data in enumerate(files):
                with self.subTest(voice, case=index):
                    self.put(voice, data)
                    self.assertEqual(adaptor.data_fingerprint(self.data, voice), self.expected_fingerprint(voice))

    def test_a_wrong_primary_language_is_refused_even_when_the_expected_one_appears_later(self):
        for voice, bad in (('fr-fr', b'name x\nlanguage de-de\n'), ('fr-fr', b'language es\n'), ('fr-fr', b'language en-gb 2\nlanguage fr-fr\n'), ('fr-fr', b'language de-de\nlanguage fr-fr\nlanguage fr\n'),
                           ('es', b'language fr-fr\nlanguage fr\n'), ('en-gb', b'language fr-fr\n'), ('en-gb', b'language de\nlanguage en-gb\n'), ('es', VOICE_FILES['lang/roa/fr']),
                           ('fr-fr', VOICE_FILES['lang/roa/es']), ('fr-fr', VOICE_FILES['lang/gmw/en'])):
            with self.subTest(voice, data=bad[:30]):
                self.refused(voice, bad, 'primary language')

    def test_the_right_stem_with_another_region_is_not_the_listed_language(self):
        for voice, bad in (('fr-fr', b'language fr-be\n'), ('fr-fr', b'language fr\nlanguage fr-fr\n'), ('fr-fr', b'language fr-ch 5\n'), ('es', b'language es-419\n'),
                           ('en-gb', b'language en-us 2\nlanguage en 3\n'), ('en-gb', b'language en\n'), ('en-gb', b'language en-gb-x-rp\n')):
            with self.subTest(voice, data=bad[:30]):
                self.refused(voice, bad, 'first language')

    def test_a_missing_primary_language_is_refused(self):
        for voice in VOICE_FILE_OF:
            for index, bad in enumerate((b'', b'\n', b'name Something\ndictrules 1\ntunes s3 c3 q3 e3\n', b'# language fr-fr\n// language fr-fr\n', b' language %s\n' % voice.encode(),
                                         b'Language %s\n' % voice.encode(), b'languages %s\n' % voice.encode(), b'name language %s\n' % voice.encode(),
                                         b'\xef\xbb\xbflanguage %s\n' % voice.encode(),         # a byte order mark makes the first attribute another name
                                         b'language\xc2\xa0%s\n' % voice.encode())):           # a no-break space is not native whitespace
                with self.subTest(voice, case=index):
                    self.refused(voice, bad, 'no primary language')

    def test_a_foreign_dictionary_override_is_refused_anywhere_in_the_file(self):
        for voice, bad in (('fr-fr', b'language fr-fr\ndictionary de\n'), ('fr-fr', b'dictionary de\nlanguage fr-fr\n'), ('fr-fr', b'language fr-fr\ndictionary en\nlanguage fr\n'),
                           ('fr-fr', b'language fr-fr\ndictionary fr_dict\n'), ('fr-fr', b'language fr-fr\ndictionary es   // not a comment-only line\n'),
                           ('fr-fr', b'language fr-fr\ndictionary\tde\n'), ('es', b'language es\ndictionary fr\n'), ('en-gb', b'language en-gb\ndictionary fr\n'),
                           ('en-gb', b'language en-gb\ndictionary en-gb\n'), ('es', b'language es\ndictionary ES\n'), ('fr-fr', b'language fr-fr\ndictionary fr\ndictionary de\n')):
            with self.subTest(voice, data=bad[:40]):
                self.refused(voice, bad, 'dictionary')

    def test_declarations_without_a_usable_argument_are_refused_because_the_native_parser_reads_past_the_line(self):
        for voice in VOICE_FILE_OF:
            good = b'language %s\n' % voice.encode()
            for index, bad in enumerate((good + b'dictionary\n', good + b'dictionary   \n', good + b'dictionary // de\n', good + b'dictionary\t\n', b'language\n' + good,
                                         b'language \n' + good, good + b'language\n', b'language // x\n' + good, good + b'language  \r\n')):
                with self.subTest(voice, case=index):
                    self.refused(voice, bad, 'without an argument')

    def test_malformed_unsupported_or_oversized_language_declarations_are_refused(self):
        for voice in VOICE_FILE_OF:
            good = b'language %s\n' % voice.encode()
            for bad, fragment in ((b'language variant\n' + good, 'variant'), (good + b'language variant\n', 'variant'), (b'language FR-FR\n', 'malformed'),
                                  (b'language fr_fr\n', 'malformed'), (b'language fr-\n', 'malformed'), (b'language -fr\n', 'malformed'), (b'language f\n', 'malformed'),
                                  (b'language fr--fr\n', 'malformed'), (b'language fr-fr!\n', 'malformed'), (good + b'language !!\n', 'malformed'),
                                  (good + b'language ' + b'a' * 40 + b'\n', 'too long'), (good + b'dictionary ' + b'a' * 40 + b'\n', 'too long'),
                                  (good + b'# ' + b'x' * 200 + b'\n', 'line longer'), (good + b'name ' + b'y' * 161 + b'\n', 'line longer'),
                                  (good + b'\0\n', 'NUL'), (b'\0' + good, 'NUL'), (b'name Fran\xe7ais\n' + good, 'UTF-8'), (good + b'name \xff\xfe\n', 'UTF-8'), (good + b'\xc3\n', 'UTF-8')):
                with self.subTest(voice, data=bad[:40]):
                    self.refused(voice, bad, fragment)

    def test_the_longest_accepted_line_is_inside_the_smallest_native_buffer(self):
        for voice in VOICE_FILE_OF:
            self.put(voice, b'language %s\n' % voice.encode() + b'#' + b'x' * (adaptor.VOICE_FILE_LINE_LIMIT - 2) + b'\n')      # a line of LIMIT - 1 bytes
            self.assertEqual(adaptor.data_fingerprint(self.data, voice), self.expected_fingerprint(voice))
            self.put(voice, b'language %s\n' % voice.encode() + b'#' + b'x' * (adaptor.VOICE_FILE_LINE_LIMIT - 1) + b'\n')      # a line of LIMIT bytes
            self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME')
        self.assertLess(adaptor.VOICE_FILE_LINE_LIMIT, 160 + 30)       # N_PATH_HOME_DEF of the smallest platform + the 30 bytes LoadVoice adds, NUL included

    def test_the_voice_file_must_be_a_bounded_regular_file_that_is_not_shadowed(self):
        for voice, name in VOICE_FILE_OF.items():
            path = Path(self.data) / name
            genuine = path.read_bytes()
            outside = self.root / ('outside-' + voice)
            outside.write_bytes(genuine)
            with self.subTest(voice, case='symlink'):
                path.unlink()
                path.symlink_to(outside)
                self.assertIn('incomplete', self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME').message)
            with self.subTest(voice, case='directory'):
                path.unlink()
                path.mkdir()
                self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME')
                path.rmdir()
            with self.subTest(voice, case='fifo'):
                os.mkfifo(path)
                self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME')
                path.unlink()
            with self.subTest(voice, case='missing'):
                self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME')
            filler = b'#' + b'x' * 98 + b'\n'
            with self.subTest(voice, case='exactly the limit'):
                body = genuine + filler * ((adaptor.DATA_FILE_LIMIT - len(genuine)) // len(filler))
                body += b'#' * (adaptor.DATA_FILE_LIMIT - len(body) - 1) + b'\n'
                self.assertEqual(len(body), adaptor.DATA_FILE_LIMIT)
                path.write_bytes(body)
                self.assertEqual(adaptor.data_fingerprint(self.data, voice), self.expected_fingerprint(voice))
            with self.subTest(voice, case='one byte over the limit'):
                path.write_bytes(body + b'\n')
                self.assertIn('within %d bytes' % adaptor.DATA_FILE_LIMIT, self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME').message)
            path.write_bytes(genuine)
            shadow = Path(self.data) / 'voices' / name[len('lang/'):]
            with self.subTest(voice, case='an empty voices directory does not shadow'):
                shadow.parent.mkdir(parents=True, exist_ok=True)
                self.assertEqual(adaptor.data_fingerprint(self.data, voice), self.expected_fingerprint(voice))
            with self.subTest(voice, case='voices file shadows the hashed file'):
                shadow.write_bytes(b'language de-de\n')
                fault = self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME')
                self.assertEqual(fault.location, 'version')
                self.assertIn('voices/' + name[len('lang/'):], fault.message)
                shadow.unlink()
                shadow.symlink_to(outside)
                self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME')
                shadow.unlink()
            self.assertEqual(adaptor.data_fingerprint(self.data, voice), self.expected_fingerprint(voice))

    def test_the_bytes_inspected_are_the_bytes_hashed_in_one_read(self):
        for voice, name in VOICE_FILE_OF.items():
            path = Path(self.data) / name
            genuine, reads = path.read_bytes(), []
            real = adaptor.bounded

            def swapping(target, *args, **kwargs):
                data = real(target, *args, **kwargs)
                if Path(target) == path:
                    reads.append(data)
                    path.write_bytes(b'language de-de\ndictionary de\n')     # a change after the read cannot reach the fingerprint
                return data
            with self.subTest(voice), mock.patch.object(adaptor, 'bounded', swapping):
                observed = adaptor.data_fingerprint(self.data, voice)
            path.write_bytes(genuine)
            self.assertEqual((len(reads), reads[0]), (1, genuine))
            self.assertEqual(observed, self.expected_fingerprint(voice))
            # and the changed bytes would have been refused had they been the ones read
            self.put(voice, b'language de-de\ndictionary de\n')
            self.fault(lambda: adaptor.data_fingerprint(self.data, voice), 'UNSUPPORTED_RUNTIME')
            path.write_bytes(genuine)

    def test_the_legacy_en_us_fingerprint_is_the_original_six_files_and_its_voice_file_is_not_parsed(self):
        legacy = (Path(self.data) / self.legacy_name)
        before = adaptor.data_fingerprint(self.data)
        self.assertEqual(before, adaptor.data_fingerprint(self.data, 'en-us'))
        self.assertEqual(before, LEGACY_FINGERPRINT_OF_FIXTURE)
        for junk in (b'\0\xff not a voice file', b'language de-de\ndictionary de\n', b''):
            legacy.write_bytes(junk)
            hashes = {name: hashlib.sha256((Path(self.data) / name).read_bytes()).hexdigest() for name in DATA_FILES}
            self.assertEqual(adaptor.data_fingerprint(self.data), hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest())
        # the new profiles never read the legacy file, and the legacy profile never reads another voice file
        self.assertNotIn(self.legacy_name, adaptor.VOICE_PROFILES['fr-fr']['data'])
        for name in VOICE_FILE_OF.values():
            self.assertNotIn(name, adaptor.DATA_FILES)
            (Path(self.data) / name).write_bytes(b'\0 broken')
            self.assertEqual(adaptor.data_fingerprint(self.data), adaptor.data_fingerprint(self.data, 'en-us'))

    def test_the_run_refuses_before_the_voices_stage_and_a_genuine_proof_does_not_verify_on_a_changed_voice_file(self):
        directory, _ = self.publish(document('fr-fr'), name='genuine')
        self.put('fr-fr', VOICE_FILES['lang/roa/fr'] + b'dictionary de\n')
        self.log.unlink(missing_ok=True)
        fault = self.verify_fault(directory, 'UNSUPPORTED_RUNTIME')
        self.assertEqual(fault.location, 'version')
        self.assertEqual(self.invocations(), [['--version']])
        refused = self.root / 'refused'
        self.fault(lambda: adaptor.run(document('fr-fr'), refused, executable=self.espeak, timeout=60), 'UNSUPPORTED_RUNTIME')
        self.assertEqual(self.invocations(), [['--version'], ['--version']])      # never reached the voices or narrate stage
        self.assertEqual(adaptor.read_json(refused, 'result.json')['status'], 'failed')
        self.assertFalse(any((refused / name).exists() for name in ('native.wav', 'narration.wav', 'verification.json')))
        # the other new voices and the legacy voice are untouched by the broken French voice file
        self.assertEqual(self.publish(document('es'), name='es')[1]['voice'], 'es')
        self.assertEqual(self.publish(document(text=ENGLISH), name='legacy')[1]['status'], 'succeeded')
        # restoring the genuine bytes restores verification
        self.put('fr-fr', VOICE_FILES['lang/roa/fr'])
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    def test_a_broken_en_us_voice_file_does_not_affect_an_absent_or_explicit_en_us_run(self):
        (Path(self.data) / self.legacy_name).write_bytes(b'not parsed here')
        for name, doc in (('absent', document(text=ENGLISH)), ('explicit', document('en-us', text=ENGLISH))):
            self.assertEqual(self.publish(doc, name=name)[1]['status'], 'succeeded')


class VoiceBoundaries(VoiceCase):
    def test_every_voice_runs_and_verifies_with_its_own_fixed_stages_and_fresh_resynthesis(self):
        for voice in adaptor.VOICE_CHOICES:
            with self.subTest(voice):
                self.log.unlink(missing_ok=True)
                doc = document(voice, rateWpm=150)
                directory, result = self.publish(doc, name='run-' + voice)
                pcm = fake_tone(voice, TEXTS[voice], 150)
                query = adaptor.VOICE_PROFILES[voice]['query']
                narrate = ['-v' + VOICE_ARGUMENT[voice], '-s150', '-p50', '-a100', '-b1', '-w', 'native.wav', '-f', 'captured.txt']
                calls = self.invocations()                    # the run's own synthesis, then each fresh verification synthesis: every set is exactly the three fixed stages
                self.assertTrue(len(calls) >= 6 and len(calls) % 3 == 0, calls)
                self.assertEqual(calls, [['--version'], [query], narrate] * (len(calls) // 3))
                self.assertEqual(result['voice'], voice)
                self.assertEqual(result['pcmSha256'], hashlib.sha256(pcm).hexdigest())
                self.assertEqual((directory / 'narration.wav').read_bytes(), wav_bytes(pcm))
                self.assertEqual((directory / 'captured.txt').read_bytes(), TEXTS[voice].encode('utf-8'))
                summary = adaptor.read_json(directory, 'espeakng-summary.json')
                self.assertEqual(summary['voice'], {'requested': voice, 'listing': adaptor.VOICE_PROFILES[voice]['listing'], 'rateWpm': 150, 'pitch': 50, 'amplitude': 100,
                                                    'inputEncoding': 'UTF-8 (-b1)'})
                self.assertEqual(summary['runtime']['dataFingerprint'], adaptor.data_fingerprint(self.data, voice))
                self.assertEqual(summary['review'], adaptor.REVIEW_VOICE % (voice, adaptor.VOICE_PROFILES[voice]['listing']['name'], adaptor.VOICE_PROFILES[voice]['listing']['file']))
                self.assertIn('nothing is translated', summary['review'])
                self.assertNotEqual(summary['review'], adaptor.REVIEW)
                self.assertEqual(adaptor.read_json(directory, 'captures.json')['voice'], voice)
                self.assertEqual(adaptor.read_json(directory, 'verification.json')['voice'], voice)
                self.assertEqual(adaptor.read_json(directory, 'plan.json')['voice'], voice)
                self.assertEqual(adaptor.verify(directory, executable=self.espeak), {k: v for k, v in result.items() if k != 'status'})

    def test_voice_changes_the_sound_and_the_fingerprint_for_the_same_text_and_rate(self):
        pcms, prints = {}, {}
        for voice in adaptor.VOICE_CHOICES:
            directory, result = self.publish(document(voice, text=ENGLISH), name='same-' + voice)
            pcms[voice], prints[voice] = result['pcmSha256'], result['runtime']['dataFingerprint']
        self.assertEqual(len(set(pcms.values())), 4)
        self.assertEqual(len(set(prints.values())), 4)

    def test_absent_voice_publishes_exactly_the_legacy_record_shape(self):
        directory, result = self.publish(document(text=ENGLISH), name='legacy')
        self.assertNotIn('voice', result)
        self.assertEqual(sorted(adaptor.read_json(directory, 'verification.json')), ['artifacts', 'evidence', 'executables', 'runtime'])
        self.assertEqual(adaptor.read_json(directory, 'captures.json'), {'kind': 'literal', 'bytes': len(ENGLISH), 'sha256': hashlib.sha256(ENGLISH.encode()).hexdigest()})
        summary = adaptor.read_json(directory, 'espeakng-summary.json')
        self.assertEqual((summary['review'], summary['voice']['requested'], summary['voice']['listing']['file']), (adaptor.REVIEW, 'en-us', 'gmw/en-US'))
        self.assertEqual(summary['runtime']['dataFingerprint'], adaptor.data_fingerprint(self.data))
        self.assertEqual(self.invocations()[1], ['--voices=en'])
        # An explicit en-us has the same sound, stages and fingerprint but is recorded as an explicit choice.
        explicit, explicit_result = self.publish(document('en-us', text=ENGLISH), name='explicit')
        self.assertEqual((explicit_result['pcmSha256'], explicit_result['runtime']), (result['pcmSha256'], result['runtime']))
        self.assertEqual(explicit_result['voice'], 'en-us')
        queries = [call for call in self.invocations() if call[0].startswith('--voices')]
        self.assertTrue(len(queries) >= 6 and all(call == ['--voices=en'] for call in queries), queries)

    def test_a_file_source_with_a_voice_captures_the_utf8_bytes_and_records_the_voice(self):
        script = self.root / 'script.txt'
        script.write_bytes(FRENCH.encode('utf-8'))
        directory, result = self.publish({'version': 'schemaxis.espeakng/1', 'operation': 'narrate', 'source': str(script), 'voice': 'fr-fr'}, name='file')
        self.assertEqual(adaptor.read_json(directory, 'captures.json'), {'kind': 'file', 'bytes': len(FRENCH.encode()), 'sha256': hashlib.sha256(FRENCH.encode()).hexdigest(),
                                                                       'source': str(script), 'voice': 'fr-fr'})
        self.assertEqual(result['voice'], 'fr-fr')
        self.assertEqual(adaptor.reusableInputs({'version': 'schemaxis.espeakng/1', 'operation': 'narrate', 'source': str(script), 'voice': 'fr-fr'}),
                         {str(script): hashlib.sha256(FRENCH.encode()).hexdigest()})

    # ------------------------------------------------------------ runtime fallback and removal
    def test_a_runtime_that_does_not_list_the_voice_is_refused_even_though_the_native_program_would_speak(self):
        for voice in ('en-gb', 'fr-fr', 'es', 'en-us'):
            with self.subTest(voice):
                query = adaptor.VOICE_PROFILES[voice]['query'][len('--voices='):]
                silent = self.program('no-listing-' + voice, listings={query: HEADER + ' 5  de              --/M      German             gmw/de               \n'}, log=str(self.log))
                self.log.unlink(missing_ok=True)
                directory = self.root / ('refused-' + voice)
                fault = self.fault(lambda: adaptor.run(document(voice), directory, executable=silent, timeout=60), 'UNSUPPORTED_RUNTIME')
                self.assertEqual(fault.location, 'voices')
                self.assertEqual([call[0] for call in self.invocations()], ['--version', adaptor.VOICE_PROFILES[voice]['query']])    # never reached the narrate stage
                self.assertEqual(adaptor.read_json(directory, 'result.json')['status'], 'failed')
                self.assertFalse(any((directory / name).exists() for name in ('native.wav', 'narration.wav', 'verification.json')))

    def test_a_runtime_that_lists_the_selected_voice_twice_is_refused_before_synthesis_and_verification(self):
        for voice in ('en-gb', 'fr-fr', 'es', 'en-us'):
            with self.subTest(voice):
                query = adaptor.VOICE_PROFILES[voice]['query'][len('--voices='):]
                row = next(line + '\n' for line in LISTINGS[query].splitlines() if adaptor.VOICE_ROW.fullmatch(line) and line.split()[1] == voice)
                doubled = self.program('doubled-' + voice, listings={query: LISTINGS[query] + row}, log=str(self.log))
                self.log.unlink(missing_ok=True)
                directory = self.root / ('doubled-run-' + voice)
                fault = self.fault(lambda: adaptor.run(document(voice), directory, executable=doubled, timeout=60), 'UNSUPPORTED_RUNTIME')
                self.assertEqual(fault.location, 'voices')
                self.assertIn('times', fault.message)
                self.assertEqual([call[0] for call in self.invocations()], ['--version', adaptor.VOICE_PROFILES[voice]['query']])    # never reached the narrate stage
                self.assertFalse(any((directory / name).exists() for name in ('native.wav', 'narration.wav', 'verification.json')))
                genuine, _ = self.publish(document(voice), name='genuine-' + voice)
                self.assertEqual(self.verify_fault(genuine, 'UNSUPPORTED_RUNTIME', executable=doubled).location, 'voices')

    def test_a_runtime_that_lists_a_different_name_or_file_is_refused(self):
        for voice, row in (('fr-fr', ' 5  fr-fr           --/M      French_(Belgium)   roa/fr-BE            (fr 8)\n'),
                           ('es', ' 5  es              --/M      Spanish_(Latin_America) roa/es-419           (es-mx 6)\n'),
                           ('en-gb', ' 5  en-gb           --/M      English_(Scotland) gmw/en-GB-scotland   (en 4)\n')):
            with self.subTest(voice):
                query = adaptor.VOICE_PROFILES[voice]['query'][len('--voices='):]
                other = self.program('other-' + voice, listings={query: HEADER + row})
                self.fault(lambda: adaptor.run(document(voice), self.root / ('other-run-' + voice), executable=other, timeout=60), 'UNSUPPORTED_RUNTIME')

    def test_missing_voice_data_stops_before_synthesis_and_a_genuine_proof_does_not_verify_on_it(self):
        directory, _ = self.publish(document('fr-fr'), name='genuine')
        (Path(self.data) / 'lang/roa/fr').unlink()
        self.log.unlink(missing_ok=True)
        fault = self.verify_fault(directory, 'UNSUPPORTED_RUNTIME')
        self.assertEqual(fault.location, 'version')
        self.assertEqual(self.invocations(), [['--version']])
        # Restoring the file restores verification.
        make_voice_data(self.data)
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])

    def test_missing_dictionary_of_the_selected_voice_only_affects_that_voice(self):
        (Path(self.data) / 'fr_dict').unlink()
        self.fault(lambda: adaptor.run(document('fr-fr'), self.root / 'fr', executable=self.espeak, timeout=60), 'UNSUPPORTED_RUNTIME')
        directory, result = self.publish(document('es'), name='es')
        self.assertEqual(result['voice'], 'es')

    def test_unchanged_geometry_silence_and_budget_limits_apply_to_every_voice(self):
        silent = self.program('silent', transform='wav_bytes(bytes(4410))')
        for voice in adaptor.VOICE_CHOICES:
            with self.subTest(voice):
                directory = self.root / ('silent-' + voice)
                self.fault(lambda: adaptor.run(document(voice), directory, executable=silent, timeout=60), 'ESPEAKNG_SILENT_OUTPUT')
                self.assertEqual(adaptor.read_json(directory, 'result.json')['status'], 'failed')
        wrong_rate = self.program('wrong-rate', transform='wav_bytes(tone_pcm(b"x y", 175), rate=16000)')
        self.fault(lambda: adaptor.run(document('fr-fr'), self.root / 'rate', executable=wrong_rate, timeout=60), 'ESPEAKNG_OUTPUT_REJECTED')
        long_one = self.program('long', transform='wav_bytes(tone_pcm(b"a b", 175, seconds=130))')
        self.fault(lambda: adaptor.run(document('es'), self.root / 'long-run', executable=long_one, timeout=60), 'ESPEAKNG_BUDGET')

    # ------------------------------------------------------------ forged voice claims with every ordinary hash refreshed
    def forged(self, voice, edit, *, refreshed=True, name=None):
        directory, _ = self.publish(document(voice), name=name or ('forged-' + voice))
        edit(directory)
        if refreshed:
            refresh(directory)
        return directory

    def test_editing_the_authored_voice_and_plan_without_the_sound_fails_with_every_hash_refreshed(self):
        for source, target in (('en-gb', 'fr-fr'), ('fr-fr', 'es'), ('es', 'fr-fr'), ('fr-fr', None), (None, 'fr-fr')):
            with self.subTest(source, target=target):
                directory, _ = self.publish(document(source, text=ENGLISH), name='swap-%s-%s' % (source, target))
                authored = adaptor.read_json(directory, 'authored.json')
                authored.pop('voice', None)
                if target:
                    authored['voice'] = target
                self.write(directory, 'authored.json', authored)
                prepared = adaptor.plan(authored)
                self.write(directory, 'plan.json', prepared)
                self.write(directory, 'captures.json', adaptor.capture_record(prepared, ENGLISH.encode()))
                refresh(directory)
                # the receipt still claims the original voice, which is refused before any synthesis ...
                self.assertEqual(self.verify_fault(directory).message, 'receipt voice claim differs from the authored voice selection')
                # ... and a forger who also rewrites the receipt claim meets the fresh native re-synthesis of the selected voice
                receipt = {k: v for k, v in adaptor.read_json(directory, 'verification.json').items() if k != 'voice'}
                if target:
                    receipt['voice'] = target
                self.write(directory, 'verification.json', receipt)
                refresh(directory)
                self.assertIn('does not equal fresh native re-synthesis', self.verify_fault(directory).message)

    def test_replacing_the_sound_with_another_voice_fails(self):
        for voice, other in (('fr-fr', 'en-us'), ('es', 'fr-fr'), ('en-gb', 'en-us'), ('fr-fr', 'es')):
            with self.subTest(voice, other=other):
                wav = wav_bytes(fake_tone(other, TEXTS[voice]))

                def edit(directory, wav=wav):
                    (directory / 'narration.wav').write_bytes(wav)
                    (directory / 'native.wav').write_bytes(wav)
                directory = self.forged(voice, edit, name='sound-%s-%s' % (voice, other))
                self.assertIn('does not equal fresh native re-synthesis', self.verify_fault(directory).message)

    def test_a_voice_claim_that_disagrees_with_the_authored_choice_is_refused_in_every_record(self):
        cases = {
            'receipt other voice': lambda d: self.write(d, 'verification.json', {**adaptor.read_json(d, 'verification.json'), 'voice': 'es'}),
            'receipt voice removed': lambda d: self.write(d, 'verification.json', {k: v for k, v in adaptor.read_json(d, 'verification.json').items() if k != 'voice'}),
            'captures other voice': lambda d: self.write(d, 'captures.json', {**adaptor.read_json(d, 'captures.json'), 'voice': 'es'}),
            'captures voice removed': lambda d: self.write(d, 'captures.json', {k: v for k, v in adaptor.read_json(d, 'captures.json').items() if k != 'voice'}),
            'summary requested': lambda d: self.write(d, 'espeakng-summary.json', {**adaptor.read_json(d, 'espeakng-summary.json'),
                                                                                  'voice': {**adaptor.read_json(d, 'espeakng-summary.json')['voice'], 'requested': 'es'}}),
            'summary listing': lambda d: self.write(d, 'espeakng-summary.json', {**adaptor.read_json(d, 'espeakng-summary.json'),
                                                                                'voice': {**adaptor.read_json(d, 'espeakng-summary.json')['voice'], 'listing': adaptor.VOICE_PROFILES['es']['listing']}}),
            'summary review legacy text': lambda d: self.write(d, 'espeakng-summary.json', {**adaptor.read_json(d, 'espeakng-summary.json'), 'review': adaptor.REVIEW}),
            'result other voice': lambda d: self.write(d, 'result.json', {**adaptor.read_json(d, 'result.json'), 'voice': 'es'}),
            'result voice removed': lambda d: self.write(d, 'result.json', {k: v for k, v in adaptor.read_json(d, 'result.json').items() if k != 'voice'}),
            'voices listing retained for another voice': lambda d: (d / 'voices.stdout').write_text(LISTINGS['es']),
            'plan voice': lambda d: self.write(d, 'plan.json', {**adaptor.read_json(d, 'plan.json'), 'voice': 'es'}),
            'voice typed as list': lambda d: self.write(d, 'verification.json', {**adaptor.read_json(d, 'verification.json'), 'voice': ['fr-fr']}),
        }
        for label, edit in cases.items():
            with self.subTest(label):
                directory = self.forged('fr-fr', edit, name='claim-' + label.replace(' ', '-'))
                # a retained listing for another voice is rejected by the same exact-listing check that guards the runtime
                self.verify_fault(directory, 'UNSUPPORTED_RUNTIME' if label.startswith('voices listing') else 'VERIFICATION_FAILED')

    def test_a_launcher_or_submission_naming_another_voice_is_refused(self):
        def swap_launcher(directory):
            prepared = adaptor.plan(document('es'))
            command, names, limit = adaptor.stage_commands(prepared['rateWpm'], str(self.espeak), 'es')['narrate']
            (directory / 'narrate-launcher.py').write_text(adaptor.launcher('narrate', names, command, limit))
        directory = self.forged('fr-fr', swap_launcher, name='launcher-swap')
        self.assertEqual(self.verify_fault(directory).message, 'trusted native launcher differs')

        def swap_voices_launcher(directory):
            prepared = adaptor.plan(document('fr-fr'))
            command, names, limit = adaptor.stage_commands(prepared['rateWpm'], str(self.espeak), 'es')['voices']
            (directory / 'voices-launcher.py').write_text(adaptor.launcher('voices', names, command, limit))
        directory = self.forged('fr-fr', swap_voices_launcher, name='voices-launcher-swap')
        self.assertEqual(self.verify_fault(directory).message, 'trusted native launcher differs')

    def test_a_proof_of_one_voice_does_not_verify_under_another_runtime_listing(self):
        directory, _ = self.publish(document('fr-fr'), name='listing')
        other = self.program('relisted', listings={'fr-fr': HEADER + ' 5  fr-fr           --/M      French_(France)    roa/fr-CH            (fr 8)\n'})
        self.verify_fault(directory, 'UNSUPPORTED_RUNTIME', executable=other)

    def test_verification_uses_the_same_voice_in_the_trusted_runtime_and_a_changed_data_file_reports_the_matching_runtime_hint(self):
        directory, _ = self.publish(document('es'), name='hint')
        changed = self.program('changed', data=make_voice_data(self.root / 'data2', b'-other'))
        message = self.verify_fault(directory, executable=changed).message
        self.assertIn('verifying runtime or native data differs', message)

    def test_edits_to_files_only_other_voices_use_do_not_invalidate_a_proof(self):
        directory, _ = self.publish(document('fr-fr'), name='unrelated')
        (Path(self.data) / 'es_dict').write_bytes(b'changed Spanish dictionary')
        (Path(self.data) / 'lang/gmw/en').write_bytes(b'changed British voice')
        self.assertTrue(adaptor.verify(directory, executable=self.espeak)['verified'])
        (Path(self.data) / 'fr_dict').write_bytes(b'changed French dictionary')
        self.assertIn('differs', self.verify_fault(directory).message)


class RealEspeakngVoices(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('SCHEMAXIS_ESPEAKNG'), 'SCHEMAXIS_ESPEAKNG is not set; native voice qualification is tools/qualify_espeakng_voices.py')
    def test_each_voice_is_listed_exactly_and_speaks_nonzero_utf8_audio(self):
        espeak = os.environ['SCHEMAXIS_ESPEAKNG']
        with tempfile.TemporaryDirectory() as tmp:
            for voice in adaptor.VOICE_CHOICES:
                directory = Path(tmp) / voice
                result = adaptor.run(document(voice), directory, executable=espeak, timeout=120)
                self.assertEqual((result['status'], result['verified'], result['voice']), ('succeeded', True, voice))
                self.assertTrue(adaptor.verify(directory, executable=espeak)['verified'])


    @unittest.skipUnless(os.environ.get('SCHEMAXIS_ESPEAKNG'), 'SCHEMAXIS_ESPEAKNG is not set; native voice qualification is tools/qualify_espeakng_voices.py')
    def test_a_private_data_copy_with_a_redirecting_voice_cannot_redirect_the_fixed_voice_file_identifier(self):
        """The old ``-v<language name>`` command is redirected by extra voices in a private data copy; the fixed ``-v<file identifier>`` is not.

        A private copy of the data is reached through a wrapper that only sets ESPEAK_DATA_PATH (the installation is never modified, and no receipt path is run).
        """
        espeak = os.environ['SCHEMAXIS_ESPEAKNG']
        rate = 150
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            data = Path(subprocess.run([espeak, '--version'], capture_output=True, text=True, check=True, timeout=30).stdout.split('Data at: ')[1].strip())
            shutil.copytree(data, tmp / 'copy/espeak-ng-data')
            private = tmp / 'copy/espeak-ng-data'
            wrapper = tmp / 'wrapped-espeak-ng'
            wrapper.write_text('#!%s\nimport os, sys\nos.environ["ESPEAK_DATA_PATH"] = %r\nos.execv(%r, [%r, *sys.argv[1:]])\n' % (sys.executable, str(tmp / 'copy'), espeak, espeak))
            wrapper.chmod(0o700)
            counter = iter(range(1000))

            def speak(argument, voice):
                source, target = tmp / ('text-%d.txt' % next(counter)), tmp / ('control-%d.wav' % next(counter))
                source.write_bytes(TEXTS[voice].encode('utf-8'))
                subprocess.run([str(wrapper), '-v' + argument, '-s%d' % rate, '-p50', '-a100', '-b1', '-w', str(target), '-f', str(source)], check=True, timeout=60, capture_output=True)
                return target.read_bytes()[44:]

            def adapted(voice):
                directory = tmp / ('run-%d' % next(counter))
                result = adaptor.run(document(voice, rateWpm=rate), directory, executable=str(wrapper), timeout=120)
                self.assertTrue(adaptor.verify(directory, executable=str(wrapper))['verified'])
                return (directory / 'narration.wav').read_bytes()[44:], result

            controls = {}
            for voice in ('en-gb', 'fr-fr', 'es'):
                with self.subTest('unmodified copy ' + voice):
                    by_file = speak(VOICE_ARGUMENT[voice], voice)
                    self.assertEqual(speak(voice, voice), by_file)    # genuine layout: name and identifier are the same voice file
                    self.assertEqual(adapted(voice)[0], by_file)
                    controls[voice] = by_file
            redirects = [('top-level lang/<name>', 'lang/%s', b'name x\nlanguage de\n', ('en-gb', 'fr-fr', 'es')),
                         ('higher-scored Other Languages voice', 'lang/%s-x', b'name zz\nlanguage de\nlanguage %s 1\n', ('en-gb', 'fr-fr'))]
            for label, pattern, body, voices in redirects:
                for voice in voices:
                    with self.subTest(label + ' ' + voice):
                        stem = {'en-gb': 'lang/gmw/en', 'fr-fr': 'lang/roa/fr'}.get(voice)
                        path = private / (pattern % voice if label.startswith('top') else stem + '-x')
                        path.write_bytes(body % voice.encode() if b'%s' in body else body)
                        try:
                            self.assertNotEqual(speak(voice, voice), controls[voice], 'the old language-name command must be redirected by this extra voice')
                            self.assertEqual(speak(VOICE_ARGUMENT[voice], voice), controls[voice])
                            pcm, result = adapted(voice)
                            self.assertEqual(pcm, controls[voice])
                            self.assertEqual(result['voice'], voice)
                        finally:
                            path.unlink()
            with self.subTest('lang/fr-fr/voices/fr-fr'):
                (private / 'lang/fr-fr/voices').mkdir(parents=True)
                (private / 'lang/fr-fr/voices/fr-fr').write_bytes(b'name x\nlanguage de\n')
                try:
                    self.assertEqual(adapted('fr-fr')[0], controls['fr-fr'])
                finally:
                    shutil.rmtree(private / 'lang/fr-fr')
            with self.subTest('voices/<identifier> shadow'):
                (private / 'voices/roa').mkdir()
                (private / 'voices/roa/fr').write_bytes(b'name x\nlanguage de\n')
                try:
                    self.assertNotEqual(speak('roa/fr', 'fr-fr'), controls['fr-fr'], 'the native program reads voices/ before lang/')
                    directory = tmp / 'shadow-run'
                    fault = self.fault_of(lambda: adaptor.run(document('fr-fr', rateWpm=rate), directory, executable=str(wrapper), timeout=120))
                    self.assertEqual(fault.code, 'UNSUPPORTED_RUNTIME')
                    self.assertFalse((directory / 'narration.wav').exists())
                finally:
                    shutil.rmtree(private / 'voices/roa')

    def fault_of(self, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        return caught.exception.fault


if __name__ == '__main__':
    unittest.main()
