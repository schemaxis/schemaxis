"""Original file trees and independent collision, membership and content attacks."""
import json
from pathlib import Path
from schemaxis.adaptors.zstandard import adaptor
from schemaxis.adaptors import registry
from schemaxis.artifacts import atomic_json


def file_sets(directory,run,refused,refreshed,executable):
    source=directory/'tree-input';source.mkdir();(source/'nested').mkdir()
    expected={'alpha.bin':b'alpha-data\n'*80,'nested/beta.bin':bytes(range(256))*3,'nested/empty.bin':b''}
    for name,data in expected.items():(source/name).write_bytes(data)
    (source/'ignored.log').write_bytes(b'not selected')
    checks={};total=sum(map(len,expected.values()))
    for codec in adaptor.FORMATS:
        compressed=directory/('tree-compress-'+codec)
        options={'streamInput':True,'contentSize':'require'} if codec=='zstd' else {}
        result=run('tree-compress-'+codec,operation='compressFiles',fileSet={'root':str(source),'include':['*.bin']},format=codec,**options)
        assert result['observations']['decodedBytes']==total
        restored=directory/('tree-restore-'+codec)
        run('tree-restore-'+codec,operation='restoreFiles',fileSet={'root':str(compressed/'files'),'include':['*'+adaptor.file_sets.SUFFIX[codec]]},maxDecodedBytes=total)
        from schemaxis.publication_metadata import committed_companions
        companions=committed_companions(restored,None)
        assert sorted(p.relative_to(restored/'files').as_posix() for p in (restored/'files').rglob('*') if p.is_file() and p.resolve() not in companions)==sorted(expected)
        for name,data in expected.items():assert (restored/'files'/name).read_bytes()==data
        checks[codec]={'files':len(expected),'decodedBytes':total,'exactLiteralRestoration':True}
    source.rename(directory/'tree-originals-hidden')
    assert adaptor.verify(directory/'tree-compress-zstd')['verified']
    compressed=directory/'tree-compress-zstd'
    (compressed/'files').rename(compressed/'temporarily-hidden-inputs')
    try:assert adaptor.verify(directory/'tree-restore-zstd')['verified']
    finally:(compressed/'temporarily-hidden-inputs').rename(compressed/'files')
    checks['original-paths-removed']=True

    # Publication goes through the public framework too: longest admitted leaf
    # names leave room for shared metadata staging, and file extensions cannot
    # turn opaque restored bytes into a declared text/table contract.
    opaque=directory/'opaque-input';opaque.write_bytes(b'\xff\xfe\x00opaque bytes\n')
    long_doc={'version':adaptor.VERSION,'operation':'compressFiles','fileSet':{'files':[{'source':str(opaque),'name':'x'*219}]}}
    public=directory/'public-max-name';registry.run(long_doc,public,locations={'zstandard':executable},timeout=120)
    assert registry.verify(public)['verified'];encoded=public/'files'/('x'*219+'.zst')
    for extension in ('csv','json','txt'):
        target=directory/('public-opaque-'+extension)
        doc={'version':adaptor.VERSION,'operation':'restoreFiles','fileSet':{'files':[{'source':str(encoded),'name':'opaque.'+extension+'.zst'}]}}
        registry.run(doc,target,locations={'zstandard':executable},timeout=120)
        assert registry.verify(target)['verified'];assert (target/'files'/('opaque.'+extension)).read_bytes()==opaque.read_bytes()
        artifact=next(row for row in json.loads((target/'verification.json').read_text())['artifacts'] if row['file'].endswith('opaque.'+extension))
        assert artifact['kind']=='file'
    checks['public-name-and-opaque-kinds']=True

    selected=directory/'selection-root';selected.mkdir();(selected/'private').mkdir()
    (selected/'safe').write_bytes(b'safe literal');(selected/'private/secret').write_bytes(b'safe literal')
    filtered=directory/'excluded-ancestor'
    run('excluded-ancestor',operation='compressFiles',fileSet={'root':str(selected),'exclude':['private']})
    membership=filtered/'selection.json';before=membership.read_bytes();value=json.loads(before)
    value[0].update(name='private/secret',source=str(selected/'private/secret'));atomic_json(membership,value)
    try:checks['excluded-ancestor']=refused(lambda:adaptor.verify(filtered),'INVALID_ZSTANDARD_FILE_SET')
    finally:membership.write_bytes(before)
    assert adaptor.verify(filtered)['verified']

    selection={'files':[
        {'source':str(directory/'tree-originals-hidden/alpha.bin'),'name':'run-A/data'},
        {'source':str(directory/'tree-originals-hidden/nested/beta.bin'),'name':'run-B/data'},
    ]}
    run('named-files',operation='compressFiles',fileSet=selection,fast=2,chunkBytes=256)
    for names in (['a.zst','a.gz'],['a.zst','a/b.zst'],['A.zst','a.zst'],['../outside.zst'],
                  ['a.zst','a.metadata.json.zst'],['a.zst','a.metadata.json.staging.zst'],['x'*252]):
        checks['collision-'+','.join(names)]=refused(lambda:adaptor.plan({'version':adaptor.VERSION,'operation':'restoreFiles',
            'fileSet':{'files':[{'name':name,'source':'/example/'+str(index)} for index,name in enumerate(names)]}}),'INVALID_ZSTANDARD_FILE_SET')

    # A restored content mutation with refreshed publication hashes must still
    # disagree with the exact compressed capture, not merely a historical hash.
    restored=directory/'tree-restore-zstd';target=restored/'files/alpha.bin';before=target.read_bytes()
    target.write_bytes(b'X'+before[1:]);refreshed(restored)
    try:checks['changed-restored-bytes']=refused(lambda:adaptor.verify(restored),'VERIFICATION_FAILED')
    finally:target.write_bytes(before);refreshed(restored)
    assert adaptor.verify(restored)['verified']
    manifest=restored/'files.json';before=manifest.read_bytes();value=json.loads(before);value['files'][0]['sourceName']='invented-input.zst'
    atomic_json(manifest,value);refreshed(restored)
    try:checks['invented-file-membership']=refused(lambda:adaptor.verify(restored),'VERIFICATION_FAILED')
    finally:manifest.write_bytes(before);refreshed(restored)
    assert adaptor.verify(restored)['verified']

    # Change only a recorded budget. All files fit separately, but their total
    # must be refused by host metadata admission before native decoding.
    authored=restored/'authored.json';plan=restored/'plan.json';old_authored=authored.read_bytes();old_plan=plan.read_bytes()
    doc=json.loads(old_authored);doc['maxDecodedBytes']=total-1
    atomic_json(authored,doc);atomic_json(plan,adaptor.plan(doc))
    try:checks['aggregate-published-budget']=refused(lambda:adaptor.verify(restored),'ZSTANDARD_BUDGET')
    finally:authored.write_bytes(old_authored);plan.write_bytes(old_plan)
    assert adaptor.verify(restored)['verified']
    return checks
