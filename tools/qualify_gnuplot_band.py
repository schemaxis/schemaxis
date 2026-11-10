#!/usr/bin/env python3
"""Gnuplot asserted lower/upper range envelope: native oracle, hostile evidence, lifecycle, Arrow CSV workflow.

Expectations are literal pixel/vertex values worked out from the fixed plot
margins (x 15%..95% of the width, y 20%..90% of the height) and the declared
linear axes; PNG samples use a decoder local to this file. Production checkers
are exercised as the system under test, never as the oracle.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zlib

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.gnuplot import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis.publication_metadata import finalise
from schemaxis import workflow

ROOT=Path(__file__).resolve().parents[1]
SVG='{http://www.w3.org/2000/svg}'
FIXTURES=ROOT/'examples/schemaxis/fixtures/gnuplot'
# Red series, 20 percent over white: 255-0.2*(255-c) for c=(214,39,40).
FILL=(247,212,212)
BASE_POLYGON=[(120,410),(440,256),(760,340),(760,200),(440,130),(120,270)]
CHANGED_POLYGON=[(120,452),(440,256),(760,340),(760,116),(440,130),(120,270)]


def decode_png(data):
    """Local stdlib decoder: 8-bit RGB/RGBA, all five filters."""
    assert data[:8]==b'\x89PNG\r\n\x1a\n';pos=8;idat=b'';width=height=channels=0
    while pos<len(data):
        n=struct.unpack('>I',data[pos:pos+4])[0];kind=data[pos+4:pos+8];body=data[pos+8:pos+8+n];pos+=12+n
        if kind==b'IHDR':
            width,height,depth,colour=struct.unpack('>IIBB',body[:10]);assert depth==8 and colour in (2,6);channels=3 if colour==2 else 4
        elif kind==b'IDAT':idat+=body
    raw=zlib.decompress(idat);stride=width*channels;rows=[];prev=bytearray(stride);at=0
    for _ in range(height):
        mode=raw[at];line=bytearray(raw[at+1:at+1+stride]);at+=1+stride
        for i in range(stride):
            a=line[i-channels] if i>=channels else 0;b=prev[i];c=prev[i-channels] if i>=channels else 0
            if mode==1:line[i]=(line[i]+a)&255
            elif mode==2:line[i]=(line[i]+b)&255
            elif mode==3:line[i]=(line[i]+(a+b)//2)&255
            elif mode==4:
                p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c);line[i]=(line[i]+(a if pa<=pb and pa<=pc else b if pb<=pc else c))&255
        rows.append([tuple(line[x:x+3]) for x in range(0,stride,channels)]);prev=line
    return width,height,rows


def native_polygon(directory):
    """The band polygon is the longer polygon of the first plot group, read straight from native SVG."""
    root=ET.fromstring((directory/'plot.svg').read_bytes())
    group=next(g for g in root.iter(SVG+'g') if g.get('id')=='gnuplot_plot_1')
    polygons=list(group.iter(SVG+'polygon'));assert len(polygons)==2
    return [tuple(map(float,v.split(','))) for v in polygons[1].get('points').split()],polygons[1].attrib


def literal_band(directory,polygon,interior,exterior):
    points,attributes=native_polygon(directory)
    assert len(points)==len(polygon),(points,polygon)
    assert all(abs(a-c)<=.06 and abs(b-d)<=.06 for (a,b),(c,d) in zip(points,polygon)),(points,polygon)
    assert attributes['fill'].replace(' ','')=='rgb(214,39,40)' and float(attributes['fill-opacity'])==.2,attributes
    width,height,image=decode_png((directory/'plot.png').read_bytes());assert (width,height)==(800,600)
    for x,y in interior:assert all(abs(a-b)<=3 for a,b in zip(image[y][x],FILL)),('interior',x,y,image[y][x])
    for x,y in exterior:assert image[y][x]==(255,255,255),('exterior',x,y,image[y][x])
    return {'nativePolygon':points,'literalPolygon':polygon,'interiorSamples':interior,'exteriorSamples':exterior,'fill':attributes['fill'],'opacity':attributes['fill-opacity']}


def refused(action,code,message=None,location=None):
    try:action()
    except SchemaxisError as error:
        fault=error.fault.to_dict();assert fault['code']==code,fault
        if message is not None:assert message in fault['message'] if not message.startswith('=') else fault['message']==message[1:],fault
        if location is not None:assert fault['location']==location,fault
        return fault
    raise AssertionError('invalid plot/evidence accepted: '+code)


def refresh(directory):
    """Ordinary mutable bindings are all refreshed, so only independent semantics can refuse."""
    receipt=adaptor.read(directory,'verification.json');receipt['artifacts']=adaptor.artifacts(directory)
    receipt['evidence']={n:adaptor.digest(directory,n) for n in receipt['evidence']}
    atomic_json(directory/'verification.json',receipt);finalise(directory)


def refresh_source(directory,mutate):
    path=directory/'captured.csv';path.write_bytes(mutate(path.read_bytes()))
    capture=adaptor.read(directory,'captures.json');capture['sha256']=adaptor.digest(directory,'captured.csv');capture['bytes']=path.stat().st_size;atomic_json(directory/'captures.json',capture)
    inputs=adaptor.read(directory,'render-inputs.json');inputs[str(path)]=adaptor.digest(directory,'captured.csv');atomic_json(directory/'render-inputs.json',inputs)


def png_bytes(width,height,image):
    def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body))
    raw=b''.join(b'\0'+bytes(v for pixel in row for v in pixel) for row in image)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


def hostile(directory):
    """Every mutation refreshes all digests/publication metadata, then the cause must be exact."""
    report={};saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    def restore():
        for path,data in saved.items():path.write_bytes(data)
    svg=(directory/'plot.svg').read_text()
    line=next(l for l in svg.splitlines() if "fill-opacity = '0.200000' points = '120.00,410.00" in l).strip()
    polygon=lambda old,new:svg.replace(line,line.replace(old,new))
    width,height,image=decode_png((directory/'plot.png').read_bytes())
    def repaint(predicate,colour):
        return png_bytes(width,height,[[colour if predicate(x,y,pixel) else pixel for x,pixel in enumerate(row)] for y,row in enumerate(image)])
    near=lambda p:all(abs(a-b)<=3 for a,b in zip(p,FILL))
    # A nearly plot-sized shaded polygon wrapped exactly like native fill groups, placed where it must not be.
    box='130.00,470.00 750.00,470.00 750.00,70.00 130.00,70.00 ';triangle='130.00,470.00 750.00,470.00 440.00,70.00 '
    def fill(colour,points):
        return ('<g fill="none" color="black" stroke="currentColor" stroke-width="1.00" stroke-linecap="butt" stroke-linejoin="miter">\n\t'
            "<g stroke='none' shape-rendering='crispEdges'>\n\t\t<polygon fill = '"+colour+"' fill-opacity = '0.200000' points = '"+points+"'/>\n\t</g>\n</g>\n")
    curve='\t<g id="gnuplot_plot_2"  fill="none"><title>gnuplot_plot_2</title>\n';assert svg.count(curve)==1
    red,blue='rgb(214,  39,  40)','rgb( 31, 119, 180)'
    swatch='389.04,586.50 431.60,586.50 431.60,577.50 389.04,577.50';assert svg.count(swatch)==1
    nest="\t<g stroke='none' shape-rendering='crispEdges'>\n";assert svg.count(nest)==1
    cases=[('wrongLowerVertex','plot.svg',polygon('440.00,256.01','440.00,250.01'),'SVG envelope polygon vertex 1 differs'),
        ('wrongUpperVertex','plot.svg',polygon('759.98,200.01','759.98,190.01'),'SVG envelope polygon vertex 3 differs'),
        ('wrongShapeExtraVertex','plot.svg',polygon("120.00,270.00 '/>","120.00,270.00 120.00,271.00 '/>"),'SVG envelope polygon vertex count differs'),
        ('missingPolygon','plot.svg',svg.replace(line,''),'SVG envelope polygon membership differs'),
        ('extraPolygon','plot.svg',svg.replace(line,line+'\n'+line),'SVG envelope polygon membership differs'),
        ('wrongOpacity','plot.svg',polygon("fill-opacity = '0.200000'","fill-opacity = '0.500000'"),'SVG polygon paint/opacity/attributes differ'),
        ('zeroOpacity','plot.svg',polygon("fill-opacity = '0.200000'","fill-opacity = '0.000000'"),'SVG polygon paint/opacity/attributes differ'),
        ('wrongColour','plot.svg',polygon("rgb(214,  39,  40)","rgb( 31, 119, 180)"),'SVG envelope colour differs'),
        ('plotKindChangedToPath','plot.svg',svg.replace(line,"<path fill='none' d='M120,410 L440,256'/>"),'SVG path paint/attributes differ'),
        ('wrongCentralCurve','plot.svg',svg.replace('L440.00,200.01','L440.00,215.01'),'SVG declared line/error segment differs'),
        ('wrongCentralMarker','plot.svg',svg.replace('translate(440.00,200.01)','translate(440.00,215.01)'),'SVG sample coordinates differ'),
        ('wrongUnits','plot.svg',svg.replace('Reading (V)','Reading (mV)'),'SVG y-axis label position/text differs'),
        ('fillRemovedRightOnly','plot.png',repaint(lambda x,y,p:x>560 and near(p),(255,255,255)),'PNG envelope interior pixel differs at'),
        ('fillRemovedLeftOnly','plot.png',repaint(lambda x,y,p:x<300 and near(p),(255,255,255)),'PNG envelope interior pixel differs at'),
        ('exteriorFilled','plot.png',repaint(lambda x,y,p:70<=y<125 and 130<x<750 and p==(255,255,255),FILL),'PNG envelope exterior pixel differs at'),
        ('wrongPlotKind','plot.gp',None,'trusted plot script differs'),
        ('extraRedPolygonInCurveGroup','plot.svg',svg.replace(curve,curve+fill(red,box)),'SVG fill group outside the envelope group'),
        ('extraBlueTriangleInCurveGroup','plot.svg',svg.replace(curve,curve+fill(blue,triangle)),'SVG fill group outside the envelope group'),
        ('extraGreenPolygonInCurveGroup','plot.svg',svg.replace(curve,curve+fill('rgb( 44, 160,  44)',box)),'SVG fill group outside the envelope group'),
        ('extraPolygonAtCanvasLevel','plot.svg',svg.replace(curve,fill(red,box)+curve),'SVG fill group paint/attributes differ'),
        ('extraPolygonNestedInFillGroup','plot.svg',svg.replace(nest,nest+nest+"\t\t<polygon fill = '"+red+"' fill-opacity = '0.200000' points = '"+box+"'/>\n\t</g>\n"),'SVG fill group paint/attributes differ'),
        ('extraBlueTriangleInEnvelopeGroup','plot.svg',svg.replace(line,line+"\n\t\t<polygon fill = '"+blue+"' fill-opacity = '0.200000' points = '"+triangle+"'/>"),'SVG envelope polygon membership differs'),
        ('legendSwatchFullWidth','plot.svg',svg.replace(swatch,'10.00,599.00 790.00,599.00 790.00,541.00 10.00,541.00'),'SVG envelope legend swatch differs'),
        ('legendSwatchShifted','plot.svg',svg.replace(swatch,'300.00,586.50 342.56,586.50 342.56,577.50 300.00,577.50'),'SVG envelope legend swatch differs'),
        ('legendSwatchTaller','plot.svg',svg.replace(swatch,'389.04,586.50 431.60,586.50 431.60,520.50 389.04,520.50'),'SVG envelope legend swatch differs')]
    for name,target,changed,message in cases:
        try:
            path=directory/target
            if target=='plot.gp':changed=path.read_text().replace('with filledcurves','with lines')
            if isinstance(changed,str):changed=changed.encode()
            assert changed!=path.read_bytes(),name;path.write_bytes(changed);refresh(directory)
            report[name]=refused(lambda:adaptor.verify(directory),'VERIFICATION_FAILED','='+message if not message.endswith('at') else message)['message']
        finally:restore()
    # Changed asserted bounds in the captured source, with every binding refreshed.
    for name,old,new,message in [('sourceLowerChanged',b'1,2,1.6,2.5',b'1,2,1.5,2.5','SVG envelope polygon vertex 1 differs'),
            ('sourceUpperChanged',b'2,1.5,1,2',b'2,1.5,1,2.4','SVG envelope polygon vertex 3 differs'),
            ('sourceCentreChanged',b'1,2,1.6,2.5',b'1,2.2,1.6,2.5','SVG sample coordinates differ')]:
        try:
            refresh_source(directory,lambda b:b.replace(old,new));refresh(directory)
            report[name]=refused(lambda:adaptor.verify(directory),'VERIFICATION_FAILED','='+message)['message']
        finally:restore()
    assert adaptor.verify(directory)['verified'];return report


def native_geometry(directory,document,executable):
    """Actual Gnuplot runs through the production run path at supported sizes and on the tick-window data.

    Every expectation is literal: the fixed margins (x 15..95 percent, y 20..90 percent of the image) applied to the
    CSV values written here, and a native legend swatch at a fixed offset from its label. The PNG is read with this
    file's own decoder, and the probes stay out of the tick-bearing border strips."""
    data={'band.csv':[(0,1,.5,1.5),(1,2,1.6,2.5),(2,1.5,1,2)],'band-tick-window.csv':[(0,1,.5,1.5),(1,2,1.6,2.92),(2,1.5,1,2)]}
    report={}
    for name,csv,w,h in [('tickWindow800x600','band-tick-window.csv',800,600),('band640x480','band.csv',640,480),('band1600x1200','band.csv',1600,1200),
            ('band1600x480','band.csv',1600,480),('band640x1200','band.csv',640,1200)]:
        rows=data[csv];assert (FIXTURES/csv).read_text().split()[1:]==[','.join(f'{v:g}' for v in r) for r in rows],csv
        sx=lambda x:w*(.15+.8*x/2);sy=lambda y:h*(.8-.7*y/3)
        literal=[(sx(r[0]),sy(r[2])) for r in rows]+[(sx(r[0]),sy(r[3])) for r in reversed(rows)]
        d=copy.deepcopy(document);d.update(width=w,height=h,source=str(FIXTURES/csv))
        result=adaptor.run(d,directory/('geometry-'+name),executable=executable,timeout=30);run=directory/('geometry-'+name)
        assert result['verified'] and adaptor.verify(run)['verified'],name
        root=ET.fromstring((run/'plot.svg').read_bytes());group=next(g for g in root.iter(SVG+'g') if g.get('id')=='gnuplot_plot_1')
        polygons=list(group.iter(SVG+'polygon'));assert len(polygons)==2==len(list(root.iter(SVG+'polygon')))
        points=[tuple(map(float,v.split(','))) for v in polygons[1].get('points').split()]
        assert len(points)==6 and all(abs(a-c)<=.06 and abs(b-e)<=.06 for (a,b),(c,e) in zip(points,literal)),(name,points,literal)
        label=next(n for n in group.iter(SVG+'text') if ''.join(n.itertext())=='Mean range');anchor=next(g for g in group.iter(SVG+'g') if label in list(g))
        lx,ly=map(float,re.match(r'translate\(([-0-9.]+),([-0-9.]+)\)',anchor.get('transform')).groups());assert abs(ly-(h-14.10))<=.06
        swatch=[tuple(map(float,v.split(','))) for v in polygons[0].get('points').split()]
        box=[(lx+8.39,ly+.6),(lx+8.39+42.56,ly+.6),(lx+8.39+42.56,ly-8.4),(lx+8.39,ly-8.4)]
        assert all(abs(a-c)<=.06 and abs(b-e)<=.06 for (a,b),(c,e) in zip(swatch,box)),(name,swatch,box)
        width,height,image=decode_png((run/'plot.png').read_bytes());assert (width,height)==(w,h)
        up=sy(rows[1][3]);centre=sy(rows[1][1]);low=sy(rows[1][2]);x1=round(sx(1))
        interior=[(x1,round((up+centre)/2)),(x1,round((centre+low)/2)) if low-centre>14 else (x1,round((up+centre)/2)+1)]
        exterior=[(x1,round((low+h*.8)/2)),(round(sx(.5)),round(h*.8-20))]
        for x,y in interior:assert all(abs(a-b)<=3 for a,b in zip(image[y][x],FILL)),(name,'interior',x,y,image[y][x])
        for x,y in exterior:assert image[y][x]==(255,255,255),(name,'exterior',x,y,image[y][x])
        report[name]={'size':[w,h],'verified':True,'nativePolygon':points,'literalPolygon':[[round(a,3),round(b,3)] for a,b in literal],'swatch':swatch,'label':[lx,ly],'interior':interior,'exterior':exterior}
        if csv=='band-tick-window.csv':
            # Why the old probe window failed this legitimate plot: a 4 px border margin chose (440,65), which is a native black tick mark.
            assert image[65][440]==(0,0,0) and image[int(h*.1)+3][440]==(0,0,0),image[65][440]
            report[name]['formerExteriorProbe']={'pixel':[440,65],'colour':image[65][440],'is':'native top tick mark'}
    return report


def real_gnuplot_blocker(directory,executable):
    """Real Gnuplot 6.0.5 held by its own `pause` command in the render stage (not mid-render proof)."""
    wrapper=directory/'held-gnuplot.sh';marker=directory/'held.json'
    wrapper.write_text(f'#!/bin/sh\nif [ "$2" = plot.gp ]; then\n  echo $$ > {directory}/held.pid\n  exec {executable} -e "pause 60" "$@"\nfi\nexec {executable} "$@"\n');wrapper.chmod(0o700)
    return wrapper


def lifecycle(directory,document,executable):
    outcomes={}
    wrapper=real_gnuplot_blocker(directory,executable);pidfile=directory/'held.pid'
    for action in ('timeout','cancel'):
        if pidfile.exists():pidfile.unlink()
        cancel=threading.Event();seen={}
        def watch():
            end=time.monotonic()+10
            while time.monotonic()<end:
                if pidfile.exists() and pidfile.read_text().strip():
                    pid=int(pidfile.read_text());time.sleep(.8)
                    try:
                        seen['exe']=os.readlink(f'/proc/{pid}/exe');seen['cmdline']=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[:6]
                        seen['pgid']=os.getpgid(pid);seen['pid']=pid
                    except OSError as error:seen['error']=str(error)
                    if action=='cancel':cancel.set()
                    return
                time.sleep(.02)
        thread=threading.Thread(target=watch,daemon=True);thread.start()
        run=directory/('live-'+action)
        try:
            with allocation({'threads':1,'ranks':1},cancel):
                fault=refused(lambda:adaptor.run(document,run,executable=str(wrapper),timeout=20 if action=='cancel' else 4),'RUNNER_CANCELLED' if action=='cancel' else 'RUNNER_TIMED_OUT')
        finally:thread.join(12)
        assert seen.get('exe','').endswith('/gnuplot'),seen
        pid=seen['pid']
        gone=False
        for _ in range(50):
            try:os.kill(pid,0)
            except ProcessLookupError:gone=True;break
            time.sleep(.1)
        assert gone,'owned Gnuplot survived '+action
        try:os.killpg(seen['pgid'],0)
        except ProcessLookupError:group=True
        else:group=False
        result=json.loads((run/'result.json').read_text());assert result['status']=='failed' and result['verified'] is False and result['fault']['code']==fault['code']
        assert not any((run/n).exists() for n in ('verification.json','plot.svg','plot.png','plot-summary.json'))
        outcomes[action]={'code':fault['code'],'gnuplotPid':pid,'exe':seen['exe'],'argv':[a.decode() for a in seen['cmdline']],'processGone':gone,'groupGone':group,'resultStatus':result['status'],'successfulPublication':False,
            'scope':'real Gnuplot 6.0.5 process held by its own pause command in the render stage; not a mid-render proof'}
    return outcomes


def native_oracle(directory,document,executable):
    """Actual Gnuplot output for changed colour/order/edge/thin/degenerate bounds, read independently."""
    report={}
    def render(name,rows,mutate_script=None,colour='red'):
        run=directory/('oracle-'+name);run.mkdir()
        d=copy.deepcopy(document);d['series'][0]['colour']=colour
        plan=adaptor.plan({**d,'source':str(run/'x.csv')});(run/'captured.csv').write_text('time,mean,lower,upper\n'+rows)
        text=adaptor.script(plan)
        if mutate_script:text=mutate_script(text)
        (run/'plot.gp').write_text(text);subprocess.run([executable,'-d','plot.gp'],cwd=run,check=True,capture_output=True,timeout=30)
        return run
    run=render('blue','0,1,0.5,1.5\n1,2,1.6,2.5\n2,1.5,1,2\n',colour='blue')
    root=ET.fromstring((run/'plot.svg').read_bytes());g=next(g for g in root.iter(SVG+'g') if g.get('id')=='gnuplot_plot_1');poly=list(g.iter(SVG+'polygon'))[1]
    assert poly.get('fill').replace(' ','')=='rgb(31,119,180)' and float(poly.get('fill-opacity'))==.2
    report['colour']={'fill':poly.get('fill'),'opacity':poly.get('fill-opacity')}
    run=render('swapped','0,1,0.5,1.5\n1,2,1.6,2.5\n2,1.5,1,2\n',lambda t:t.replace('using 1:3:4','using 1:4:3'))
    points,_=native_polygon(run);report['swappedColumnOrder']={'nativeFirstVertex':points[0],'lowerFirstExpected':BASE_POLYGON[0]}
    assert abs(points[0][1]-270)<=.06 and abs(points[0][1]-410)>1  # native then starts on the upper edge: order matters
    run=render('edge','0,1,0,1.5\n1,2,0,2.5\n2,1.5,0,2\n')
    points,_=native_polygon(run);assert all(abs(points[k][1]-480)<=.06 for k in range(3)),points
    report['axisEdgeLower']={'lowerEdgeY':[round(points[k][1],2) for k in range(3)]}
    run=render('thin','0,1,0.5,1.5\n1,2,1.92,2.08\n2,1.5,1,2\n');points,_=native_polygon(run)
    assert abs((points[1][1]-points[4][1])-22.4)<=.06,points
    report['tinyWidthNative']={'rowHeightPixels':round(points[1][1]-points[4][1],2),'productionRefusal':'PLOT_BAND_UNVERIFIABLE before native (policy limit: 24 pixels)'}
    run=render('degenerate','0,1,1,1\n1,2,2,2\n2,1.5,1.5,1.5\n');points,_=native_polygon(run)
    report['degenerateNative']={'polygonVertices':len(points),'zeroHeightRows':True,'productionRefusal':'INVALID_PLOT_BOUNDS before native'}
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--gnuplot',required=True,type=Path)
    parser.add_argument('--apachearrow',required=True,type=Path,help='absolute launcher of the Arrow runtime; never dereferenced');parser.add_argument('--output-directory',required=True,type=Path)
    args=parser.parse_args();directory=args.output_directory.absolute();directory.mkdir(parents=True,exist_ok=False)
    executable=str(args.gnuplot.absolute());arrow=os.path.abspath(args.apachearrow)
    locations={'gnuplot':executable,'apachearrow':arrow};report={'verified':False,'gnuplot':executable,'arrowLauncher':arrow}
    try:
        receipt=qualify(adaptor.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=30,wall_timeout=45)
        report['kit']={'verified':receipt['verified'],'cases':[c['id'] for c in receipt['cases']],'runtimes':[c['runtime'] for c in receipt['cases']]}
        assert receipt['verified'] and 'range-envelope' in report['kit']['cases'] and 'changed-range-envelope' in report['kit']['cases']
        base=directory/'kit/range-envelope';changed=directory/'kit/changed-range-envelope'
        assert (base/'captured.csv').read_bytes()==(FIXTURES/'band.csv').read_bytes()
        report['literalBaseline']=literal_band(base,BASE_POLYGON,[(200,330),(600,200),(440,160)],[(200,400),(600,130),(440,100)])
        report['literalChanged']=literal_band(changed,CHANGED_POLYGON,[(200,390),(600,140),(440,160)],[(200,430),(600,100),(440,100)])
        # Same two probes distinguish the baseline from the changed non-adjacent bounds.
        _,_,before=decode_png((base/'plot.png').read_bytes());_,_,after=decode_png((changed/'plot.png').read_bytes())
        assert before[390][200]==(255,255,255) and after[390][200]!=(255,255,255) and before[140][600]==(255,255,255) and after[140][600]!=(255,255,255)
        report['hostile']=hostile(base)
        document=json.loads((ROOT/'examples/schemaxis/gnuplot-band.json').read_text());document['source']=str(FIXTURES/'band.csv')
        report['nativeOracle']=native_oracle(directory,document,executable)
        report['nativeGeometry']=native_geometry(directory,document,executable)
        pre={}
        for name,fixture,code in [('lowerAboveCentre','band-lower-above-invalid.csv','INVALID_PLOT_BOUNDS'),('reversed','band-reversed-invalid.csv','INVALID_PLOT_BOUNDS'),('outsideAxes','band-outside-invalid.csv','PLOT_DATA_OUTSIDE_RANGE'),
                ('thin','band-thin-invalid.csv','PLOT_BAND_UNVERIFIABLE'),('noExteriorClearOfTicks','band-border-ticks-invalid.csv','PLOT_BAND_UNVERIFIABLE'),('missingCell','band-null-invalid.csv','INVALID_PLOT_DATA'),('wrongHeader','band-header-invalid.csv','INVALID_PLOT_DATA'),('unsortedX','band-order-invalid.csv','INVALID_PLOT_DATA')]:
            run=directory/('refused-'+name);refused(lambda:adaptor.run({**document,'source':str(FIXTURES/fixture)},run,executable=executable),code)
            assert not any((run/n).exists() for n in ('render-submission.json','plot.gp','plot.svg','plot.png','version-submission.json'));pre[name]=code
        for name,change,code in [('symmetricAndBounds',lambda d:d['series'][0].update(error='lower'),'INVALID_PLOT_BOUNDS'),('logAxis',lambda d:d['yAxis'].update(scale='log10',range=[.1,3]),'PLOT_BOUNDS_UNSUPPORTED')]:
            d=copy.deepcopy(document);change(d);run=directory/('refused-'+name);refused(lambda:adaptor.run(d,run,executable=executable),code);assert not (run/'plot.gp').exists();pre[name]=code
        report['refusedBeforeNative']=pre
        report['lifecycle']=lifecycle(directory,document,executable)
        # Real workflow: Arrow publishCSV (artifact index 2, kind file) -> Gnuplot envelope.
        graph=json.loads((ROOT/'examples/schemaxis/apachearrow-gnuplot-band-workflow.json').read_text())
        source=directory/'arrow-source.csv';shutil.copyfile(FIXTURES/'arrow-band-source.csv',source);graph['operations'][0]['document']['source']=str(source)
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=90);assert workflow.verify(directory/'workflow')['verified']
        producer=next(j for j in first['jobs'] if j['operation']=='prepare');consumer=next(j for j in first['jobs'] if j['operation']=='plot')
        produced=next(Path(producer['directory']).rglob('table.csv'));held=Path(consumer['directory'])
        assert produced.read_bytes()==b'x,mean,lower,upper\n0,1,0.5,1.5\n1,2,1.6,2.5\n2,1.5,1,2\n',produced.read_bytes()
        assert (held/'captured.csv').read_bytes()==produced.read_bytes()
        assert adaptor.verify(held)['verified']
        flow=literal_band(held,BASE_POLYGON,[(200,330),(600,200)],[(200,400),(600,130)])
        second=workflow.execute(graph,directory/'workflow',locations=locations,timeout=90,resume=True);assert all(j['reused'] for j in second['jobs'])
        source.write_bytes(source.read_bytes().replace(b'1.0,2.0,1.6,2.5,1',b'1.0,2.0,1.5,2.5,1'))
        third=workflow.execute(graph,directory/'workflow',locations=locations,timeout=90,resume=True);assert not any(j['reused'] for j in third['jobs']);assert workflow.verify(directory/'workflow')['verified']
        producer=next(j for j in third['jobs'] if j['operation']=='prepare');consumer=next(j for j in third['jobs'] if j['operation']=='plot')
        assert next(Path(producer['directory']).rglob('table.csv')).read_bytes()==b'x,mean,lower,upper\n0,1,0.5,1.5\n1,2,1.5,2.5\n2,1.5,1,2\n'
        newpoly=[(120,410),(440,270.0),(760,340),(760,200),(440,130),(120,270)]
        changed_flow=literal_band(Path(consumer['directory']),newpoly,[(200,330),(600,200)],[(200,400),(600,130)])
        job=json.loads((held/'job.json').read_text());import hashlib
        assert [(h['from'],h['index'],h['sha256']) for h in job['handoffs']]==[('prepare',2,hashlib.sha256(produced.read_bytes()).hexdigest())]==[('prepare',2,hashlib.sha256((held/'captured.csv').read_bytes()).hexdigest())]
        report['workflow']={'baseline':flow,'unchangedReusedBoth':True,'samePathChangedBytesInvalidatedBoth':True,'changedPolygon':changed_flow['nativePolygon'],'handoff':job['handoffs'],'producerCSVEqualsConsumerCapture':True}
        # Changed AUTHORED consumer intent: resume contract decides; record what actually happened.
        edited=copy.deepcopy(graph);edited['operations'][1]['document']['title']='Arrow range envelope edited'
        try:
            workflow.execute(edited,directory/'workflow',locations=locations,timeout=90,resume=True);edit='accepted'
        except SchemaxisError as error:edit=error.fault.code
        fresh=workflow.execute(edited,directory/'workflow-fresh',locations=locations,timeout=90);assert workflow.verify(directory/'workflow-fresh')['verified']
        report['workflow']['authoredEditResume']=edit;report['workflow']['authoredEditFreshWorkflow']='succeeded'
        negatives={}
        def attempt(name,mutate,code):
            g=copy.deepcopy(graph);run=directory/('wf-'+name);src=directory/('src-'+name+'.csv');shutil.copyfile(FIXTURES/'arrow-band-source.csv',src);g['operations'][0]['document']['source']=str(src)
            fixture=mutate(g,src)
            try:workflow.execute(g,run,locations=locations,timeout=90)
            except SchemaxisError as error:
                assert error.fault.code==code,error.fault.to_dict()
                plotdir=run/'plot';assert not list(run.rglob('render-submission.json')) and not list(run.rglob('plot.svg')),'Gnuplot process started'
                produced=[json.loads(p.read_text()) for p in (run/'prepare').rglob('result.json')]
                negatives[name]={'code':code,'location':error.fault.location,'message':error.fault.message[:160],'gnuplotLaunched':False,
                                 'producerResultStatuses':[r.get('status') for r in produced],'producerVerifiedFlags':[r.get('verified') for r in produced]}
            else:raise AssertionError(name+' accepted')
        attempt('noCSVOptIn',lambda g,s:g['operations'][0]['document'].update(publishCSV=False),'INVALID_SELECTION')
        attempt('wrongArtifactIndex',lambda g,s:g['operations'][1]['document']['source'].update(index=9),'INVALID_SELECTION')
        attempt('parquetBinaryFile',lambda g,s:g['operations'][1]['document']['source'].update(index=0),'INVALID_PLOT_SOURCE')
        attempt('textReportNotCSV',lambda g,s:g['operations'][1]['document']['source'].update(index=1),'TYPE_MISMATCH')
        attempt('wrongColumnOrder',lambda g,s:g['operations'][1]['document'].update(columns=[g['operations'][1]['document']['columns'][i] for i in (0,2,1,3)]),'INVALID_PLOT_DATA')
        attempt('wrongUnitsForBounds',lambda g,s:g['operations'][1]['document']['columns'][3].update(unit='mV'),'PLOT_UNIT_MISMATCH')
        attempt('boundsOutsideAxes',lambda g,s:s.write_bytes(s.read_bytes().replace(b'2.0,1.5,1.0,2.0,1',b'2.0,1.5,1.0,3.5,1')),'PLOT_DATA_OUTSIDE_RANGE')
        attempt('lowerAboveCentre',lambda g,s:s.write_bytes(s.read_bytes().replace(b'2.0,1.5,1.0,2.0,1',b'2.0,1.5,1.7,2.0,1')),'INVALID_PLOT_BOUNDS')
        report['workflow']['negatives']=negatives
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
