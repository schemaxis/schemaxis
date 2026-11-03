#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Bounded cross-app acceptance with independent pixels, timing and GIS measures."""
import argparse
import copy
import json
from pathlib import Path

from schemaxis.core.faults import SchemaxisError
from schemaxis import workflow
from schemaxis.artifacts import atomic_json

ROOT=Path(__file__).resolve().parents[1]


def qualify(directory, locations):
    directory=Path(directory).absolute()
    directory.mkdir(parents=True,exist_ok=False)
    checks={}
    def run(label, document):
        destination=directory/label
        outcome=workflow.execute(document,destination,locations=locations,timeout=180)
        checks[label]={'verification':workflow.verify(destination),'directory':str(destination)}
        repeated=workflow.execute(document,destination,locations=locations,timeout=180,resume=True)
        assert all(job['reused'] for job in repeated['jobs']), 'unchanged inputs should reuse verified attempts'
        checks[label]['resumeReused']=len(repeated['jobs'])
        return outcome
    if locations.get('aseprite') and locations.get('godot'):
        d=json.loads((ROOT/'examples/schemaxis/sprite-to-godot.json').read_text())
        d['operations'][-1]['document']['preview']=True
        run('sprite-godot',d)
    if locations.get('aseprite') and locations.get('ffmpeg'):
        d=json.loads((ROOT/'examples/schemaxis/sprite-to-video.json').read_text())
        result=run('sprite-video',d)
        path=Path(result['jobs'][-1]['directory'])
        receipt=json.loads((path/'verification.json').read_text())
        assert (receipt['frames'],receipt['fps'],receipt['duration'])==(8,25,0.32)
        assert all(value==0 for value in receipt['meanErrors'])
        checks['sprite-video']['independentTiming']={'frames':8,'fps':25,'duration':0.32,'allPixelErrors':0}
        movie=Path(receipt['artifacts'][0]['file']);original=movie.read_bytes()
        try:
            movie.write_bytes(original+b'altered')
            try:workflow.verify(directory/'sprite-video')
            except SchemaxisError:checks['sprite-video']['tamperRejected']=True
            else:raise AssertionError('changed video was accepted')
        finally:movie.write_bytes(original)
    if locations.get('blender') and locations.get('ffmpeg'):
        run('blender-video',json.loads((ROOT/'examples/schemaxis/blender-to-video.json').read_text()))
    if locations.get('qgis'):
        fixture=directory/'sites.geojson'
        fixture.write_bytes((ROOT/'examples/schemaxis/qgis-sites.geojson').read_bytes())
        initial=json.loads((ROOT/'examples/schemaxis/qgis-site-analysis.json').read_text())
        initial['nodes'][0]['options']['file']=str(fixture)
        initial['nodes']=initial['nodes'][:-1];initial['output']='zones'
        clipped={'version':'schemaxis.qgis/1','nodes':[
            {'id':'zones','filter':'readVector','options':{'file':{'$artifact':'zones','index':0}}},
            {'id':'study','filter':'clip','inputs':{'input':'zones'},'options':{'bounds':[200,-25,250,25]}}],
            'output':'study','preview':True}
        d={'version':'schemaxis.workflow/1','operations':[{'id':'zones','document':initial},{'id':'study','document':clipped}]}
        if locations.get('ffmpeg'):
            d['operations'].append({'id':'movie','document':{'version':'schemaxis.ffmpeg/1','nodes':[
                {'id':'video','filter':'encodeFrames','options':{'files':[{'$artifact':'zones','index':2},
                 {'$artifact':'study','index':2}]*6,'fps':6,'codec':'h264'}}]}})
        result=run('qgis-study',d)
        target=Path(next(job['directory'] for job in result['jobs'] if job['operation']=='study'))
        snap=json.loads((target/'reopened.json').read_text())['snapshot']
        assert snap['crs']=='EPSG:3857' and snap['count']==1
        assert snap['bounds']==[200,-25,250,25]
        assert snap['features'][0]['area']==2500 and snap['features'][0]['attributes']=={'name':'east'}
        checks['qgis-study']['independentGeometry']={'area':2500,'bounds':snap['bounds'],'name':'east'}
        # Degrees must never be silently accepted as metres.
        bad=copy.deepcopy(initial)
        bad['nodes']=[bad['nodes'][0],{'id':'invalid','filter':'buffer','inputs':{'input':'sites'},'options':{'distance':100}}]
        bad['output']='invalid'
        from schemaxis.adaptors.qgis.adaptor import run as native_run
        try:native_run(bad,directory/'rejected-geographic-buffer',executable=locations['qgis'])
        except SchemaxisError as error:
            assert 'buffer requires a projected CRS in metres' in error.fault.message
            checks['qgis-study']['geographicBufferRejected']=True
        else:raise AssertionError('geographic buffering was accepted')
    if not checks:
        raise ValueError('Supply runtimes for at least one supported acceptance chain.')
    atomic_json(directory/'qualification.json',checks)
    return checks


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',required=True)
    for app in ('aseprite','godot','blender','ffmpeg','qgis'):parser.add_argument('--'+app)
    args=parser.parse_args()
    print(json.dumps(qualify(args.directory,{app:getattr(args,app) for app in ('aseprite','godot','blender','ffmpeg','qgis')}),indent=2))
