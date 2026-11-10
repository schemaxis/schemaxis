"""Speech conform: PCM16 mono/stereo WAV to PCM16 mono 16000 Hz.

SoX 14.4.2 converts in an isolated process (`remix`, then `rate -v 16000`, dither
off). This module checks that result independently of the command line. Samples
stream through ``array('h')`` chunks; no Python list proportional to the recording
is ever built. Whole files are held only as ``bytes`` within the stated budgets.

Channel conversion at the same rate is recomputed exactly. For a resampled signal,
source and output pass through one independent low-pass and are compared in a
declared band at bounded interior instants: not a bit-exact or full-band oracle.
"""
from array import array
import io
import math
from operator import mul
import struct
import sys
import wave

from schemaxis.errors import fail

OPERATION = 'conform'
RATE = 16000
SOURCE_LIMIT = 32 * 1024 * 1024
OUTPUT_LIMIT = 24 * 1024 * 1024
MAX_SECONDS = 600
POLICIES = ('average', 'left', 'right')
# `remix -` is the documented mix-down of all input channels to mono: 1/n scaling.
REMIX = {'average': '-', 'left': '1', 'right': '2'}
CHUNK = 65536
BLOCK = 4096
EVEN_SPOTS = 256
LOUD_BLOCKS = 64
LOUD_PER_BLOCK = 4
# Declared band-limited verification for resampled output (see summary and docs/sox.md).
# N is the lower Nyquist; only 0..PASS_EDGE*N is verified, SoX's transition is ~0.9N..N.
PASS_EDGE, STOP_EDGE, STOP_DB = 0.6, 0.8, 100.0
# Fixed rounding allowance includes the int16 mix-reference approximation and internal rounding.
LEAKAGE, ROUNDING_LSB, TABLE = 0.004, 1.0, 8192
GAIN_RELATIVE, GAIN_ABSOLUTE = 1.25, 4.0
CLIP_RATE = r'WARN rate: rate clipped ([0-9]+) samples; decrease volume\?'
CLIP_OUTPUT = r"WARN sox: `audio\.wav' output clipped ([0-9]+) samples; decrease volume\?"

LOSSES = [
    'One local PCM16 WAV, mono or stereo, 8000–192000 Hz, becomes PCM16 mono 16000 Hz. Source <=32MiB and <=600 seconds; compressed audio, float, 24-bit and more than two channels are refused.',
    'channelPolicy is explicit. average mixes each stereo frame as (left+right+1)>>1 with no anti-clip gain; left and right copy one channel. Mono accepts average or left (the only channel) and refuses right.',
    'Fixed SoX chain: remix, then rate -v 16000, with dither and automatic gain disabled. No normalisation, noise reduction, filtering other than anti-alias resampling, or other sample rates.',
    'Output frame count is round-half-up(frames*16000/rate). Same-rate channel conversion is recomputed exactly by the host; resampled samples are NOT recomputed bit-exactly. Their 0-0.6xNyquist band is compared with the source through an independent low-pass at bounded interior instants; content above that band (SoX\'s own transition and stop band) and edges are not verified.',
    'Resampling can overshoot full-scale input; saturated output samples and SoX clipping warnings are counted and reported, never hidden. Averaging anti-phase channels cancels the signal and is flagged.']


def info_of(data, code='INVALID_AUDIO_DATA', at='$.source', limit=SOURCE_LIMIT):
    """Strict RIFF inspection without decoding samples: info, data offset and byte count."""
    try:
        if len(data) > limit: raise ValueError('file byte budget exceeded')
        if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE' or struct.unpack_from('<I', data, 4)[0] + 8 != len(data): raise ValueError('RIFF size/header mismatch')
        chunks, order, offset = {}, [], 12
        while offset < len(data):
            if offset + 8 > len(data): raise ValueError('truncated chunk header')
            name, size = data[offset:offset + 4], struct.unpack_from('<I', data, offset + 4)[0]
            end = offset + 8 + size
            if end + (size & 1) > len(data) or name in chunks: raise ValueError('duplicate or truncated chunk')
            if name not in (b'fmt ', b'data', b'LIST', b'JUNK'): raise ValueError('unsupported WAV chunk')
            if size & 1 and data[end:end + 1] != b'\0': raise ValueError('nonzero chunk padding byte')
            chunks[name] = (offset + 8, size); order.append(name); offset = end + (size & 1)
        if b'fmt ' not in chunks or b'data' not in chunks: raise ValueError('fmt/data required')
        if order.index(b'fmt ') > order.index(b'data'): raise ValueError('fmt chunk must precede data')
        if chunks[b'fmt '][1] != 16: raise ValueError('canonical 16-byte PCM fmt required')
        encoding, channels, rate, byte_rate, align, bits = struct.unpack_from('<HHIIHH', data, chunks[b'fmt '][0])
        if encoding != 1 or bits != 16 or channels not in (1, 2) or not 8000 <= rate <= 192000 or align != 2 * channels or byte_rate != rate * align:
            raise ValueError('require PCM16 mono/stereo with consistent format/rate')
        start, size = chunks[b'data']
        if not size or size % align: raise ValueError('nonempty integral sample frames required')
        with wave.open(io.BytesIO(data), 'rb') as stream:
            if (stream.getnframes() * align, stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (size, rate, channels, 2): raise ValueError('WAV decoder/header mismatch')
        return {'rate': rate, 'channels': channels, 'frames': size // align}, start, size, order
    except (ValueError, struct.error, wave.Error, EOFError) as error:
        fail(code, 'use canonical bounded PCM16 WAV: ' + str(error), at)


def canonical_info(data, code, at, limit=OUTPUT_LIMIT):
    """Native output must be exactly the 44-byte fmt+data layout SoX 14.4.2 writes."""
    info, start, size, order = info_of(data, code, at, limit)
    if order != [b'fmt ', b'data'] or start != 44: fail(code, 'native output must have only fmt and data chunks', at)
    return info, start, size


def expected_frames(frames, rate):
    return (2 * frames * RATE + rate) // (2 * rate)


def check_source(p, data, info, at='$.source'):
    """Policy, duration and minimum-length rules that need the source header."""
    if p['channelPolicy'] == 'right' and info['channels'] == 1:
        fail('AUDIO_CHANNEL_POLICY', "a mono source has no right channel: use channelPolicy 'average' or 'left'", '$.channelPolicy')
    if info['frames'] > MAX_SECONDS * info['rate']:
        fail('AUDIO_RESOURCE_LIMIT', f'source exceeds {MAX_SECONDS} seconds of audio', at)
    if not expected_frames(info['frames'], info['rate']):
        fail('AUDIO_SOURCE_BOUNDS', 'source is too short to yield one 16000 Hz output frame', at)


def chunks(data, start, size, channels):
    view = memoryview(data)[start:start + size]
    step = CHUNK * channels * 2
    for offset in range(0, size, step):
        block = array('h')
        block.frombytes(view[offset:offset + step])
        if sys.byteorder == 'big': block.byteswap()
        yield block


def mix(block, channels, policy):
    if channels == 1: return block
    left, right = block[0::2], block[1::2]
    if policy == 'left': return left
    if policy == 'right': return right
    return array('h', [(a + b + 1) >> 1 for a, b in zip(left, right)])


def energy(block): return sum(map(mul, block, block))


def measure(data, start, size, info, policy):
    """One streaming pass over the source: per-channel and mixed integer statistics."""
    channels = info['channels']
    sums, peaks = [0] * channels, [0] * channels
    mixed_sum, mixed_peak, blocks = 0, 0, []
    for block in chunks(data, start, size, channels):
        for c in range(channels):
            lane = block[c::channels] if channels > 1 else block
            sums[c] += energy(lane); peaks[c] = max(peaks[c], max(lane), -min(lane))
        mixed = mix(block, channels, policy)
        mixed_peak = max(mixed_peak, max(mixed), -min(mixed))
        for offset in range(0, len(mixed), BLOCK):
            part = energy(mixed[offset:offset + BLOCK]); blocks.append(part); mixed_sum += part
    return {'channelSumSquares': sums, 'channelPeaks': peaks, 'mixedSumSquares': mixed_sum, 'mixedPeak': mixed_peak, 'blockEnergies': blocks}


def read_output(data, start, size):
    """Output frame statistics, streamed. Saturated samples sit at the PCM16 limits."""
    total, peak, saturated = 0, 0, 0
    for block in chunks(data, start, size, 1):
        total += energy(block); peak = max(peak, max(block), -min(block))
        saturated += block.count(32767) + block.count(-32768)
    return total, peak, saturated


def exact_same_rate(source, s_start, s_size, info, policy, output, o_start, o_size):
    """At 16000 Hz the conversion is pure integer mixing: every sample must match exactly."""
    produced = chunks(output, o_start, o_size, 1)
    base = 0
    for block in chunks(source, s_start, s_size, info['channels']):
        wanted = mix(block, info['channels'], policy)
        actual = next(produced, None)
        if actual is None or actual != wanted:
            frame = base + next((i for i, (a, b) in enumerate(zip(wanted, actual or [])) if a != b), min(len(wanted), len(actual or [])))
            fail('VERIFICATION_FAILED', f'same-rate channel conversion differs from the exact integer rule at output frame {frame}', 'audio.wav')
        base += len(wanted)
    if next(produced, None) is not None: fail('VERIFICATION_FAILED', 'native output has extra frames', 'audio.wav')


def bessel(x):
    total = term = 1.0
    k = 1
    while term > 1e-12 * total:
        term *= (x / (2 * k)) ** 2; total += term; k += 1
    return total


class Projection:
    """Independent physical-time low-pass L (Kaiser-windowed sinc; not SoX's filter).

    With N the lower Nyquist, L passes 0..PASS_EDGE*N and stops from STOP_EDGE*N with
    STOP_DB design attenuation. It is applied to the mixed source at its rate and to
    the native output at 16000 Hz, then both are compared at the same instants. SoX's
    own transition (-3 dB at 0.95 N, stop at N) lies inside L's stop band, so legitimate
    filter shape there cannot register as an error; only the declared band is verified."""
    def __init__(self, rate, sample_rate):
        nyquist = min(rate, RATE) / 2
        self.cutoff = (PASS_EDGE + STOP_EDGE) / 2 * nyquist / sample_rate
        # One kernel in physical time: the same half-span in seconds at both rates.
        seconds = (STOP_DB - 7.95) / (2.285 * 2 * math.pi * (STOP_EDGE - PASS_EDGE) * nyquist) / 2
        self.span = seconds * sample_rate
        self.half = int(self.span) + 1
        beta = 0.1102 * (STOP_DB - 8.7)
        scale = bessel(beta)
        self.table = [bessel(beta * math.sqrt(1 - (i / TABLE) ** 2)) / scale for i in range(TABLE + 1)]

    def kernel(self, t):
        ratio = abs(t) / self.span
        if ratio >= 1: return 0.0
        position = ratio * TABLE
        index = int(position)
        window = self.table[index] + (self.table[index + 1] - self.table[index]) * (position - index)
        core = 2 * self.cutoff if t == 0 else math.sin(2 * math.pi * self.cutoff * t) / (math.pi * t)
        return core * window

    def weights(self, fraction):
        """Kernel for samples c-half+1 .. c+half where the instant is c+fraction."""
        return [self.kernel(k - self.half + 1 - fraction) for k in range(2 * self.half)]


def instants(source_half, output_half, frames, out_frames, rate):
    """Output frames j whose source and output windows both lie inside the signals."""
    low = max(output_half - 1, -(-(source_half - 1) * RATE // rate))
    high = min(out_frames - 1 - output_half, ((frames - 1 - source_half) * RATE) // rate)
    return low, high


def spots(low, high, rate, blocks):
    if high < low: return []
    chosen = {low + (high - low) * k // (EVEN_SPOTS - 1) for k in range(EVEN_SPOTS)}
    loudest = sorted(range(len(blocks)), key=lambda i: (-blocks[i], i))[:LOUD_BLOCKS]
    for index in loudest:
        if not blocks[index]: continue
        for q in range(LOUD_PER_BLOCK):
            source_frame = index * BLOCK + (2 * q + 1) * BLOCK // (2 * LOUD_PER_BLOCK)
            chosen.add(min(max(source_frame * RATE // rate, low), high))
    return sorted(chosen)


def band_check(source, s_start, info, policy, output, o_start, frames, blocks, peak, clipped):
    """Compare L(source) with L(native output) at bounded interior instants.

    Per instant |L(out)-L(src)| must stay within half the output kernel's L1 norm
    (output rounding), ROUNDING_LSB, and LEAKAGE x source peak (composite residual of
    two linear-phase low-passes). When SoX reported clipping, instants whose output
    window touches a saturated sample are excluded and counted, never compared."""
    rate, channels = info['rate'], info['channels']
    src, out = Projection(rate, rate), Projection(rate, RATE)
    out_weights = out.weights(0.0)
    limit = 0.5 * sum(map(abs, out_weights)) + ROUNDING_LSB + LEAKAGE * peak
    low, high = instants(src.half, out.half, info['frames'], frames, rate)
    compared = excluded = 0
    worst = 0.0
    for j in spots(low, high, rate, blocks):
        window = array('h'); first = o_start + 2 * (j - out.half + 1)
        window.frombytes(output[first:first + 4 * out.half])
        if sys.byteorder == 'big': window.byteswap()
        if clipped and (32767 in window or -32768 in window): excluded += 1; continue
        centre, remainder = divmod(j * rate, RATE)
        first = s_start + (centre - src.half + 1) * channels * 2
        samples = array('h'); samples.frombytes(source[first:first + 4 * src.half * channels])
        if sys.byteorder == 'big': samples.byteswap()
        expected = sum(map(mul, mix(samples, channels, policy), src.weights(remainder / RATE)))
        actual = sum(map(mul, window, out_weights))
        compared += 1; worst = max(worst, abs(actual - expected))
    if worst > limit:
        fail('VERIFICATION_FAILED', f'resampled output departs from the source in the verified 0-{PASS_EDGE:g}*Nyquist band beyond the declared limit', 'audio.wav',
             comparedPositions=compared, worstErrorLSB=round(worst, 3), limitLSB=round(limit, 3))
    return compared, excluded


def diagnostics(text, executable):
    """Native stderr must contain only SoX's two documented clipping warnings."""
    import re
    rate = out = 0
    for line in text.splitlines():
        if not line.startswith(executable + ' '): fail('VERIFICATION_FAILED', 'unexpected native diagnostic: ' + line[:200], 'conform.stderr')
        body = line[len(executable) + 1:]
        match = re.fullmatch(CLIP_RATE, body)
        if match: rate += int(match.group(1)); continue
        match = re.fullmatch(CLIP_OUTPUT, body)
        if match: out += int(match.group(1)); continue
        fail('VERIFICATION_FAILED', 'unexpected native diagnostic: ' + line[:200], 'conform.stderr')
    return {'rateEffectSamples': rate, 'outputSamples': out}


def exact_seconds(frames, rate):
    divisor = math.gcd(frames, rate)
    return {'numerator': frames // divisor, 'denominator': rate // divisor}


FIDELITY_LIMIT = ('Resampled samples are not recomputed and individual samples are not certified. The source and the native output are both passed through '
                  'one independent low-pass and compared at up to 512 interior instants (even spacing plus the loudest source blocks); only content below '
                  '0.6 of the lower Nyquist (4800 Hz for sources at or above 16000 Hz) is verified. SoX\'s transition and stop band, edges within one filter '
                  'half-length, sources too short for any interior instant and instants touching native clipping are not compared.')


TIMELINE = ('Conform keeps the recording\'s time axis: output frame f is source time f/16000 s from the first source frame, with no trimming, '
            'padding or gaps, so transcript timestamps equal original recording timestamps. Duration changes only by the final-frame rounding rule '
            '(under 1/16000 s) and alignment of the verified band is checked within the declared limit.')


def summarise(p, source, info, s_start, s_size, output, o_start, o_size, stderr, executable):
    """Host reopening: exact structure, exact integer conversion where possible, bounded checks elsewhere."""
    import hashlib
    out_info, _, _ = canonical_info(output, 'VERIFICATION_FAILED', 'audio.wav')
    frames = expected_frames(info['frames'], info['rate'])
    if out_info != {'rate': RATE, 'channels': 1, 'frames': frames}:
        fail('VERIFICATION_FAILED', f"native output must be mono 16000 Hz with {frames} frames (round-half-up of frames*16000/rate), found {out_info}", 'audio.wav')
    policy = p['channelPolicy']
    stats = measure(source, s_start, s_size, info, policy)
    out_sum, out_peak, saturated = read_output(output, o_start, o_size)
    clipping = diagnostics(stderr, executable)
    if sum(clipping.values()) and not saturated: fail('VERIFICATION_FAILED', 'native reported clipping but no output sample is saturated', 'conform.stderr')
    exact = info['rate'] == RATE
    if exact:
        exact_same_rate(source, s_start, s_size, info, policy, output, o_start, o_size)
        compared = excluded = 0
    else:
        # Mean-square level, not total energy: upsampling adds frames without adding level.
        if out_sum * info['frames'] > (GAIN_RELATIVE ** 2 * stats['mixedSumSquares'] + GAIN_ABSOLUTE ** 2 * info['frames']) * frames:
            fail('VERIFICATION_FAILED', 'resampled output is louder than the conformed source allows', 'audio.wav')
        compared, excluded = band_check(source, s_start, info, policy, output, o_start, frames, stats['blockEnergies'], stats['mixedPeak'], sum(clipping.values()) > 0)
    channel_peaks = stats['channelPeaks']
    warnings = []
    loud = max(stats['channelSumSquares'])
    if policy == 'average' and info['channels'] == 2 and loud and stats['mixedSumSquares'] * 1024 < loud:
        warnings.append({'code': 'CHANNEL_CANCELLATION', 'message': 'averaging cancelled at least 30 dB of the louder channel; the channels are largely out of phase, so choose left or right'})
    if not out_peak and max(channel_peaks):
        warnings.append({'code': 'SILENT_OUTPUT', 'message': 'the source has signal but the conformed output is silent'})
    if saturated:
        warnings.append({'code': 'OUTPUT_SATURATION', 'message': f'{saturated} output samples sit at the PCM16 limits; '
                         + ('resampling can overshoot full-scale material' if not exact else 'the source or channel conversion reaches full scale')
                         + (f'; {excluded} verification instants touching native clipping were not compared' if excluded else '')})
    if not exact and not compared:
        warnings.append({'code': 'FIDELITY_NOT_SAMPLED', 'message': 'no interior instant could be compared (source shorter than the verification filter, or every instant touches native clipping); only header, frame count and loudness were checked'})
    mix_rule = {'average': 'average: (left+right+1)>>1 per stereo frame (SoX remix, 1/n scaling, round half up); a mono source passes through',
                'left': 'left: copy of channel 1', 'right': 'right: copy of channel 2'}[policy]
    return {'operation': OPERATION, 'channelPolicy': policy, 'rate': RATE, 'channels': 1, 'frames': frames,
            'durationSeconds': frames / RATE, 'durationExact': exact_seconds(frames, RATE),
            'source': {'sha256': hashlib.sha256(source).hexdigest(), 'bytes': len(source), **info, 'durationExact': exact_seconds(info['frames'], info['rate']),
                       'channelPeaksPCM16': channel_peaks,
                       'channelRmsPCM16': [math.sqrt(s / info['frames']) for s in stats['channelSumSquares']]},
            'conversion': {'channelMix': mix_rule, 'resampled': not exact, 'frameRule': 'round-half-up(sourceFrames*16000/sourceRate)'},
            'peakPCM16': out_peak, 'rmsPCM16': math.sqrt(out_sum / frames), 'saturatedSamples': saturated, 'nativeClippingWarnings': clipping,
            'fidelity': {'method': 'exact-integer-channel-conversion' if exact else 'independent-band-limited-projection', 'samplesRecomputedExactly': exact,
                         'comparedPositions': compared, 'excludedForNativeClipping': excluded,
                         'verifiedBand': None if exact else {'upperFractionOfLowerNyquist': PASS_EDGE, 'upperHz': exact_seconds(int(PASS_EDGE * 10) * min(info['rate'], RATE), 20)},
                         'projectionFilter': None if exact else {'kind': 'Kaiser-windowed sinc', 'passFractionOfLowerNyquist': PASS_EDGE, 'stopFractionOfLowerNyquist': STOP_EDGE, 'designStopBandDB': STOP_DB},
                         'errorLimit': None if exact else {'outputRounding': 'half the L1 norm of the output projection kernel', 'absoluteLSB': ROUNDING_LSB, 'relativeToSourcePeak': LEAKAGE},
                         'limit': FIDELITY_LIMIT if not exact else 'Every output sample equals the exact integer channel rule.'},
            'warnings': warnings, 'timeline': {'originalTimestampsPreserved': True, 'explanation': TIMELINE}}
