"""Native EXR fixtures and hostile file bounds independent of Blender readback."""
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from schemaxis.adaptors.blender.exr_output import inspect
from schemaxis.errors import SchemaxisError

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/blender-render-bundles'


def header_offsets(raw):
    position, result = 8, {}
    while raw[position]:
        end = raw.index(0, position);name = raw[position:end].decode();position = end + 1
        end = raw.index(0, position);kind = raw[position:end].decode();position = end + 1
        size, = struct.unpack_from('<i', raw, position);position += 4
        result[name] = (position, size, kind);position += size
    return result, position + 1


class RenderEXR(unittest.TestCase):
    def test_native_literal_hdr_planes_and_exact_bits(self):
        result = inspect(FIXTURES / 'literal-float-zip.exr', samples=[(0, 0), (3, 2)])
        self.assertEqual(result['size'], [4, 3]);self.assertEqual(result['compression'], 'zip')
        self.assertEqual([c['pixelType'] for c in result['channels']], ['float'] * 4)
        for sample in result['samples'].values():
            self.assertEqual({k:v['value'] for k,v in sample.items()}, {'R':2.,'G':.125,'B':.5,'A':1.})
            self.assertEqual(sample['R']['bits'], struct.pack('<f',2.).hex())

    def test_native_fileoutput_pass_types_and_physical_values(self):
        result = inspect(FIXTURES / 'passes-float-zip.exr', samples=[(16, 8), (0, 0)])
        center = result['samples']['16,8'];outside = result['samples']['0,0']
        expected = {'beauty.R':.2,'beauty.G':.4,'beauty.B':.6,'beauty.A':1.,
                    'depth.V':3.,'normal.X':0.,'normal.Y':0.,'normal.Z':1.,'calibration.V':.375}
        for name,value in expected.items():self.assertAlmostEqual(center[name]['value'],value,places=6)
        self.assertEqual(outside['beauty.A']['value'],0.)
        self.assertEqual({c['name'] for c in result['channels']},set(expected)|{'position.X','position.Y','position.Z'})

    def test_native_bytes_truncated_at_header_table_chunk_and_tail_refuse(self):
        raw = (FIXTURES / 'passes-float-zip.exr').read_bytes();_,table = header_offsets(raw)
        with tempfile.TemporaryDirectory() as folder:
            for length in (0,7,40,table-1,table+3,len(raw)-1):
                with self.subTest(length=length):self.refuses(Path(folder),raw[:length])
            self.refuses(Path(folder),raw+b'unclaimed foreign bytes')

    def refuses(self, folder, raw):
        path = folder / 'mutant.exr';path.write_bytes(raw)
        with self.assertRaises(SchemaxisError) as caught:inspect(path)
        self.assertEqual(caught.exception.fault.code,'INVALID_RENDER_OUTPUT')

    def test_native_header_and_chunk_authority_attacks_refuse(self):
        original = (FIXTURES / 'passes-float-zip.exr').read_bytes();fields,table = header_offsets(original)
        mutations = {}
        raw=bytearray(original);struct.pack_into('<I',raw,4,2|0x1000);mutations['multipart']=raw
        raw=bytearray(original);offset,_,_=fields['dataWindow'];struct.pack_into('<i',raw,offset+8,2**30);mutations['width-budget']=raw
        raw=bytearray(original);offset,_,_=fields['channels'];end=raw.index(0,offset);struct.pack_into('<i',raw,end+1,99);mutations['unknown-pixel-type']=raw
        raw=bytearray(original);offset,_,_=fields['channels'];end=raw.index(0,offset);struct.pack_into('<i',raw,end+1+8,2);mutations['subsampled']=raw
        raw=bytearray(original);struct.pack_into('<Q',raw,table,0);mutations['header-as-chunk']=raw
        raw=bytearray(original);offset,=struct.unpack_from('<Q',raw,table);struct.pack_into('<i',raw,offset+4,2**30);mutations['chunk-length']=raw
        raw=bytearray(original);offset,=struct.unpack_from('<Q',raw,table);struct.pack_into('<i',raw,offset,100);mutations['outside-row']=raw
        raw=bytearray(original);offset,_,_=fields['compression'];raw[offset]=4;mutations['unreviewed-codec']=raw
        with tempfile.TemporaryDirectory() as folder:
            for label,raw in mutations.items():
                with self.subTest(case=label):self.refuses(Path(folder),raw)

    def test_sample_coordinates_are_bounded_and_integral(self):
        for samples in ([(4,0)],[(0,3)],[(True,0)],[(0.1,0)],[(0,)],'0,0'):
            with self.subTest(samples=samples):
                with self.assertRaises(SchemaxisError):inspect(FIXTURES/'literal-float-zip.exr',samples=samples)

    def test_compressed_expansion_and_trailing_stream_refuse(self):
        raw=(FIXTURES/'literal-float-zip.exr').read_bytes();_,table=header_offsets(raw)
        offset,=struct.unpack_from('<Q',raw,table);row,=struct.unpack_from('<i',raw,offset)
        # The genuine native file declares 4*3*4 FLOAT components (192 bytes).
        # An otherwise valid zlib stream must not expand past that derived bound.
        payloads=[zlib.compress(b'\0'*193),zlib.compress(b'\0'*192)+b'foreign']
        with tempfile.TemporaryDirectory() as folder:
            for payload in payloads:
                mutant=raw[:offset]+struct.pack('<ii',row,len(payload))+payload
                self.refuses(Path(folder),mutant)


if __name__=='__main__':unittest.main()
