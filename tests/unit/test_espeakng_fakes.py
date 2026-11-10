"""Pure-stdlib canonical WAV builder and the deterministic HOST FAKE ``espeak-ng`` shared by the eSpeak NG host tests.

The fake makes no speech. It derives a repeating tone from the captured text and the declared rate (the number of words sets the
duration, a hash of text and rate sets the pitch), so different words, rates or runtimes give different PCM and identical inputs
give identical PCM. It proves host behaviour only: fixed arguments, captured input, canonical WAV handling, receipts, trusted
executables, lifecycle and standard hooks. Native acceptance is tools/qualify_espeakng.py. Kept free of Schemaxis imports so the fake
starts quickly; ``wav_bytes`` is an independent writer that the host tests compare with the adaptor's.
"""
import hashlib
import math
from pathlib import Path
import struct
import sys

RATE = 22050
VERSION_TEXT = 'eSpeak NG text-to-speech: 1.52.0  Data at: %s\n'
DATA_FILES = ('phontab', 'phonindex', 'phondata', 'intonations', 'en_dict', 'lang/gmw/en-US')
HEADER = 'Pty Language       Age/Gender VoiceName          File                 Other Languages\n'
EN_GB = ' 2  en-gb           --/M      English_(Great_Britain) gmw/en               (en 2)\n'
EN_US = ' 2  en-us           --/M      English_(America)  gmw/en-US            (en 3)\n'
SCOTLAND = ' 5  en-gb-scotland  --/M      English_(Scotland) gmw/en-GB-scotland   (en 4)\n'
VOICES = HEADER + EN_GB + EN_US + SCOTLAND


def wav_bytes(pcm, rate=RATE, channels=1, bits=16, encoding=1, extra=b'', riff_delta=0, data_delta=0):
    """Independent canonical-layout writer; ``extra`` inserts chunks between fmt and data, the deltas corrupt a size field."""
    align = channels * bits // 8
    fmt = b'fmt ' + struct.pack('<IHHIIHH', 16, encoding, channels, rate, rate * align, align, bits)
    data = b'data' + struct.pack('<I', len(pcm) + data_delta) + pcm
    body = b'WAVE' + fmt + extra + data
    return b'RIFF' + struct.pack('<I', len(body) + riff_delta) + body


def tone_pcm(text, rate_wpm, seconds=None):
    """The fake synthesizer: a tone whose length follows the word count and rate; silence when the text has no letter or digit."""
    text = text.decode('utf-8')
    words = len(text.split())
    frames = int(RATE * (seconds if seconds is not None else max(0.05, words * 60 / rate_wpm)))
    digest = hashlib.sha256(text.encode('utf-8') + b'|%d' % rate_wpm).digest()
    if not any(character.isalnum() for character in text):
        return bytes(2 * frames)
    frequency = 150 + digest[0] % 200
    period = max(2, round(RATE / frequency))
    cycle = b''.join(struct.pack('<h', int(9000 * math.sin(2 * math.pi * index / period)) or 1) for index in range(period))
    return (cycle * (frames // period + 1))[:2 * frames]


def synth_wav(text, rate_wpm, seconds=None):
    return wav_bytes(tone_pcm(text, rate_wpm, seconds))


def make_data(directory, tag=b''):
    """A fake native data directory with the six files the adaptor fingerprints; ``tag`` changes the fingerprint."""
    directory = Path(directory)
    for name in DATA_FILES:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fake native data ' + name.encode() + tag)
    return str(directory)


FAKE = '''#!{python}
import json, sys
sys.path.insert(0, {tests!r})
from test_espeakng_fakes import synth_wav, tone_pcm, wav_bytes
args = sys.argv[1:]
if {log!r}:
    open({log!r}, 'a').write(json.dumps(args) + '\\n')
if args == ['--version']:
    sys.stdout.write({version!r}); sys.exit(0)
if args == ['--voices=en']:
    sys.stdout.write({voices!r}); sys.exit(0)
text = open(args[args.index('-f') + 1], 'rb').read()
rate = int([a for a in args if a.startswith('-s')][0][2:])
{marker}
wav = synth_wav(text, rate)
wav = {transform}
if wav is not None:
    open(args[args.index('-w') + 1], 'wb').write(wav)
'''


def program(directory, name, tests, data, *, version=None, voices=VOICES, marker='', transform='wav', log=''):
    """Write an executable fake espeak-ng; ``marker`` runs before synthesis, ``transform`` rewrites or drops (None) the WAV."""
    path = Path(directory) / name
    path.write_text(FAKE.format(python=sys.executable, tests=str(tests), version=version if version is not None else VERSION_TEXT % data,
                                voices=voices, marker=marker, transform=transform, log=log))
    path.chmod(0o700)
    return str(path)
