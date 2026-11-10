"""Admit native benchmark observations without authenticating historical speed."""
import unittest
from schemaxis.adaptors.zstandard import adaptor as a,benchmark
from schemaxis.core.faults import SchemaxisError

class BenchmarkReports(unittest.TestCase):
    text='bench 1.5.7 : input 12024 bytes, 1 seconds, 0 KB blocks\n-1          288 (41.750) 5461.93 MB/s 1701.5 MB/s  ured-source-0.bin\n'
    def test_real_native_report_admits_truncated_capture_name_and_rounded_ratio(self):
        p=a.plan({'version':a.VERSION,'operation':'benchmark','source':'/example/source','firstLevel':1,'lastLevel':1})
        result=benchmark.parse(self.text,p,12024,12024,'captured-source-0.bin')
        self.assertFalse(result['timingVerified']);self.assertEqual(result['levels'][0]['compressedBytes'],288)
        for text in (self.text.replace('41.750','41.749'),self.text.replace('ured-source-0.bin','other.bin'),self.text.replace('1701.5','0.0'),self.text+'-2 288 (41.750) 1 MB/s 1 MB/s source\n'):
            with self.subTest(text=text),self.assertRaises(SchemaxisError):benchmark.parse(text,p,12024,12024,'captured-source-0.bin')

    def test_benchmark_range_and_decode_controls_are_meaningful(self):
        for values in ({'operation':'benchmark','firstLevel':4,'lastLevel':3},{'operation':'benchmark','firstLevel':1,'lastLevel':5},
                       {'operation':'benchmark','benchmarkBlockBytes':512},{'operation':'benchmarkDecode','firstLevel':1}):
            with self.subTest(values=values),self.assertRaises(SchemaxisError):a.plan({'version':a.VERSION,'source':'/example/source',**values})
