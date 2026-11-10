"""Independent known scanline bytes exercise bundle PNG precision and bounds."""
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from schemaxis.adaptors.blender import png_output as P
from schemaxis.core.faults import SchemaxisError


def chunk(kind,payload=b''):
    return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)


def header(width,height,depth,colour,interlace=0):
    return chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,depth,colour,0,0,interlace))


def png(width,height,depth,colour,scanlines):
    return P.SIGNATURE+header(width,height,depth,colour)+chunk(b'IDAT',zlib.compress(scanlines))+chunk(b'IEND')


class BundlePNG(unittest.TestCase):
    def inspect(self,data):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'samples.png';path.write_bytes(data)
            return P.inspect(path)

    def test_known_rgb8_average_up_and_rgba8_sub_preserve_exact_channels(self):
        # Hand-encoded 2x3 RGB: NONE, AVERAGE, UP; expected bytes are explicit.
        rows=[bytes.fromhex('0a141e28323c'),bytes.fromhex('14283c506478'),bytes.fromhex('192d4155697d')]
        encoded=b'\0'+rows[0]+b'\3'+bytes.fromhex('0f1e2d32373c')+b'\2'+b'\5'*6
        value=self.inspect(png(2,3,8,2,encoded))
        self.assertEqual(value,{'size':[2,3],'depth':'8','channels':'rgb','pixelsSha256':hashlib.sha256(b''.join(rows)).hexdigest()})
        rgba=bytes.fromhex('10203000405060ff')
        value=self.inspect(png(2,1,8,6,b'\1'+bytes.fromhex('10203000303030ff')))
        self.assertEqual(value['channels'],'rgba');self.assertEqual(value['pixelsSha256'],hashlib.sha256(rgba).hexdigest())

    def test_known_rgb16_sub_up_keeps_big_endian_low_bytes(self):
        rows=[bytes.fromhex('00011234abcdff0056789abc'),bytes.fromhex('0102030405060708090a0b0c')]
        encoded=b'\1'+bytes.fromhex('00011234abcdffff4444efef')+b'\2'+bytes.fromhex('0101f1d05a390808b3927150')
        value=self.inspect(png(2,2,16,2,encoded))
        self.assertEqual(value,{'size':[2,2],'depth':'16','channels':'rgb','pixelsSha256':hashlib.sha256(b''.join(rows)).hexdigest()})
        # A low sample byte affects the hash; it is not truncated to 8 bits.
        changed=rows[0][:-1]+bytes([rows[0][-1]^1])+rows[1]
        self.assertNotEqual(value['pixelsSha256'],hashlib.sha256(changed).hexdigest())

    def test_known_rgba16_paeth_uses_eight_byte_pixel_distance(self):
        row0=bytes.fromhex('01020304050607081112131415161718')
        row1=bytes.fromhex('02030405060708091213141516171819')
        encoded=b'\1'+row0[:8]+b'\x10'*8+b'\4'+b'\1'*16
        value=self.inspect(png(2,2,16,6,encoded))
        self.assertEqual(value,{'size':[2,2],'depth':'16','channels':'rgba','pixelsSha256':hashlib.sha256(row0+row1).hexdigest()})

    def test_consecutive_split_idat_and_ancillary_chunk_positive(self):
        stream=zlib.compress(b'\0\x01\x02\x03')
        data=P.SIGNATURE+header(1,1,8,2)+chunk(b'tEXt',b'label\0sample')+chunk(b'IDAT',stream[:2])+chunk(b'IDAT',stream[2:])+chunk(b'IEND')
        self.assertEqual(self.inspect(data)['pixelsSha256'],hashlib.sha256(b'\1\2\3').hexdigest())

    def test_invalid_chunks_filters_precision_and_truncation_refuse(self):
        valid=png(1,1,8,2,b'\0\1\2\3')
        broken_crc=bytearray(valid);broken_crc[-5]^=1
        variants=[valid[:n]for n in (0,7,12,len(valid)-1)]
        variants += [bytes(broken_crc),valid+b'tail',png(1,1,8,2,b'\5\1\2\3'),
                     png(2049,1,8,2,b'\0\1\2\3'),png(1,1,4,2,b'\0\1\2\3'),
                     P.SIGNATURE+header(1,1,8,2,1)+chunk(b'IDAT',zlib.compress(b'\0\1\2\3'))+chunk(b'IEND')]
        for data in variants:
            with self.subTest(length=len(data)),self.assertRaises(SchemaxisError):self.inspect(data)

    def test_zlib_eof_extra_output_tail_and_idat_order_refuse(self):
        stream=zlib.compress(b'\0\1\2\3')
        variants=[stream[:-1],stream+b'extra',stream+zlib.compress(b''),zlib.compress(b'\0\1\2\3\4')]
        prefix=P.SIGNATURE+header(1,1,8,2)
        for value in variants:
            with self.subTest(stream=value),self.assertRaises(SchemaxisError):self.inspect(prefix+chunk(b'IDAT',value)+chunk(b'IEND'))
        for first in (b'',stream[:2]):
            with self.subTest(first=first),self.assertRaises(SchemaxisError):
                self.inspect(prefix+chunk(b'IDAT',first)+chunk(b'tEXt',b'gap')+chunk(b'IDAT',stream)+chunk(b'IEND'))
        with self.assertRaises(SchemaxisError):self.inspect(prefix+chunk(b'IDAT',stream)+chunk(b'ABCD')+chunk(b'IEND'))
        with self.assertRaises(SchemaxisError):self.inspect(prefix+chunk(b'IDAT',stream)+chunk(b'tRNS',b'\0'*6)+chunk(b'IEND'))

    def test_chunk_count_and_oversized_file_are_bounded_before_decode(self):
        data=P.SIGNATURE+header(1,1,8,2)+chunk(b'tEXt')*P.MAX_CHUNKS
        with self.assertRaises(SchemaxisError):self.inspect(data)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'oversized.png'
            with path.open('wb') as stream:stream.truncate(P.MAX_FILE_BYTES+1)
            with self.assertRaises(SchemaxisError):P.inspect(path)

if __name__=='__main__':unittest.main()
