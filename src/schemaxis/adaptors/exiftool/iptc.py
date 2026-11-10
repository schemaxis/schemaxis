"""Bounded IPTC-IIM reader for the Photoshop APP13 container of a JPEG (standard library only).

Datasets are read by (record, dataset number); repeated datasets are all kept. The coded character set (1:90) is explicit: ESC % G is
UTF-8; a missing 1:90 leaves the charset unspecified (only 7-bit ASCII text is then readable); any other value is unsupported rather
than guessed. Extended-length datasets are unsupported.
"""
import struct

MAX_DATASETS = 4096
MAX_BYTES = 1024 * 1024
UTF8 = b'\x1b%G'


class Problem(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def resources(app13):
    """Photoshop image resource blocks of one APP13 body as ``[(id, data)]``."""
    prefix = b'Photoshop 3.0\0'
    if app13[:len(prefix)] != prefix:
        raise Problem('IPTC_CONTAINER_UNSUPPORTED', 'APP13 is not a Photoshop 3.0 resource container')
    position, found = len(prefix), []
    while position + 12 <= len(app13):
        if app13[position:position + 4] != b'8BIM':
            raise Problem('IPTC_MALFORMED', 'a Photoshop image resource lacks the 8BIM signature')
        ident = struct.unpack_from('>H', app13, position + 4)[0]
        name_length = app13[position + 6]
        position += 6 + 1 + name_length + (1 + name_length) % 2
        if position + 4 > len(app13):
            raise Problem('IPTC_MALFORMED', 'a Photoshop image resource is truncated')
        size = struct.unpack_from('>I', app13, position)[0]
        position += 4
        if position + size > len(app13):
            raise Problem('IPTC_MALFORMED', 'a Photoshop image resource exceeds its segment')
        found.append((ident, app13[position:position + size]))
        position += size + size % 2
    return found


def datasets(block):
    """``{charset, datasets: {(record, number): [bytes]}}`` from an IPTC-NAA resource body; raises Problem."""
    if len(block) > MAX_BYTES:
        raise Problem('IPTC_BOUND', 'IPTC data exceeds %d bytes' % MAX_BYTES)
    position, found, count = 0, {}, 0
    while position < len(block):
        if block[position] != 0x1C or position + 5 > len(block):
            raise Problem('IPTC_MALFORMED', 'an IPTC dataset marker is missing or truncated')
        record, number, length = block[position + 1], block[position + 2], struct.unpack_from('>H', block, position + 3)[0]
        if length & 0x8000:
            raise Problem('IPTC_EXTENDED_UNSUPPORTED', 'extended-length IPTC datasets are unsupported')
        position += 5
        if position + length > len(block):
            raise Problem('IPTC_MALFORMED', 'an IPTC dataset exceeds the data')
        count += 1
        if count > MAX_DATASETS:
            raise Problem('IPTC_BOUND', 'IPTC has more than %d datasets' % MAX_DATASETS)
        found.setdefault((record, number), []).append(block[position:position + length])
        position += length
    coded = found.get((1, 90))
    if coded is None:
        charset = 'unspecified'
    elif len(coded) == 1 and coded[0] == UTF8:
        charset = 'utf-8'
    else:
        charset = 'unsupported'
    return {'charset': charset, 'datasets': found}
