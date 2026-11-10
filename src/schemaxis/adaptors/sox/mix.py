"""Two-track overlay: a narration and a background PCM16 recording mixed with explicit gains and placements.

Each track has a gain (a decimal with at most four fractional digits, 0 to 4) and an
`offsetFrames` placement: the number of silent output frames before the track's first
frame. Both recordings must already have the same sample rate and channel count; nothing
is resampled or channel-converted. Output length follows the explicit `durationPolicy`:
`longest` ends with the later track, `narration` ends with the narration and cuts any
background beyond it. The exact mixed value of every output sample is the sum of the two
gained source samples (silence where a track is absent); it, and each gained term, must lie
within PCM16 before SoX starts, otherwise the job is refused with `AUDIO_CLIPPING`. Nothing
is clipped, limited, ducked or rescaled.

SoX pads each track with `pad` (an exact integer copy plus zeros), then mixes with
`-m -v GAIN`. The host checks every output sample with exact integer arithmetic: the
output must be a nearest PCM16 integer to the exact sum (ties may go either way, because
SoX's tie rule is not documented). Gains with at most four fractional digits keep every
non-tie value at least 1e-4 PCM16 units from a tie, which is larger than SoX's two internal
32-bit roundings, so this check needs no floating-point tolerance.
"""
from fractions import Fraction
import math

from schemaxis.errors import fail

OPERATION = 'mix'
ROLES = ('narration', 'background')
POLICIES = ('longest', 'narration')
MAX_FRAMES = 262144
GAIN_SCALE = 10000
LOW, HIGH = -32768, 32767

LOSSES = [
    'Two local PCM16 WAV recordings, mono or stereo, 8000–192000 Hz, one narration and one background, both with the same sample rate and channel count; no resampling, channel conversion, other formats, more tracks or crossfades. Use conform first when the recordings differ. Aggregate source bytes <=4MiB and combined source/output scalar samples <=1048576.',
    'Each track has a gain from 0 to 4 written with at most four decimal places (exact; a gain such as 0.12345 is refused) and an offsetFrames placement of silent frames before the track begins on the output timeline. Whole frames only; nothing is trimmed from the source, and the background is not ducked or levelled against the narration.',
    'durationPolicy has no default. longest ends the output with the later of the two tracks, padding the earlier with silence. narration ends the output with the narration and cuts any background beyond it; a background that starts at or after the narration end is refused.',
    'The exact mixed value of each output sample (gain*sample for each track present, summed) must lie within -32768..32767, and so must each gained term, before SoX starts; otherwise the job is refused with AUDIO_CLIPPING. Nothing is clipped, limited or rescaled, and the check covers background frames that durationPolicy narration would cut.',
    'Every output sample must be a nearest PCM16 integer to its exact mixed value (ties may go either way). SoX output must be the canonical 44-byte WAV and its standard output and error must be empty.',
    'This is a sample-wise sum. It makes no claim about loudness, intelligibility, audio quality, level balance, ducking, phase or listening result, and does not certify the recordings.']

LIMITS = ['Sample-wise arithmetic on PCM16 only; loudness, intelligibility and listening quality are not assessed.',
          'Source content, authenticity and metadata retention are not certified; output is a bare canonical WAV.']


def gain_scaled(value, at):
    """Gain as an exact integer count of 1/10000 units, from the shortest round-trip decimal."""
    if type(value) not in (int, float) or not math.isfinite(value): fail('INVALID_ARGUMENT', 'gain must be a finite number', at)
    scaled = Fraction(str(value)) * GAIN_SCALE
    if scaled.denominator != 1:
        fail('INVALID_ARGUMENT', 'gain must have at most four decimal places so that mixing is exact; round it, for example to 0.1235', at)
    return int(scaled)


def layout(p, infos):
    """Frame counts and the output timeline of both tracks under durationPolicy."""
    tracks = []
    for role, info in zip(ROLES, infos):
        offset = p[role]['offsetFrames']
        tracks.append({'role': role, 'offset': offset, 'frames': info['frames'], 'end': offset + info['frames']})
    longest = max(t['end'] for t in tracks)
    if longest > MAX_FRAMES: fail('AUDIO_RESOURCE_LIMIT', f'mix would span {longest} frames; the limit is {MAX_FRAMES}', '$')
    total = longest if p['durationPolicy'] == 'longest' else tracks[0]['end']
    if total <= tracks[1]['offset']:
        fail('AUDIO_SOURCE_BOUNDS', 'the background begins at or after the narration end, so durationPolicy narration would cut all of it; reduce offsetFrames or use longest', '$.background.offsetFrames')
    return tracks, total


def exact_values(p, tracks, samples, channels):
    """Exact scaled mix of every untrimmed frame: integer sample*gain*10000 sums; refuses clipping."""
    gains = [gain_scaled(p[r]['gain'], f'$.{r}.gain') for r in ROLES]
    span = max(t['end'] for t in tracks)
    lo, hi = LOW * GAIN_SCALE, HIGH * GAIN_SCALE
    values = [0] * (span * channels)
    for i, (t, g, values_in) in enumerate(zip(tracks, gains, samples)):
        base = t['offset'] * channels
        for k, v in enumerate(values_in):
            term = v * g
            if not lo <= term <= hi:
                fail('AUDIO_CLIPPING', f"{ROLES[i]} sample {v} at gain {p[ROLES[i]]['gain']} lies outside PCM16 before mixing; reduce its gain", f'$.{ROLES[i]}.gain')
            values[base + k] += term
    if any(not lo <= v <= hi for v in values):
        fail('AUDIO_CLIPPING', 'the exact mixed value of some sample lies outside PCM16; reduce a gain or the source levels (nothing is clipped or limited)', '$')
    return values


def native_gain(value): return format(float(Fraction(str(value))), '.17g')


def reopen(values, actual, total_samples):
    """Every output scalar sample against its exact mixed value; returns the maximum error in 1/10000 units."""
    if len(actual) != total_samples: return None
    worst = 0
    for exact, got in zip(values, actual):
        error = abs(got * GAIN_SCALE - exact)
        if error > GAIN_SCALE // 2: return None
        if error > worst: worst = error
    return worst


def exact_seconds(frames, rate):
    divisor = math.gcd(frames, rate)
    return {'numerator': frames // divisor, 'denominator': rate // divisor}


def gain_text(value):
    fraction = Fraction(str(value))
    return f'{fraction.numerator}/{fraction.denominator}'


def error_text(worst):
    """Largest observed distance from an exact value, in PCM16 units, as a reduced fraction."""
    fraction = Fraction(worst, GAIN_SCALE)
    return f'{fraction.numerator}/{fraction.denominator}'
