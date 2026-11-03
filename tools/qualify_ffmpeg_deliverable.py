#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Bounded media intent, lossless/lossy readback and rejection acceptance."""
import argparse
import copy
import json
from pathlib import Path
import struct
import zlib

from schemaxis.adaptors.ffmpeg import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.publication_metadata import finalise
from schemaxis.core.faults import SchemaxisError


def image(width, height, colour):
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+(bytes(colour)*width if colour is not None else bytes(
        (x*31+y*47+c*83)%256 if c<3 else 255 for x in range(width) for c in range(4)))
        for y in range(height))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            +chunk(b'IDAT', zlib.compress(raw))+chunk(b'IEND', b''))


def expect_fault(callback, code):
    try:
        callback()
    except SchemaxisError as error:
        if error.fault.code != code:
            raise AssertionError(f'expected {code}, observed {error.fault.code}') from error
        return error.fault.to_dict()
    raise AssertionError(f'expected {code}, operation succeeded')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=60)
    args=parser.parse_args()
    root=args.output_directory.absolute();root.mkdir(parents=True, exist_ok=False)
    sources=[]
    for index, colour in enumerate(((220, 30, 10, 255), (20, 130, 210, 255))):
        path=root/f'frame-{index}.png';path.write_bytes(image(32,24,colour));sources.append(str(path))
    document={'version':'schemaxis.ffmpeg/1','nodes':[{'id':'movie','filter':'encodeFrames',
        'options':{'files':sources,'codec':'ffv1','fps':25}}],
        'deliverable':{'width':32,'height':24,'frames':2,'durationSeconds':.08,
            'durationToleranceSeconds':.001,'maxBytes':100000,'maxMeanRGBError':0}}
    checks={}
    for codec in ('ffv1','h264'):
        candidate=copy.deepcopy(document);candidate['nodes'][0]['options']['codec']=codec
        candidate['deliverable']['maxMeanRGBError']=0 if codec=='ffv1' else 16
        output=root/codec
        result=adaptor.run(candidate,output,executable=args.executable,timeout=args.timeout)
        observed=adaptor.verify(output)
        assert observed['deliverable']['accepted'] and result['deliverable']==observed['deliverable']
        assert observed['deliverable']['observed']['frames']==2
        assert observed['deliverable']['observed']['bytes']==(output/adaptor.plan(candidate)['output']).stat().st_size
        publication=output/adaptor.plan(candidate)['output'];original=publication.read_bytes()
        try:
            publication.write_bytes(original+b'altered')
            tamper=expect_fault(lambda:adaptor.verify(output),'VERIFICATION_FAILED')
        finally:
            publication.write_bytes(original)
        verification=output/'verification.json';saved_receipt=verification.read_bytes()
        try:
            publication.write_bytes(b'\0'*len(original))
            receipt=json.loads(saved_receipt)
            receipt['artifacts'][0]['sha256']=adaptor.file_digest(publication)
            atomic_json(verification,receipt);finalise(output)
            readback_tamper=expect_fault(lambda:adaptor.verify(output),'VERIFICATION_FAILED')
            assert 'consumed different encoded bytes' in readback_tamper['message']
        finally:
            publication.write_bytes(original);verification.write_bytes(saved_receipt);finalise(output)
        assert adaptor.verify(output)['nativeReadbackBound']
        stage=output/'encode-submission.json';original=stage.read_bytes()
        try:
            submission=json.loads(original);submission['exitCode']=1;atomic_json(stage,submission)
            stage_tamper=expect_fault(lambda:adaptor.verify(output),'VERIFICATION_FAILED')
        finally:
            stage.write_bytes(original)
        checks[codec]={'verification':observed,'changedPublication':tamper['code'],
            'changedCompletion':stage_tamper['code'],'refreshedPublicationReadbackTamper':readback_tamper['code']}
    sheet=root/'sheet.png';sheet.write_bytes(image(64,24,(40,80,120,255)))
    metadata=root/'sheet.json'
    atomic_json(metadata,{'version':'schemaxis.aseprite.sheet/1','width':64,'height':24,
        'frames':[{'x':0,'y':0,'width':32,'height':24,'durationMS':120},
                  {'x':32,'y':0,'width':32,'height':24,'durationMS':200}],'tags':[]})
    sprite={'version':'schemaxis.ffmpeg/1','nodes':[{'id':'movie','filter':'encodeSheet',
        'options':{'file':str(sheet),'metadata':str(metadata),'codec':'ffv1','fps':25}}],
        'deliverable':{'width':32,'height':24,'frames':8,'durationSeconds':.32,
            'maxBytes':100000,'maxMeanRGBError':0}}
    adaptor.run(sprite,root/'sheet',executable=args.executable,timeout=args.timeout)
    checks['sheet']=adaptor.verify(root/'sheet')
    for label, requirements in (('byte-budget',{'maxBytes':1}), ('wrong-duration',{'durationSeconds':1}),
                                ('wrong-size',{'width':30}), ('strict-lossy-quality',{'maxMeanRGBError':0})):
        candidate=copy.deepcopy(document);candidate['deliverable']=requirements
        if label=='strict-lossy-quality':candidate['nodes'][0]['options']['codec']='h264'
        output=root/label
        fault=expect_fault(lambda:adaptor.run(candidate,output,executable=args.executable,timeout=args.timeout),
            'DELIVERABLE_NOT_MET')
        receipt=json.loads((output/'verification.json').read_text())
        assert not receipt['deliverable']['accepted'] and (output/adaptor.plan(candidate)['output']).is_file()
        assert json.loads((output/'result.json').read_text())['verified'] is False
        checks[label]={'fault':fault['code'],'assessment':receipt['deliverable']}
    # Offline evidence remains useful after original input paths disappear.
    for path in [*map(Path,sources),sheet,metadata]:path.unlink()
    for label in ('ffv1','h264','sheet'):assert adaptor.verify(root/label)['verified']
    # Version-3 single-slice encoders can accept tiny fixtures yet fail an
    # ordinary diagram. Nonuniform pixels expose row/edge loss in skinny images.
    shapes={}
    for width,height in ((2,2),(32,24),(400,200),(1,1),(1,64),(64,1),(3,17),(17,3),(640,360)):
        label=f'{width}x{height}';source=root/(label+'.png');source.write_bytes(image(width,height,None))
        candidate={'version':'schemaxis.ffmpeg/1','nodes':[{'id':'movie','filter':'encodeFrames',
            'options':{'files':[str(source)],'codec':'ffv1','fps':25}}],
            'deliverable':{'width':width,'height':height,'frames':1,'maxMeanRGBError':0}}
        output=root/('shape-'+label)
        adaptor.run(candidate,output,executable=args.executable,timeout=args.timeout)
        shapes[label]=adaptor.verify(output)
        # Independent fixture construction checks every RGB edge and row.
        expected=bytes((x*31+y*47+c*83)%256 for y in range(height) for x in range(width) for c in range(3))
        assert (output/'decoded.rgb').read_bytes()==expected
        source.unlink();assert adaptor.verify(output)['verified']
    receipt={'version':'schemaxis.ffmpeg.deliverable-qualification/1','verified':True,
        'scope':'Two ordered 32x24 solid-colour PNGs, H.264/FFV1 full decode; timed 8-frame FFV1 sheet; '
                'size/duration/byte-budget/strict lossy-quality rejection, publication/completion tamper, encoded-byte replacement with refreshed ordinary publication metadata, stage-bound native readback and offline retained sources. '
                'FFV1 version-1 nonuniform RGB checks at 2x2,32x24,400x200,1x1,1x64,64x1,3x17,17x3,640x360 '
                'independently compare every decoded row, edge and channel. '
                'No audio, perceptual certification, scaling or general editing qualification.',
        'checks':checks,'ffv1Dimensions':shapes}
    atomic_json(root/'qualification.json',receipt)
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
