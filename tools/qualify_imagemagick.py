#!/usr/bin/env python3
"""All-pixel PNG native cases, policy denial, hostile receipts and workflow reuse."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from schemaxis.adaptor_conformance import qualify,register
from schemaxis.adaptor_delivery import case_document,route_materials
from schemaxis.adaptors.imagemagick import adaptor,png
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow
from qualify_imagemagick_fixtures import GRID,fixture

ROOT=Path(__file__).resolve().parents[1]


def refused(action,code='VERIFICATION_FAILED'):
    try:action()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        return error.fault.code
    raise AssertionError('invalid raster/evidence accepted')


def refresh(directory):
    receipt=adaptor.read(directory,'verification.json');p=adaptor.plan(adaptor.read(directory,'authored.json'))
    receipt['artifacts']=adaptor.artifacts(directory,p);receipt['evidence']={n:adaptor.digest(directory,n) for n in receipt['evidence']};atomic_json(directory/'verification.json',receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def literal_cases(directory):
    """Explicit expected rows are separate from the adaptor's transform/layout."""
    red=(255,0,0,255);green=(0,255,0,128);blue=(0,0,255,255);yellow=(255,255,0,64);cyan=(0,255,255,255);hidden=(17,33,65,0)
    rows={'baseline':[[red,red,green,green],[red,red,green,green],[blue,blue,yellow,yellow],[blue,blue,yellow,yellow]],
        'variant':[[yellow,green],[cyan,hidden]],
        'flatten':[[(20,40,60,255),cyan],[(10,148,30,255),(79,94,45,255)]]}
    report={}
    for name,wanted in rows.items():
        width,height,pixels,_=png.decode((directory/name/'image-00.png').read_bytes(),output=True)
        actual=[[tuple(pixels[4*(y*width+x):4*(y*width+x)+4]) for x in range(width)] for y in range(height)]
        assert actual==wanted,(name,actual,wanted);report[name]={'dimensions':[width,height],'literalRows':wanted,'everyRGBAChannelExact':True}
    width,height,pixels,_=png.decode((directory/'sheet/sheet.png').read_bytes(),output=True);assert (width,height)==(11,6)
    expected=[[(240,240,240,255)]*11 for _ in range(6)]
    for y,row in enumerate(rows['baseline']):expected[y+1][1:5]=row
    for y,row in enumerate([[cyan,yellow,blue],[hidden,green,red]]):expected[y+1][6:9]=[(*pixel[:3],255) for pixel in row]
    actual=[[tuple(pixels[4*(y*width+x):4*(y*width+x)+4]) for x in range(width)] for y in range(height)]
    assert actual==expected,(actual,expected);report['sheet']={'dimensions':[width,height],'everyRGBAChannelExact':True,'placements':[[1,1],[6,1]],'metadataIndexOnly':True}
    return report


def hostile(directory,opaque_directory,transparent_directory):
    report={};saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    def restore():
        for p,data in saved.items():p.write_bytes(data)
    for name,target,change in [
        ('wrongPixel','image-00.png',lambda b:fixture([[(1,2,3,255)]])),
        ('wrongSheet','sheet.png',lambda b:fixture(GRID)),
        ('trustedPolicy','config/policy.xml',lambda b:b.replace(b'pattern="PNG"',b'pattern="*"',1)),
        ('nativePolicyReadback','policy.stdout',lambda b:b.replace(b'pattern: PNG',b'pattern: *',1)),
        ('nativeCommand','prepare-00-launcher.py',lambda b:b.replace(b"'-sample', '200%'",b"'-sample', '300%'"))]:
        try:
            path=directory/target;before=path.read_bytes();changed=change(before);assert before!=changed,name;path.write_bytes(changed);refresh(directory)
            report[name+'WithRefreshedHashes']=refused(lambda:adaptor.verify(directory))
        finally:restore()
    try:
        # Rebind capture and submission hashes: independently reconstructed pixels
        # must still reject images generated from a different captured source.
        path=directory/'captured-00.png';path.write_bytes(fixture([[(255,255,255,255),*GRID[0][1:]],GRID[1]]))
        capture=adaptor.read(directory,'captures.json');capture[0].update(sha256=adaptor.digest(directory,'captured-00.png'),bytes=path.stat().st_size);atomic_json(directory/'captures.json',capture)
        for stage in ['prepare-00']:
            bindings=adaptor.read(directory,stage+'-inputs.json');bindings[str(path)]=adaptor.digest(directory,'captured-00.png');atomic_json(directory/(stage+'-inputs.json'),bindings)
        refresh(directory);report['changedCaptureWithRefreshedBindings']=refused(lambda:adaptor.verify(directory))
    finally:restore()
    for name,mutate in [('forgedMembership',lambda r:r['artifacts'].pop()),('missingEvidence',lambda r:r['evidence'].pop('prepare-00.stdout')),('extraEvidence',lambda r:r['evidence'].update({'unowned.json':'0'*64})),('forgedRuntime',lambda r:r.update(runtime='Version: ImageMagick 9.9.9'))]:
        try:
            receipt=adaptor.read(directory,'verification.json');mutate(receipt);atomic_json(directory/'verification.json',receipt);report[name]=refused(lambda:adaptor.verify(directory))
        finally:restore()
    try:
        submission=adaptor.read(directory,'prepare-00-submission.json');submission['nativeCommand']=['/forged/native'];atomic_json(directory/'prepare-00-submission.json',submission);refresh(directory);report['forgedSubmissionWithRefreshedHashes']=refused(lambda:adaptor.verify(directory))
    finally:restore()
    opaque_saved={p:p.read_bytes() for p in opaque_directory.rglob('*') if p.is_file()}
    for name,data in [('equivalentRGBOutput',fixture([[(20,40,60,255),(0,255,255,255)],[(10,148,30,255),(79,94,45,255)]],rgba=False,tagged=False)),
            ('taggedRGBAOutput',fixture([[(20,40,60,255),(0,255,255,255)],[(10,148,30,255),(79,94,45,255)]]))]:
        try:
            (opaque_directory/'image-00.png').write_bytes(data);refresh(opaque_directory)
            report[name+'WithRefreshedHashes']=refused(lambda:adaptor.verify(opaque_directory))
        finally:
            for p,data in opaque_saved.items():p.write_bytes(data)
    transparent_saved={p:p.read_bytes() for p in transparent_directory.rglob('*') if p.is_file()}
    try:
        (transparent_directory/'image-00.png').write_bytes(fixture([[(255,255,0,64),(0,255,0,128)],[(0,255,255,255),(0,0,0,0)]],tagged=False));refresh(transparent_directory)
        report['hiddenTransparentRGBWithRefreshedHashes']=refused(lambda:adaptor.verify(transparent_directory))
    finally:
        for p,data in transparent_saved.items():p.write_bytes(data)
    assert adaptor.verify(directory)['verified'];assert adaptor.verify(opaque_directory)['verified'];return report


def native_policy_probes(directory,executable):
    # Deliberate trusted probes, never exposed as authored native options.
    env={'LANG':'C','LC_ALL':'C','HOME':str(directory/'config'),'XDG_CONFIG_HOME':str(directory/'config'),'MAGICK_CONFIGURE_PATH':str(directory/'config'),'MAGICK_TEMPORARY_PATH':str(directory/'config'),'MAGICK_THREAD_LIMIT':'1'}
    target=str(directory/'sheet.png');captured=str(directory/'captured-00.png');before=(directory/'sheet.png').read_bytes()
    forbidden=directory/'forbidden.png';forbidden.write_bytes(fixture(GRID))
    svg=directory/'hostile.svg';svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>')
    cases={'unlistedPath':[str(forbidden),target],'svgCoder':['SVG:'+str(svg),target],'indirectRead':['@'+captured,target],'httpsDelegate':['HTTPS://127.0.0.1:9/not-networked.png',target],'pseudoImage':['xc:red',target],'nonPNGOutput':[captured,str(directory/'forbidden.jpg')]}
    report={}
    for name,args in cases.items():
        result=subprocess.run([executable,*args],cwd=directory,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        assert result.returncode!=0,(name,result.stdout,result.stderr)
        message=result.stderr.lower()
        denied=b'security policy' in message or b'not authorized' in message or b'notauthorized' in message
        unavailable=name=='pseudoImage' and b'nodecodedelegateforthisimageformat' in message
        assert denied or unavailable,(name,result.stderr)
        assert (directory/'sheet.png').read_bytes()==before,name
        report[name]={'exitCode':result.returncode,'denial':'native security policy' if denied else 'pseudo coder unavailable under minimal child environment','stderr':result.stderr.decode(errors='replace')[:1500]}
    forbidden.unlink();svg.unlink();return report


def interrupted_processes(directory,document):
    wrapper=directory/'slow-runtime.py';marker=directory/'slow.pid'
    wrapper.write_text('#!'+sys.executable+'\nimport os,time\nfrom pathlib import Path\nPath('+repr(str(marker))+').write_text(str(os.getpid()))\ntime.sleep(30)\n');wrapper.chmod(0o700)
    results={}
    for action in ['timeout','cancel']:
        if marker.exists():marker.unlink()
        cancel=threading.Event()
        def trigger():
            end=time.monotonic()+5
            while not marker.exists() and time.monotonic()<end:time.sleep(.01)
            if marker.exists():cancel.set()
        thread=threading.Thread(target=trigger,daemon=True) if action=='cancel' else None
        if thread:thread.start()
        try:
            with allocation({'threads':1,'ranks':1},cancel):results[action]=refused(lambda:adaptor.run(document,directory/('inflight-'+action),executable=str(wrapper),timeout=8 if thread else .4),'RUNNER_CANCELLED' if thread else 'RUNNER_TIMED_OUT')
        finally:
            if thread:thread.join(6)
        assert marker.exists(),'lifecycle double did not launch owned process'
        try:os.kill(int(marker.read_text()),0)
        except ProcessLookupError:pass
        else:raise AssertionError('owned process survived '+action)
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--imagemagick',type=Path,required=True);parser.add_argument('--output-directory',type=Path,required=True);parser.add_argument('--register',action='store_true')
    args=parser.parse_args();directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False);executable=str(args.imagemagick.resolve());locations={'imagemagick':executable};report={'verified':False}
    try:
        receipt=qualify(adaptor.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=30,wall_timeout=45)
        report['native']={'verified':receipt['verified'],'cases':[c['id'] for c in receipt['cases']],'runtimes':[c['runtime'] for c in receipt['cases']],'lifecycle':receipt['lifecycle']}
        report['literalPixels']=literal_cases(directory/'kit');report['hostile']=hostile(directory/'kit/sheet',directory/'kit/flatten',directory/'kit/variant');report['policyDenials']=native_policy_probes(directory/'kit/sheet',executable)
        _,_,entry=route_materials(adaptor.VERSION);doc=case_document(entry,entry['development']['cases'][0],ROOT)
        bad=copy.deepcopy(doc);bad['images'][0]['crop']['x']=3
        report['cropRejectedBeforeNative']=refused(lambda:adaptor.run(bad,directory/'bad-crop',executable=executable),'RASTER_CROP_OUTSIDE');assert not (directory/'bad-crop/version-submission.json').exists()
        src=directory/'source.png';shutil.copyfile(doc['images'][0]['source'],src);doc['images'][0]['source']=str(src)
        consumer={'version':adaptor.VERSION,'operation':'raster','images':[{'id':'reusedDetail','source':{'$artifact':'prepare','index':0},'quarterTurns':1}],'colourPolicy':'assume-srgb'}
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'prepare','document':doc},{'id':'compare','document':consumer}]}
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30);assert workflow.verify(directory/'workflow')['verified']
        second=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert all(j['reused'] for j in second['jobs'])
        src.write_bytes((ROOT/'examples/schemaxis/fixtures/imagemagick/grid-changed.png').read_bytes())
        third=workflow.execute(graph,directory/'workflow',locations=locations,timeout=30,resume=True);assert all(not j['reused'] for j in third['jobs']);assert workflow.verify(directory/'workflow')['verified']
        report['workflow']={'baseline':first['status'],'PNGArtifactHandoff':True,'unchangedReused':True,'changedSamePathSourceBytesReused':False}
        study=copy.deepcopy(doc);study['axes']=[{'name':'scale','values':[1,2]}];study['images'][0]['scale']={'$axis':'scale'}
        outcome=adaptor.run(study,directory/'study',executable=executable,timeout=30);assert len(outcome['states'])==2;assert adaptor.verify(directory/'study')['verified'];report['composition']={'states':2,'verified':True}
        report['inflightLifecycle']=interrupted_processes(directory,doc)
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
