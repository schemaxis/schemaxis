"""Independent literal checksum, frame-boundary and hostile-stream controls."""
import struct
import unittest
from schemaxis.adaptors.zstandard import frames
from schemaxis.core.faults import SchemaxisError


def raw_frame(data,checksum=True):
    assert len(data)<256
    body=b'\x28\xb5\x2f\xfd'+bytes([0x24 if checksum else 0x20,len(data)])
    body+=((len(data)<<3)|1).to_bytes(3,'little')+data
    if checksum:body+=(frames.xxh64(data)&0xffffffff).to_bytes(4,'little')
    return body


class FrameChecks(unittest.TestCase):
    def test_published_xxh64_vectors(self):
        for data,expected in [(b'',0xef46db3751d8e999),(b'a',0xd24ec4f1a98c6e5b),(b'abc',0x44bc2cf5ad770999)]:
            self.assertEqual(frames.xxh64(data),expected)

    def test_literal_raw_frame_and_concatenated_skip_boundaries(self):
        # Literal checksum is independent of the helper used for other cases.
        frame=bytes.fromhex('28b52ffd2403190000616263990977ad')
        records=frames.inspect(frame)
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['contentBytes'],3)
        frames.check_content(records[0],b'abc')
        skip=bytes.fromhex('502a4d18')+struct.pack('<I',4)+b'note'
        joined=frames.inspect(frame+skip+raw_frame(b''))
        self.assertEqual([r['kind'] for r in joined],['zstandard','skippable','zstandard'])
        self.assertEqual([r['offset'] for r in joined],[0,len(frame),len(frame)+len(skip)])

    def test_truncation_reserved_block_and_bounded_declared_content(self):
        frame=raw_frame(b'abc')
        for bad in (frame[:-1],frame[:3],frame+b'x',frame[:4]+bytes([frame[4]|8])+frame[5:],frame[:6]+b'\x07\x00\x00'+frame[9:]):
            with self.subTest(data=bad),self.assertRaises(SchemaxisError):frames.inspect(bad)
        with self.assertRaises(SchemaxisError):frames.inspect(frame,max_decoded=2)
        with self.assertRaises(SchemaxisError):frames.check_content(frames.inspect(frame)[0],b'abd')
        with self.assertRaises(SchemaxisError):frames.check_content(frames.inspect(frame)[0],b'abcd')

    def test_skip_only_stream_and_frame_count_are_bounded(self):
        skip=bytes.fromhex('502a4d1800000000')
        self.assertEqual(frames.inspect(skip)[0]['kind'],'skippable')
        with self.assertRaises(SchemaxisError):frames.inspect(b'')
        with self.assertRaises(SchemaxisError):frames.inspect(skip*4097+raw_frame(b''))

    def test_dictionary_identity_is_parsed_without_loading_native_code(self):
        self.assertEqual(frames.dictionary_id(b'\x37\xa4\x30\xec'+struct.pack('<I',50001)+b'x'),50001)
        with self.assertRaises(SchemaxisError):frames.dictionary_id(b'not-a-dictionary')
