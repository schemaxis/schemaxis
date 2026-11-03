#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Qualify GDAL with independent pixel/corner oracles and hostile lifecycle probes."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import struct
import threading
import subprocess
import os
import signal
from unittest.mock import patch
import time

from schemaxis import workflow
from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptors.gdal import adaptor, reference
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from qualify_gdal_fixtures import tiff

ROOT=Path(__file__).resolve().parents[1]


def refused(action,code='VERIFICATION_FAILED'):
    try:action()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        return code
    raise AssertionError('invalid input/evidence accepted')


def change_tag(data,tag,value):
    out=bytearray(data);off=struct.unpack_from('<I',out,4)[0];n=struct.unpack_from('<H',out,off)[0]
    for i in range(n):
        p=off+2+i*12
        if struct.unpack_from('<H',out,p)[0]==tag:
            struct.pack_into('<I',out,p+8,value);return bytes(out)
    raise AssertionError('tag absent')


def refresh(directory):
    receipt=adaptor.read(directory,'verification.json');prepared=adaptor._native_plan(adaptor.read(directory,'authored.json'))
    receipt['artifacts']=adaptor.artifacts(directory,prepared)
    receipt['evidence']={name:adaptor.digest(directory,name) for name in receipt['evidence']}
    atomic_json(directory/'verification.json',receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def hostile(directory):
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()};report={}
    def restore():
        for p in directory.glob('raster*'):
            if p not in saved:p.unlink()
        for p,data in saved.items():p.write_bytes(data)
    def changed_pixel():
        p=directory/'raster.tif';data=bytearray(p.read_bytes());off=struct.unpack_from('<I',data,4)[0];n=struct.unpack_from('<H',data,off)[0]
        for i in range(n):
            tag,kind,count,start=struct.unpack_from('<HHII',data,off+2+12*i)
            if tag==273:struct.pack_into('<h',data,start,999);break
        p.write_bytes(data)
    def changed_origin():
        p=directory/'raster.tif';data=bytearray(p.read_bytes());off=struct.unpack_from('<I',data,4)[0];n=struct.unpack_from('<H',data,off)[0]
        for i in range(n):
            tag,kind,count,start=struct.unpack_from('<HHII',data,off+2+12*i)
            if tag==33922:struct.pack_into('<d',data,start+24,500020);break
        p.write_bytes(data)
    def changed_native():
        for name in ('window.stdout','readback.stdout'):
            value=adaptor.read(directory,name);value['raster']['units']='K';atomic_json(directory/name,value)
    def boolean_native():
        value=adaptor.read(directory,'readback.stdout');value['raster']['band']=True;atomic_json(directory/'readback.stdout',value)
    def boolean_pixel():
        value=adaptor.read(directory,'readback.stdout');value['raster']['pixels'][0]=bool(value['raster']['pixels'][0]);atomic_json(directory/'readback.stdout',value)
    def rebound_source():
        p=directory/'source.tif';p.write_bytes(p.read_bytes()+b'\0')
        capture=adaptor.read(directory,'capture.json');capture.update(bytes=p.stat().st_size,sha256=adaptor.digest(directory,'source.tif'));atomic_json(directory/'capture.json',capture)
    changes={'pixel-refreshed':changed_pixel,'affine-origin-refreshed':changed_origin,'native-unit-refreshed':changed_native,'native-boolean-band-refreshed':boolean_native,'native-boolean-pixel-refreshed':boolean_pixel,'source-rebound-refreshed':rebound_source,'trusted-worker-refreshed':lambda:(directory/'native-worker.py').write_text(adaptor.worker_source()+'\n#changed\n'),'extra-publication':lambda:(directory/'raster.extra').write_text('extra'),'extra-sidecar':lambda:(directory/'raster.extra.metadata.json').write_text('{}')}
    for name,action in changes.items():
        try:action();refresh(directory);report[name]=refused(lambda:adaptor.verify(directory))
        finally:restore()
    assert adaptor.verify(directory)['verified'];return report


def inputs(directory,document,executable):
    source=Path(document['source']).read_bytes();report={}
    malformed={'compressed':change_tag(source,259,5),'extra-band':change_tag(source,277,2),'strip-offset':change_tag(source,273,2),'strip-size':change_tag(source,279,99999),'pixel-budget':change_tag(source,256,999999),'truncated':source[:-1],'unsupported-metadata':source.replace(b'UNITTYPE',b'FOOBARRY'),'nonfinite':tiff([float('nan')]*30,dtype='Float32'),'unresolvable-affine':tiff([1]*30,origin=(1e15,1e15),spacing=(.1,.1))}
    for name,data in malformed.items():
        path=directory/(name+'.tif');path.write_bytes(data)
        report[name]=refused(lambda:adaptor.run({**document,'source':str(path)},directory/(name+'-run'),executable=executable),'INVALID_RASTER_CONTENT')
    for name,change in [('wrong-crs',{'epsg':4326}),('wrong-units',{'units':'K'}),('wrong-nodata',{'nodata':0}),('outside',{'x':5})]:
        report[name]=refused(lambda:adaptor.run({**document,**change},directory/(name+'-run'),executable=executable),'INVALID_RASTER_CONTENT')
    for dtype,nodata in [('UInt16',65535),('Int16',-9999),('Float32',-9999)]:
        name='all-nodata-'+dtype;p=directory/(name+'.tif');p.write_bytes(tiff([nodata]*30,dtype=dtype,nodata=nodata))
        out=directory/(name+'-run');adaptor.run({**document,'source':str(p),'nodata':nodata},out,executable=executable)
        summary=adaptor.read(out,'raster-summary.json')
        assert summary['nodataCount']==12 and summary['validCount']==0 and summary['mean'] is None and summary['minimum'] is None and summary['maximum'] is None
        report[name]='verified'
    for name,dtype,units,nodata,pixels,width,height in [
        ('uint16-dimensionless','UInt16','1',65535,[0,1,65534,65535,7,8]*5,6,5),
        ('float32-nonround-multistrip','Float32','K',-9999,[i*.1 for i in range(4096)],64,64),
    ]:
        path=directory/(name+'.tif');path.write_bytes(tiff(pixels,width=width,height=height,dtype=dtype,units=units,nodata=nodata))
        out=directory/(name+'-run')
        result=adaptor.run({**document,'source':str(path),'units':units,'nodata':nodata,'x':0,'y':0,'width':width,'height':height,'outputWidth':width,'outputHeight':height},out,executable=executable)
        assert result['verified'];expected=reference.parse(path.read_bytes());actual=reference.parse((out/'raster.tif').read_bytes());reference.compare(expected,actual)
        report[name]={'verified':True,'pixels':width*height}
    return report


def active_cancellation(directory, document, executable):
    """Observe the real native PID after it hashes consumed inputs, then cancel."""
    source=directory/'active-source.tif'
    source.write_bytes(tiff([i*.1 for i in range(262144)],width=512,height=512,dtype='Float32'))
    document={**document,'source':str(source),'x':0,'y':0,'width':512,'height':512,'outputWidth':512,'outputHeight':512}
    cancel=threading.Event();active=directory/'active-cancel';observed=[];processes=[];watcher_errors=[]
    launch=subprocess.Popen
    def capture_process(*args,**kwargs):
        process=launch(*args,**kwargs);processes.append(process);return process
    def trigger():
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if (active/'window-inputs.json').is_file():
                for process in processes:
                    try:command=Path('/proc',str(process.pid),'cmdline').read_bytes()
                    except FileNotFoundError:continue
                    if process.poll() is None and str(active/'native-worker.py').encode() in command:
                        # Bounded cancellation fixture: hold the confirmed real
                        # native process after source consumption so the shared
                        # 100ms monitor cannot race with this very fast workload.
                        os.kill(process.pid,signal.SIGSTOP)
                        stop_deadline=time.monotonic()+1
                        while time.monotonic()<stop_deadline:
                            state=Path('/proc',str(process.pid),'stat').read_text().rsplit(')',1)[1].split()[0]
                            if state=='T':break
                            time.sleep(.001)
                        assert state=='T','native fixture did not stop'
                        observed.append({'pid':process.pid,'marker':'window-inputs.json','nativeCommandObserved':True,'pauseInjected':'SIGSTOP after real native source consumption'});cancel.set();return
            time.sleep(.001)
        cancel.set()
    def watch():
        try:trigger()
        except Exception as error:watcher_errors.append(str(error));cancel.set()
    thread=threading.Thread(target=watch);thread.start()
    try:
        # This observer returns the real Popen object. The source-consumed
        # native job is paused explicitly; normal dispatcher cancellation owns
        # its termination. No application result or executable is replaced.
        with patch('schemaxis.dispatch.subprocess.Popen',side_effect=capture_process):
            with allocation({'threads':1,'ranks':1},cancel):
                fault=refused(lambda:adaptor.run(document,active,executable=executable,timeout=20),'RUNNER_CANCELLED')
    finally:
        thread.join(timeout=16)
        # Even a failed fixture assertion must leave no paused owned process.
        for process in processes:
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=5)
    assert not thread.is_alive() and not watcher_errors,watcher_errors
    assert observed, 'did not observe an active native worker consuming source'
    victim=next(p for p in processes if p.pid==observed[0]['pid'])
    assert victim.poll() is not None and victim.returncode<0, 'observed native process was not terminated by cancellation'
    assert not Path('/proc',str(victim.pid)).exists(), 'cancelled owned process still present'
    assert not (active/'verification.json').exists(), 'cancelled execution published a success receipt'
    return {'fault':fault,**observed[0],'returnCode':victim.returncode,'ownedProcessGone':True,'pixels':262144}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--gdal',type=Path,required=True);parser.add_argument('--output-directory',type=Path,required=True);parser.add_argument('--register',action='store_true');args=parser.parse_args()
    directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    executable=str(args.gdal.absolute());locations={'gdal':executable};report={'verified':False}
    try:
        receipt=qualify(adaptor.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=30,wall_timeout=60)
        assert receipt['verified'],receipt
        report['kit']={'verified':receipt['verified'],'lifecycle':receipt['lifecycle'],'cases':[c['id'] for c in receipt['cases']]}
        baseline=reference.parse((directory/'kit/window/raster.tif').read_bytes());nearest=reference.parse((directory/'kit/nearest/raster.tif').read_bytes());geographic=reference.parse((directory/'kit/geographic/raster.tif').read_bytes())
        assert baseline['pixels']==[21,-9999,23,24,31,32,33,34,41,42,43,-9999]
        assert nearest['pixels']==[21,23,24,41,43,-9999]
        assert reference.summary(baseline)['corners']==[[500010,5499980],[500050,5499920]]
        assert geographic['pixels'][:9]==[273.25,273.5,273.5,273.75,274.,274.,274.25,274.5,274.5]
        assert geographic['pixels'][-1]==280.5 and geographic['pixels'][-9]==279.25
        report['literal']={'baselinePixels':12,'nearestPixels':[21,23,24,41,43,-9999],'corners':[[500010,5499980],[500050,5499920]],'geographicLastPixel':280.5}
        report['hostile']=hostile(directory/'kit/window')
        document=json.loads((ROOT/'examples/schemaxis/gdal-window.json').read_text());document['source']=str(ROOT/'examples/schemaxis/fixtures/gdal/elevation.tif')
        report['inputs']=inputs(directory,document,executable)
        # First dimensionless pixel is literally zero: False would compare equal
        # without exact numeric-type validation. Refresh outer hashes as well.
        report['hostileDimensionless']=hostile(directory/'uint16-dimensionless-run')
        report['activeCancellation']=active_cancellation(directory,document,executable)
        source=directory/'workflow-source.tif';shutil.copyfile(document['source'],source);document['source']=str(source)
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'crop','document':document},{'id':'sample','document':{**document,'source':{'$artifact':'crop','index':0},'x':0,'y':0,'outputWidth':3,'outputHeight':2}}]}
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30);assert workflow.verify(directory/'workflow')['verified']
        second=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert all(job['reused'] for job in second['jobs'])
        source.write_bytes(source.read_bytes()+b'\0')
        changed=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert not changed['jobs'][0]['reused'];assert workflow.verify(directory/'workflow')['verified']
        report['workflow']={'status':first['status'],'unchangedReused':True,'samePathChangedBytesReused':False,'handoff':'Verified GeoTIFF crop consumed by a second nearest window.'}
        study=copy.deepcopy(document);study['axes']=[{'name':'columns','values':[3,4]}];study['outputWidth']={'$axis':'columns'};study['definitions']={'method':'nearest'};study['resampling']={'$document':'/definitions/method'}
        result=adaptor.run(study,directory/'study',executable=executable,timeout=30);assert len(result['states'])==2 and adaptor.verify(directory/'study')['verified'];report['composition']={'states':2,'verified':True}
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
