"""Source-bound native Zstandard file, dictionary, frame and lifecycle acceptance.

Original expectations are literal bytes written by this tool. Compatibility
streams also cross Python's independent gzip/lzma readers. The adaptor's parser
is never used to derive the expected original byte sequences.
"""
import argparse
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import random

from schemaxis import workflow
from schemaxis.adaptor_conformance import qualify as conformance
from schemaxis.adaptor_delivery import source_digest
from schemaxis.adaptors.zstandard import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError


def digest(data):return hashlib.sha256(data).hexdigest()


def refused(action,code=None,detail=None):
    try:action()
    except SchemaxisError as error:
        if code:assert error.fault.code==code,error.fault.to_dict()
        if detail:assert detail in str(error.fault.to_dict()),error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('A required refusal was accepted')


def refreshed(directory):
    path=directory/'verification.json';record=json.loads(path.read_text())
    for artifact in record['artifacts']:artifact['sha256']=digest(Path(artifact['file']).read_bytes())
    atomic_json(path,record)


def attacks(directory,alternate):
    """Restore every publication after semantic mutations with refreshed hashes."""
    names=('authored.json','plan.json','summary.json','verification.json','payload.zst')
    before={name:(directory/name).read_bytes() for name in names};result={}
    def restore():
        for name,data in before.items():(directory/name).write_bytes(data)
    try:
        (directory/'payload.zst').write_bytes(alternate.read_bytes());refreshed(directory)
        result['different-compression-controls']=refused(lambda:adaptor.verify(directory),'VERIFICATION_FAILED','current compression controls')
        restore()
        summary=json.loads((directory/'summary.json').read_text());summary['observations']['decodedBytes']+=1
        atomic_json(directory/'summary.json',summary);refreshed(directory)
        result['invented-content-length']=refused(lambda:adaptor.verify(directory),'VERIFICATION_FAILED','independent current-byte verification')
        restore()
        authored=json.loads((directory/'authored.json').read_text());authored['checksum']=False
        atomic_json(directory/'authored.json',authored);atomic_json(directory/'plan.json',adaptor.plan(authored))
        result['changed-checksum-intent']=refused(lambda:adaptor.verify(directory),'VERIFICATION_FAILED','checksum or dictionary ID policy')
        restore()
        data=bytearray(before['payload.zst']);data[-1]^=1;(directory/'payload.zst').write_bytes(data);refreshed(directory)
        result['corrupt-content-checksum']=refused(lambda:adaptor.verify(directory),'ZSTANDARD_NATIVE_FAILED')
    finally:restore()
    assert adaptor.verify(directory)['verified']
    return result


def qualify(directory,executable):
    if directory.exists():raise ValueError('Use a fresh qualification directory')
    directory.mkdir(parents=True)
    report={'verified':False,'sourceDigest':source_digest('zstandard'),'runtime':'1.5.7','checks':{}}
    report['qualificationTools']={name:digest((Path(__file__).parent/name).read_bytes()) for name in
        ('qualify_zstandard.py','zstandard_acceptance_extra.py','zstandard_file_acceptance.py','zstandard_captured_acceptance.py')}
    with location_context({'zstandard':executable}):
        try:
            report['development']=conformance(adaptor.VERSION,directory/'development',native=True,
                locations={'zstandard':executable},timeout=180,wall_timeout=600)
            source=directory/'source.bin'
            original=(b'{"sensor":"alpha","unit":"K","value":300,"samples":[1,2,3]}\n'*512
                      +bytes(range(256))*16+b'\0'*4096)
            # Variable repeated records exercise match search. A perfectly
            # repetitive tiny corpus can legitimately encode identically at
            # different levels, so it cannot serve as a policy-tamper control.
            generator=random.Random(2505)
            vocabulary=[('measurement-%03d='%i).encode()+bytes([65+i%26])*generator.randrange(3,70) for i in range(128)]
            original+=b'\n'.join(b'|'.join(generator.choice(vocabulary) for _ in range(generator.randrange(2,9))) for _ in range(1000))
            source.write_bytes(original)
            def run(name,**options):
                result=adaptor.run({'version':adaptor.VERSION,**options},directory/name,executable=executable,timeout=240)
                assert result['verified']
                assert adaptor.verify(directory/name)['verified']
                print(name+' verified',flush=True)
                return result
            codec_runs={}
            for codec in adaptor.FORMATS:
                name='codec-'+codec
                result=run(name,operation='compress',source=str(source),format=codec,level=6)
                output=Path(result['artifacts'][0]['file']);codec_runs[codec]=output
                encoded=output.read_bytes()
                if codec=='gzip':assert gzip.decompress(encoded)==original
                if codec in ('xz','lzma'):assert lzma.decompress(encoded)==original
                restored=run('restore-'+codec,operation='restore',source=str(output))
                assert Path(restored['artifacts'][0]['file']).read_bytes()==original
                report['checks'][name]={'decodedBytes':len(original),'decodedSha256':digest(original),
                                       'independentPythonCodec':codec in ('gzip','xz','lzma')}
            fast=run('fast',operation='compress',source=str(source),fast=3)
            assert Path(fast['artifacts'][0]['file']).read_bytes()!=codec_runs['zstd'].read_bytes()
            run('ultra',operation='compress',source=str(source),level=22,singleThread=True)
            run('tuned',operation='compress',source=str(source),level=9,threads=2,
                longWindowLog=20,rsyncable=True,literals='raw',
                tuning={'windowLog':20,'hashLog':15,'chainLog':16,'searchLog':2,'minMatch':4,'targetLength':64,'strategy':'btopt'})
            streamed=run('streamed',operation='compress',source=str(source),streamInput=True,chunkBytes=8192,checksum=False,fast=2)
            frames=streamed['observations']['frames']
            assert len(frames)>1 and all(f['contentBytes'] is None and f['checksum'] is None for f in frames)
            empty=directory/'empty.bin';empty.write_bytes(b'')
            result=run('empty',operation='compress',source=str(empty))
            assert result['observations']['decodedBytes']==0 and len(result['observations']['frames'])==1
            # Original hand-written raw frame, including a literal independently
            # known checksum, and a skippable record: not produced by the adaptor.
            frame=bytes.fromhex('28b52ffd2403190000616263990977ad')
            skip=bytes.fromhex('502a4d1804000000')+b'note'
            literal=directory/'literal.zst';literal.write_bytes(skip+frame+skip+frame)
            literal_result=run('literal',operation='restore',source=str(literal))
            assert Path(literal_result['artifacts'][0]['file']).read_bytes()==b'abcabc'
            joined=run('joined',operation='concatenate',sources=[str(codec_runs['zstd']),str(literal)])
            assert joined['observations']['decodedBytes']==len(original)+6
            reference=directory/'earlier.bin';reference.write_bytes(original.replace(b'300',b'280'))
            delta=run('delta',operation='encodeDelta',source=str(source),reference=str(reference))
            restored=run('delta-restored',operation='restore',source=delta['artifacts'][0]['file'],reference=str(reference))
            assert Path(restored['artifacts'][0]['file']).read_bytes()==original
            refused(lambda:adaptor.run({'version':adaptor.VERSION,'operation':'restore','source':delta['artifacts'][0]['file']},directory/'missing-reference',executable=executable))
            samples=[]
            for index in range(64):
                sample=directory/('sample-'+str(index)+'.json')
                sample.write_bytes((('{"sensor":"sample-%d","unit":"K","value":%d,"time":%d}\n'%(index,270+index%40,index*10))*40).encode())
                samples.append(str(sample))
            held_out=directory/'held-out.json';held_out.write_bytes(b'{"sensor":"sample-unknown","unit":"K","value":296,"time":9999}\n'*20)
            for algorithm in ('fastCover','cover','legacy'):
                trained=run('dictionary-'+algorithm,operation='trainDictionary',samples=samples,algorithm=algorithm,maxDictionaryBytes=1024,id=50001)
                dictionary=trained['artifacts'][0]['file']
                encoded=run('held-out-'+algorithm,operation='compress',source=str(held_out),dictionary=dictionary,dictionaryID=False)
                restored=run('held-out-restored-'+algorithm,operation='restore',source=encoded['artifacts'][0]['file'],dictionary=dictionary)
                assert Path(restored['artifacts'][0]['file']).read_bytes()==held_out.read_bytes()
                assert encoded['observations']['frames'][0]['dictionaryID']==0
            compared=run('profiles',operation='compareProfiles',source=str(source),profiles=[{'id':'small','level':9},{'id':'quick','level':1},{'id':'compatible','format':'gzip','level':6}])
            assert compared['observations']['timingVerified'] is False
            from zstandard_acceptance_extra import extended
            report['checks']['extended']=extended(directory,run,refused,refreshed,source,original,executable)
            from zstandard_file_acceptance import file_sets
            report['checks']['fileSets']=file_sets(directory,run,refused,refreshed,executable)
            from zstandard_captured_acceptance import captured_inputs
            report['checks']['capturedInputs']=captured_inputs(directory,executable)
            report['checks']['refreshedHashAttacks']=attacks(directory/'codec-zstd',Path(fast['artifacts'][0]['file']))
            refused(lambda:adaptor.run({'version':adaptor.VERSION,'operation':'restore','source':str(codec_runs['zstd']),'maxDecodedBytes':len(original)-1},directory/'decoded-budget',executable=executable),'ZSTANDARD_BUDGET')
            source.rename(directory/'original-hidden.bin')
            assert adaptor.verify(directory/'codec-zstd')['verified']
            source.write_bytes(original)
            document={'version':'schemaxis.workflow/1','execution':{'maxWorkers':1,'cpus':2},'operations':[
                {'id':'compress','document':{'version':adaptor.VERSION,'operation':'compress','source':str(source),'level':6}},
                {'id':'restore','document':{'version':adaptor.VERSION,'operation':'restore','source':{'$artifact':'compress','index':0}}}]}
            work=directory/'workflow'
            first=workflow.execute(document,work,locations={'zstandard':executable},timeout=240)
            assert workflow.verify(work)['verified']
            restore_job=next(job for job in first['jobs'] if job['operation']=='restore')
            assert (Path(restore_job['directory'])/'restored.bin').read_bytes()==original
            resumed=workflow.execute(document,work,locations={'zstandard':executable},timeout=240,resume=True)
            assert all(job['reused'] for job in resumed['jobs'])
            source.write_bytes(original+b'changed source\n')
            changed=workflow.execute(document,work,locations={'zstandard':executable},timeout=240,resume=True)
            assert all(not job['reused'] for job in changed['jobs'])
            assert workflow.verify(work)['verified']
            target=Path(next(job for job in changed['jobs'] if job['operation']=='compress')['directory'])/'payload.zst'
            target.write_bytes(target.read_bytes()+b'broken')
            repaired=workflow.execute(document,work,locations={'zstandard':executable},timeout=240,resume=True)
            assert all(not job['reused'] for job in repaired['jobs'])
            assert workflow.verify(work)['verified']
            report['checks']['workflow']={'exactRestoration':True,'verifiedReuse':True,'changedInputInvalidation':True,'corruptionRebuild':True}
            assert source_digest('zstandard')==report['sourceDigest'],'source changed during qualification'
            report['verified']=True
            return report
        finally:atomic_json(directory/'report.json',report)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--executable',required=True)
    arguments=parser.parse_args()
    print(json.dumps(qualify(arguments.directory.absolute(),arguments.executable),indent=2))
