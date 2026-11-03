#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Native captured-PNG acceptance: baseline, changed artwork and legacy regression."""
import argparse
import hashlib
import subprocess
import json
from pathlib import Path

from schemaxis.adaptors.aseprite import run, verify
from schemaxis.adaptors.aseprite.adaptor import digest
from schemaxis.adaptors.aseprite.integration import reusableInputs
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

ROOT=Path(__file__).resolve().parents[1]


def example(label):
    d=json.loads((ROOT/f'examples/schemaxis/aseprite-{label}.json').read_text())
    for n in d['nodes']:
        if n['filter']=='importImage':
            n['options']['source']=str(ROOT/'examples/schemaxis/fixtures/aseprite'/Path(n['options']['source']).name)
    return d


def reject(directory):
    try: verify(directory)
    except SchemaxisError as error: return error.fault.code
    raise AssertionError('misleading evidence was accepted: '+str(directory))


def qualify_legacy_receipt(base, executable, timeout):
    """Execute only the pinned, previous trusted worker to produce old evidence."""
    from schemaxis.adaptors.aseprite import plan
    from schemaxis.adaptors.aseprite.adaptor import FILES, artifact_manifest
    from schemaxis.adaptors.aseprite.native_source import LEGACY_PROCEDURAL_WORKER_SHA256
    from schemaxis.publication_metadata import finalise
    source=(ROOT/'examples/schemaxis/fixtures/aseprite/legacy-procedural-worker.lua').read_bytes()
    assert hashlib.sha256(source).hexdigest()==LEGACY_PROCEDURAL_WORKER_SHA256
    base.mkdir();d=example('icon')
    atomic_json(base/'authored.json',d);atomic_json(base/'plan.json',plan(d))
    (base/'worker.lua').write_bytes(source)
    for stage in ['build','reopen']:
        with (base/(stage+'.log')).open('wb') as log:
            subprocess.run([executable,'--batch','--script-param','stage='+stage,'--script',str(base/'worker.lua')],
                cwd=base,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,check=True)
    receipt=json.loads((base/'verification.json').read_text());receipt['artifacts']=artifact_manifest(base)
    atomic_json(base/'verification.json',receipt)
    atomic_json(base/'result.json',{'status':'succeeded','verified':True,
        'sha256':{f:digest(base/f) for f in (*FILES,'verification.json','worker.lua')}})
    finalise(base)
    assert not (base/'input-manifest.json').exists()
    return verify(base)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable',required=True)
    parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=60)
    args=parser.parse_args();base=args.output_directory.absolute();base.mkdir(parents=True,exist_ok=False)
    results={}
    for label in ['import','import-variant','icon','animation']:
        d=example(label);target=base/label
        results[label]=run(d,target,args.executable,args.timeout)
        assert verify(target)['verified']
    first=json.loads((base/'import/verification.json').read_text())
    variant=json.loads((base/'import-variant/verification.json').read_text())
    assert first['native']['durationsMS']==[80,160]
    assert variant['native']['durationsMS']==[80,240]
    assert first['native']['cels']!=variant['native']['cels']
    pixels=bytes.fromhex(first['preview']['pixels'])
    assert pixels[(1*6+2)*4:(1*6+3)*4]==bytes([20,40,80,255])
    cel=bytes.fromhex(first['native']['cels'][1][0])
    assert cel[(1*6+2)*4:(1*6+3)*4]==bytes(4)
    assert reusableInputs(example('import'))!=reusableInputs(example('import-variant'))
    # Overlap within one cel exercises replacement/erasure after native import.
    d=example('import');d['nodes']=d['nodes'][:5]
    d['nodes'].append({'id':'overlap','filter':'importImage','inputs':{'sprite':'import'},
        'options':{'source':example('import-variant')['nodes'][4]['options']['source'],
                   'layer':'art','x':2,'y':1,'width':3,'height':2}})
    d['output']='overlap';results['overlap']=run(d,base/'overlap',args.executable,args.timeout)
    # Shared authored/effective resolution keeps source declarations readable.
    composed=example('import')
    composed['definitions']={'asset':composed['nodes'][4]['options']['source']}
    for n in composed['nodes']:
        if n['filter']=='importImage':n['options']['source']={'$document':'/definitions/asset'}
    results['composed']=run(composed,base/'composed',args.executable,args.timeout)
    assert verify(base/'composed')['verified']
    assert json.loads((base/'composed/authored.json').read_text())==composed
    # Source fingerprints govern resume: same bytes reuse, changed bytes rerun.
    from schemaxis import workflow
    reuse_source=base/'reuse-source.png'
    reuse_source.write_bytes((ROOT/'examples/schemaxis/fixtures/aseprite/badge.png').read_bytes())
    reuse=example('import')
    for n in reuse['nodes']:
        if n['filter']=='importImage':n['options']['source']=str(reuse_source)
    authored={'version':'schemaxis.workflow/1','operations':[{'id':'artwork','document':reuse}]}
    target=base/'reuse-workflow'
    initial=workflow.execute(authored,target,locations={'aseprite':args.executable},timeout=args.timeout)
    unchanged=workflow.execute(authored,target,locations={'aseprite':args.executable},timeout=args.timeout,resume=True)
    assert all(j['reused'] for j in unchanged['jobs'])
    reuse_source.write_bytes((ROOT/'examples/schemaxis/fixtures/aseprite/badge-variant.png').read_bytes())
    changed=workflow.execute(authored,target,locations={'aseprite':args.executable},timeout=args.timeout,resume=True)
    assert all(not j['reused'] for j in changed['jobs'])
    assert workflow.verify(target)['verified']
    reuse_result={'unchangedReused':True,'changedReran':True,'verified':True}
    handoff=json.loads((ROOT/'examples/schemaxis/aseprite-import-workflow.json').read_text())
    handoff_target=base/'handoff-workflow'
    assert workflow.execute(handoff,handoff_target,locations={'aseprite':args.executable},timeout=args.timeout)['verified']
    assert workflow.verify(handoff_target)['verified']
    reuse_result['verifiedPngHandoff']=True
    results['pre-capture-procedural']=qualify_legacy_receipt(base/'pre-capture-procedural',args.executable,args.timeout)
    integrity=[]
    for filename in ['inputs/source-004.png','input-manifest.json','sprite.aseprite','preview.png','sheet.png','sheet.json','worker.lua']:
        target=base/'import'/filename;original=target.read_bytes()
        try:
            target.write_bytes(original+b'corrupted')
            integrity.append({'file':filename,'fault':reject(base/'import')})
        finally:target.write_bytes(original)
    # Coherent receipt/result digest edits must still fail the independent model.
    path=base/'import/verification.json';original=path.read_bytes()
    resultpath=base/'import/result.json';original_result=resultpath.read_bytes()
    for field in ['cel','duration','preview']:
        receipt=json.loads(original)
        if field=='cel':receipt['native']['cels'][1][0]='00'*96
        elif field=='duration':receipt['native']['durationsMS'][1]=240
        else:receipt['preview']['pixels']='00'*96
        try:
            atomic_json(path,receipt)
            result=json.loads(original_result);result['sha256']['verification.json']=digest(path);atomic_json(resultpath,result)
            integrity.append({'forgery':field,'fault':reject(base/'import')})
        finally:path.write_bytes(original);resultpath.write_bytes(original_result)
    # Forged publication and both asserted digests cannot evade independent PNG decode.
    png=base/'import/preview.png';original_png=png.read_bytes()
    try:
        png.write_bytes((base/'import-variant/preview.png').read_bytes())
        receipt=json.loads(original)
        for artifact in receipt['artifacts']:
            if Path(artifact['file']).name=='preview.png':artifact['sha256']=digest(png)
        atomic_json(path,receipt)
        result=json.loads(original_result);result['sha256']['preview.png']=digest(png);result['sha256']['verification.json']=digest(path)
        atomic_json(resultpath,result)
        integrity.append({'forgery':'publication-plus-digests','fault':reject(base/'import')})
    finally:png.write_bytes(original_png);path.write_bytes(original);resultpath.write_bytes(original_result)
    assert verify(base/'import')['verified']
    receipt={'version':'schemaxis.aseprite.import-qualification/1','verified':True,
             'runtime':results['import']['runtime'],'cases':results,'workflowReuse':reuse_result,'integrity':integrity,
             'scope':'Fresh native batch build/reopen; exact captured RGBA8 binary-alpha replacement and normal-layer composite samples, changed source/placement/duration, same-cel overlap, two procedural regressions. No GUI/partial-alpha/profile/blend qualification.'}
    atomic_json(base/'qualification.json',receipt)
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
