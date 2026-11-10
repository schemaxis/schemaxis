"""Independent literals and adversarial lifecycle cases for Zstandard's extended tasks."""
import json
import threading
from pathlib import Path
from schemaxis.adaptors.zstandard import adaptor
from schemaxis.artifacts import atomic_json
from schemaxis.dispatch import allocation


def extended(directory,run,refused,refreshed,source,original,executable):
    checks={}
    for name,options in [
        ('size-omitted',{'contentSize':'omit'}),
        ('stream-pledged',{'streamInput':True,'pledgedBytes':len(original),'contentSize':'require'}),
        ('stream-hinted',{'streamInput':True,'sizeHintBytes':len(original)+17,'targetBlockBytes':1024}),
        ('adaptive',{'adaptive':{'minLevel':1,'maxLevel':9}}),
        ('worker-history',{'threads':2,'jobBytes':524288,'longWindowLog':20,
            'tuning':{'overlapLog':8,'ldmHashLog':16,'ldmMinMatch':32,'ldmBucketSizeLog':3,'ldmHashRateLog':4}}),
        ('optimal-three-byte-matching',{'tuning':{'strategy':'btopt','minMatch':3,'searchLog':2}}),
        ('fast-seven-byte-matching',{'tuning':{'strategy':'fast','minMatch':7}}),
    ]:
        result=run(name,operation='compress',source=str(source),**options)
        checks[name]={'decodedBytes':result['observations']['decodedBytes'],
                      'contentSizes':[f['contentBytes'] for f in result['observations']['frames']]}
        if name=='size-omitted':assert checks[name]['contentSizes']==[None]
        if name=='stream-pledged':assert checks[name]['contentSizes']==[len(original)]
        if name=='adaptive':assert result['observations']['adaptiveLevelHistoryVerified'] is False
    history=directory/'raw-history.dict';history.write_bytes(original[:4096])
    raw=run('raw-dictionary',operation='compress',source=str(source),dictionary=str(history),dictionaryMode='raw')
    restored=run('raw-dictionary-restore',operation='restore',source=raw['artifacts'][0]['file'],dictionary=str(history),dictionaryMode='raw')
    assert Path(restored['artifacts'][0]['file']).read_bytes()==original
    run('raw-dictionary-inspection',operation='inspectDictionary',source=str(history),dictionaryMode='raw')
    broken=directory/'broken-trained.dict';broken.write_bytes(bytes.fromhex('37a430ec51c30000'))
    checks['invalid-dictionary-tables']=refused(lambda:adaptor.run({'version':adaptor.VERSION,'operation':'inspectDictionary','source':str(broken)},directory/'invalid-dictionary',executable=executable),'ZSTANDARD_NATIVE_FAILED')
    for algorithm in ('fastCover','cover','legacy'):
        run('inspect-dictionary-'+algorithm,operation='inspectDictionary',source=str(directory/('dictionary-'+algorithm)/'dictionary.zdict'))

    skip=directory/'only-metadata.zst';skip.write_bytes(bytes.fromhex('502a4d1804000000')+b'note')
    result=run('skip-only',operation='restore',source=str(skip),maxDecodedBytes=0)
    assert Path(result['artifacts'][0]['file']).read_bytes()==b''
    run('skip-only-inspect',operation='inspect',source=str(skip),maxDecodedBytes=0)
    combined=run('skip-around-content',operation='concatenate',sources=[str(skip),str(directory/'literal.zst')])
    assert combined['observations']['decodedBytes']==6

    # Different literal inputs prevent ordering checks passing on identical data.
    for streamed in (False,True):
        sources=[]
        for i,letter in enumerate((b'a',b'b',b'c')):
            literal=directory/('budget-'+str(i)+'.bin');literal.write_bytes(letter*600)
            encoded=run('budget-'+str(streamed)+'-'+str(i),operation='compress',source=str(literal),streamInput=streamed)
            sources.append(encoded['artifacts'][0]['file'])
        exact=run('budget-exact-'+str(streamed),operation='concatenate',sources=sources,maxDecodedBytes=1800)
        assert exact['observations']['decodedBytes']==1800
        for limit in (1000,1799):
            checks['aggregate-'+str(streamed)+'-'+str(limit)]=refused(lambda:adaptor.run({'version':adaptor.VERSION,'operation':'concatenate','sources':sources,'maxDecodedBytes':limit},directory/('overflow-'+str(streamed)+'-'+str(limit)),executable=executable),'ZSTANDARD_BUDGET')

    trained=directory/'dictionary-fastCover';target=trained/'dictionary.zdict'
    before=target.read_bytes();target.write_bytes((directory/'dictionary-cover/dictionary.zdict').read_bytes());refreshed(trained)
    try:checks['replaced-trained-dictionary']=refused(lambda:adaptor.verify(trained),'VERIFICATION_FAILED')
    finally:target.write_bytes(before);refreshed(trained)
    assert adaptor.verify(trained)['verified']
    held=directory/'held-out-fastCover/payload.zst'
    checks['missing-dictionary']=refused(lambda:adaptor.run({'version':adaptor.VERSION,'operation':'restore','source':str(held)},directory/'missing-dictionary',executable=executable))
    bad=directory/'wrong.dict';bad.write_bytes(bytes.fromhex('37a430ec51c30000'))
    checks['wrong-dictionary']=refused(lambda:adaptor.run({'version':adaptor.VERSION,'operation':'restore','source':str(held),'dictionary':str(bad)},directory/'wrong-dictionary',executable=executable),'ZSTANDARD_NATIVE_FAILED')
    stale=directory/'stale-reference';stale.write_bytes(b'unrelated earlier history '*1024)
    checks['stale-reference']=refused(lambda:adaptor.run({'version':adaptor.VERSION,'operation':'restore','source':str(directory/'delta/payload.zst'),'reference':str(stale)},directory/'stale-reference-run',executable=executable))
    joined=directory/'joined';target=joined/'payload.zst';before=target.read_bytes()
    target.write_bytes((directory/'literal.zst').read_bytes()+(directory/'codec-zstd/payload.zst').read_bytes());refreshed(joined)
    try:checks['swapped-joined-order']=refused(lambda:adaptor.verify(joined),'VERIFICATION_FAILED')
    finally:target.write_bytes(before);refreshed(joined)
    assert adaptor.verify(joined)['verified']

    # A second corpus makes benchmark block and ratio expectations independent
    # of the large compression-policy fixture above.
    bench=directory/'benchmark-input';bench.write_bytes(b'abcde12345 '*1000+bytes(range(256))*4)
    for label,options in [('whole',{}),('blocks',{'benchmarkBlockBytes':1024})]:
        result=run('benchmark-'+label,operation='benchmark',source=str(bench),firstLevel=1,lastLevel=2,**options)
        assert result['observations']['timingVerified'] is False
        for row in result['observations']['levels']:
            assert abs(len(bench.read_bytes())/row['compressedBytes']-row['ratio'])<=.000500001
    result=run('benchmark-decode',operation='benchmarkDecode',source=str(directory/'codec-zstd/payload.zst'))
    assert result['observations']['decodedBytes']==len(original)
    benchmark_doc={'version':adaptor.VERSION,'operation':'benchmark','source':str(bench),'firstLevel':1,'lastLevel':1,'minimumSeconds':3}
    checks['timeout']=refused(lambda:adaptor.run(benchmark_doc,directory/'timeout',executable=executable,timeout=.2),'RUNNER_TIMED_OUT')
    cancel=threading.Event();timer=threading.Timer(.3,cancel.set)
    try:
        with allocation({},cancel):
            timer.start()
            checks['cancel']=refused(lambda:adaptor.run(benchmark_doc,directory/'cancel',executable=executable),'RUNNER_CANCELLED')
    finally:timer.cancel();timer.join()
    assert cancel.is_set()
    return checks
