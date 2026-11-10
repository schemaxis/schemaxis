"""Host contract for GDAL zonalSummary: schema, authored zones, independent oracle, numerics and typed CSV."""
import copy
from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.gdal import adaptor, reference
from schemaxis.core.faults import SchemaxisError
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('gdal_fixtures',ROOT/'tools/qualify_gdal_fixtures.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
Z=lambda i,x,y,w,h:{'id':i,'x':x,'y':y,'width':w,'height':h}
U=Fraction(1,2**53)
f32=lambda v:struct.unpack('<f',struct.pack('<f',v))[0]


def feature(zone,**stats): return {'type':'Feature','properties':{'zone':zone,**stats},'geometry':None}


class GdalZonalTests(unittest.TestCase):
    def setUp(self):
        self.document=json.loads((ROOT/'examples/schemaxis/gdal-zonal.json').read_text())
        self.document['source']=str(ROOT/'examples/schemaxis/fixtures/gdal/elevation.tif')
        self.source=reference.parse(Path(self.document['source']).read_bytes())

    def test_plan_is_typed_immutable_and_closed(self):
        original=copy.deepcopy(self.document);prepared=adaptor._native_plan(self.document);self.assertEqual(original,self.document)
        self.assertEqual(prepared['operation'],'zonalSummary');self.assertEqual(adaptor.query(self.document)[0],['zonalSummary'])
        for key in adaptor.ZONAL_OPTIONS:
            with self.subTest(missing=key),self.assertRaises(SchemaxisError):adaptor._native_plan({k:v for k,v in self.document.items() if k!=key})
        bad=[{'x':1},{'outputWidth':3},{'nativeFlags':['-stat']},{'missing':'zero'},{'epsg':32614},{'zones':[]},{'zones':[Z('a',0,0,1,1)]*2},
             {'zones':[Z('a',True,0,1,1)]},{'zones':[Z('a',0,0,0,1)]},{'zones':[Z('a',-1,0,1,1)]},{'zones':[{**Z('a',0,0,1,1),'polygon':[]}]},
             {'zones':[Z('',0,0,1,1)]},{'zones':[Z('\\N',0,0,1,1)]},{'zones':[Z(' pad',0,0,1,1)]},{'zones':[Z('tab\t',0,0,1,1)]},{'zones':[Z('é',0,0,1,1)]},
             {'zones':[Z('z%d'%i,0,0,1,1) for i in range(17)]},{'zones':[Z('a',0,0,4096,4096)]*2},{'lossPolicy':'permissive'},{'nodata':float('nan')},{'source':'relative.tif'}]
        for change in bad:
            with self.subTest(change=str(change)[:60]),self.assertRaises(SchemaxisError):adaptor._native_plan({**self.document,**change})
        with self.assertRaises(SchemaxisError):adaptor._native_plan({k:v for k,v in self.document.items() if k!='zones'}|{'operation':'window'})

    def test_window_documents_refuse_zonal_keys_and_back(self):
        window=json.loads((ROOT/'examples/schemaxis/gdal-window.json').read_text());window['source']=self.document['source']
        self.assertEqual(adaptor._native_plan(window)['operation'],'window')
        with self.assertRaises(SchemaxisError):adaptor._native_plan({**window,'zones':self.document['zones']})
        with self.assertRaises(SchemaxisError):adaptor._native_plan({**window,'missing':'exclude'})

    def test_schema_is_closed_operation_union(self):
        schema=adaptor.schema();self.assertEqual(len(schema['oneOf']),2);self.assertFalse(schema['additionalProperties'])
        zonal=next(b for b in schema['oneOf'] if b['properties']['operation']['const']=='zonalSummary')
        self.assertEqual(set(zonal['required']),{'version','operation',*adaptor.ZONAL_OPTIONS});self.assertEqual(zonal['properties']['zones']['maxItems'],16)
        self.assertFalse(zonal['properties']['zones']['items']['additionalProperties'])

    def test_literal_oracle_overlap_missing_and_corners(self):
        rows=reference.zonal_expected(self.source,adaptor._native_plan(self.document))
        got=[(r['zone'],r['pixels'],r['valid'],r['minimum'],r['maximum'],r['sum'],r['mean']) for r in rows]
        self.assertEqual(got,[('007',6,5,11,23,80,16),('=1+2',1,0,None,None,None,None),('north',6,6,10,15,75,12.5),('south',12,11,40,55,526,526/11)])
        self.assertEqual(rows[0]['corners'],[[500010,5500000],[500040,5499960]]);self.assertEqual(rows[3]['corners'],[[500000,5499940],[500060,5499900]])
        self.assertEqual(rows[1]['coverage'],0);self.assertEqual(rows[0]['coverage'],5/6)
        # Zones 007 and north overlap on row 0; each is an independent summary.
        self.assertEqual(sum(r['pixels'] for r in rows),25)

    def test_geometry_is_authored_pixel_rectangles(self):
        geo=reference.zones_geojson(self.source,self.document['zones'])
        self.assertEqual(geo['crs']['properties']['name'],'EPSG:3857')
        self.assertEqual(geo['features'][0]['geometry']['coordinates'][0],[[500010,5500000],[500040,5500000],[500040,5499960],[500010,5499960],[500010,5500000]])
        self.assertEqual([f['properties']['zone'] for f in geo['features']],['007','=1+2','north','south'])
        wrong=copy.deepcopy(geo);wrong['features'][0]['geometry']['coordinates'][0][1][0]+=10
        self.assertNotEqual(wrong,reference.zones_geojson(self.source,self.document['zones']))

    def test_refusals_carry_stable_codes_and_locations(self):
        def code(change):
            with self.assertRaises(reference.ZoneError) as caught:reference.zonal_expected(self.source,adaptor._native_plan({**self.document,**change}))
            return caught.exception.code,caught.exception.index
        self.assertEqual(code({'zones':[Z('a',0,0,1,1),Z('b',5,4,2,1)]}),('INVALID_ZONE',1))
        self.assertEqual(code({'zones':[Z('a',0,0,1,1),Z('b',0,5,1,1)]}),('INVALID_ZONE',1))
        self.assertEqual(code({'missing':'refuse'}),('ZONE_MISSING_VALUES',0))
        with self.assertRaises(ValueError):reference.zonal_expected(self.source,adaptor._native_plan({**self.document,'epsg':4326}))
        with self.assertRaises(ValueError):reference.zonal_expected(self.source,adaptor._native_plan({**self.document,'units':'K'}))
        with self.assertRaises(ValueError):reference.zonal_expected(self.source,adaptor._native_plan({**self.document,'nodata':0}))

    def oracle(self,pixels,zone=Z('a',0,0,2,1),dtype='Float32',nodata=-9999,missing='exclude',width=2,height=1,**kw):
        raster=reference.parse(fixtures.tiff(pixels,width=width,height=height,dtype=dtype,nodata=nodata,units='1',**kw))
        return reference.zonal_expected(raster,{'epsg':3857,'units':'1','nodata':nodata,'zones':[zone],'missing':missing})[0]

    def test_numeric_edge_values_are_exact(self):
        tiny=struct.unpack('<f',struct.pack('<f',1e-45))[0];huge=struct.unpack('<f',b'\xff\xff\x7f\x7f')[0]
        row=self.oracle([tiny,tiny]);self.assertEqual((row['minimum'],row['maximum'],row['sum']),(tiny,tiny,2*tiny));self.assertGreater(row['sum'],0)
        row=self.oracle([huge,huge]);self.assertEqual(row['sum'],2*huge);self.assertEqual(row['mean'],huge)
        row=self.oracle([-0.0,0.0]);self.assertEqual(row['sum'],0);self.assertEqual(row['sumAllowance'],0);self.assertEqual(row['meanAllowance'],0)
        row=self.oracle([-2.5,4.0]);self.assertEqual(row['sum'],1.5)

    def test_cancellation_is_refused_not_hidden(self):
        for pixels in ([1.0,-1.0],[3e30,-3e30]):
            with self.subTest(pixels=pixels):
                with self.assertRaises(reference.ZoneError) as caught:self.oracle(pixels)
                self.assertEqual(caught.exception.code,'ZONE_SUM_UNRESOLVABLE')
        # Large but resolvable: the exact sum 1 lies far above the roundoff bound.
        self.assertEqual(self.oracle([16777216.0,-16777215.0])['sum'],1)

    def test_allowance_is_derived_from_the_exact_sum_never_from_the_origin(self):
        self.assertEqual(reference.summation_allowance(1,Fraction(5)),0);self.assertEqual(reference.summation_allowance(0,0),0)
        self.assertLess(reference.summation_allowance(4096,Fraction(1,10**30)),Fraction(1,10**40));self.assertGreater(reference.summation_allowance(4,Fraction(100)),0)
        row=self.oracle([0.5,0.25,0.125],zone=Z('a',0,0,3,1),width=3);gamma=2*U/(1-2*U)
        self.assertEqual(row['exactSum'],Fraction(7,8));self.assertEqual(row['sumAllowance'],gamma*Fraction(7,8))
        self.assertEqual(row['meanAllowance'],(gamma*Fraction(7,8)*(1+U)+U*Fraction(7,8))/3)
        # Host rounding is accounted exactly: the target is the real-number sum, not the correctly rounded fsum that is published.
        row=self.oracle([1.0,2.0**-60]);self.assertEqual(row['sum'],1.0);self.assertEqual(row['exactSum'],1+Fraction(1,2**60))
        row=self.oracle([1e-30,2e-30]);native=[feature('a',count=2.0,min=1e-30,max=2e-30,sum=0.0,mean=0.0)]
        with self.assertRaises(ValueError):reference.compare_zonal([row],reference.normalise_native_zones(native,['a']))
        good=[feature('a',count=2.0,min=row['minimum'],max=row['maximum'],sum=row['sum'],mean=row['mean'])]
        reference.compare_zonal([row],reference.normalise_native_zones(good,['a']))

    def test_published_values_stay_within_their_derived_rounding_limits(self):
        """Published sum is fsum (within u of the exact sum) and mean is fsum/n in double (within 2u+u^2): the host's own rounding is bounded, not ignored."""
        for pixels in ([f32(0.1),f32(0.2),f32(0.3),f32(-0.05),7.0],[16777216.0,-16777215.0,0.5,3.0,5.0],[f32(1e-3)]*5):
            row=self.oracle(pixels,zone=Z('a',0,0,5,1),width=5);exact=row['exactSum']
            with self.subTest(pixels=pixels):
                self.assertLessEqual(abs(Fraction(row['sum'])-exact),U*abs(exact))
                self.assertLessEqual(abs(Fraction(row['mean'])-exact/5),(2*U+U*U)*abs(exact/5))

    def test_unresolvable_partial_cancellation_is_refused_before_native_work(self):
        """Float32 [1e19,-1e19,1e4]: the old bound was 44 % of the sum, so native sums scaled by 0.6 or 0.9 passed; the 2**-26 ceiling refuses the zone."""
        big=f32(1e19);zone=Z('a',0,0,3,1)
        self.assertEqual(reference.RESOLUTION,Fraction(1,2**26))
        with self.assertRaises(reference.ZoneError) as caught:self.oracle([big,-big,1e4],zone=zone,width=3)
        self.assertEqual((caught.exception.code,caught.exception.index),('ZONE_SUM_UNRESOLVABLE',0))
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'partial.tif';source.write_bytes(fixtures.tiff([big,-big,1e4]+[1.0]*27,dtype='Float32',units='1'))
            document={**self.document,'source':str(source),'units':'1','nodata':-9999,'zones':[Z('a',0,0,3,1)]}
            with patch.object(adaptor,'execute',side_effect=AssertionError('native process must not start')) as native:
                with self.assertRaises(SchemaxisError) as refused:adaptor.run(document,Path(temporary)/'run',executable=sys.executable,timeout=30)
            native.assert_not_called()
            fault=refused.exception.fault.to_dict();self.assertEqual((fault['code'],fault['location']),('ZONE_SUM_UNRESOLVABLE','$.zones[0]'))
            self.assertEqual(json.loads((Path(temporary)/'run/result.json').read_text())['status'],'failed')

    def test_ordinary_mixed_sign_zone_near_the_boundary_is_accepted_and_small_tampering_refused(self):
        """Float32 [16777216,-16777215,0.5] (exact sum 1.5, allowance about 7.45e-9) is resolvable; consistency, not science: decisive deviations are refused."""
        row=self.oracle([16777216.0,-16777215.0,0.5],zone=Z('a',0,0,3,1),width=3);ids=['a']
        self.assertEqual((row['sum'],row['mean']),(1.5,0.5));self.assertLess(row['sumAllowance']/row['exactSum'],reference.RESOLUTION)
        def native(total,mean):return reference.normalise_native_zones([feature('a',count=3.0,min=-16777215.0,max=16777216.0,sum=total,mean=mean)],ids)
        reference.compare_zonal([row],native(1.5,0.5));reference.compare_zonal([row],native(1.5+7e-9,0.5));reference.compare_zonal([row],native(1.5-7e-9,0.5))
        reference.compare_zonal([row],native(1.5,0.5+2e-9))
        for total,mean in ((1.5+8e-9,0.5),(1.5-8e-9,0.5),(1.5*0.9,0.5),(1.5*0.6,0.5),(1.5*(1+1e-6),0.5),(0.0,0.5),(1.5,0.5+3e-9),(1.5,0.5*0.9),(1.5,0.5*(1+1e-6)),(1.5,0.0)):
            with self.subTest(total=total,mean=mean),self.assertRaises(ValueError):reference.compare_zonal([row],native(total,mean))

    def test_signed_zero_is_published_as_zero_only_for_zonal_numbers(self):
        for pixels in ([-0.0,0.0],[0.0,-0.0],[-0.0,-0.0]):
            row=self.oracle(pixels)
            with self.subTest(pixels=pixels):
                for key in ('minimum','maximum','sum','mean'):
                    self.assertEqual(row[key],0);self.assertEqual(math.copysign(1,row[key]),1,key)
                line=reference.csv_text([{**row,'zone':'a'}]).splitlines()[1]
                self.assertEqual(line,'"a",2,0,1,0,0,0,0')
                raster=reference.parse(fixtures.tiff(pixels,width=2,height=1,dtype='Float32',nodata=-9999,units='1'))
                plan={'epsg':3857,'units':'1','nodata':-9999,'zones':[Z('a',0,0,2,1)],'missing':'exclude'}
                self.assertNotIn('-0',json.dumps(reference.zonal_report(raster,plan,[row])))
        self.assertEqual(reference.decimal(-0.0),'0')

    def test_native_forgeries_fail_the_independent_oracle(self):
        rows=reference.zonal_expected(self.source,adaptor._native_plan(self.document));ids=[r['zone'] for r in rows]
        def native(**patch):
            features=[feature('007',count=5.0,min=11.0,max=23.0,sum=80.0,mean=16.0),feature('=1+2',count=0.0,sum=0.0),feature('north',count=6.0,min=10.0,max=15.0,sum=75.0,mean=12.5),feature('south',count=11.0,min=40.0,max=55.0,sum=526.0,mean=526/11)]
            for key,value in patch.items():
                index,field=key.split('_');features[int(index)]['properties'][field]=value
            return features
        reference.compare_zonal(rows,reference.normalise_native_zones(native(),ids))
        for patch in ({'0_count':6.0},{'0_min':10.0},{'0_max':24.0},{'0_sum':81.0},{'0_mean':16.5},{'2_sum':75.0000001},{'3_count':12.0},{'0_sum':0.0}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):reference.compare_zonal(rows,reference.normalise_native_zones(native(**patch),ids))
        for patch in ({'0_count':5.5},{'0_count':True},{'0_sum':True},{'0_mean':float('inf')},{'0_zone':'x'},{'1_sum':1.0},{'1_count':1.0}):
            with self.subTest(patch=patch),self.assertRaises(ValueError):reference.normalise_native_zones(native(**patch),ids)
        with self.assertRaises(ValueError):reference.normalise_native_zones(native()[::-1],ids)
        with self.assertRaises(ValueError):reference.normalise_native_zones(native()[:3],ids)
        invented=native();invented[1]['properties'].update(min=0.0,max=0.0,mean=0.0)
        with self.assertRaises(ValueError):reference.normalise_native_zones(invented,ids)
        zeroed=reference.normalise_native_zones(native(),ids)
        zeroed[1]['sum']=0.0
        with self.assertRaises(ValueError):reference.compare_zonal(rows,zeroed)

    def test_typed_csv_is_fixed_and_literal(self):
        rows=reference.zonal_expected(self.source,adaptor._native_plan(self.document))
        lines=reference.csv_text(rows).splitlines()
        self.assertEqual(lines[0],'"zone","valid","missing","coverage","minimum","maximum","sum","mean"')
        self.assertEqual(lines[1],'"007",5,1,0.8333333333333334,11,23,80,16')
        self.assertEqual(lines[2],'"=1+2",0,1,0,\\N,\\N,\\N,\\N')
        self.assertEqual(lines[3].split(',')[-4:],['10','15','75','12.5'])
        self.assertEqual([c[0] for c in reference.CSV_COLUMNS],['zone','valid','missing','coverage','minimum','maximum','sum','mean'])
        self.assertEqual([reference.decimal(v) for v in (1e-7,1.5e300,-0.0,2.0,0.1)],['1e-7','1.5e300','0','2','0.1'])
        report=reference.zonal_report(self.source,adaptor._native_plan(self.document),rows)
        self.assertEqual(report['units'],'m');self.assertEqual(report['zones'][1]['minimum'],None);self.assertEqual(report['pixelVisits'],25)

    def test_published_edit_cases_agree_with_the_stdlib_oracle(self):
        """The hand-stated development-case literals (edited through the shared closed patch grammar) match an exhaustive host pixel visit."""
        from schemaxis.adaptor_delivery import case_document
        entry=json.loads((ROOT/'src/schemaxis/adaptors/gdal/readiness.json').read_text())['routes']['schemaxis.gdal/1']
        cases={c['id']:c for c in entry['development']['cases']}
        self.assertTrue({'zonal','zonal-taller-north','zonal-added-east','zonal-geographic'}<=set(cases))
        self.assertTrue(cases['zonal-taller-north']['edits'] and cases['zonal-added-east']['edits'])
        for name in ('zonal','zonal-taller-north','zonal-added-east','zonal-geographic'):
            case=cases[name]
            document=case_document({'examples':entry['examples']},case,ROOT)
            source=reference.parse(Path(document['source']).read_bytes())
            rows=reference.zonal_expected(source,adaptor._native_plan(document))
            report=reference.zonal_report(source,adaptor._native_plan(document),rows)
            for check in case['checks']:
                value=report
                for part in check['pointer'].strip('/').split('/'):value=value[int(part)] if isinstance(value,list) else value[part]
                with self.subTest(case=name,pointer=check['pointer']):
                    if isinstance(check['expected'],(int,float)):self.assertAlmostEqual(value,check['expected'],delta=abs(check['expected'])*check.get('relative',0)+check.get('absolute',0))
                    else:self.assertEqual(value,check['expected'])

    def test_declarations_publications_and_losses(self):
        self.assertEqual(set(adaptor.DECLARATIONS),{'window','zonalSummary'})
        self.assertEqual(adaptor.ZONAL_PUBLICATIONS,(('zones-summary.csv','table'),('zones-summary.json','text')))
        text=' '.join(adaptor.ZONAL_LOSSES)
        for phrase in ('overlapping zones','not an area integral','EPSG:4326 angular','native zero sum is normalised to null','cancellation','2**-26','consistency threshold','not a scientific accuracy claim'):
            self.assertIn(phrase,text)
        docs=(ROOT/'docs/gdal.md').read_text()
        for phrase in ('2⁻²⁶','eight zones that each cover a full source','a ninth exceeds it','consistency threshold'):
            self.assertIn(phrase,docs)
        self.assertNotIn('4096-pixel source',docs)


if __name__=='__main__':unittest.main()
