"""Meaningful numeric plot contracts and independent geometry/PNG checks."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors import registry
from schemaxis.adaptors.gnuplot import adaptor
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]


class GnuplotContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Pending packages stay outside global discovery during concurrent work.
        # This private test registry permits complete host admission before activation.
        path=ROOT/'src/schemaxis/adaptors/gnuplot/adaptor.json.pending'
        cls.registration=patch.dict(registry.ADAPTORS,{'gnuplot':json.loads(path.read_text())}) if path.exists() else patch.dict(registry.ADAPTORS,{})
        cls.registration.start()

    @classmethod
    def tearDownClass(cls): cls.registration.stop()

    def document(self,name='calibration'):
        return json.loads((ROOT/f'examples/schemaxis/gnuplot-{name}.json').read_text())

    def prepared(self,name='calibration'): return adaptor.plan(self.document(name))

    def fault(self,action,code):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code,code)
        return caught.exception.fault

    def test_host_admission_search_guidance(self):
        from schemaxis.adaptor_conformance import host
        from schemaxis.capabilities import CapabilityCatalogue
        from schemaxis.search_acceptance import check_cases
        from schemaxis.studio_guidance import audit
        self.assertTrue(host(adaptor.VERSION)['verified'])
        self.assertTrue(check_cases(CapabilityCatalogue(providers=['gnuplot']),'gnuplot')['complete'])
        self.assertTrue(audit('gnuplot')['complete'])

    def test_immutable_plan_defaults_and_exact_mappings(self):
        d=self.document();d.pop('width');d['xAxis'].pop('scale');before=copy.deepcopy(d)
        p=adaptor.plan(d);self.assertEqual(d,before);self.assertEqual(p,adaptor.plan(d))
        self.assertEqual((p['width'],p['height'],p['xAxis']['scale']),(800,600,'linear'))
        self.assertIn('every ::1 using 1:2:3 with yerrorlines',adaptor.script(p))
        self.assertEqual(adaptor.query(d)[0],['plot'])

    def test_ranges_units_and_mapping_faults(self):
        for bounds in ([2,0],[1,1],[1,1.00000000001]):
            d=self.document();d['xAxis']['range']=bounds
            self.assertEqual(self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_RANGE').location,'$.xAxis.range')
        d=self.document('range-invalid');self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_RANGE')
        d=self.document();d['columns'][1]['unit']='mV';self.fault(lambda:adaptor.plan(d),'PLOT_UNIT_MISMATCH')
        d=self.document();d['series'][0]['y']='missing';self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_COLUMNS')
        d=self.document();d['columns'][1]['name']='time';self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_COLUMNS')
        d=self.document();d['series']*=2;self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_SERIES')

    def test_injection_and_closed_options(self):
        for text in ("x'; system 'echo bad'",'`touch bad`','%s','a\nb',' x','x ','x_{a}','line\\text'):
            d=self.document();d['title']=text;self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_LABEL')
        for name in ('command','script','options'):
            d=self.document();d[name]='anything';self.fault(lambda:adaptor.plan(d),'UNKNOWN_ARGUMENT')
        for source in ('relative.csv','https://example.org/data.csv','/tmp/data.dat'):
            d=self.document();d['source']=source;self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_SOURCE')

    def test_numeric_capture_and_log_endpoint_semantics(self):
        p=self.prepared();data=(ROOT/'examples/schemaxis/fixtures/gnuplot/calibration.csv').read_bytes()
        self.assertEqual(adaptor.table(data,p)[1]['reading'],2)
        for old,new in [(b'time,reading',b'reading,time'),(b'1,2,0.5',b'1,nan,0.5'),(b'1,2,0.5',b'1,2'),(b'1,2,0.5',b'1, 2,0.5'),(b'1,2,0.5',b'1,2,-0.5'),(b'2,3,0.25',b'1,3,0.25')]:
            self.fault(lambda:adaptor.table(data.replace(old,new),p),'INVALID_PLOT_DATA')
        self.fault(lambda:adaptor.table(data.replace(b'2,3,0.25',b'2,5,0.25'),p),'PLOT_DATA_OUTSIDE_RANGE')
        log=self.prepared('logarithmic');self.fault(lambda:adaptor.table((ROOT/'examples/schemaxis/fixtures/gnuplot/log-invalid.csv').read_bytes(),log),'INVALID_LOG_DATA')
        self.assertEqual(len(adaptor.table((ROOT/'examples/schemaxis/fixtures/gnuplot/logarithmic.csv').read_bytes(),log)),3)

    def test_bounded_source_and_byte_reuse_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'data.csv';data=(ROOT/'examples/schemaxis/fixtures/gnuplot/calibration.csv').read_bytes();p.write_bytes(data)
            d=self.document();d['source']=str(p);first=adaptor.reusableInputs(d)
            p.write_bytes(data.replace(b'1,2,0.5',b'1,2.0,0.5'));self.assertNotEqual(first,adaptor.reusableInputs(d))
            link=Path(temp)/'link.csv';link.symlink_to(p);self.fault(lambda:adaptor.bounded(link,'INVALID_PLOT_SOURCE'),'INVALID_PLOT_SOURCE')
            if hasattr(os,'mkfifo'):
                fifo=Path(temp)/'fifo.csv';os.mkfifo(fifo);self.fault(lambda:adaptor.bounded(fifo,'INVALID_PLOT_SOURCE'),'INVALID_PLOT_SOURCE')
            p.write_bytes(b'0'*(1024*1024+1));self.fault(lambda:adaptor.reusableInputs(d),'INVALID_PLOT_SOURCE')

    def test_literal_affine_and_log_oracle(self):
        from schemaxis.adaptors.gnuplot.inspection import coord
        p=self.prepared();self.assertEqual([(round(coord(x,p['xAxis'],800,True),6),round(coord(y,p['yAxis'],600,False),6)) for x,y in [(0,1),(1,2),(2,3)]],[(120,375),(440,270),(760,165)])
        p=self.prepared('logarithmic');self.assertAlmostEqual(coord(10,p['xAxis'],800,True),440)
        self.assertAlmostEqual(coord(100,p['yAxis'],600,False),200)
        self.assertAlmostEqual(coord(80,p['yAxis'],600,False),213.56740182112793)


if __name__=='__main__':unittest.main()
