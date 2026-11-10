"""whisper.cpp language codes admitted by the transcribe route, bound to one upstream release.

The set is the key list of `g_lang` in whisper.cpp v1.9.5 `src/whisper.cpp` (language ids 0 to 99, in id
order). `whisper_lang_id` also resolves English full names such as "german", and the CLI accepts "auto" and
lowercases `-l`; this route admits only the canonical lowercase codes below and applies no alias mapping
(v1.9.5 has `jw` and `yue` but no `iw`; `he` is Hebrew). The native CLI refuses an unknown code only after
the audio and model have been read and hashed, and exits 0 without writing results, so the host refuses it
first, from this static table: planning never imports or runs native code and never reads the network.

Membership says only that the pinned whisper.cpp release knows the code. It does not say that the chosen
model is multilingual (an English-only `.en` model ignores a non-English request with a warning) or that
recognition in that language is accurate.
"""

from schemaxis.core.faults import Fault, SchemaxisError

RELEASE = '1.9.5'
CODES = (
    'en', 'zh', 'de', 'es', 'ru', 'ko', 'fr', 'ja', 'pt', 'tr', 'pl', 'ca', 'nl', 'ar', 'sv', 'it', 'id', 'hi', 'fi',
    'vi', 'he', 'uk', 'el', 'ms', 'cs', 'ro', 'da', 'hu', 'ta', 'no', 'th', 'ur', 'hr', 'bg', 'lt', 'la', 'mi', 'ml',
    'cy', 'sk', 'te', 'fa', 'lv', 'bn', 'sr', 'az', 'sl', 'kn', 'et', 'mk', 'br', 'eu', 'is', 'hy', 'ne', 'mn', 'bs',
    'kk', 'sq', 'sw', 'gl', 'mr', 'pa', 'si', 'km', 'sn', 'yo', 'so', 'af', 'oc', 'ka', 'be', 'tg', 'sd', 'gu', 'am',
    'yi', 'lo', 'uz', 'fo', 'ht', 'ps', 'tk', 'nn', 'mt', 'sa', 'lb', 'my', 'bo', 'tl', 'mg', 'as', 'tt', 'haw', 'ln',
    'ha', 'ba', 'jw', 'su', 'yue')
SUPPORTED = frozenset(CODES)
DEFAULT = 'en'
STATEMENT = ('Admission means whisper.cpp ' + RELEASE + ' knows the code; it does not certify that the selected model is '
             'multilingual or how well it recognises that language.')


def admit(value):
    """Raise INVALID_LANGUAGE unless the value is exactly one canonical code; runs before any file is read."""
    if type(value) is str and value in SUPPORTED: return
    observed = {'value': value} if type(value) is str and len(value) <= 40 and value.isascii() and value.isprintable() else ({'type': 'str', 'length': len(value)} if type(value) is str else {'type': type(value).__name__})
    raise SchemaxisError(Fault('INVALID_LANGUAGE', f'language must be one of the {len(CODES)} canonical lowercase whisper.cpp {RELEASE} codes',
        '$.language', 'pipeline', observed=observed,
        recovery='use a lowercase code from the schema enum, for example en (default), de, fr, ja or yue; full names, uppercase, auto/detection '
                 'and aliases such as iw are not accepted. ' + STATEMENT))
