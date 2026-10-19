#!/usr/bin/env python3
"""Gnuplot four-case geometry, hostile evidence, lifecycle and source reuse."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zlib

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptor_delivery import case_document,route_materials
from schemaxis.adaptors.gnuplot import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow

ROOT=Path(__file__).resolve().parents[1]
SVG='{http://www.w3.org/2000/svg}'


def refused(action,code='VERIFICATION_FAILED'):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('invalid plot/evidence accepted')


def refresh(directory):
    """Ordinary hashes are insufficient: independent semantic checks must refuse."""
    receipt=adaptor.read(directory,'verification.json')
    receipt['artifacts']=adaptor.artifacts(directory)
    receipt['evidence']={n:adaptor.digest(directory,n) for n in receipt['evidence']}
    atomic_json(directory/'verification.json',receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def literal(directory,expected,uncertainty):
    """Directly observe native SVG coordinates against reviewed literal fixtures."""
    root=ET.fromstring((directory/'plot.svg').read_bytes());group=next(g for g in root.iter(SVG+'g') if g.get('id')=='gnuplot_plot_1')
    points=[];path=''
    for node in group.iter():
        if node.tag==SVG+'use' and node.get('color')=='rgb(214,  39,  40)':
            match=re.match(r'translate\(([-0-9.]+),([-0-9.]+)\)',node.get('transform',''))
            x,y=map(float,match.groups())
            if y<=480.1:points.append([x,y])
        if node.tag==SVG+'path' and node.get('stroke')=='rgb(214,  39,  40)': path+=node.get('d','')
    assert len(points)==len(expected),(points,expected)
    assert all(abs(a-b)<=.06 for actual,wanted in zip(points,expected) for a,b in zip(actual,wanted)),(points,expected)
    tokens=[(op,float(x),float(y)) for op,x,y in re.findall(r'([ML])\s*([-0-9.]+),([-0-9.]+)',path)]
    for x,lo,hi in uncertainty:
        assert any(b[0]=='L' and max(abs(a[1]-x),abs(a[2]-lo),abs(b[1]-x),abs(b[2]-hi))<=.06 for a,b in zip(tokens,tokens[1:])),(x,lo,hi,path)
    from schemaxis.adaptors.gnuplot.inspection import pixels
    width,height,image=pixels((directory/'plot.png').read_bytes());assert (width,height)==(800,600)
    # These sample-centre pixels are literal independent observations, separate
    # from host-authored plot-summary.json and the producer's numeric mappings.
    for x,y in expected:
        assert any(image[yy][xx]==(214,39,40) for yy in range(round(y)-2,round(y)+3) for xx in range(round(x)-2,round(x)+3)),(x,y)
    return {'nativeSVGPoints':points,'literalExpected':expected,'literalErrorEndpoints':uncertainty,'pngDimensions':[width,height],'pngLiteralSampleColours':True}


def white_png(width,height):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff'*(width*3))*height))+chunk(b'IEND',b'')


def negative(directory):
    report={};saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    def restore():
        for path,data in saved.items():path.write_bytes(data)
    mutations=[('svgBlackInteriorOverlay','plot.svg',lambda b:b.replace(b"stroke='black'  d='M120.00,480.00 L129.00,480.00",b"stroke='black'  d='M200,200 L500,400",1)),
        ('svgRemovedNumericTicks','plot.svg',lambda b:re.sub(rb'<g transform="translate\([^"\n]+\)"[^>]+>\s*<text>[0-9.eE+ -]+</text>\s*</g>',b'',b)),
('svgTickMeaning','plot.svg',lambda b:b.replace(b'<text>2</text>',b'<text>99</text>',1)),
        ('svgFilterOverride','plot.svg',lambda b:b.replace(b'id="gnuplot_plot_1"',b'id="gnuplot_plot_1" filter="url(#textbox)"',1)),
        ('svgSeriesWrongColour','plot.svg',lambda b:b.replace(b"stroke='rgb(214,  39,  40)'",b"stroke='rgb( 31, 119, 180)'",1)),
('svgStrokeOpacity','plot.svg',lambda b:b.replace(b'id="gnuplot_plot_1"',b'id="gnuplot_plot_1" stroke-opacity="0"',1)),
        ('svgFillOpacity','plot.svg',lambda b:b.replace(b'fill="black" font-family=',b'fill="black" fill-opacity="0" font-family=',1)),
        ('svgZeroDimensions','plot.svg',lambda b:b.replace(b'width="800" height="600"',b'width="0" height="0"',1)),
        ('svgMarkerScale','plot.svg',lambda b:b.replace(b'scale(3.15)',b'scale(0.00)',1)),
        ('svgExtraSeriesPath','plot.svg',lambda b:b.replace(b'L440.00,270.00',b'L440.00,270.00 M200,200 L300,300',1)),
        ('svgSampleGeometry','plot.svg',lambda b:b.replace(b'translate(440.00,270.00)',b'translate(440.00,200.00)',1)),
        ('svgConnectedGeometry','plot.svg',lambda b:b.replace(b'L440.00,270.00',b'L440.00,200.00',1)),
        ('svgErrorEndpoint','plot.svg',lambda b:b.replace(b'M440.00,322.50',b'M440.00,300.50',1)),
        ('svgAxisLabel','plot.svg',lambda b:b.replace(b'Time (s)',b'Time (m)')),
        ('svgHiddenSeries','plot.svg',lambda b:b.replace(b'id="gnuplot_plot_1"',b'id="gnuplot_plot_1" opacity="0"',1)),
        ('svgMovedSeries','plot.svg',lambda b:b.replace(b'id="gnuplot_plot_1"',b'id="gnuplot_plot_1" transform="translate(100,100)"',1)),
        ('svgMarkerDefinition','plot.svg',lambda b:b.replace(b"id='gpPt5' stroke-width='0.222'",b"id='gpPt5' stroke-width='0.000'",1)),
        ('blankRaster','plot.png',lambda b:white_png(800,600)),
        ('wrongRasterDimensions','plot.png',lambda b:white_png(801,600)),
        ('trustedScript','plot.gp',lambda b:b.replace(b'using 1:2:3',b'using 1:3:2'))]
    for name,target,mutate in mutations:
        try:
            path=directory/target;before=path.read_bytes();changed=mutate(before);assert changed!=before,name;path.write_bytes(changed);refresh(directory)
            report[name+'WithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
        finally:restore()
    try:
        # Refresh capture AND stage bindings, so raw native geometry must catch
        # the mismatch instead of relying on an ordinary stale digest.
        path=directory/'captured.csv';path.write_bytes(path.read_bytes().replace(b'1,2,0.5',b'1,3,0.5'))
        capture=adaptor.read(directory,'captures.json');capture['sha256']=adaptor.digest(directory,'captured.csv');capture['bytes']=path.stat().st_size;atomic_json(directory/'captures.json',capture)
        inputs=adaptor.read(directory,'render-inputs.json');inputs[str(path)]=adaptor.digest(directory,'captured.csv');atomic_json(directory/'render-inputs.json',inputs);refresh(directory)
        report['changedCapturedNumericSeriesWithRefreshedBindings']=refused(lambda:adaptor.verify(directory))['code']
    finally:restore()
    for label,mutation in [('missingNativeEvidence',lambda r:r['evidence'].pop('render.stdout')),
            ('extraNativeEvidence',lambda r:r['evidence'].update({'extra.json':'0'*64})),
            ('forgedPublicationMembership',lambda r:r['artifacts'].pop()),
            ('forgedRuntime',lambda r:r.update(runtime='gnuplot 9.9 patchlevel 9'))]:
        try:
            receipt=adaptor.read(directory,'verification.json');mutation(receipt);atomic_json(directory/'verification.json',receipt)
            report[label]=refused(lambda:adaptor.verify(directory))['code']
        finally:restore()
    try:
        submission=adaptor.read(directory,'render-submission.json');submission['nativeCommand']=['/not/the/native/command'];atomic_json(directory/'render-submission.json',submission);refresh(directory)
        report['forgedNativeCommandWithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
    finally:restore()
    assert adaptor.verify(directory)['verified'];return report


def interrupted_processes(directory,document):
    """Deterministic process lifecycle probe; this wrapper is not Gnuplot evidence."""
    wrapper=directory/'slow-runtime.py';marker=directory/'slow.pid'
    wrapper.write_text('#!'+sys.executable+'\nimport os,time\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text(str(os.getpid()))\ntime.sleep(30)\n');wrapper.chmod(0o700)
    outcomes={}
    for action in ['timeout','cancel']:
        if marker.exists():marker.unlink()
        cancel=threading.Event()
        def trigger():
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline: time.sleep(.01)
            if marker.exists():cancel.set()
        thread=threading.Thread(target=trigger,daemon=True) if action=='cancel' else None
        if thread:thread.start()
        try:
            with allocation({'threads':1,'ranks':1},cancel):
                outcomes[action]=refused(lambda:adaptor.run(document,directory/('inflight-'+action),executable=str(wrapper),timeout=8 if thread else .4),'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')['code']
        finally:
            if thread:thread.join(6)
        assert marker.exists(),'lifecycle probe did not launch owned child'
        pid=int(marker.read_text())
        try:os.kill(pid,0)
        except ProcessLookupError:pass
        else:raise AssertionError('owned process survived '+action)
    return outcomes


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--gnuplot',required=True,type=Path);parser.add_argument('--output-directory',required=True,type=Path)
    parser.add_argument('--register',action='store_true',help='register a fresh successful source-bound native receipt')
    args=parser.parse_args();directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    locations={'gnuplot':str(args.gnuplot.resolve())};report={'verified':False}
    try:
        receipt=qualify(adaptor.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=30,wall_timeout=45)
        report['native']={'verified':receipt['verified'],'cases':[c['id'] for c in receipt['cases']],'runtimes':[c['runtime'] for c in receipt['cases']],'lifecycle':receipt['lifecycle']}
        baseline=directory/'kit/calibration'
        assert (baseline/'captured.csv').read_bytes()==(ROOT/'examples/schemaxis/fixtures/gnuplot/calibration.csv').read_bytes()
        assert adaptor.read(baseline,'authored.json')['series']==[{'label':'Measured','x':'time','y':'reading','error':'uncertainty','colour':'red'}]
        report['literalLinear']=literal(baseline,[[120,375],[440,270],[760,165]],[[120,401.25,348.75],[440,322.5,217.5],[760,191.25,138.75]])
        report['literalLog']=literal(directory/'kit/logarithmic',[[120,340],[440,200],[760,102.144]],[[120,353.567,328.915],[440,213.567,188.915],[760,115.711,91.059]])
        report['negative']=negative(baseline)
        _,_,entry=route_materials(adaptor.VERSION);document=case_document(entry,entry['development']['cases'][0],ROOT)
        bad=copy.deepcopy(document);bad['xAxis']['range']=[1,100];bad['xAxis']['scale']='log10';bad['yAxis']['range']=[1,1000];bad['yAxis']['scale']='log10';bad['source']=str(ROOT/'examples/schemaxis/fixtures/gnuplot/log-invalid.csv')
        report['negative']['invalidLogEndpoint']=refused(lambda:adaptor.run(bad,directory/'invalid-log',executable=locations['gnuplot']),'INVALID_LOG_DATA')['code'];assert not (directory/'invalid-log/render-submission.json').exists()
        source=directory/'source.csv';shutil.copyfile(document['source'],source);document['source']=str(source)
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'plot','document':document}]}
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30);assert workflow.verify(directory/'workflow')['verified']
        second=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert second['jobs'][0]['reused']
        source.write_bytes(source.read_bytes().replace(b'1,2,0.5',b'1,2.0,0.5'))
        third=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert not third['jobs'][0]['reused'];assert workflow.verify(directory/'workflow')['verified']
        report['workflow']={'baseline':first['status'],'unchangedReused':True,'changedSamePathBytesReused':False}
        study=copy.deepcopy(document);study['definitions']={'title':'Bound calibration'};study['title']={'$document':'/definitions/title'};study['axes']=[{'name':'size','values':[800,960]}];study['width']={'$axis':'size'}
        result=adaptor.run(study,directory/'study',executable=locations['gnuplot'],timeout=30);assert adaptor.verify(directory/'study')['verified'];assert len(result['states'])==2
        report['composition']={'states':2,'verified':True}
        report['inflightLifecycle']=interrupted_processes(directory,document)
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
