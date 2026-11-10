"""Pure-stdlib FLAC/WAV byte builders shared by the FLAC host tests and the fake native program.

Kept free of Schemaxis imports so the fake flac executable starts quickly. ``crc8`` here is an independent implementation of the
RFC 9639 frame-header CRC (polynomial x^8 + x^2 + x + 1, initial value 0) that the host tests compare with the adaptor's.
"""
import hashlib
import struct

RATE_CODE = {88200: 1, 176400: 2, 192000: 3, 8000: 4, 16000: 5, 22050: 6, 24000: 7, 32000: 8, 44100: 9, 48000: 10, 96000: 11}
MARKER = b'PCM!'


def crc8(data):
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ 0x07) & 0xff if value & 0x80 else (value << 1) & 0xff
    return value


def wav_bytes(rate=8000, channels=2, pcm=bytes(8), bits=16, encoding=1, fmt_size=16, extra=b'', data_first=False, riff_delta=0, tail=b''):
    align = channels * bits // 8
    fmt = struct.pack('<HHIIHH', encoding, channels, rate, rate * align, align, bits) + bytes(fmt_size - 16)
    chunks = [b'fmt ' + struct.pack('<I', fmt_size) + fmt, b'data' + struct.pack('<I', len(pcm)) + pcm + b'\0' * (len(pcm) & 1)]
    if data_first:
        chunks.reverse()
    body = b'WAVE' + extra + b''.join(chunks) + tail
    return b'RIFF' + struct.pack('<I', len(body) + riff_delta) + body


def streaminfo(rate=8000, channels=2, bits=16, total=2, md5=b'\x11' * 16, min_block=4096, max_block=4096, min_frame=0, max_frame=0):
    packed = (rate << 44) | ((channels - 1) << 41) | ((bits - 1) << 36) | total
    return struct.pack('>HH', min_block, max_block) + min_frame.to_bytes(3, 'big') + max_frame.to_bytes(3, 'big') + packed.to_bytes(8, 'big') + md5


def frame_header(rate=8000, channels=2, total=2, size=None, rate_code=None, channel_code=None, depth_code=4, sync=0xf8, number=0, corrupt_crc=False, reserved=0):
    size = size if size is not None else min(total, 4096)
    code = 12 if size == 4096 else 6 if size <= 256 else 7
    code = {192: 1, 576: 2, 1152: 3, 2304: 4, 4608: 5}.get(size, code)
    rate_code = rate_code if rate_code is not None else RATE_CODE.get(rate, 13)
    channel_code = channel_code if channel_code is not None else channels - 1
    head = bytes([0xff, sync, (code << 4) | rate_code, (channel_code << 4) | (depth_code << 1) | reserved, number])
    if code == 6:
        head += bytes([size - 1])
    elif code == 7:
        head += struct.pack('>H', size - 1)
    if rate_code == 13:
        head += struct.pack('>H', rate)
    return head + bytes([crc8(head) ^ (1 if corrupt_crc else 0)])


def metadata_stream(blocks):
    """Marker plus blocks given as (type, body); the last flag is set on the final block."""
    out = b'fLaC'
    for index, (kind, body) in enumerate(blocks):
        out += bytes([(0x80 if index == len(blocks) - 1 else 0) | kind]) + len(body).to_bytes(3, 'big') + body
    return out


def vorbis(vendor=b'reference libFLAC 1.5.0 20250211', count=0):
    return struct.pack('<I', len(vendor)) + vendor + struct.pack('<I', count)


def build_flac(rate=8000, channels=2, pcm=None, *, total=None, md5=None, extra_blocks=(), info=None, header=None, order=None, vendor=True, body=None):
    pcm = bytes(4 * 2) if pcm is None else pcm
    total = total if total is not None else len(pcm) // (2 * channels)
    md5 = md5 if md5 is not None else hashlib.md5(pcm).digest()
    blocks = [(0, info if info is not None else streaminfo(rate, channels, 16, total, md5))]
    if vendor:
        blocks.append((4, vorbis()))
    blocks.extend(extra_blocks)
    if order:
        blocks = order(blocks)
    frame = header if header is not None else frame_header(rate, channels, total)
    return metadata_stream(blocks) + frame + MARKER + (pcm if body is None else body)


def chunk_list(payload=b'INFOISFT\x04\x00\x00\x00abc\x00'):
    return b'LIST' + struct.pack('<I', len(payload)) + payload


def parse_fake(data):
    """Minimal reader of build_flac output: STREAMINFO facts and the raw PCM body after the marker (what the fake decoder needs)."""
    offset, info = 4, None
    while True:
        last, kind, size = data[offset] >> 7, data[offset] & 0x7f, int.from_bytes(data[offset + 1:offset + 4], 'big')
        if kind == 0:
            raw = data[offset + 4:offset + 4 + size]
            packed = int.from_bytes(raw[10:18], 'big')
            info = {'channels': ((packed >> 41) & 7) + 1, 'totalSamples': packed & 0xfffffffff, 'md5': raw[18:34].hex()}
        offset += 4 + size
        if last:
            break
    return info, data[data.index(MARKER, offset) + 4:]
