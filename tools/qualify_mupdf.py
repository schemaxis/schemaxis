#!/usr/bin/env python3
"""Native MuPDF qualification with an independent literal fixture oracle."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import struct
import threading
import time
import zlib

from schemaxis.adaptor_conformance import qualify,register
from schemaxis.adaptor_delivery import case_document,route_materials
from schemaxis.adaptors.mupdf import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis import workflow
from qualify_mupdf_fixtures import check as independent_check,fixture

ROOT=Path(__file__).resolve().parents[1]


def refused(action,code='VERIFICATION_FAILED'):
    try:action()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        return code
    raise AssertionError('invalid input/evidence accepted')


def refresh(directory):
    receipt=adaptor.read(directory,'verification.json');prepared=adaptor._native_plan(adaptor.read(directory,'authored.json'))
    receipt['artifacts']=adaptor.artifacts(directory,prepared)
    receipt['evidence']={name:adaptor.digest(directory,name) for name in receipt['evidence']}
    atomic_json(directory/'verification.json',receipt)
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def png_changed(data):
    # Keep CRCs, compression, geometry and ordinary hashes valid while changing
    # raster pixels. Native readback must still reject this altered publication.
    offset=8;chunks=[]
    while offset<len(data):
        size=int.from_bytes(data[offset:offset+4],'big');kind=data[offset+4:offset+8];body=data[offset+8:offset+8+size]
        if kind==b'IDAT':
            pixels=bytearray(zlib.decompress(body));pixels[1]^=255;body=zlib.compress(pixels)
        chunks.append(struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)));offset+=12+size
    return data[:8]+b''.join(chunks)


def negative(directory):
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()};report={}
    def restore():
        for path in directory.glob('page-*'):
            if path not in saved:path.unlink()
        for path,data in saved.items():path.write_bytes(data)
    mutations={
      'png-refreshed':lambda:(directory/'page-001.png').write_bytes(png_changed((directory/'page-001.png').read_bytes())),
      'text-refreshed':lambda:(directory/'page-001.txt').write_text('Forged text\n'),
      'unexpected-page-refreshed':lambda:(directory/'page-999.png').write_bytes((directory/'page-001.png').read_bytes()),
    }
    def source_rebound():
        path=directory/'source.pdf';path.write_bytes(path.read_bytes()+b'\n%changed source\n')
        capture=adaptor.read(directory,'capture.json');capture['bytes']=path.stat().st_size;capture['sha256']=adaptor.digest(directory,'source.pdf');atomic_json(directory/'capture.json',capture)
    mutations['captured-source-rebound-refreshed']=source_rebound
    def altered_metadata():
        for name in ('render.stdout','readback.stdout'):
            data=adaptor.read(directory,name);data['pages'][0]['bounds'][2]+=1;atomic_json(directory/name,data)
    mutations['forged-native-bounds-refreshed']=altered_metadata
    def truncated_native_pages():
        for name in ('render.stdout','readback.stdout'):
            data=adaptor.read(directory,name);data['pages'].pop();atomic_json(directory/name,data)
        data=adaptor.read(directory,'review-summary.json');data['pages'].pop();atomic_json(directory/'review-summary.json',data)
    mutations['truncated-both-native-page-lists-refreshed']=truncated_native_pages
    def boolean_page():
        for name in ('inspect.stdout','render.stdout','readback.stdout'):
            data=adaptor.read(directory,name);data['pages'][1]['page']=True;atomic_json(directory/name,data)
    mutations['boolean-native-page-refreshed']=boolean_page
    def altered_readback_text():
        data=adaptor.read(directory,'readback.stdout');data['pages'][0]['text']='Forged text';atomic_json(directory/'readback.stdout',data)
    mutations['forged-native-text-refreshed']=altered_readback_text
    def altered_script():
        path=directory/'render.js';path.write_text(path.read_text()+'\nprint("forged");\n')
        inputs=adaptor.read(directory,'render-inputs.json');inputs['render.js']=adaptor.digest(directory,'render.js');atomic_json(directory/'render-inputs.json',inputs)
    mutations['trusted-script-refreshed']=altered_script
    for label,mutation in mutations.items():
        try:
            mutation();refresh(directory);report[label]=refused(lambda:adaptor.verify(directory))
        finally:restore()
    assert adaptor.verify(directory)['verified']
    return report


def input_probes(directory,document,executable):
    report={}
    encrypted=directory/'encrypted.pdf'
    # Native encryption builds a real fixture, including empty-user-password
    # encryption. The host never attempts to infer encryption by PDF byte search.
    subprocess.run([executable,'clean','-E','aes-256','-O','fixture-owner','-U','',document['source'],str(encrypted)],check=True,capture_output=True,timeout=20)
    report['emptyPasswordEncrypted']=refused(lambda:adaptor.run({**document,'source':str(encrypted)},directory/'encrypted-run',executable=executable),'ENCRYPTED_PDF')
    data=Path(document['source']).read_bytes();repaired=directory/'repair-required.pdf'
    repaired.write_bytes(data[:data.index(b'xref\n')]+b'%%EOF\n')
    report['nativeRepairRequired']=refused(lambda:adaptor.run({**document,'source':str(repaired)},directory/'repair-run',executable=executable),'PDF_REPAIRED')
    malformed=directory/'malformed.pdf';malformed.write_bytes(b'%PDF-1.7\nnot a PDF document\n')
    try:adaptor.run({**document,'source':str(malformed)},directory/'malformed-run',executable=executable)
    except SchemaxisError as error:report['malformedRejected']=error.fault.code
    else:raise AssertionError('malformed PDF accepted')
    excessive=directory/'too-many-pages.pdf';excessive.write_bytes(fixture(129))
    report['wholeDocumentPageLimit']=refused(lambda:adaptor.run({**document,'source':str(excessive),'pages':[1]},directory/'page-limit-run',executable=executable),'PDF_PAGE_LIMIT')
    giant=directory/'giant-crop.pdf'
    giant.write_bytes(Path(document['source']).read_bytes().replace(b'/MediaBox [10 20 250 200] /CropBox [30 40 210 160]',b'/MediaBox [00 00 999 999] /CropBox [00 00 999 999]'))
    report['pixelLimitBeforeRender']=refused(lambda:adaptor.run({**document,'source':str(giant),'pages':[1],'dpi':300},directory/'pixel-limit-run',executable=executable),'PDF_PIXEL_LIMIT')
    report['missingPage']=refused(lambda:adaptor.run({**document,'pages':[4]},directory/'range-run',executable=executable),'PDF_PAGE_RANGE')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--mupdf',type=Path,required=True)
    parser.add_argument('--ffmpeg',type=Path,help='Optional native lossless page-preview video handoff');parser.add_argument('--output-directory',type=Path,required=True);parser.add_argument('--register',action='store_true');args=parser.parse_args()
    directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False);executable=str(args.mupdf.resolve())
    locations={'mupdf':executable};report={'verified':False}
    try:
        receipt=qualify(adaptor.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=60,wall_timeout=90)
        report['native']={'verified':receipt['verified'],'cases':[c['id'] for c in receipt['cases']],'runtime':[c['runtime'] for c in receipt['cases']],'lifecycle':receipt['lifecycle']}
        report['independent']=[independent_check(directory/'kit/ordered-review',[2,1,3],72,0),independent_check(directory/'kit/density-rotation-order',[3,2,1],144,90)]
        report['tamper']=negative(directory/'kit/ordered-review')
        _,_,entry=route_materials(adaptor.VERSION);document=case_document(entry,entry['development']['cases'][0],ROOT)
        report['input']=input_probes(directory,document,executable)
        # Explicit lifecycle is shared-kit qualified; this additional active
        # cancellation uses a real larger raster and waits for its render stage.
        cancel=threading.Event();active=directory/'active-cancel';observed=[]
        def trigger():
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                path=active/'render.stdout'
                if path.exists():observed.append('render stage opened');cancel.set();return
                time.sleep(.001)
            cancel.set()
        thread=threading.Thread(target=trigger);thread.start()
        try:
            with allocation({'threads':1,'ranks':1},cancel):
                report['activeCancellation']=refused(lambda:adaptor.run({**document,'dpi':300},active,executable=executable,timeout=20),'RUNNER_CANCELLED')
        finally:thread.join(timeout=11)
        assert observed, 'cancellation did not observe active native render dispatch'
        source=directory/'workflow-source.pdf';shutil.copyfile(document['source'],source);document['source']=str(source)
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'review','document':document}]}
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60);assert workflow.verify(directory/'workflow')['verified']
        resumed=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60,resume=True);assert resumed['jobs'][0]['reused']
        source.write_bytes(source.read_bytes()+b'\n%new capture identity\n')
        changed=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60,resume=True);assert not changed['jobs'][0]['reused'];assert workflow.verify(directory/'workflow')['verified']
        report['workflow']={'baseline':first['status'],'unchangedReused':True,'samePathChangedBytesReused':False}
        study=copy.deepcopy(document);study['definitions']={'density':72};study['dpi']={'$document':'/definitions/density'}
        study['axes']=[{'name':'turn','values':[0,180]}];study['rotation']={'$axis':'turn'}
        result=adaptor.run(study,directory/'study',executable=executable,timeout=60);assert adaptor.verify(directory/'study')['verified'];assert len(result['states'])==2
        report['composition']={'states':2,'verified':True}
        if args.ffmpeg:
            handoff=json.loads((ROOT/'examples/schemaxis/mupdf-to-ffmpeg.json').read_text());handoff['operations'][0]['document']['source']=document['source']
            media=workflow.execute(handoff,directory/'page-video',locations={**locations,'ffmpeg':str(args.ffmpeg.resolve())},timeout=60)
            assert workflow.verify(directory/'page-video')['verified']
            report['handoff']={'workflowStatus':media['status'],'format':'FFV1 MKV','frames':2,'seconds':1,'rgbError':0,'scope':'One captured page PNG held for two frames through an actual verified artifact binding; no multipage dimension normalization.'}
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
