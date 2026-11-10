"""Pure-stdlib stored-ZIP byte builder shared by the Info-ZIP host tests and the fake native program.

Kept free of Schemaxis imports so the fake zip executable starts quickly. ``build_zip`` is an independent writer of the
canonical archive Info-ZIP 3.0 produces for this adaptor (stored, 1980-01-01 00:00:00, regular mode 0600, no extras), and
``layout`` reports the byte offsets of every record so tests can corrupt single fields.
"""
import struct
import zlib

LOCAL, CENTRAL, END = 30, 46, 22
EXTERNAL = (0o100000 | 0o600) << 16


def build_zip(members, *, made=0x031e, needed=10, flags=0, method=0, time=0, date=0x21, external=EXTERNAL, comment=b''):
    """Canonical stored archive of (name, bytes) members, with header fields overridable for hostile variants."""
    body, central, offset = b'', b'', 0
    for name, data in members:
        raw = name.encode('latin-1')
        crc = zlib.crc32(data)
        local = struct.pack('<4sHHHHHIIIHH', b'PK\x03\x04', needed, flags, method, time, date, crc, len(data), len(data), len(raw), 0) + raw + data
        central += struct.pack('<4sHHHHHHIIIHHHHHII', b'PK\x01\x02', made, needed, flags, method, time, date, crc, len(data), len(data),
                               len(raw), 0, 0, 0, 0, external, offset) + raw
        body += local
        offset += len(local)
    end = struct.pack('<4sHHHHIIH', b'PK\x05\x06', 0, 0, len(members), len(members), len(central), offset, len(comment)) + comment
    return body + central + end


def layout(members):
    """Offsets of each local header, each central entry, the central directory and the end record of ``build_zip(members)``."""
    locals_, centrals, offset, central = [], [], 0, 0
    for name, data in members:
        locals_.append(offset)
        offset += LOCAL + len(name) + len(data)
    central = offset
    for name, _ in members:
        centrals.append(offset)
        offset += CENTRAL + len(name)
    return {'local': locals_, 'central': centrals, 'directory': central, 'end': offset}
