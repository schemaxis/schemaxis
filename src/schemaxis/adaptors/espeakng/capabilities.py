"""Curated intent-level eSpeak NG plain-text narration discovery without native imports."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'eSpeak NG', 'purpose': 'Turn a short plain-text script into a synthetic voiceover DRAFT: a canonical PCM16 mono 22050 Hz WAV from the fixed eSpeak NG en-us voice or one explicitly selected voice (en-gb, fr-fr or es), with every PCM byte proven by a fresh native re-synthesis. A person must listen to it; it is not a human recording and nothing is translated.',
                            'keywords': ['eSpeak NG', 'espeak-ng', 'text to speech', 'TTS', 'speech synthesis', 'narration draft', 'voiceover']},
            'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
            'requirements': ['narrate: exactly one script, either a literal text string or an absolute local UTF-8 .txt file or artifact, of at most 1024 Unicode code points and 8 KiB, plus an optional integer rateWpm of 120-240 (default 175) and an optional voice (en-us, en-gb, fr-fr or es; absent means the original en-us voice).',
                             'A configured eSpeak NG 1.52.0 espeak-ng executable with its matching native data (--espeakng, schemaxis configure espeakng or SCHEMAXIS_ESPEAKNG); verification needs the same trusted espeak-ng because no host speech synthesizer exists.',
                             'No other voice, variant, voice path, pitch, markup, SSML, phoneme code, network, playback, language detection or translation; control characters and [[ ]] phoneme escapes are refused. The script must already be in the language of the selected voice.'],
            'references': ['docs/espeakng.md', 'src/schemaxis/adaptors/espeakng/readiness.json'],
            'operations': {
                'narrate': {
                    'purpose': 'Speak one plain-text script with the fixed offline English (United States) eSpeak NG voice, or one explicitly selected voice (en-gb, fr-fr or es), and publish a canonical PCM16 mono WAV voiceover draft, proven by a fresh native re-synthesis of the same text.',
                    'keywords': ['text to speech', 'TTS', 'speech synthesis', 'narration', 'voiceover draft', 'synthetic voice', 'read text aloud', 'text to WAV', 'espeak', 'espeak-ng', 'eSpeak NG', 'en-us voice', 'offline narration', 'French voice', 'Spanish voice', 'British English voice', 'multilingual narration', 'Spanish narration', 'French narration', 'British English narration', 'fr-fr voice', 'en-gb voice'],
                    'semantics': ['The script is captured as immutable UTF-8 bytes (a literal string or a .txt file or artifact) and refused, never rewritten, when it has control characters, [[ ]] phoneme escapes, markup, no letter or digit, or more than 1024 code points or 8 KiB. Pitch (50) and amplitude (100) are fixed; the speaking rate in words per minute and an optional voice (en-us, en-gb, fr-fr or es) are authored. The voice speaks the script as written: no translation or language detection.',
                                  'The published WAV is the exact native PCM in a canonical 44-byte header (22050 Hz, mono, 16-bit, nonzero, at most 120 seconds and 8 MiB) that SoX conform accepts. Verification needs the trusted espeak-ng: it re-synthesises the captured text in a private directory and compares every PCM byte with the same voice. This proves consistent derivation only; the narration is a synthetic draft that a person must listen to, with no intelligibility, pronunciation, accent or accessibility certified.'],
                    'examples': [{'reference': 'examples/schemaxis/espeakng-baseline.json', 'purpose': 'Narrate a literal two-sentence script at the default 175 words per minute.'},
                                 {'reference': 'examples/schemaxis/espeakng-variant.json', 'purpose': 'Narrate a numbered, multi-line script from a UTF-8 text file at a slower 140 words per minute.'},
                                 {'reference': 'examples/schemaxis/espeakng-voice-en-gb.json', 'purpose': 'Narrate a literal script with the explicitly selected English (Great Britain) voice.'},
                                 {'reference': 'examples/schemaxis/espeakng-voice-fr-fr.json', 'purpose': 'Narrate a French literal with the French (France) voice.'},
                                 {'reference': 'examples/schemaxis/espeakng-voice-es.json', 'purpose': 'Narrate a Spanish literal with the Spanish (Spain) voice at 160 words per minute.'}]}}}
