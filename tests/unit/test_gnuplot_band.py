"""Asserted lower/upper range envelope: declaration, data, script and independent verifier.

Verifier mutations use a retained native Gnuplot 6.0.5 SVG/PNG pair
(examples/schemaxis/fixtures/gnuplot/band-native.*) with literal expectations, so
no native process is needed here. Native execution is qualified separately.
"""
import copy
import json
from pathlib import Path
import re
import struct
import unittest
import zlib

from schemaxis.adaptors import registry
from schemaxis.adaptors.gnuplot import adaptor
from schemaxis.adaptors.gnuplot import inspection
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[2]
FIXTURES=ROOT/'examples/schemaxis/fixtures/gnuplot'
POLYGON_LINE="<polygon fill = 'rgb(214,  39,  40)' fill-opacity = '0.200000' points = '120.00,410.00 440.00,256.01 759.98,340.00 759.98,200.01 440.00,130.01 120.00,270.00 '/>"


def document(name='band'): return json.loads((ROOT/f'examples/schemaxis/gnuplot-{name}.json').read_text())


def png(width,height,image):
    def chunk(kind,body): return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body))
    raw=b''.join(b'\0'+bytes(v for pixel in row for v in pixel) for row in image)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


class RangeEnvelope(unittest.TestCase):
    def fault(self,action,code,message=None,location=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        fault=caught.exception.fault;self.assertEqual(fault.code,code)
        if message is not None: self.assertIn(message,fault.message)
        if location is not None: self.assertEqual(fault.location,location)
        return fault

    def rows(self,name='band'):
        p=adaptor.plan(document());return p,adaptor.table((FIXTURES/(name+'.csv')).read_bytes(),p)

    def test_declaration_schema_and_artifact_kinds(self):
        p=adaptor.plan(document())
        self.assertEqual(p['series'][0]['bounds'],{'lower':'lower','upper':'upper'})
        self.assertEqual(len(p['losses']),6);self.assertIn('ASSERTED',p['losses'][-1])
        self.assertEqual(len(adaptor.plan(document('calibration'))['losses']),5)
        bounds=adaptor.schema()['properties']['series']['items']['properties']['bounds']
        self.assertEqual(sorted(bounds['properties']),['lower','upper'])
        route=registry.resolve(document(),legacy=True)[1];self.assertEqual(route['acceptedArtifacts'],['table','file'])

    def test_plan_refusals_with_exact_locations(self):
        d=document();d['series'][0]['error']='lower'
        self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_BOUNDS','either a symmetric error or an asserted','$.series[0].bounds')
        d=document();d['yAxis']['scale']='log10';d['yAxis']['range']=[.1,3]
        self.fault(lambda:adaptor.plan(d),'PLOT_BOUNDS_UNSUPPORTED','linear axes only','$.yAxis.scale')
        d=document();d['xAxis']['scale']='log10';d['xAxis']['range']=[.1,2]
        self.fault(lambda:adaptor.plan(d),'PLOT_BOUNDS_UNSUPPORTED','linear axes only','$.xAxis.scale')
        d=document();d['series'].append({'label':'Other','x':'time','y':'mean','colour':'blue'})
        self.fault(lambda:adaptor.plan(d),'PLOT_BOUNDS_UNSUPPORTED','only series','$.series[0].bounds')
        d=document();d['series'][0]['bounds']['upper']='lower'
        self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_BOUNDS','three distinct','$.series[0].bounds')
        d=document();d['series'][0]['bounds']['lower']='mean'
        self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_BOUNDS','three distinct','$.series[0].bounds')
        d=document();d['series'][0]['bounds']['lower']='missing'
        self.fault(lambda:adaptor.plan(d),'INVALID_PLOT_COLUMNS','declared column','$.series[0].bounds.lower')
        d=document();d['columns'][3]['unit']='mV'
        self.fault(lambda:adaptor.plan(d),'PLOT_UNIT_MISMATCH','y-axis unit','$.series[0].bounds.upper')
        d=document();d['series'][0]['bounds']['extra']='lower'
        self.fault(lambda:adaptor.plan(d),'UNKNOWN_ARGUMENT')
        d=document();d['series'][0]['bounds']={'lower':'lower'}
        self.fault(lambda:adaptor.plan(d),'MISSING_ARGUMENT')

    def test_data_refusals_before_native_with_precise_rows(self):
        p=adaptor.plan(document())
        read=lambda n:(FIXTURES/n).read_bytes()
        self.assertEqual(len(adaptor.table(read('band.csv'),p)),3)
        self.assertEqual(len(adaptor.table(read('band-variant.csv'),p)),3)
        self.fault(lambda:adaptor.table(read('band-lower-above-invalid.csv'),p),'INVALID_PLOT_BOUNDS','lower <= representative <= upper','$.series[0].bounds row 3')
        self.fault(lambda:adaptor.table(read('band-reversed-invalid.csv'),p),'INVALID_PLOT_BOUNDS','lower <= representative <= upper','$.series[0].bounds row 2')
        self.fault(lambda:adaptor.table(read('band-outside-invalid.csv'),p),'PLOT_DATA_OUTSIDE_RANGE','every lower and upper bound','$.series[0].bounds row 3')
        thin=self.fault(lambda:adaptor.table(read('band-thin-invalid.csv'),p),'PLOT_BAND_UNVERIFIABLE','row 3 envelope is 22.4 pixels tall','$.series[0].bounds')
        self.assertIn('at least 24 are required',thin.message)
        self.fault(lambda:adaptor.table(read('band-null-invalid.csv'),p),'INVALID_PLOT_DATA','rectangular finite numeric cells','$.source')
        self.fault(lambda:adaptor.table(read('band-header-invalid.csv'),p),'INVALID_PLOT_DATA','header must exactly match','$.source')
        self.fault(lambda:adaptor.table(read('band-order-invalid.csv'),p),'INVALID_PLOT_DATA','x samples must increase strictly','$.series[0].x row 4')
        self.fault(lambda:adaptor.table(b'\x00\x01\xff\xfe',p),'INVALID_PLOT_DATA')
        equal=read('band.csv').replace(b'1,2,1.6,2.5',b'1,2,2,2')
        self.fault(lambda:adaptor.table(equal,p),'INVALID_PLOT_BOUNDS','lower < upper','$.series[0].bounds row 3')

    def test_script_is_fixed_native_three_column_filledcurves(self):
        script=adaptor.script(adaptor.plan(document()))
        self.assertIn("set style fill transparent solid 0.2 noborder\n",script)
        self.assertIn("plot 'captured.csv' every ::1 using 1:3:4 with filledcurves lc rgb '#d62728' title 'Mean range', 'captured.csv' every ::1 using 1:2 with linespoints lw 2 pt 7 ps 0.7 lc rgb '#d62728' title 'Mean'\n",script)
        # Legacy scripts are unchanged: no fill style and no filledcurves.
        legacy=adaptor.script(adaptor.plan(document('calibration')))
        self.assertNotIn('filledcurves',legacy);self.assertNotIn('style fill',legacy)

    def test_independent_literal_polygon_and_probe_oracle(self):
        p,rows=self.rows()
        vertices=inspection.band_geometry(p,p['series'][0],rows)
        self.assertEqual([[round(v,6) for v in x] for x in vertices],[[120,270,410,340],[440,130,256,200],[760,200,340,270]])
        self.assertEqual([(round(x,6),round(y,6)) for x,y in inspection.band_polygon(vertices)],[(120,410),(440,256),(760,340),(760,200),(440,130),(120,270)])
        probes=inspection.band_samples(p,p['series'][0],rows)
        self.assertEqual((len(probes['interior']),len(probes['exterior'])),(5,5))
        for x,y in probes['interior']:
            self.assertTrue(120<x<760 and 100<y<430)
        # Changed non-adjacent bounds move the polygon, not just the markers.
        q,variant=self.rows('band-variant');moved=inspection.band_polygon(inspection.band_geometry(q,q['series'][0],variant))
        self.assertEqual([(round(x,6),round(y,6)) for x,y in moved],[(120,452),(440,256),(760,340),(760,116),(440,130),(120,270)])

    def inspect(self,svg=None,image=None,p=None,rows=None):
        base,table=self.rows()
        return inspection.inspect_plot(svg if svg is not None else (FIXTURES/'band-native.svg').read_bytes(),
            image if image is not None else (FIXTURES/'band-native.png').read_bytes(),p or base,rows or table)

    def refused(self,message,**kw):
        with self.assertRaises(SchemaxisError) as caught: self.inspect(**kw)
        self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED');self.assertEqual(caught.exception.fault.message,message)

    def test_native_pair_verifies_with_independent_summary(self):
        summary=self.inspect();band=summary['geometry'][0]['band']
        self.assertEqual(band['polygon'],[[120,410],[440,256],[760,340],[760,200],[440,130],[120,270]])
        self.assertEqual((band['opacity'],band['interiorProbes'],band['exteriorProbes']),(.2,5,5))

    def svg(self): return (FIXTURES/'band-native.svg').read_text()

    def test_svg_mutations_fail_with_exact_causes(self):
        text=self.svg();self.assertIn(POLYGON_LINE,text)
        def mutate(old,new,count=1):
            self.assertIn(old,text);return text.replace(old,new,count).encode()
        def polygon(old,new):
            self.assertIn(old,POLYGON_LINE);return text.replace(POLYGON_LINE,POLYGON_LINE.replace(old,new)).encode()
        self.refused('SVG envelope polygon vertex 1 differs',svg=polygon('440.00,256.01','440.00,250.01'))
        self.refused('SVG envelope polygon vertex 3 differs',svg=polygon('759.98,200.01','759.98,190.01'))
        self.refused('SVG envelope polygon vertex 5 differs',svg=polygon('120.00,270.00 ','120.00,300.00 '))
        self.refused('SVG envelope polygon membership differs',svg=text.replace(POLYGON_LINE,'').encode())
        self.refused('SVG envelope polygon membership differs',svg=text.replace(POLYGON_LINE,POLYGON_LINE+POLYGON_LINE).encode())
        self.refused('SVG envelope polygon vertex count differs',svg=polygon('120.00,270.00 \'/>','120.00,270.00 120.00,271.00 \'/>'))
        self.refused('SVG polygon paint/opacity/attributes differ',svg=mutate("fill-opacity = '0.200000' points = '120","fill-opacity = '0.500000' points = '120"))
        self.refused('SVG polygon paint/opacity/attributes differ',svg=mutate("fill-opacity = '0.200000' points = '120","fill-opacity = '0.000000' points = '120"))
        self.refused('SVG envelope colour differs',svg=mutate("fill = 'rgb(214,  39,  40)' fill-opacity = '0.200000' points = '120","fill = 'rgb( 31, 119, 180)' fill-opacity = '0.200000' points = '120"))
        self.refused('SVG envelope legend swatch differs',svg=mutate('389.04,586.50 431.60,586.50 431.60,577.50 389.04,577.50','389.04,586.50 431.60,586.50 431.60,586.50 389.04,586.50'))
        self.refused('SVG envelope legend label differs',svg=mutate('<text>Mean range</text>','<text>Mean</text>'))
        self.refused('SVG declared line/error segment differs',svg=mutate('L440.00,200.01','L440.00,220.01'))
        self.refused('SVG sample coordinates differ',svg=mutate('translate(440.00,200.01)','translate(440.00,210.01)'))
        self.refused('SVG x-axis label differs',svg=mutate('Time (s)','Time (m)'))
        self.refused('SVG polygon paint/opacity/attributes differ',svg=mutate("<polygon fill","<polygon stroke = 'black' fill"))
        self.refused('SVG fill group paint/attributes differ',svg=mutate("<g stroke='none' shape-rendering='crispEdges'>","<g stroke='none' shape-rendering='crispEdges' opacity='0'>"))

    def test_every_polygon_must_be_in_the_envelope_group(self):
        text=self.svg()
        paint='<g fill="none" color="black" stroke="currentColor" stroke-width="1.00" stroke-linecap="butt" stroke-linejoin="miter">\n\t<g stroke=\'none\' shape-rendering=\'crispEdges\'>\n\t\t<polygon fill = \'%s\' fill-opacity = \'0.200000\' points = \'%s\'/>\n\t</g>\n</g>\n'
        red,blue='rgb(214,  39,  40)','rgb( 31, 119, 180)'
        box='130.00,470.00 750.00,470.00 750.00,70.00 130.00,70.00 ';triangle='130.00,470.00 750.00,470.00 440.00,70.00 '
        anchor='\t<g id="gnuplot_plot_2"  fill="none"><title>gnuplot_plot_2</title>\n'
        self.assertEqual(text.count(anchor),1)
        # Review mutants: a nearly plot-sized filled polygon inside the central-curve group.
        self.refused('SVG fill group outside the envelope group',svg=text.replace(anchor,anchor+paint%(red,box)).encode())
        self.refused('SVG fill group outside the envelope group',svg=text.replace(anchor,anchor+paint%(blue,triangle)).encode())
        self.refused('SVG fill group outside the envelope group',svg=text.replace(anchor,anchor+paint%('rgb( 44, 160,  44)',box)).encode())
        # At canvas level, nested in the fill group, or as a third polygon in the envelope group.
        self.refused('SVG fill group paint/attributes differ',svg=text.replace(anchor,paint%(red,box)+anchor).encode())
        nest="\t<g stroke='none' shape-rendering='crispEdges'>\n"
        self.refused('SVG fill group paint/attributes differ',svg=text.replace(nest,nest+nest+"\t\t<polygon fill = '%s' fill-opacity = '0.200000' points = '%s'/>\n\t</g>\n"%(red,box),1).encode())
        extra="<polygon fill = '%s' fill-opacity = '0.200000' points = '%s'/>\n"%(blue,triangle)
        self.refused('SVG envelope polygon membership differs',svg=text.replace(POLYGON_LINE,POLYGON_LINE+'\n\t\t'+extra,1).encode())

    def test_legend_swatch_is_the_native_sample_box_at_its_label(self):
        text=self.svg();swatch='389.04,586.50 431.60,586.50 431.60,577.50 389.04,577.50'
        self.assertIn(swatch,text)
        for name,points in [('full width','10.00,599.00 790.00,599.00 790.00,541.00 10.00,541.00'),('shifted','300.00,586.50 342.56,586.50 342.56,577.50 300.00,577.50'),
                ('taller','389.04,586.50 431.60,586.50 431.60,520.50 389.04,520.50'),('narrower','389.04,586.50 400.00,586.50 400.00,577.50 389.04,577.50'),
                ('reversed order','389.04,577.50 431.60,577.50 431.60,586.50 389.04,586.50')]:
            with self.subTest(name): self.refused('SVG envelope legend swatch differs',svg=text.replace(swatch,points).encode())

    def test_probes_avoid_tick_bearing_borders_and_admit_the_review_data(self):
        p=adaptor.plan(document());rows=adaptor.table((FIXTURES/'band-tick-window.csv').read_bytes(),p)
        probes=inspection.band_samples(p,p['series'][0],rows);w,h=p['width'],p['height']
        clear=inspection.BORDER_CLEARANCE
        for x,y in probes['interior']+probes['exterior']:
            self.assertTrue(w*.15+clear<=x<=w*.95-clear and h*.1+clear<=y<=h*.8-clear,(x,y))
        self.assertGreaterEqual(len(probes['exterior']),1)
        # Retained native pair for this data: the formerly selected exterior pixel is a black tick mark.
        width,height,image=inspection.pixels((FIXTURES/'band-tick-window-native.png').read_bytes())
        self.assertEqual(image[65][440],(0,0,0))
        summary=inspection.inspect_plot((FIXTURES/'band-tick-window-native.svg').read_bytes(),(FIXTURES/'band-tick-window-native.png').read_bytes(),p,rows)
        self.assertEqual(summary['geometry'][0]['band']['polygon'],[[120,410],[440,256],[760,340],[760,200],[440,71.2],[120,270]])
        # Literal independent expectations: inside the fill, and outside it and away from every tick.
        for x,y in [(440,160),(200,330),(600,200)]: self.assertTrue(all(abs(a-b)<=3 for a,b in zip(image[y][x],(247,212,212))),(x,y,image[y][x]))
        for x,y in [(440,300),(200,440),(600,100)]: self.assertEqual(image[y][x],(255,255,255),(x,y))

    def test_no_exterior_pixel_clear_of_ticks_is_refused_before_native(self):
        p=adaptor.plan(document())
        fault=self.fault(lambda:adaptor.table((FIXTURES/'band-border-ticks-invalid.csv').read_bytes(),p),'PLOT_BAND_UNVERIFIABLE','no exterior pixel clear of the envelope','$.series[0].bounds')
        self.assertIn('tick-bearing borders',fault.message)
        # End segments shorter than twice the end probe distance cannot place a clear end probe.
        p=adaptor.plan(document());rows=b'time,mean,lower,upper\n0,1,.5,1.5\n.05,2,1.6,2.5\n2,1.5,1,2\n'
        self.fault(lambda:adaptor.table(rows,p),'PLOT_BAND_UNVERIFIABLE','first and last at least 26')

    def test_changed_bounds_and_central_values_govern_geometry(self):
        q,variant=self.rows('band-variant')
        with self.assertRaises(SchemaxisError) as caught: self.inspect(p=q,rows=variant)
        self.assertEqual(caught.exception.fault.message,'SVG envelope polygon vertex 0 differs')
        # Changing only a non-adjacent upper bound (row 3) is also detected.
        p,rows=self.rows();rows=copy.deepcopy(rows);rows[2]['upper']=2.4
        with self.assertRaises(SchemaxisError) as caught: self.inspect(rows=rows)
        self.assertEqual(caught.exception.fault.message,'SVG envelope polygon vertex 3 differs')
        p,rows=self.rows();rows=copy.deepcopy(rows);rows[1]['lower']=1.5
        with self.assertRaises(SchemaxisError) as caught: self.inspect(rows=rows)
        self.assertEqual(caught.exception.fault.message,'SVG envelope polygon vertex 1 differs')
        p,rows=self.rows();rows=copy.deepcopy(rows);rows[1]['mean']=2.2
        with self.assertRaises(SchemaxisError) as caught: self.inspect(rows=rows)
        self.assertEqual(caught.exception.fault.message,'SVG sample coordinates differ')

    def pixels(self):
        width,height,image=inspection.pixels((FIXTURES/'band-native.png').read_bytes());return width,height,[list(r) for r in image]

    def test_png_fill_and_exterior_checks_are_independent_of_markers(self):
        width,height,image=self.pixels()
        want=(247,212,212)
        near=lambda c:all(abs(a-b)<=3 for a,b in zip(c,want))
        def repaint(rows,predicate,colour):
            out=copy.deepcopy(image)
            for y in rows:
                for x in range(width):
                    if predicate(x,y): out[y][x]=colour
            return out
        # Remove only the fill right of x=600; markers and lines stay intact.
        gone=repaint(range(height),lambda x,y:x>560 and near(image[y][x]),(255,255,255))
        with self.assertRaises(SchemaxisError) as caught: self.inspect(image=png(width,height,gone))
        self.assertTrue(caught.exception.fault.message.startswith('PNG envelope interior pixel differs at '),caught.exception.fault.message)
        # Remove fill only in the left half.
        left=repaint(range(height),lambda x,y:x<300 and near(image[y][x]),(255,255,255))
        with self.assertRaises(SchemaxisError) as caught: self.inspect(image=png(width,height,left))
        self.assertTrue(caught.exception.fault.message.startswith('PNG envelope interior pixel differs at '))
        # Fill the exterior above the band.
        above=repaint(range(70,125),lambda x,y:130<x<750 and image[y][x]==(255,255,255),(247,212,212))
        with self.assertRaises(SchemaxisError) as caught: self.inspect(image=png(width,height,above))
        self.assertTrue(caught.exception.fault.message.startswith('PNG envelope exterior pixel differs at '))
        # The unmodified decode round-trips through the same encoder.
        self.assertTrue(self.inspect(image=png(width,height,image))['geometry'][0]['band'])


if __name__=='__main__':unittest.main()
