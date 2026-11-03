#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Prepare, independently preflight and run a three-method ParaView AI pilot.

Synthetic spatial/time fields avoid private case redistribution and make silent
errors checkable. Bulk evidence, model transcripts and native results stay local.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from benchmark_workflows import ROOT, command, save
from run_rlc_ai_pilot import invoke
from summarise_ai_pilot import summarise

RECIPES=ROOT/'examples/benchmarks/paraview'
NATIVE=Path(__file__).with_name('paraview_benchmark_native.py')
ARMS=('ordinary','ordinary-template','schemaxis')
ORDERS=(ARMS,('schemaxis','ordinary','ordinary-template'),
        ('ordinary-template','schemaxis','ordinary'),('ordinary','schemaxis','ordinary-template'))
TASK='''Implement or use a reusable ParaView procedure driven by task.json.
Read the supplied PVD series in inputs/CASE-ID/series.pvd using native ParaView.
These are synthetic analytic fields, not solved CFD. Read the data; do not replace
native processing with fabricated analytic outputs. For every case, time and slice
fraction, cut a plane normal to sliceAxis (0=x, 1=y, 2=z), at fraction times the
case extent on that axis. Publish a nonempty VTP preserving both POINTS T and
CELLS T: these have deliberately different values despite their identical names.
Output: submission/CASE-ID/slice-TIME_INDEX-SLICE_INDEX.vtp.

For each slice, render every appearance and camera in task.json. Appearance field
association, preset and fixed range must be honoured; do not auto-rescale per image.
Use Surface, opacity 1, no scalar bars, white solid background, no orientation axes.
Use parallel projection, given view-up, distance and parallel scale. Focal point is
the slice bounding-box centre. Camera position is focal point plus normalized
direction times distance. Use imageSize exactly and native default surface lighting.
PNG names: slice-TIME_INDEX-SLICE_INDEX-appearance-APPEARANCE_INDEX-camera-CAMERA_INDEX.png.
All indices follow current task list order. Render with --force-offscreen-rendering.
An independent grader reads geometry/fields and decoded PNG pixels. It checks
camera/colour consistency with tolerance for small raster-edge differences.

Keep your editable procedure and rerun instructions. Later turns repeat inputs,
revise the task/add a case, and damage publications to test recovery. Validate any
outputs you reuse; complete regeneration is also allowed. Preserve native logs.
Native location/configuration is in runtime.json; pvbatch is /opt/paraview/bin/pvbatch.
Python 3 and ordinary system tools are available. Keep work under /work. Inputs
are read-only. Do not install software, change accounts, submit cluster jobs,
communicate externally, or look for coordinator/grader solutions. Native public
manuals/help are allowed. Report incomplete results honestly. Execute the task.
'''


def case(identity,length,width,height,offset,axis=0,fractions=None,times=None):
    directions=([1,0,0],[1,1,1]) if axis==0 else ([0,1,0],[1,1,1])
    return {'id':identity,'length':length,'width':width,'height':height,'offset':offset,
            'sliceAxis':axis,'fractions':fractions or [.25,.75],'times':times or [0,1],
            'cameras':[{'direction':d,'up':[0,0,1],'distance':6,
                        'scale':.7*max(length if axis==1 else width,height)} for d in directions]}


def tasks():
    initial={'inputs':'/work/inputs','imageSize':[192,160],
        'appearances':[{'field':['POINTS','T'],'range':[0,60],'preset':'Grayscale'},
                       {'field':['CELLS','T'],'range':[60,130],'preset':'Grayscale'}],
        'cases':[case('field-a',2,1,.6,4),case('field-b',3,1.4,.8,12)]}
    revision=copy.deepcopy(initial)
    revision['cases'][0]=case('field-a',2,1,.6,4,axis=1,fractions=[.33,.66,.85],times=[0,2])
    revision['cases'].append(case('field-c',1.6,.9,.7,7,times=[0,2]))
    revision['appearances'][0]['range']=[0,50]
    return {'initial':initial,'revision':revision}


def digest(task):
    return hashlib.sha256(json.dumps(task,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def tree_digest(root):
    return digest({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(root.rglob('*')) if p.is_file()})


def runtime_configuration():
    return {'version':1,'locations':{'roots':['/opt/paraview']}}


def native_command(pvbatch,script,*args):
    return [str(pvbatch),'--force-offscreen-rendering',str(script),*map(str,args)]


def grade(task_path,submission,reference,pvbatch,logs):
    logs.mkdir(parents=True,exist_ok=False)
    output=logs/'grade.json'
    command(native_command(pvbatch,NATIVE,'grade',task_path,submission,reference,output),logs,'grader',180)
    result=json.loads(output.read_text())
    task=json.loads(task_path.read_text())
    expected={c['id'] for c in task['cases']}
    actual={p.name for p in submission.iterdir() if p.is_dir()} if submission.is_dir() else set()
    result['caseSetMatches']=actual==expected
    result['passed']=result['passed'] and result['caseSetMatches']
    save(output,result)
    return result


def prepare(destination,pvbatch):
    destination.mkdir(parents=True,exist_ok=False)
    for phase,task in tasks().items():
        root=destination/phase; root.mkdir(); save(root/'task.json',task)
        command(native_command(pvbatch,NATIVE,'fixture',root/'task.json',root/'inputs'),root,'fixtures')
        host={**task,'inputs':str(root/'inputs')}; save(root/'host-task.json',host)
        command(native_command(pvbatch,RECIPES/'native_recipe.py',root/'host-task.json',root/'reference'),root,'reference')
        checked=grade(root/'host-task.json',root/'reference',root/'reference',pvbatch,root/'reference-grade')
        if not checked['passed']: raise RuntimeError('analytic reference failed')


def prove(package,destination,pvbatch,config):
    destination.mkdir(parents=True,exist_ok=False)
    records=[]
    for phase in tasks():
        root=destination/phase; root.mkdir()
        command(['/usr/bin/env','PYTHONPATH='+str(ROOT/'src'),
                 'SCHEMAXIS_CONFIG='+str(config),sys.executable,
                 str(RECIPES/'schemaxis_recipe.py'),str(package/phase/'host-task.json'),
                 str(root/'submission')],root,'schemaxis',300)
        checked=grade(package/phase/'host-task.json',root/'submission',package/phase/'reference',pvbatch,root/'grade')
        records.append({'phase':phase,'grade':checked})
    save(destination/'report.json',records)
    if not all(r['grade']['passed'] for r in records): raise RuntimeError('Schemaxis native reference preflight failed')


def challenge(package,destination,pvbatch):
    destination.mkdir(parents=True,exist_ok=False)
    root=package/'initial'
    mutations={
        'wrong-time':('field-a/slice-1-0.vtp','field-a/slice-0-0.vtp'),
        'wrong-plane':('field-a/slice-0-1.vtp','field-a/slice-0-0.vtp'),
        'wrong-association':('field-a/slice-0-0-appearance-1-camera-0.png','field-a/slice-0-0-appearance-0-camera-0.png'),
        'wrong-camera':('field-a/slice-0-0-appearance-0-camera-1.png','field-a/slice-0-0-appearance-0-camera-0.png'),
        'stale-image-time':('field-a/slice-0-0-appearance-0-camera-0.png','field-a/slice-1-0-appearance-0-camera-0.png'),
        'missing-image':(None,'field-a/slice-0-0-appearance-0-camera-0.png'),
        'missing-case':(None,'field-b')}
    records=[]
    for name,(source,target) in mutations.items():
        output=destination/name; submission=output/'submission'
        shutil.copytree(root/'reference',submission)
        if source: shutil.copyfile(submission/source,submission/target)
        elif (submission/target).is_dir(): shutil.rmtree(submission/target)
        else: (submission/target).unlink()
        save(submission/'claimed-success.json',{'verified':True})
        result=grade(root/'task.json',submission,root/'reference',pvbatch,output/'grade')
        records.append({'mutation':name,'rejected':not result['passed']})
    # Render a genuinely wrong fixed scale; do not just forge its receipt.
    output=destination/'wrong-colour-range'; output.mkdir()
    task=json.loads((root/'host-task.json').read_text()); task['appearances'][0]['range']=[0,30]
    save(output/'task.json',task)
    command(native_command(pvbatch,RECIPES/'native_recipe.py',output/'task.json',output/'submission'),output,'render')
    result=grade(root/'task.json',output/'submission',root/'reference',pvbatch,output/'grade')
    records.append({'mutation':'wrong-colour-range','rejected':not result['passed']})
    save(destination/'report.json',{'passed':all(r['rejected'] for r in records),'checks':records})
    if not all(r['rejected'] for r in records): raise RuntimeError('independent grader accepted a mutation')


# HOME inside the isolated sandbox, bound to a fresh per-run directory.
SANDBOX_HOME='/sandbox/home'


def sandbox(home,work,inputs,pvroot,claude,credentials,product=None):
    args=['bwrap','--ro-bind','/usr','/usr']
    for alias in ('bin','sbin','lib','lib64'): args+=['--symlink','usr/'+alias,'/'+alias]
    args+=['--ro-bind','/etc','/etc','--ro-bind','/run/systemd/resolve','/run/systemd/resolve',
           '--proc','/proc','--dev','/dev','--tmpfs','/tmp',
           '--bind',str(home),SANDBOX_HOME,'--dir',SANDBOX_HOME+'/.claude',
           '--ro-bind',str(credentials),SANDBOX_HOME+'/.claude/.credentials.json',
           '--ro-bind',str(claude),'/opt/claude','--ro-bind',str(pvroot),'/opt/paraview',
           '--bind',str(work),'/work','--ro-bind',str(inputs),'/work/inputs',
           '--chdir','/work','--clearenv','--setenv','HOME',SANDBOX_HOME,
           '--setenv','PATH','/usr/bin:/bin','--setenv','LANG','C.UTF-8',
           '--setenv','QT_QPA_PLATFORM','offscreen','--setenv','OMP_NUM_THREADS','1',
           '--setenv','LIBGL_ALWAYS_SOFTWARE','1','--setenv','__GLX_VENDOR_LIBRARY_NAME','mesa',
           '--setenv','__EGL_VENDOR_LIBRARY_FILENAMES','/usr/share/glvnd/egl_vendor.d/50_mesa.json',
           '--setenv','SCHEMAXIS_CONFIG','/work/runtime.json','--unshare-pid','--die-with-parent']
    if product: args+=['--ro-bind',str(product),'/opt/schemaxis','--setenv','PYTHONPATH','/opt/schemaxis/src']
    # Give each isolated invocation its own software-rendering X server. The
    # installed ParaView needs X even with offscreen publication enabled.
    return args+['--','/usr/bin/xvfb-run','-a','-s','-screen 0 1024x768x24']


def damage(work):
    changes=[]
    missing=work/'submission/field-a/slice-0-0.vtp'
    if missing.is_file(): missing.unlink(); changes.append({'file':str(missing.relative_to(work)),'action':'deleted'})
    target=work/'submission/field-b/slice-0-0-appearance-0-camera-0.png'
    wrong=work/'submission/field-b/slice-0-0-appearance-1-camera-1.png'
    if target.is_file() and wrong.is_file():
        shutil.copyfile(wrong,target); changes.append({'file':str(target.relative_to(work)),'action':'replaced with wrong appearance/view'})
    return changes


def run(args,pvroot):
    destination=args.output_directory.resolve(); destination.mkdir(parents=True,exist_ok=False)
    package=args.package.resolve(); product=destination/'product'
    shutil.copytree(ROOT/'src',product/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (product/'docs').mkdir()
    for name in ('getting-started.md','workflow-authoring.md','json-input.md','schema-guide.md','capability-discovery.md'):
        shutil.copyfile(ROOT/'docs'/name,product/'docs'/name)
    report={'kind':'autonomous-ai-three-method-pilot','family':'paraview','replicates':1,
        'model':args.model,'effort':args.effort,'schemaxisMode':'required','status':'running','runs':[],
        'sourceCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'productSourceDigest':tree_digest(product/'src'), 'recipeDigest':tree_digest(RECIPES),
        'limits':{'wallSecondsPerInvocation':args.seconds,'claudeMaxBudgetUSDFlag':args.budget_usd},
        'orders':ORDERS,'conditions':{'ordinary':'native scripting from scratch',
        'ordinary-template':'complete reusable native Python recipe','schemaxis':'complete reusable Schemaxis pipeline recipe'},
        'scope':'one conversation per method; rotating order is not independent replication; network available'}
    sessions={}
    for arm in ARMS:
        base=destination/arm; work=base/'work'; work.mkdir(parents=True); home=base/'home'; home.mkdir()
        (work/'inputs').mkdir(); save(work/'runtime.json',runtime_configuration())
        extra='\nUse ordinary ParaView Python; Schemaxis is unavailable and prohibited.\n'
        if arm!='ordinary':
            script='native_recipe.py' if arm=='ordinary-template' else 'schemaxis_recipe.py'
            shutil.copyfile(RECIPES/script,work/script)
            extra+=f'\nA complete reusable starting procedure is supplied: {script}. You may use, inspect and modify it.\n'
        if arm=='schemaxis':
            extra='\nUse Schemaxis for all slicing and rendering. Ordinary Python may prepare inputs, inspect results and collect publications.\n'
            extra+='A complete reusable procedure is supplied: schemaxis_recipe.py. Run with Python 3. Source/docs: /opt/schemaxis.\n'
        (work/'TASK.md').write_text(TASK+extra+f'\nTime allowance: {args.seconds} seconds per turn.\n')
        sessions[arm]=str(uuid.uuid4())
        prefix=sandbox(home,work,package/'initial/inputs',pvroot,args.claude,args.credentials,product if arm=='schemaxis' else None)
        # Execute each supplied recipe in the actual namespace before model usage.
        save(work/'task.json',json.loads((package/'initial/task.json').read_text()))
        probe_script='schemaxis_recipe.py' if arm=='schemaxis' else 'native_recipe.py'
        if arm=='ordinary': shutil.copyfile(RECIPES/'native_recipe.py',work/probe_script)
        launch=['python3','/work/'+probe_script,'/work/task.json','/work/.preflight-output'] if arm=='schemaxis' else native_command('/opt/paraview/bin/pvbatch','/work/'+probe_script,'/work/task.json','/work/.preflight-output')
        probe=subprocess.run(prefix+launch,text=True,capture_output=True,timeout=240)
        (base/'native-preflight.log').write_text(probe.stdout+probe.stderr)
        if arm=='ordinary': (work/probe_script).unlink()
        if probe.returncode: raise RuntimeError('sandbox native preflight failed: '+arm)
        shutil.move(work/'.preflight-output',base/'native-preflight-output')
        checked=grade(package/'initial/task.json',base/'native-preflight-output',
                      package/'initial/reference',pvroot/'bin/pvbatch',base/'native-preflight-grade')
        if not checked['passed']: raise RuntimeError('sandbox independent artifact preflight failed: '+arm)
    save(destination/'report.json',report)
    for index,label in enumerate(('initial','repeat','revision','repair')):
        phase='initial' if index<2 else 'revision'
        for arm in ORDERS[index]:
            base=destination/arm; work=base/'work'; home=base/'home'
            task=json.loads((package/phase/'task.json').read_text()); save(work/'task.json',task)
            mutations=damage(work) if label=='repair' else []
            prefix=sandbox(home,work,package/phase/'inputs',pvroot,args.claude,args.credentials,product if arm=='schemaxis' else None)
            command_args=prefix+['/opt/claude','-p','--safe-mode','--strict-mcp-config','--mcp-config','{"mcpServers":{}}',
                '--tools','Bash,Read,Write,Edit,Glob,Grep','--allowedTools','Bash','Read','Write','Edit','Glob','Grep',
                '--permission-mode','dontAsk','--model',args.model,'--effort',args.effort,
                '--max-budget-usd',str(args.budget_usd),'--output-format','stream-json','--verbose']
            command_args+=['--session-id',sessions[arm]] if label=='initial' else ['--resume',sessions[arm]]
            prompts={'initial':'Read TASK.md and task.json. Implement or use the reusable procedure and execute all cases now.',
                'repeat':'Repeat the unchanged task using your existing procedure. Validate any reused publications; regeneration is allowed. Execute now and report what reran or reused.',
                'revision':'task.json and read-only inputs now contain revised parameters and a new case. Read them and execute all requested outputs using or adapting your procedure. Starting recipes were not regenerated.',
                'repair':'Some published files have been deleted or replaced with incorrect outputs. task.json and inputs are unchanged. Check and repair the complete submission using your procedure, retaining evidence. Do not trust file existence alone.'}
            print(json.dumps({'event':'start','arm':arm,'round':label}),flush=True)
            record=invoke(command_args,prompts[label],base/label,args.seconds)
            record.update(arm=arm,round=label,taskDigest=digest(task),
                          inputDigest=tree_digest(package/phase/'inputs'),mutations=mutations)
            if record['terminalReason']=='api_error' or record['apiErrorStatus'] is not None:
                record['grade']={'passed':None,'cases':[],'status':'not-scored'}
                report['runs'].append(record); report.update(status='blocked',blockedReason=record['providerMessage'])
                save(destination/'report.json',report); return report
            shutil.copytree(work,base/label/'workspace',symlinks=True)
            submission=base/label/'workspace/submission'
            record['grade']=grade(package/phase/'task.json',submission,package/phase/'reference',pvroot/'bin/pvbatch',base/label/'grade')
            report['runs'].append(record); save(destination/'report.json',report)
            print(json.dumps({'event':'finish','arm':arm,'round':label,'seconds':record['wallSeconds'],
                              'passed':record['grade']['passed']}),flush=True)
    report['status']='complete'; report['allArtifactsPassed']=all(r['grade']['passed'] for r in report['runs'])
    save(destination/'report.json',report)
    measured=summarise(report); measured['scope']=report['scope']; save(destination/'measurements.json',measured)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','prove','challenge','run'))
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--package',type=Path)
    parser.add_argument('--model',default='claude-opus-5-5')
    parser.add_argument('--effort',default='high'); parser.add_argument('--seconds',type=int,default=600)
    parser.add_argument('--budget-usd',type=float,default=6)
    parser.add_argument('--claude',type=Path,default=Path.home()/'.local/bin/claude')
    parser.add_argument('--credentials',type=Path,default=Path.home()/'.claude/.credentials.json')
    args=parser.parse_args(); args.output_directory=args.output_directory.resolve()
    args.claude=args.claude.resolve(); args.credentials=args.credentials.resolve()
    config=args.config.resolve(); os.environ['SCHEMAXIS_CONFIG']=str(config)
    pvroot=Path(json.loads(config.read_text())['locations']['roots'][0]).resolve()
    if args.action=='prepare': prepare(args.output_directory,pvroot/'bin/pvbatch')
    elif args.action=='prove': prove(args.package.resolve(),args.output_directory,pvroot/'bin/pvbatch',config)
    elif args.action=='challenge': challenge(args.package.resolve(),args.output_directory,pvroot/'bin/pvbatch')
    else:
        report=run(args,pvroot)
        return 2 if report['status']=='blocked' else 0 if report['allArtifactsPassed'] else 1
    return 0


if __name__=='__main__': raise SystemExit(main())
