#!/usr/bin/env python3
"""Independent literal/native QGIS attribute, summary and lifecycle acceptance."""
import argparse
import copy
import json
import math
from pathlib import Path
import sqlite3
import struct
import threading
import time

from schemaxis.adaptors.qgis import adaptor
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation
from schemaxis.publication_metadata import finalise
from schemaxis import workflow

EXPECTED = [
    (None, ['e'], 1, 1, 2, 2), ('', ['i'], 1, 1, 3, 3),
    ('empty', ['h'], 1, 0, None, None), ('north', ['b','g'], 2, 1, 6, 6),
    ('south', ['c'], 1, 1, 4, 4)]


def fault(action, expected):
    try: action()
    except SchemaxisError as error:
        assert error.fault.code == expected, error.fault.to_dict()
        return error.fault.to_dict()
    raise AssertionError('expected '+expected)


def independently_check(output, expected, fixture):
    """Literal table arithmetic and source point geometry; no adaptor helper oracle."""
    table=json.loads((output/'summary-regional_load.json').read_text())
    rows=table['rows'];assert len(rows)==len(expected)
    for row,(group,members,count,valid,total,mean) in zip(rows,expected):
        assert row['group']==group and row['groupIsNull']==(group is None)
        assert row['memberIds']==members and row['assets']==count and row['valid_loads']==valid
        for name,value in [('total_kw',total),('mean_kw',mean)]:
            assert row[name] is None if value is None else math.isclose(row[name],value,rel_tol=1e-12,abs_tol=1e-12)
    assert [c['units'] for c in table['columns']]==['unitless','unitless','unitless','features','features','kW','kW']
    expected_ids=sorted(identity for row in expected for identity in row[1])
    source={f['properties']['asset_id']:f for f in fixture['features']}
    reopened=json.loads((output/'reopened.json').read_text());built=json.loads((output/'built.json').read_text())
    assert reopened['pid']!=built['pid'] and reopened['projectReopened'] is True
    assert reopened['summaryTables']['regional_load']['spatial'] is False
    features=reopened['snapshot']['features'];assert len(features)==len(expected_ids)
    assert sorted(f['attributes']['asset_id'] for f in features)==expected_ids
    for feature in features:
        identity=feature['attributes']['asset_id'];wkb=bytes.fromhex(feature['geometry'])
        assert wkb[:5]==bytes.fromhex('0101000000')
        point=list(struct.unpack('<dd',wkb[5:]));assert point==source[identity]['geometry']['coordinates']
        assert feature['attributes']==source[identity]['properties']
    with sqlite3.connect(output/'summary-regional_load.gpkg') as database:
        observed=database.execute('SELECT "group",memberIds,assets,valid_loads,total_kw,mean_kw FROM summary ORDER BY "group" IS NOT NULL,"group"').fetchall()
        assert observed==[(g,json.dumps(ids,separators=(',',':')),count,valid,total,mean) for g,ids,count,valid,total,mean in expected]
    return {'memberIds':expected_ids,'groups':len(rows),'runtime':reopened['runtime'],'freshProjectTables':list(reopened['summaryTables'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qgis',required=True)
    parser.add_argument('--output-directory',required=True,type=Path)
    args=parser.parse_args();root=args.output_directory.resolve();root.mkdir(parents=True,exist_ok=False)
    executable=str(Path(args.qgis).resolve());repository=Path(__file__).resolve().parents[1]
    fixture=json.loads((repository/'examples/schemaxis/fixtures/qgis/assets.geojson').read_text())
    source=root/'assets.geojson';atomic_json(source,fixture)
    document=json.loads((repository/'examples/schemaxis/qgis-attributes.json').read_text());document['nodes'][0]['options']['file']=str(source)
    report={'verified':False,'cases':{},'negative':{},'probes':{}}
    try:
        baseline=root/'baseline';adaptor.run(document,baseline,executable=executable,timeout=60)
        report['cases']['baseline']=independently_check(baseline,EXPECTED,fixture)
        report['cases']['baseline']['offline']=adaptor.verify(baseline)
        assert (baseline/'schema.snapshot.json').is_file()
        variant=copy.deepcopy(document);variant['nodes'][1]['options'].update(minFeatures=1,maxFeatures=1)
        variant['nodes'][1]['options']['predicates'][0]['comparison']='gt'
        adaptor.run(variant,root/'strict-threshold',executable=executable,timeout=60)
        report['cases']['strict-threshold']=independently_check(root/'strict-threshold',EXPECTED[:1],fixture)
        lower=copy.deepcopy(document);lower['nodes'][1]['options'].update(minFeatures=8,maxFeatures=8)
        lower['nodes'][1]['options']['predicates'][0]['value']=10
        adaptor.run(lower,root/'lower-threshold',executable=executable,timeout=60)
        lower_expected=copy.deepcopy(EXPECTED);lower_expected[3]=('north',['a','b','f','g'],4,3,7,7/3)
        report['cases']['lower-threshold']=independently_check(root/'lower-threshold',lower_expected,fixture)
        changed=copy.deepcopy(document);changed['nodes'][2]['options']['groupBy']='asset_id'
        adaptor.run(changed,root/'group-variant',executable=executable,timeout=60)
        table=json.loads((root/'group-variant/summary-regional_load.json').read_text())
        assert [r['group'] for r in table['rows']]==['b','c','e','g','h','i']
        assert [r['memberIds'] for r in table['rows']]==[[v] for v in ['b','c','e','g','h','i']]
        group_expected=[('b',['b'],1,0,None,None),('c',['c'],1,1,4,4),('e',['e'],1,1,2,2),
                        ('g',['g'],1,1,6,6),('h',['h'],1,0,None,None),('i',['i'],1,1,3,3)]
        report['cases']['group-variant']=independently_check(root/'group-variant',group_expected,fixture)
        # Captured runs survive external changes, but reusable input fingerprints must change.
        fingerprint=adaptor.reusableInputs(document);changed_fixture=copy.deepcopy(fixture)
        changed_fixture['features'][6]['properties']['load_kw']=10
        atomic_json(source,changed_fixture);assert fingerprint!=adaptor.reusableInputs(document)
        assert adaptor.verify(baseline)['verified']
        source.rename(root/'assets-absent.geojson')
        try: assert adaptor.verify(baseline)['verified']
        finally: (root/'assets-absent.geojson').rename(source)
        adaptor.run(document,root/'changed-source',executable=executable,timeout=60)
        changed_expected=copy.deepcopy(EXPECTED);changed_expected[3]=('north',['b','g'],2,1,10,10)
        report['cases']['changed-source']=independently_check(root/'changed-source',changed_expected,changed_fixture)
        atomic_json(source,fixture)
        for name,mutate,code,location in [
            ('missing-field',lambda d:d['nodes'][1]['options']['predicates'][0].update(field='absent'),'INVALID_ATTRIBUTE','eligible.options.predicates[0].field'),
            ('wrong-field-type',lambda d:d['nodes'][1]['options']['predicates'][0].update(field='region'),'INVALID_ATTRIBUTE','eligible.options.predicates[0].field'),
            ('feature-requirement',lambda d:d['nodes'][1]['options'].update(minFeatures=7,maxFeatures=9),'FEATURE_REQUIREMENT_FAILED','eligible.options.minFeatures'),
            ('numeric-group',lambda d:d['nodes'][2]['options'].update(groupBy='score'),'INVALID_ATTRIBUTE','regional_load.options.groupBy')]:
            candidate=copy.deepcopy(document);mutate(candidate)
            found=fault(lambda:adaptor.run(candidate,root/name,executable=executable,timeout=60),code)
            assert found['location']==location;assert json.loads((root/name/'result.json').read_text())['verified'] is False
            report['negative'][name]=found
        for name,mutate in [('duplicate-id',lambda f:f['features'][1]['properties'].update(asset_id='a')),('mixed-numeric',lambda f:f['features'][0]['properties'].update(score='ten'))]:
            bad=copy.deepcopy(fixture);mutate(bad);atomic_json(source,bad)
            report['negative'][name]=fault(lambda:adaptor.run(document,root/name,executable=executable,timeout=60),'INVALID_ATTRIBUTE')
        atomic_json(source,fixture)
        # Crossed native CRS is checked even though attributes do not reproject geometry.
        bad=copy.deepcopy(fixture);bad['crs']['properties']['name']='EPSG:999999';atomic_json(source,bad)
        report['negative']['invalid-crs']=fault(lambda:adaptor.run(document,root/'invalid-crs',executable=executable,timeout=60),'NATIVE_EXECUTION_FAILED')
        atomic_json(source,fixture)
        # Refresh ordinary metadata/digests so arithmetic and source membership must reject the deception.
        for label,filename,mutate in [
            ('false-member','built.json',lambda d:d['attributes']['eligible'].update(memberIds=['a','b','c','e','g','h'])),
            ('false-mean','summary-regional_load.json',lambda d:d['rows'][3].update(mean_kw=3)),
            ('null-becomes-zero','summary-regional_load.json',lambda d:d['rows'][2].update(total_kw=0)),
            ('false-source','input-assets.geojson',lambda d:d['features'][6]['properties'].update(load_kw=99))]:
            path=baseline/filename;original=path.read_bytes();receipt_path=baseline/'verification.json';original_receipt=receipt_path.read_bytes();sources_path=baseline/'sources.json';original_sources=sources_path.read_bytes()
            try:
                value=json.loads(original);mutate(value);atomic_json(path,value)
                receipt=json.loads(original_receipt)
                if filename in receipt['evidence']:receipt['evidence'][filename]=file_digest(path)
                if filename=='input-assets.geojson':
                    sources=json.loads(original_sources);sources['assets']['sha256']=file_digest(path);atomic_json(sources_path,sources);receipt['evidence']['sources.json']=file_digest(sources_path)
                atomic_json(receipt_path,receipt);finalise(baseline)
                report['probes'][label]=fault(lambda:adaptor.verify(baseline),'VERIFICATION_FAILED')['code']
            finally:
                path.write_bytes(original);receipt_path.write_bytes(original_receipt);sources_path.write_bytes(original_sources);finalise(baseline)
        report['probes']['timeout']=fault(lambda:adaptor.run(document,root/'timeout',executable=executable,timeout=.001),'RUNNER_TIMED_OUT')['code']
        event=threading.Event();observed={}
        def cancel_after_submission():
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and not list((root/'cancelled/.dispatch/build').glob('replay-*.py')):time.sleep(.01)
            observed['dispatchCreated']=bool(list((root/'cancelled/.dispatch/build').glob('replay-*.py')))
            event.set()
        thread=threading.Thread(target=cancel_after_submission,daemon=True);thread.start()
        with allocation({'threads':1},cancel=event):
            report['probes']['cancelled']=fault(lambda:adaptor.run(document,root/'cancelled',executable=executable,timeout=60),'RUNNER_CANCELLED')['code']
        thread.join(timeout=6);assert observed.get('dispatchCreated') is True
        report['probes']['cancellationScope']='After owned process submission was created; QGIS initialisation completion is not asserted.'
        # Unchanged-input resume, invalidation and a vector GeoPackage handoff.
        consumer=copy.deepcopy(document);consumer['nodes'][0]['options']['file']={'$artifact':'select','index':0}
        flow={'version':'schemaxis.workflow/1','operations':[{'id':'select','document':document},{'id':'consume','document':consumer}]}
        location={'qgis':executable};target=root/'workflow'
        result=workflow.execute(flow,target,locations=location,timeout=60);assert result['verified']
        before={job['operation']:(job['directory'],(Path(job['directory'])/'built.json').read_bytes()) for job in result['jobs']}
        resumed=workflow.execute(flow,target,locations=location,timeout=60,resume=True);assert resumed['verified']
        assert all(job['reused'] is True and job['directory']==before[job['operation']][0] for job in resumed['jobs'])
        atomic_json(source,changed_fixture)
        resumed=workflow.execute(flow,target,locations=location,timeout=60,resume=True);assert resumed['verified']
        assert all(job['reused'] is False and job['directory']!=before[job['operation']][0] for job in resumed['jobs'])
        assert all((Path(directory)/'built.json').read_bytes()==value for directory,value in before.values())
        assert workflow.verify(target)['verified']
        report['cases']['workflow']={'verified':True,'unchangedReuse':True,'changedSourceInvalidatesBoth':True}
        report['verified']=True
    finally:atomic_json(root/'report.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
