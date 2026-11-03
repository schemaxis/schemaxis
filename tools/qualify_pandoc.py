#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Bounded Pandoc report qualification, hostile evidence and workflow reuse."""
import argparse
import copy
import io
import json
from pathlib import Path
import shutil
import zipfile

from schemaxis.adaptor_conformance import qualify, register
from schemaxis.adaptor_delivery import case_document, route_materials
from schemaxis.adaptors.pandoc import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow

ROOT=Path(__file__).resolve().parents[1]


def refused(action,code='VERIFICATION_FAILED'):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code==code,error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('invalid evidence accepted')


def refresh(directory):
    """Refresh ordinary hashes; semantic checks must still reject forged content."""
    receipt=adaptor.read(directory,'verification.json')
    receipt['artifacts']=adaptor.artifacts(directory)
    receipt['evidence']={name:adaptor.digest(directory,name) for name in receipt['evidence']}
    atomic_json(directory/'verification.json',receipt)
    # Common publication metadata is independent of native semantics.
    from schemaxis.publication_metadata import finalise
    finalise(directory)


def negative(directory,report):
    saved={p:p.read_bytes() for p in directory.rglob('*') if p.is_file()}
    def restore():
        for p,data in saved.items(): p.write_bytes(data)
    for name in ('report.html','reopened.json','report.docx','report-input.json'):
        try:
            path=directory/name
            if name=='report.docx':
                buffer=io.BytesIO()
                with zipfile.ZipFile(path) as old,zipfile.ZipFile(buffer,'w') as new:
                    for item in old.infolist():
                        data=old.read(item.filename)
                        if item.filename=='word/document.xml':
                            assert b'12.0' in data;data=data.replace(b'12.0',b'99.0',1)
                        new.writestr(item,data)
                path.write_bytes(buffer.getvalue())
                # Refresh binding to force independent OOXML acceptance, beyond stale readback guard.
                inputs=adaptor.read(directory,'reopen-inputs.json');inputs[str(directory/'report.docx')]=adaptor.digest(directory,'report.docx');atomic_json(directory/'reopen-inputs.json',inputs)
            else:
                data=path.read_bytes();assert b'12.0' in data;path.write_bytes(data.replace(b'12.0',b'99.0',1))
            refresh(directory)
            report[name+'WithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
        finally: restore()
    try:
        path=directory/'report.html';path.write_text(path.read_text().replace('<p>Measured','<p hidden=\"hidden\">Measured',1));refresh(directory)
        report['hiddenHTMLWithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
    finally:restore()
    for label,old,new in [
        ('eventAttribute','<html xmlns=', '<html onload="alert(1)" xmlns='),
        ('metaRefresh','<meta charset="utf-8" />','<meta http-equiv="refresh" content="0;url=https://invalid.example" />'),
        ('externalCSS','<style>','<style>@import "https://invalid.example/style.css";'),
        ('hiddenBodyStylesheet','</style>','body { display:none }</style>'),
        ('transparentParagraphStylesheet','</style>','p { opacity:0 }</style>'),
        ('externalMedia','data:image/png;base64,','https://invalid.example/')]:
        try:
            path=directory/'report.html';source=path.read_text();assert old in source;path.write_text(source.replace(old,new,1));refresh(directory)
            report[label+'WithRefreshedHashes']=refused(lambda:adaptor.verify(directory))['code']
        finally:restore()
    try:
        # Preserve ordinary receipts while changing the retained native input.
        path=directory/'report.docx';path.write_bytes(path.read_bytes()+b'changed archive trailer');refresh(directory)
        error=refused(lambda:adaptor.verify(directory));assert 'consumed different' in error['message'];report['staleNativeReadbackBinding']=error['code']
    finally:restore()
    assert adaptor.verify(directory)['verified']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pandoc',required=True,type=Path)
    parser.add_argument('--output-directory',required=True,type=Path)
    parser.add_argument('--register',action='store_true',help='retain successful source-bound native qualification in adaptor package')
    args=parser.parse_args();directory=args.output_directory.resolve();directory.mkdir(parents=True,exist_ok=False)
    locations={'pandoc':str(args.pandoc.resolve())};report={'verified':False,'negative':{}}
    try:
        receipt=qualify(adaptor.VERSION,directory/'kit',native=True,root=ROOT,locations=locations,timeout=60,wall_timeout=90)
        report['native']={'verified':receipt['verified'],'cases':[c['id'] for c in receipt['cases']],'runtime':[c['runtime'] for c in receipt['cases']],'lifecycle':receipt['lifecycle']}
        baseline=directory/'kit/calibration-report';negative(baseline,report['negative'])
        _,_,entry=route_materials(adaptor.VERSION);document=case_document(entry,entry['development']['cases'][0],ROOT)
        image=directory/'source.png';shutil.copyfile(document['sections'][1]['content'][1]['source'],image)
        document['sections'][1]['content'][1]['source']=str(image)
        graph={'version':'schemaxis.workflow/1','operations':[{'id':'report','document':document}]}
        first=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60);assert workflow.verify(directory/'workflow')['verified']
        resumed=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60,resume=True);assert resumed['jobs'][0]['reused']
        # Valid changed image bytes with identical pixel content still invalidate byte identity.
        data=image.read_bytes();import struct,zlib
        pos=8;parts=[]
        while pos<len(data):
            length=struct.unpack('>I',data[pos:pos+4])[0];kind=data[pos+4:pos+8];body=data[pos+8:pos+8+length]
            if kind==b'IDAT':body=zlib.compress(zlib.decompress(body),level=0)
            parts.append(struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)));pos+=12+length
        image.write_bytes(data[:8]+b''.join(parts));adaptor.png(image.read_bytes(),'changed image')
        changed=workflow.execute(graph,directory/'workflow',locations=locations,timeout=60,resume=True);assert not changed['jobs'][0]['reused'];assert workflow.verify(directory/'workflow')['verified']
        report['workflow']={'baseline':first['status'],'unchangedReused':True,'changedImageReused':False}
        # Shared authored bindings and a finite study exercise effective schema execution.
        study=copy.deepcopy(document);study['definitions']={'title':'Bound calibration report'};study['title']={'$document':'/definitions/title'}
        study['axes']=[{'name':'width','values':[40,70]}];study['sections'][1]['content'][1]['widthMm']={'$axis':'width'}
        result=adaptor.run(study,directory/'study',executable=locations['pandoc'],timeout=60);assert adaptor.verify(directory/'study')['verified'];assert len(result['states'])==2
        report['composition']={'states':2,'verified':True}
        if args.register:register(directory/'kit/qualification.json')
        report['verified']=True
    finally:atomic_json(directory/'acceptance.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
