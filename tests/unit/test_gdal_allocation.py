"""Spatial-extent plausibility for declared CRS before native raster work."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from schemaxis.adaptors.gdal import adaptor, reference
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('gdal_fixtures',ROOT/'tools/qualify_gdal_fixtures.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
WEB_MERCATOR=20037508.342789244


def document(source,**change):
    return {**json.loads((ROOT/'examples/schemaxis/gdal-window.json').read_text()),'source':str(source),'x':0,'y':0,'width':4,'height':3,'outputWidth':4,'outputHeight':3,**change}


class GdalExtentTests(unittest.TestCase):
    def run_fault(self,data,**change):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.tif';source.write_bytes(data)
            out=Path(folder)/'out'
            # Any absolute executable: refusal must precede native work.
            with self.assertRaises(SchemaxisError) as caught:adaptor.run(document(source,**change),out,executable=sys.executable,timeout=30)
            result=json.loads((out/'result.json').read_text())
            return caught.exception.fault,result,sorted(p.name for p in out.iterdir())

    def test_mislabelled_projected_coordinates_are_refused_before_native_work(self):
        # Metre-scale coordinates labelled EPSG:4326 are not degrees.
        fault,result,names=self.run_fault(fixtures.tiff([1]*30,epsg=4326,units='m'),epsg=4326)
        self.assertEqual(fault.code,'RASTER_EXTENT_INVALID')
        self.assertEqual(fault.location,'$.source')
        self.assertEqual(result['status'],'failed');self.assertFalse(result['verified'])
        self.assertEqual(result['fault']['code'],'RASTER_EXTENT_INVALID')
        self.assertNotIn('native-worker.py',names);self.assertNotIn('source.tif',names)
        self.assertEqual(fault.observed['epsg'],4326)
        self.assertEqual(fault.observed['axis'],'latitude')
        self.assertEqual(fault.observed['limits'],[-90,90])

    def test_latitude_is_refused_but_projected_extent_is_preserved(self):
        fault,*_=self.run_fault(fixtures.tiff([1]*30,epsg=4326,units='m',origin=(10,95),spacing=(1,1)),epsg=4326)
        self.assertEqual((fault.code,fault.observed['axis']),('RASTER_EXTENT_INVALID','latitude'))
        fault,*_=self.run_fault(fixtures.tiff([1]*30,origin=(1e8,1e8),spacing=(10,20)))
        self.assertEqual(fault.code,'RUNNER_FAILED')  # projected coordinates are preserved

    def test_projected_coordinates_and_unwrapped_longitudes_are_preserved(self):
        # A tile square is not a general projected-coordinate validity bound.
        for epsg, origin in [(3857, (0, 20040000)), (4326, (-181, 10))]:
            with self.subTest(epsg=epsg):
                raster = reference.parse(fixtures.tiff([1]*30,epsg=epsg,units='m',origin=origin,spacing=(1,1)))
                self.assertIsNone(reference.extent_violation(raster))

    def test_distinct_from_metadata_mismatch_and_malformed(self):
        data=fixtures.tiff([1]*30)
        fault,*_=self.run_fault(data,epsg=4326)
        self.assertEqual(fault.code,'INVALID_RASTER_CONTENT')
        fault,*_=self.run_fault(data[:-1])
        self.assertEqual(fault.code,'INVALID_RASTER_CONTENT')

    def test_valid_extents_reach_native_stage(self):
        cases=[(dict(epsg=4326,units='m',origin=(-180,90),spacing=(60,36)),{'epsg':4326}),
               (dict(epsg=4326,units='m',origin=(0,60),spacing=(60,24)),{'epsg':4326}),  # 0..360 longitude convention
               (dict(origin=(-WEB_MERCATOR,WEB_MERCATOR),spacing=(WEB_MERCATOR*2/6,WEB_MERCATOR*2/5)),{}),
               # Only the selected window must be plausible; padding outside it is not published.
               (dict(epsg=4326,units='m',origin=(10,100),spacing=(1,5)),{'epsg':4326,'y':2,'height':3})]
        for kw,change in cases:
            with self.subTest(kw=kw):
                fault,result,names=self.run_fault(fixtures.tiff(list(range(30)),**kw),**change)
                # No GDAL here: the isolated worker, not the extent gate, fails.
                self.assertEqual(fault.code,'RUNNER_FAILED')
                self.assertIn('native-worker.py',names)

    def test_extent_violation_boundaries(self):
        def raster(epsg,origin,spacing,units='m'):
            return reference.parse(fixtures.tiff([1]*30,epsg=epsg,units=units,origin=origin,spacing=spacing))
        self.assertIsNone(reference.extent_violation(raster(4326,(-180,90),(60,36))))
        self.assertIsNone(reference.extent_violation(raster(4326,(180,90),(30,36))))
        self.assertIsNone(reference.extent_violation(raster(3857,(-WEB_MERCATOR,WEB_MERCATOR),(WEB_MERCATOR/3,WEB_MERCATOR*2/5))))
        for epsg,origin,spacing in ((4326,(0,90.001),(1,1)),(4326,(0,-85),(1,5))):
            with self.subTest(epsg=epsg,origin=origin):self.assertIsNotNone(reference.extent_violation(raster(epsg,origin,spacing)))

    def test_legacy_receipt_parse_is_not_rejudged(self):
        # Receipts verified under the earlier contract must stay parseable by verify.
        data=fixtures.tiff([1]*30,epsg=4326,units='m')
        self.assertEqual(reference.parse(data)['epsg'],4326)
        self.assertIsNotNone(reference.extent_violation(reference.parse(data)))


if __name__=='__main__':unittest.main()
