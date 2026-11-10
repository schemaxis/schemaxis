#!/usr/bin/env python3
"""Native design-history qualification with independent geometry and saved attacks."""
import argparse
import copy
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import adaptor
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.core.runners import Interpreter
from schemaxis.dispatch import SubprocessRunner
ROOT=Path(__file__).resolve().parents[1]


def hostile(target):
    """Refresh the publication digest, then require semantic XML failures."""
    path=target/'model.FCStd';original=path.read_bytes();receipt_path=target/'verification.json';receipt_bytes=receipt_path.read_bytes()
    with ZipFile(path) as archive:entries={n:archive.read(n) for n in archive.namelist()}
    prepared=json.loads((target/'plan.json').read_text());mapped={n['id']:'N'+str(i) for i,n in enumerate(prepared['nodes'])}
    def prop(root,identity,key):return root.find("./ObjectData/Object[@name='%s']/Properties/Property[@name='%s']"%(mapped[identity],key))
    changes={
        'wrong-body-tip':lambda r:prop(r,'enclosure','Tip').find('Link').set('value',mapped['stock']),
        'stale-pad-base':lambda r:prop(r,'boss2','BaseFeature').find('Link').set('value',mapped['stock']),
        'wrong-pocket-direction':lambda r:prop(r,'finished','Reversed').find('Bool').set('value','true'),
        'detached-boss-sketch':lambda r:prop(r,'bossProfile1','MapMode').find('Integer').set('value','0'),
        'wrong-support':lambda r:prop(r,'bossProfile1','AttachmentSupport').find('LinkSubList/Link').set('obj',mapped['stock']),
        'changed-slot-radius':lambda r:next(c for c in prop(r,'ventProfile','Constraints').find('ConstraintList') if c.get('Name')=='radius').set('Value','2'),
        'changed-slot-arc':lambda r:prop(r,'ventProfile','Geometry').find('GeometryList/Geometry/LineSegment').set('StartX','-5'),
        'changed-driver':lambda r:prop(r,'stock','ExpressionEngine').find('ExpressionEngine/Expression').set('expression','2 * SchemaxisParameters.dim_height + 0 mm')}
    report={}
    for name,change in changes.items():
        try:
            xml=ET.fromstring(entries['Document.xml']);change(xml)
            with ZipFile(path,'w') as archive:
                for member,data in entries.items():archive.writestr(member,ET.tostring(xml) if member=='Document.xml' else data)
            receipt=json.loads(receipt_bytes);receipt['artifacts'][2]['sha256']=file_digest(path);atomic_json(receipt_path,receipt)
            try:adaptor._verify(target)
            except SchemaxisError as error:
                assert error.fault.code=='VERIFICATION_FAILED' and 'digest' not in error.fault.message.lower();report[name]=error.fault.code
            else:raise AssertionError('saved design-history attack accepted: '+name)
        finally:path.write_bytes(original);receipt_path.write_bytes(receipt_bytes)
    assert registry.verify(target)['verified'];return report


def qualify(directory,executable):
    directory=Path(directory).absolute();directory.mkdir(parents=True,exist_ok=False)
    report={'verified':False,'sourceDigest':source_digest('freecad'),'checks':{}}
    enclosure=json.loads((ROOT/'examples/schemaxis/freecad-parametric-enclosure.json').read_text())
    lid=json.loads((ROOT/'examples/schemaxis/freecad-parametric-enclosure-lid.json').read_text())
    for identity,document,expected in [('enclosure',enclosure,10128+60*math.pi),('lid',lid,3528-3*math.pi)]:
        target=directory/identity;registry.run(document,target,locations={'freecad':executable},timeout=120)
        result=registry.verify(target);assert math.isclose(result['volumeMM3'],expected,rel_tol=1e-8,abs_tol=1e-6)
        report['checks'][identity]={'verified':True,'volumeMM3':result['volumeMM3'],'expectedMM3':expected};print(identity+' verified',flush=True)
    from freecad_history_cases import cases
    for identity,document,expected in cases():
        target=directory/identity;registry.run(document,target,locations={'freecad':executable},timeout=120)
        result=registry.verify(target);assert math.isclose(result['volumeMM3'],expected,rel_tol=1e-8,abs_tol=1e-6),(identity,result['volumeMM3'],expected)
        report['checks'][identity]={'verified':True,'volumeMM3':result['volumeMM3'],'expectedMM3':expected};print(identity+' verified',flush=True)
    report['checks']['saved-attacks']=hostile(directory/'enclosure')
    worker=SubprocessRunner(Interpreter('freecad',executable),directory,timeout=120)
    for mode in ('edit','reopen'):
        script='import sys\nsys.path.insert(0,'+repr(str(directory/'enclosure/runtime.zip'))+')\nsys.path.insert(0,'+repr(str(ROOT/'tools'))+')\nfrom qualify_freecad_histories_native import main\nmain('+repr(str(directory))+','+repr(mode)+')\n'
        atomic_json(directory/('native-'+mode+'-submission.json'),worker(script).to_dict())
        assert (directory/('native-'+mode+'.json')).is_file(),'independent native edit worker failed: '+mode
    first=json.loads((directory/'native-edit.json').read_text());second=json.loads((directory/'native-reopen.json').read_text())
    assert first['verified'] and second['verified'] and first['pid']!=second['pid']
    assert first['edited']==second['baseline'] and first['expressions']==second['expressions'] and first['attachments']==second['attachments']
    report['checks']['edit-save-fresh-reopen-second-edit']={'verified':True,'runtime':first['runtime'],'first':first['edited'],'second':second['edited'],'nativeAttachmentLinksPreserved':True,'nativeDriverExpressionsPreserved':True}
    report['verified']=True;atomic_json(directory/'acceptance.json',report);return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--freecad',required=True);parser.add_argument('--output-directory',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(qualify(args.output_directory,args.freecad),indent=2))

if __name__=='__main__':main()
