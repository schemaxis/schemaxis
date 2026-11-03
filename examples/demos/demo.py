#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Local demonstration launcher. Uses normal Schemaxis CLI; never overwrites a run."""
import argparse
import copy
import datetime as dt
import html
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from schemaxis.core.documents import load_document

RUNS = ROOT / 'evidence' / 'demos'
# Explicit paths keep a fresh checkout independent of local runtime wrappers.
APP_ENV = {key: 'SCHEMAXIS_DEMO_' + key.upper().replace('-', '_') for key in
           ('freecad', 'freecad-gui', 'blender', 'paraview-root', 'godot', 'aseprite', 'ffmpeg', 'qgis')}
APPS = {}
CASE = None
REQUIRED = {
    'pipe': ('freecad', 'blender', 'ffmpeg'),
    'inspection': ('freecad', 'blender', 'paraview-root'),
    'vehicle': ('paraview-root',), 'region': ('paraview-root',), 'mirror': ('paraview-root',),
    'cfd-render': ('paraview-root', 'blender', 'ffmpeg'),
    'site': ('qgis', 'godot'), 'sprite': ('aseprite', 'godot', 'ffmpeg'),
}


def require_apps(names):
    for key in names:
        value = APPS.get(key)
        path = Path(value) / 'bin/pvbatch' if value and key == 'paraview-root' else Path(value) if value else None
        if path is None or not path.is_file() or not os.access(path, os.X_OK):
            raise SystemExit('Configure --' + key + ' or ' + APP_ENV[key] + ' with an executable absolute path (ParaView: installation root).')


NAMES = ('pipe', 'inspection', 'vehicle', 'region', 'mirror', 'cfd-render', 'site', 'sprite')


def read(name):
    document = load_document((HERE / name).read_text())
    if name in ('vehicle.input.json', 'mirror.input.json') and CASE:
        document['settings']['case'] = CASE
    if name == 'site.input.json':
        document['settings']['source'] = str(HERE / 'sites.geojson')
    return document


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def node(identity, kind, options=None, inputs=None):
    d = {'id': identity, 'filter': kind}
    if options is not None: d['options'] = options
    if inputs is not None: d['inputs'] = inputs
    return d


def artifact(operation, index):
    return {'$artifact': operation, 'index': index}


def workflow(operations):
    return {'version': 'schemaxis.workflow/1', 'execution': {
        'maxWorkers': 1, 'cpus': 4, 'memoryMB': 12000, 'gpus': 0},
        'operations': [{'id': identity, 'document': document} for identity, document in operations]}


def movie(files, fps=8):
    return {'version': 'schemaxis.ffmpeg/1', 'nodes': [node('encode', 'encodeFrames',
        {'files': files, 'fps': fps, 'codec': 'h264', 'threads': 1})]}


def blender_mesh(file, cameras, *, remesh=None, gltf=False):
    nodes = [node('paint', 'material', {'colour': [.035, .30, .43, 1], 'metallic': .55, 'roughness': .27}),
             node('imported', 'readGltf' if gltf else 'readSTL',
                  {'file': file} if gltf else {'file': file, 'scale': .001})]
    previous = 'imported'
    if gltf:
        # Qualified ParaView glTF -> Blender bridge restores the source Z-up frame.
        nodes.append(node('engineeringAxes','transform',{'rotation':[-90,0,0]}, {'input':previous}))
        previous = 'engineeringAxes'
    if remesh is not None:
        nodes.append(node('metres', 'applyTransform', inputs={'input': previous}))
        previous = 'metres'
        nodes.append(node('remesh', 'voxelRemesh', {'voxelSize': remesh}, {'input': previous}))
        previous = 'remesh'
    nodes += [node('smooth', 'shadeSmooth', inputs={'input': previous}),
              node('finished', 'assignMaterial', inputs={'input': 'smooth', 'material': 'paint'})]
    return {'version': 'schemaxis.blender/1', 'nodes': nodes, 'scenes': [{
        'id': 'presentation', 'visible': ['finished'], 'meshes': ['finished'],
        'render': {'threads': 4, 'samples': 16, 'denoise': True},
        'images': [{'id': 'orbit', 'size': [640, 480], 'cameras': cameras}]}]}


def build(name):
    presentation = read('presentation.json')
    count = presentation['orbitFrames']
    cameras = [{'$analytic': {'type': 'orbit', 'start': 0, 'end': 360-360/count,
                             'count': count, 'elevation': 30}}]
    # Camera analytics occupy the complete cameras value, not an element.
    cameras = cameras[0]
    if name == 'pipe':
        return workflow([('cad', read('pipe.input.json')),
            ('render', blender_mesh(artifact('cad', 1), cameras)),
            ('movie', movie([artifact('render', i) for i in range(count)], presentation['fps']))])
    if name == 'inspection':
        operations = [('cad', read('pipe.input.json'))]
        for label, voxel in [('fine', .0015), ('coarse', .004)]:
            operations.append((label, blender_mesh(artifact('cad', 1), [{'direction': [1,-2,1.5]}], remesh=voxel)))
            pv = {'version': 'schemaxis/1', 'nodes': [
                node('mesh', 'readSTL', {'files': [artifact(label, 1)]}),
                node('area', 'cellSize', inputs={'input':'mesh'}),
                node('total', 'integrate', inputs={'input':'area'}),
                node('section', 'slice', {'normal':'z+', 'origin':[0,0,0]}, {'input':'mesh'})],
                'scenes': [{'id':'mesh', 'geometry':['area','section'],
                    'measurements':[{'node':'total', 'association':'CELLS'}],
                    'visible': {'area':{'field':['CELLS','Area'], 'legend':True, 'legendTitle':'Triangle area (m2)'},
                                'section':{'colour':'black', 'representation':'Surface'}},
                    'images':[{'id':'view','size':[640,480], 'cameras':[{'direction':[1,-2,1.5]}]}]}]}
            operations.append((label+'Measure',pv))
        return workflow(operations)
    if name in ('vehicle','region','mirror'):
        d = read(('mirror' if name == 'region' else name)+'.input.json')
        if name == 'mirror' and not d['settings'].get('mirrorBoundsConfirmed', False):
            raise SystemExit('This coupe has no identified mirror. Use run region for the labelled side-region study. For a real mirror, set measured dimensions.mirror bounds, the correct case path, and settings.mirrorBoundsConfirmed=true in mirror.input.json.')
        return d
    if name == 'cfd-render':
        pv = read('vehicle.input.json')
        pv['nodes'] += [node('carGroup','group',inputs={'input':['body','tyres']}),
                        node('carMerged','merge',inputs={'input':'carGroup'}),
                        node('carSurface','surface',inputs={'input':'carMerged'})]
        pv['scenes'] = [{'id':'flowStructure','visible':{'pressureContour':{'colour':'steelblue'}},'gltf':True},
                        {'id':'vehicle','visible':{'carSurface':{'colour':'grey'}},'gltf':True}]
        render = blender_mesh(artifact('extract',0), cameras, gltf=True)
        render['nodes'] += [node('carImported','readGltf',{'file':artifact('extract',1)}),
                            node('carAxes','transform',{'rotation':[-90,0,0]},inputs={'input':'carImported'}),
                            node('carPaint','material',{'colour':[.32,.34,.37,1],'roughness':.4}),
                            node('car','assignMaterial',inputs={'input':'carAxes','material':'carPaint'})]
        render['scenes'][0]['visible'].append('car')
        return workflow([('extract',pv),('render',render),
            ('movie',movie([artifact('render',i) for i in range(count)],presentation['fps']))])
    if name == 'site':
        qgis = read('site.input.json')
        godot = {'version':'schemaxis.godot/1','preview':True,'nodes':[
            node('map','sprite3D',{'file':artifact('map',2),'pixelSize':.01}),
            node('camera','camera',{'position':[0,0,7],'target':[0,0,0],'orbit':True}),
            node('light','directionalLight')]}
        return workflow([('map',qgis),('scene',godot)])
    if name == 'sprite':
        d = read('sprite.input.json')
        return d
    raise ValueError(name)


def env():
    return {**os.environ, 'PYTHONPATH': str(ROOT/'src'), 'PYTHONUNBUFFERED':'1'}


def command(args, log=None):
    cmd = [sys.executable, '-m', 'schemaxis', *map(str,args)]
    print('\n$ '+shlex.join(cmd), flush=True)
    if log is None:
        return subprocess.run(cmd,cwd=ROOT,env=env(),check=True)
    with log.open('w') as out:
        print('Native output is being retained in '+str(log), flush=True)
        p = subprocess.Popen(cmd,cwd=ROOT,env=env(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        try:
            for line in p.stdout:
                out.write(line);out.flush()
            if p.wait():
                print(log.read_text()[-5000:])
                raise subprocess.CalledProcessError(p.returncode,cmd)
            print('Passed. Transcript: '+str(log), flush=True)
        except KeyboardInterrupt:
            p.send_signal(2)
            try: p.wait(timeout=15)
            except subprocess.TimeoutExpired: p.terminate();p.wait(timeout=15)
            raise


def latest(name):
    p = RUNS / (name+'-latest.json')
    if not p.exists(): raise SystemExit('No completed run for '+name+'. Run it first.')
    return Path(json.loads(p.read_text())['directory'])


def gallery(directory):
    files = sorted(p for p in directory.rglob('*') if p.is_file()
                   and '.reopen' not in p.parts and '.attempts' not in p.parts)
    # Scheduled jobs keep publications under attempts; include those as fallback.
    if not any(p.suffix=='.png' for p in files):
        files = sorted(p for p in directory.rglob('*') if p.is_file() and '.reopen' not in p.parts)
    parts = ['<!doctype html><meta charset="utf-8"><title>Schemaxis demonstration</title>',
        '<style>body{font:17px system-ui;margin:36px;background:#eef3f5;color:#173247}h1{font-size:32px}section{display:inline-block;vertical-align:top;width:46%;margin:1%;background:white;padding:12px;box-sizing:border-box}img,video{width:100%}a{color:#126386}small{overflow-wrap:anywhere}</style>',
        '<h1>Schemaxis — '+html.escape(directory.name)+'</h1><p>Retained native outputs from this run. Use the input and verification records alongside these previews.</p>']
    seen = set()
    for p in files:
        rel=p.relative_to(directory).as_posix()
        if p.suffix.lower() in ('.png','.mp4','.mkv') and 'preview' not in p.parts:
            # Path based identity: never silently deduplicate different camera frames.
            if rel in seen:continue
            seen.add(rel)
            tag = '<img loading="lazy" src="'+html.escape(rel,quote=True)+'">' if p.suffix=='.png' else '<video controls loop src="'+html.escape(rel,quote=True)+'"></video>'
            parts.append('<section>'+tag+'<small>'+html.escape(rel)+'</small></section>')
    parts.append('<h2>Editable and scientific outputs</h2><ul>')
    for p in files:
        if p.suffix.lower() in ('.fcstd','.step','.blend','.csv','.vtp','.vtu','.qgz','.gpkg','.tscn','.godot'):
            rel=p.relative_to(directory).as_posix()
            parts.append('<li><a href="'+html.escape(rel,quote=True)+'">'+html.escape(rel)+'</a></li>')
    parts.append('</ul>')
    (directory/'gallery.html').write_text('\n'.join(parts))
    return directory/'gallery.html'


def main():
    global APPS, CASE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('doctor','plan','run','verify','show','console','paths','movies','open','export'))
    parser.add_argument('name',nargs='?',choices=NAMES)
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--timeout',type=int,default=600)
    parser.add_argument('--app',choices=('freecad','blender','godot','video'),default='video')
    for key, variable in APP_ENV.items():
        parser.add_argument('--' + key, default=os.environ.get(variable), help='Absolute path; environment: ' + variable)
    parser.add_argument('--case', default=os.environ.get('SCHEMAXIS_DEMO_CASE'), help='Absolute OpenFOAM .foam path; environment: SCHEMAXIS_DEMO_CASE')
    args=parser.parse_args()
    APPS = {key: getattr(args, key.replace('-', '_')) for key in APP_ENV
            if getattr(args, key.replace('-', '_'))}
    CASE = args.case
    for key, value in {**APPS, **({'case': CASE} if CASE else {})}.items():
        if not Path(value).is_absolute():
            parser.error('--' + key + ' must be an absolute path')
    RUNS.mkdir(parents=True,exist_ok=True)
    if args.action=='doctor':
        failed=False
        required = REQUIRED[args.name] if args.name else tuple(k for k in APP_ENV if k != 'freecad-gui')
        for key in required:
            value = APPS.get(key)
            p = Path(value)/'bin/pvbatch' if value and key=='paraview-root' else Path(value) if value else None
            ok = p is not None and p.is_file() and os.access(p,os.X_OK)
            print(('OK      ' if ok else 'MISSING ')+key+': '+str(p or APP_ENV[key]));failed |= not ok
        if args.name is None or args.name in ('vehicle','region','mirror','cfd-render'):
            case=Path(read('vehicle.input.json')['settings']['case'])
            ok=case.is_file()
            print(('OK      ' if ok else 'MISSING ')+'vehicle: '+str(case));failed |= not ok
        raise SystemExit(int(failed))
    if args.action=='console':
        workspace=RUNS/('console-'+dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        print('Leave this terminal running. Open the COMPLETE printed URL, including ?token=... .',flush=True)
        print('Console commands are in '+str(HERE/'console-commands.txt'),flush=True)
        command(['console','--provider','freecad','--workspace',workspace,'--web','--port',args.port])
        return
    if not args.name:parser.error('this action requires a demo name')
    if args.action=='export':
        target=RUNS/'inputs';target.mkdir(exist_ok=True)
        path=target/(args.name+'.json');write(path,build(args.name));print(path);return
    if args.action=='open':
        d=latest(args.name)
        pattern={'freecad':'model.FCStd','blender':'0000.blend','godot':'project.godot','video':'video.mp4'}[args.app]
        candidates=[p for p in (d/'run').rglob(pattern) if not any('reopen' in part.lower() for part in p.parts)]
        if args.app=='video' and not candidates:
            candidates=list((d/'run').rglob('video.mkv'))
        if len(candidates)!=1:
            raise SystemExit('Expected one '+args.app+' output; use paths '+args.name+' to select explicitly. Found '+str(candidates))
        p=candidates[0]
        if args.app != 'video':require_apps(('freecad-gui' if args.app == 'freecad' else args.app,))
        if args.app=='freecad':cmd=[APPS['freecad-gui'],str(p)]
        elif args.app=='blender':cmd=[APPS['blender'],str(p)]
        elif args.app=='godot':cmd=[APPS['godot'],'--path',str(p.parent),'--rendering-method','gl_compatibility']
        else:cmd=['xdg-open',str(p)]
        print('$ '+shlex.join(cmd));subprocess.Popen(cmd,cwd=ROOT,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);return
    if args.action=='movies':
        require_apps(('ffmpeg',))
        if args.name not in ('vehicle','region','mirror'):
            parser.error('movies is for ParaView image studies; pipe/cfd-render already include movies')
        d=latest(args.name)
        command(['verify',d/'run'],d/'verify.log')
        receipt=json.loads((d/'run/verification.json').read_text())
        groups={}
        for a in receipt['artifacts']:
            i=a.get('identity',{})
            if i.get('kind')=='image':
                key=i['scene']+'-appearance-'+str(i.get('appearance',0))
                groups.setdefault(key,[]).append(a['file'])
        target=d/('movies-'+dt.datetime.now().strftime('%H%M%S-%f'))
        target.mkdir()
        for key,files in groups.items():
            # Receipt order retains numerical camera and visit ordering (10 follows 9).
            doc=movie([f for f in files for _ in range(4)],8)
            write(target/(key+'.json'),doc)
            command(['run',target/(key+'.json'),'--output-directory',target/key,
                     '--ffmpeg',APPS['ffmpeg']],target/(key+'.log'))
            command(['verify',target/key],target/(key+'-verify.log'))
        print(gallery(d));return
    if args.action in ('verify','show','paths'):
        d=latest(args.name)
        if args.action=='verify':command(['verify',d/'run'])
        elif args.action=='show':
            p=gallery(d);print(p);subprocess.run(['xdg-open',str(p)],check=True)
        else:
            print(d)
            for p in sorted((d/'run').rglob('*')):
                if p.suffix.lower() in ('.fcstd','.blend','.mp4','.csv','.godot','.qgz'):print(p)
        return
    stamp=dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    directory=RUNS/(args.name+'-'+stamp)
    directory.mkdir()
    document=build(args.name)
    write(directory/'input.json',document)
    for p in HERE.glob('*.json'):
        (directory/('source-'+p.name)).write_bytes(p.read_bytes())
    if args.action=='plan':
        # Native time metadata is unavailable to a pure plan; use a representative time only.
        plan_document=copy.deepcopy(document)
        used_placeholder=False
        def fixed_time(d):
            nonlocal used_placeholder
            if isinstance(d.get('times'),dict):
                d['times']=[1.0];used_placeholder=True
            for operation in d.get('operations',[]):fixed_time(operation['document'])
        fixed_time(plan_document)
        write(directory/'plan-input.json',plan_document)
        command(['plan',directory/'plan-input.json'],directory/'plan.log')
        print('Plan only. CFD time 1.0 is a planning placeholder; run selects the actual latest time.'
              if used_placeholder else 'Plan only; no native application was launched.')
        print(directory)
        return
    require_apps(REQUIRED[args.name])
    flags=[v for key,value in APPS.items() if key != 'freecad-gui' for v in ('--'+key,value)]
    start=time.monotonic()
    command(['run',directory/'input.json','--output-directory',directory/'run','--timeout',args.timeout,*flags],directory/'run.log')
    command(['verify',directory/'run'],directory/'verify.log')
    write(directory/'run-summary.json',{'verified':True,'elapsedSeconds':round(time.monotonic()-start,2),'name':args.name})
    write(RUNS/(args.name+'-latest.json'),{'directory':str(directory)})
    print('\nREADY '+str(gallery(directory)))
    print('Elapsed seconds: '+str(round(time.monotonic()-start,2)))
    print('Open: python3 examples/demos/demo.py show '+args.name)


if __name__=='__main__':
    main()
