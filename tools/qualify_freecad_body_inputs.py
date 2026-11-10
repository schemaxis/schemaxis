#!/usr/bin/env python3
"""Qualify checked imported Body stock through pinned workflow inputs.

Run from the repository root with PYTHONPATH=src. Uses only programme-generated
projects and copied public fixtures. Broader topology attacks and application
coverage are separate from this focused adoption/workflow qualification.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import shutil

from schemaxis import captured_inputs, workflow
from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors import registry
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError


def qualify(root,executable,gui):
    root.mkdir(parents=True,exist_ok=False)
    (root/'snapshots').mkdir()
    locations={'freecad':str(executable)}
    if gui:locations['freecad_gui']=str(gui)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{},
            'scope':'checked STL/STEP Body stock, pinned inputs, sourced assembly workflow and recovery'}
    def record(name,value):
        report['checks'][name]=value;atomic_json(root/'report.json',report)
    def refused(document,code):
        try:workflow.execute(document,root/'workflow',locations=locations,timeout=600,resume=True)
        except SchemaxisError as error:
            assert error.fault.code==code,error.fault
            return error.fault.to_dict()
        raise AssertionError('Changed input was accepted: '+code)
    def jobs(result):return {job['operation']:Path(job['directory']) for job in result['jobs']}
    try:
        operations=[];adopted={};originals=[]
        fixtures=(('stock','freecad-body-stock.json',6021.825229575319),
                  ('turned','freecad-body-stock-turned.json',1200-5*math.pi),
                  ('step','freecad-body-step-stock.json',10840-10*math.pi),
                  ('seed','freecad-body-stock-turned.json',1200.0))
        for name,example,expected in fixtures:
            document=json.loads(Path('examples/schemaxis',example).read_text())
            if name=='seed':
                document['nodes']=document['nodes'][:3];document['output']='seed'
            supplied=Path(document['nodes'][0]['options']['file'])
            # Materially different STL files deliberately share one basename.
            original=root/'originals'/name/('casting'+supplied.suffix)
            original.parent.mkdir(parents=True);shutil.copyfile(supplied,original);originals.append(original)
            pin=captured_inputs.adopt(original,root/'snapshots'/name)
            adopted[name]=pin;document['nodes'][0]['options']['file']=pin['reference']
            operations.append({'id':name,'document':document})
        assembly={'version':'schemaxis.freecad.assembly/1',
            'parts':[{'id':name,'source':{'$artifact':name,'index':2},
                      'mounts':{'base':{},'next':{'position':[65,0,0]}}} for name in ('stock','turned')],
            'components':[{'id':'fixed','part':'stock'},{'id':'second','part':'turned'},{'id':'third','part':'stock'}],
            'grounded':'fixed','joints':[
                {'id':'one','type':'fixed','parent':{'component':'fixed','mount':'next'},'child':{'component':'second','mount':'base'}},
                {'id':'two','type':'fixed','parent':{'component':'second','mount':'next'},'child':{'component':'third','mount':'base'}}]}
        operations.append({'id':'assembly','document':assembly})
        # First/final seed-only stock has a native empty inline string table.
        # Keep its ordinary assembly composition separate from hashed histories.
        seed_assembly={'version':'schemaxis.freecad.assembly/1',
            'parts':[{'id':'stock','source':{'$artifact':'seed','index':2},
                      'mounts':{'base':{},'next':{'position':[36,-4,2]}}}],
            'components':[{'id':'fixed','part':'stock','position':[-7,2,6],'rotation':-19},
                          {'id':'copy','part':'stock'}],
            'grounded':'fixed','joints':[{'id':'join','type':'fixed',
                'parent':{'component':'fixed','mount':'next'},
                'child':{'component':'copy','mount':'base'},'clocking':41}]}
        operations.append({'id':'seedAssembly','document':seed_assembly})
        document={'version':'schemaxis.workflow/1','execution':{'maxWorkers':1,'cpus':2,'memoryMB':3072,'gpus':0},
                  'operations':operations}
        atomic_json(root/'workflow-authored.json',document)
        # Actual native readers must consume the copied snapshots alone.
        for original in originals:original.unlink()
        result=workflow.execute(document,root/'workflow',locations=locations,timeout=600)
        assert workflow.verify(root/'workflow')['verified'];directories=jobs(result)
        native={}
        for name,_,expected in fixtures:
            receipt=json.loads((directories[name]/'verification.json').read_text())
            volume=receipt['native']['volume']
            assert abs(volume-expected)<1e-7,(name,volume,expected)
            assert registry.verify(directories[name])['verified']
            native[name]={'volumeMM3':volume,'independentExpectedMM3':expected,
                          'nativeSha256':file_digest(directories[name]/'model.FCStd')}
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        for name in ('seed','seedAssembly'):
            with ZipFile(directories[name]/'model.FCStd') as archive:
                xml=ET.fromstring(archive.read('Document.xml'))
                assert xml.find('StringHasher2') is None
                assert xml.find('StringHasher').attrib=={'saveall':'0','threshold':'0','count':'0'}
        record('native-imports-original-files-removed',native)
        def rotate(point,degrees):
            angle=math.radians(degrees);c,s=math.cos(angle),math.sin(angle)
            return [c*point[0]-s*point[1],s*point[0]+c*point[1],point[2]]
        def add(a,b):return [x+y for x,y in zip(a,b)]
        def source_point(point):return add(rotate(point,31),[3,4,5])
        receipt=json.loads((directories['seedAssembly']/'verification.json').read_text())
        poses=receipt['snapshots']['persisted']['components'];fixed=[-7,2,6]
        origins=[fixed,add(fixed,rotate([36,-4,2],-19))];expected={}
        for index,(name,angle) in enumerate((('fixed',-19),('copy',22))):
            def world(point):return add(rotate(source_point(point),angle),origins[index])
            corners=[world([x,y,z]) for x in (0,20) for y in (0,12) for z in (0,5)]
            centre=world([10,6,2.5]);bounds=[f(p[d] for p in corners) for d in range(3) for f in (min,max)]
            shape=poses[name]['shape']
            assert abs(shape['volume']-1200)<1e-7 and abs(shape['area']-800)<1e-7
            assert max(abs(a-b) for a,b in zip(shape['centreOfMass'],centre))<1e-7
            assert max(abs(a-b) for a,b in zip(shape['bounds'],bounds))<1e-7
            expected[name]={'volumeMM3':1200,'areaMM2':800,'centreMM':centre,'boundsMM':bounds}
        record('seed-only-native-inline-composition',expected)
        reused=workflow.execute(document,root/'workflow',locations=locations,timeout=600,resume=True)
        assert all(job['reused'] for job in reused['jobs']);record('all-six-reused',True)
        saved=directories['assembly']/'model.FCStd';saved.write_bytes(b'damaged owned assembly')
        recovered=workflow.execute(document,root/'workflow',locations=locations,timeout=600,resume=True)
        assert workflow.verify(root/'workflow')['verified']
        states={job['operation']:job['reused'] for job in recovered['jobs']}
        assert states=={'stock':True,'turned':True,'step':True,'seed':True,'assembly':False,'seedAssembly':True};record('damage-recovery',states)
        directories=jobs(recovered)
        changed=copy.deepcopy(document)
        changed['operations'][0]['document']['nodes'][0]['options']['file']['digest']='0'*64
        record('changed-pin-refused',refused(changed,'RESUME_MISMATCH'))
        # Same authored pin, physical checkpoint corruption: no job may silently
        # rebuild from changed bytes, and restoring the checkpoint permits reuse.
        pin=adopted['stock'];asset=Path(pin['snapshot'])/'data'/pin['reference']['member'];data=asset.read_bytes()
        asset.write_bytes(data+b' changed')
        try:
            try:workflow.execute(document,root/'workflow',locations=locations,timeout=600,resume=True)
            except SchemaxisError as error:
                assert error.fault.code in ('RESOURCE_MISMATCH','INPUT_CHANGED'),error.fault
                record('changed-snapshot-bytes-refused',error.fault.to_dict())
            else:raise AssertionError('Changed checkpoint bytes were silently consumed')
        finally:asset.write_bytes(data)
        restored=workflow.execute(document,root/'workflow',locations=locations,timeout=600,resume=True)
        assert all(job['reused'] for job in restored['jobs']);record('restored-snapshot-reuse',True)
        # Verify the assembly's captured typed intent and embedded originals
        # independently after retiring all producer packets AND snapshots.
        moves=[];before=file_digest(directories['assembly']/'model.FCStd')
        try:
            for name in ('stock','turned','step','seed'):
                original=directories[name];retired=original.with_name(original.name+'-retired')
                original.rename(retired);moves.append((original,retired))
            original=root/'snapshots';retired=root/'retired-snapshots';original.rename(retired);moves.append((original,retired))
            assert registry.verify(directories['assembly'])['verified']
            assert registry.verify(directories['seedAssembly'])['verified']
            assert before==file_digest(directories['assembly']/'model.FCStd')
            record('standalone-producers-and-snapshots-removed',{'verified':True,'nativeSha256':before})
        finally:
            for original,retired in reversed(moves):retired.rename(original)
        assert workflow.verify(root/'workflow')['verified'];record('restored-workflow',True)
        assert report['sourceDigest']==source_digest('freecad')
        report['verified']=True
    finally:atomic_json(root/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freecad',type=Path,required=True)
    parser.add_argument('--freecad-gui',type=Path)
    parser.add_argument('--output-directory',type=Path,required=True)
    args=parser.parse_args()
    with location_context({'freecad':str(args.freecad),**({'freecad_gui':str(args.freecad_gui)} if args.freecad_gui else {})}):
        result=qualify(args.output_directory.absolute(),args.freecad,args.freecad_gui)
    print(json.dumps({'verified':result['verified'],'sourceDigest':result['sourceDigest']}))


if __name__=='__main__':main()
