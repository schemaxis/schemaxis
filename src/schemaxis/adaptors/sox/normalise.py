"""Peak headroom preparation: PCM16 WAV scaled by one exact rational gain to a stated absolute peak.

The host measures the largest absolute sample over every channel, derives the exact
gain `targetPeak/peak` as a fraction and refuses silence or a boost above the declared
`maxGain` before SoX starts. `maxGain` is the parsed JSON number's
shortest round-trip decimal, taken as an exact fraction (``Fraction(str(value))``): the
ordinary 6.6 is 33/5, not the binary float just below it, and there is no epsilon or clamp.
JSON parsing rounds the written literal to a binary double first, so a literal with more
digits than a double holds (6.59999999999999999999999) is read as the double 6.6 and is
compared as 33/5; the exact written decimal is not recoverable. SoX then applies its fixed
`vol` amplitude multiplier in an isolated process. This module checks the result independently of the command line: the
same frame count, rate and channels, and every scalar sample against the exact rational
`sample*targetPeak/peak`. Samples stream through ``array('h')`` chunks; only the set of
distinct (source, output) sample pairs is held. A genuine native output has one output value
per source value (at most 65536 pairs). The verifier tolerates two integer outputs per source
value (an exact tie) and, for a forged output, one fixed chunk more before it refuses, so
memory is bounded by twice the distinct source values plus one chunk.

This is peak scaling in PCM16 sample units. It is not loudness normalisation.
"""
from fractions import Fraction
import hashlib
import json
import math

from schemaxis.adaptors.sox import conform
from schemaxis.errors import fail

OPERATION = 'normalise'
SOURCE_LIMIT = conform.SOURCE_LIMIT
# Native output has a 44-byte header, so it is never larger than a canonical source.
OUTPUT_LIMIT = conform.SOURCE_LIMIT
MAX_SECONDS = conform.MAX_SECONDS
FULL_SCALE = 32767
TOLERANCE = Fraction(1, 2)
DIAGNOSTIC_TOLERANCE = 1e-4

LOSSES = [
    'One local PCM16 WAV, mono or stereo, 8000–192000 Hz, is scaled by one common gain to a stated absolute peak. Source <=32MiB and <=600 seconds; compressed audio, float, 24-bit and more than two channels are refused.',
    'targetPeak is an integer PCM16 sample magnitude from 1 to 32767, not decibels. The measured peak is the largest absolute sample over all samples of all channels; the exact gain is the fraction targetPeak/peak. A silent source cannot be scaled and is refused.',
    'maxGain (1 to 16) is an explicit ceiling on boost. It is compared as an exact fraction of the shortest round-trip decimal of the parsed JSON number (6.6 is 33/5, with no epsilon); JSON parsing first rounds a literal with more digits than a double holds to that double, so 6.59999999999999999999999 is read as 6.6 and compared as 33/5. A source that would need more gain is refused before SoX starts; the gain is never capped, clipped or the target ignored. Attenuation is always allowed. maxGain bounds this policy only: it cannot tell signal from noise.',
    'One gain multiplies both channels, so level balance is preserved. There is no mixing, resampling, trimming, fade, dither, limiter or compression. Boosting raises the noise floor, hum and quantisation noise by the same ratio as the signal.',
    'Every output sample must be a nearest PCM16 integer to sample*targetPeak/peak (ties may go either way) and the output peak must equal targetPeak. A source peak of -32768 is only negative: PCM16 has no +32768, so targetPeak never exceeds 32767 and that source is always attenuated.',
    'This is not RMS or loudness normalisation, EBU R128, true-peak or inter-sample peak control, a speech-quality, perceived-volume or accuracy measurement, or an identity or authenticity certificate.']

LIMITS = ['Peak scaling in PCM16 sample units only; the level is not loudness, true peak or perceived volume.',
          'Content, noise floor and authenticity of the recording are not assessed.']


def check_source(info, at='$.source'):
    if info['frames'] > MAX_SECONDS * info['rate']:
        fail('AUDIO_RESOURCE_LIMIT', f'source exceeds {MAX_SECONDS} seconds of audio', at)


def scan(data, start, size, channels):
    """Distinct scalar sample values over every channel, streamed in fixed chunks."""
    values = set()
    for block in conform.chunks(data, start, size, channels): values.update(block)
    return values


def ceiling(value):
    """maxGain as an exact rational: the shortest round-trip decimal of the parsed JSON number (the written literal was already rounded to a double by JSON parsing)."""
    if type(value) not in (int, float) or not math.isfinite(value): fail('INVALID_ARGUMENT', 'maxGain must be a finite number', '$.maxGain')
    return Fraction(str(value))


def decide(p, values):
    """Peak and exact gain; refuses silence and over-limit boost before any native process."""
    peak = max(map(abs, values))
    if not peak:
        fail('AUDIO_SILENT_SOURCE', 'every sample is zero, so there is no peak to scale; choose a recording that contains signal', '$.source')
    gain = Fraction(p['targetPeak'], peak)
    if gain > ceiling(p['maxGain']):
        fail('AUDIO_GAIN_LIMIT', f"reaching targetPeak {p['targetPeak']} from the measured peak {peak} needs gain {gain.numerator}/{gain.denominator}, above maxGain {p['maxGain']}; "
             'lower targetPeak, raise maxGain deliberately, or choose a louder recording', '$.maxGain', measuredPeak=peak, requiredGain=f'{gain.numerator}/{gain.denominator}')
    return peak, gain


def native_gain(gain): return format(float(gain), '.17g')


def exact_seconds(frames, rate):
    divisor = math.gcd(frames, rate)
    return {'numerator': frames // divisor, 'denominator': rate // divisor}


def fraction_json(value): return {'numerator': value.numerator, 'denominator': value.denominator}


def reopen(source, s_start, s_size, output, o_start, o_size, channels, peak, target, values):
    """Compare every output scalar sample with its exact rational; return output peak and exact maximum error."""
    produced = conform.chunks(output, o_start, o_size, channels)
    pairs = set()
    for block in conform.chunks(source, s_start, s_size, channels):
        actual = next(produced, None)
        if actual is None or len(actual) != len(block): fail('VERIFICATION_FAILED', 'native output has fewer samples than the source', 'audio.wav')
        pairs.update(zip(block, actual))
        # A correct output has one value per source value (two only at an exact tie); bound memory for a forged one.
        if len(pairs) > 2 * len(values): fail('VERIFICATION_FAILED', 'native output is not a function of the source sample value', 'audio.wav')
    if next(produced, None) is not None: fail('VERIFICATION_FAILED', 'native output has extra samples', 'audio.wav')
    bad = [(s, n) for s, n in pairs if abs(2 * n * peak - 2 * s * target) > peak]
    if bad: fail('VERIFICATION_FAILED', f'native output sample {bad[0][1]} is not the nearest PCM16 integer to {bad[0][0]}*{target}/{peak}', 'audio.wav', mismatchedValuePairs=len(bad), first=list(bad[0]))
    worst = max((Fraction(abs(n * peak - s * target), peak) for s, n in pairs), default=Fraction(0))
    out_peak = max(abs(n) for _, n in pairs)
    if out_peak != target: fail('VERIFICATION_FAILED', f'output peak {out_peak} is not targetPeak {target}', 'audio.wav')
    return out_peak, worst


def summarise(p, source, info, s_start, s_size, output, out_info, o_start, o_size, stdout, stderr):
    """Host reopening: exact structure and every scalar sample against the exact rational."""
    if stdout or stderr: fail('VERIFICATION_FAILED', 'native normalise wrote unexpected output', 'normalise.stderr' if stderr else 'normalise.stdout')
    if out_info != info: fail('VERIFICATION_FAILED', f'native output must keep rate, channels and frame count {info}, found {out_info}', 'audio.wav')
    target = p['targetPeak']
    values = scan(source, s_start, s_size, info['channels'])
    peak, gain = decide(p, values)
    out_peak, worst = reopen(source, s_start, s_size, output, o_start, o_size, info['channels'], peak, target, values)
    polarity = [name for name, value in (('negative', -peak), ('positive', peak)) if value in values]
    direction = 'unity' if gain == 1 else 'boost' if gain > 1 else 'attenuation'
    warnings = []
    if gain > 1:
        warnings.append({'code': 'NOISE_FLOOR_AMPLIFIED', 'message': f'every sample was multiplied by {gain.numerator}/{gain.denominator}: background noise, hum and the quantisation noise floor rose by the same ratio as the signal; maxGain bounds the policy but cannot separate signal from noise'})
    scalar = info['frames'] * info['channels']
    ratio = float(gain)
    return {'operation': OPERATION, **info, 'durationSeconds': info['frames'] / info['rate'], 'durationExact': exact_seconds(info['frames'], info['rate']),
            'source': {'sha256': hashlib.sha256(source).hexdigest(), 'bytes': len(source), **info, 'durationExact': exact_seconds(info['frames'], info['rate']), 'peakPCM16': peak, 'peakPolarity': polarity},
            'targetPeakPCM16': target, 'maxGain': p['maxGain'],
            'gain': {**fraction_json(gain), 'direction': direction, 'withinMaxGain': True},
            'headroom': {'inputPeakPCM16': peak, 'outputPeakPCM16': out_peak, 'positiveHeadroomPCM16': FULL_SCALE - out_peak, 'negativeHeadroomPCM16': FULL_SCALE + 1 - out_peak},
            'peakPCM16': out_peak, 'samplesCompared': scalar, 'distinctSampleValuesCompared': len(values),
            'maxErrorLSB': fraction_json(worst), 'toleranceLSB': fraction_json(TOLERANCE),
            'claims': {'oneCommonGain': True, 'everySampleCompared': True, 'outputPeakIsTargetPeak': True, 'clippedSamples': 0,
                       'loudnessNormalised': False, 'truePeakControlled': False, 'authenticityCertified': False},
            'description': {'gainRatio': ratio, 'gainDecibels': round(20 * math.log10(ratio), 4), 'outputHeadroomDecibels': round(20 * math.log10((FULL_SCALE + 1) / out_peak), 4)},
            'limits': LIMITS, 'warnings': warnings,
            'timeline': {'originalTimestampsPreserved': True, 'explanation': 'Normalise keeps every frame in order with no trimming, padding or resampling: output frame f is source frame f, so sample time (frame f at f/rate seconds) is unchanged and transcript times carry over. The output is the bare canonical 44-byte WAV: LIST/INFO or other metadata chunks of the source are not carried over.'}}


def _close(actual, expected):
    if not isinstance(actual, dict) or set(actual) != set(expected): return False
    return all(type(actual[k]) is float and math.isfinite(actual[k]) and abs(actual[k] - expected[k]) <= DIAGNOSTIC_TOLERANCE for k in expected)


def same(actual, expected):
    """Exact JSON types everywhere except the float `description`, a diagnostic compared with a small tolerance."""
    if not isinstance(actual, dict) or not isinstance(expected, dict): return False
    left, right = dict(actual), dict(expected)
    described, wanted = left.pop('description', None), right.pop('description', None)
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False) and _close(described, wanted)
