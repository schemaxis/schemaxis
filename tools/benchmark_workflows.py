#!/usr/bin/env python3
# Copyright (C) 2026 David L F Gaden
"""Prepare and prove repeatable workflow benchmarks; not autonomous AI scores.

The grader reads neutral artifacts and never calls Schemaxis.verify or trusts
producer receipts. Native reference implementations are coordinator-only helpers.
"""
import argparse
import copy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from benchmark_grading import mesh_check
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT/'examples/benchmarks/templates'
NATIVE = Path(__file__).with_name('benchmark_native.py')
FAMILIES = ('rlc', 'mesh', 'cfd', 'table')


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def require(condition, message):
    if not condition: raise ValueError(message)


def near(actual, expected, tolerance=1e-7):
    require(math.isfinite(actual) and math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance),
            f'{actual!r} differs from {expected!r}')


def validate(spec):
    require(spec.get('version') == 'schemaxis.benchmark-cases/1', 'unsupported benchmark manifest')
    require(set(spec.get('rounds', {})) == {'initial', 'revision'}, 'initial and revision rounds required')
    for cases in spec['rounds'].values():
        require(isinstance(cases, list) and 1 <= len(cases) <= 32, 'use 1–32 cases')
        names = set()
        for case in cases:
            name = case.get('id'); family = case.get('family')
            require(isinstance(name, str) and re.fullmatch('[a-z][a-z0-9-]{0,47}', name) and name not in names, 'invalid/repeated case id')
            require(family in FAMILIES, 'unknown benchmark family'); names.add(name)
            required = {'rlc': ('resistance','inductance','capacitance','amplitude','start','stop','points'),
                        'mesh': ('length','width','height','meshSize'),
                        'cfd': ('length','width','height','speed','acceleration','pressure','pressureRate','times','fractions'),
                        'table': ('columns','rows')}[family]
            require(set(case) == {'id','family',*required}, 'case fields differ from the documented contract')
            if family == 'table':
                columns = case['columns']; rows = case['rows']
                require(isinstance(columns,list) and 1 <= len(columns) <= 16 and all(isinstance(c,str) and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,47}',c) for c in columns) and len(set(columns))==len(columns),'invalid columns')
                require(isinstance(rows,list) and 1 <= len(rows) <= 512,'invalid table length')
                require(all(isinstance(r,list) and len(r)==len(columns) and all(type(x) in (int,float) and math.isfinite(x) for x in r) for r in rows),'invalid numeric table')
                continue
            for key in required:
                if key in ('times','fractions'): continue
                require(type(case[key]) in (int,float) and math.isfinite(case[key]), 'nonfinite/non-numeric '+key)
            if family == 'rlc':
                for key, low, high in [('resistance',.001,1e9),('inductance',1e-9,1e3),('capacitance',1e-12,1),('start',.001,1e9),('stop',.001,1e9)]:
                    require(low <= case[key] <= high, 'out of bounds '+key)
                require(case['stop']>case['start'] and 0<abs(case['amplitude'])<=1000, 'invalid sweep')
                require(type(case['points']) is int and 3 <= case['points'] <= 512, 'invalid points')
            else:
                require(all(.01 <= case[k] <= 100 for k in ('length','width','height')), 'geometry bounds')
                if family == 'mesh':
                    require(.1 <= case['meshSize'] <= 100 and math.prod(case[k]/case['meshSize'] for k in ('length','width','height')) <= 10000, 'mesh workload bound')
                else:
                    require(isinstance(case['times'],list) and 1<=len(case['times'])<=3 and len(set(case['times']))==len(case['times']) and all(type(t) in (int,float) and t in (0,1,2) for t in case['times']), 'fixture times are 0,1,2')
                    require(isinstance(case['fractions'],list) and 1<=len(case['fractions'])<=8 and len(set(case['fractions']))==len(case['fractions']) and all(type(f) in (int,float) and 0<f<1 for f in case['fractions']), 'slice fractions must be internal and unique')
    return spec


def csv_write(path, columns, rows):
    with Path(path).open('w', newline='') as stream:
        writer = csv.writer(stream); writer.writerow(columns); writer.writerows(rows)


def csv_read(path):
    require(Path(path).is_file() and Path(path).stat().st_size < 4*1024*1024,'missing/excessive CSV')
    with Path(path).open(newline='') as stream: rows = list(csv.reader(stream))
    require(bool(rows), 'empty CSV')
    return rows[0], [[float(v) for v in r] for r in rows[1:]]


def make_foam(case, target):
    """Own analytic 2x2x2 mesh/field fixture. No solver or colleague data involved."""
    target.mkdir(parents=True, exist_ok=False); (target/'system').mkdir(); (target/'constant/polyMesh').mkdir(parents=True)
    def header(cls, obj):
        return f'FoamFile\n{{ version 2.0; format ascii; class {cls}; object {obj}; }}\n'
    points = [(case['length']*i/2,case['width']*j/2,case['height']*k/2) for k in range(3) for j in range(3) for i in range(3)]
    def index(i,j,k): return i+3*j+9*k
    faces = {}; cell = 0
    for k in range(2):
        for j in range(2):
            for i in range(2):
                v = [index(i,j,k),index(i+1,j,k),index(i+1,j+1,k),index(i,j+1,k),index(i,j,k+1),index(i+1,j,k+1),index(i+1,j+1,k+1),index(i,j+1,k+1)]
                for local in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]:
                    face = tuple(v[q] for q in local); key = tuple(sorted(face))
                    if key in faces: faces[key][2] = cell
                    else: faces[key] = [face, cell, None]
                cell += 1
    internal = sorted((f for f in faces.values() if f[2] is not None), key=lambda f:(f[1],f[2]))
    exterior = [f for f in faces.values() if f[2] is None]; ordered = internal+exterior
    mesh = target/'constant/polyMesh'
    def listing(name,cls,records): (mesh/name).write_text(header(cls,name)+str(len(records))+'\n(\n'+'\n'.join(records)+'\n)\n')
    listing('points','vectorField',['('+' '.join(map(str,p))+')' for p in points])
    listing('faces','faceList',['4('+' '.join(map(str,f[0]))+')' for f in ordered])
    listing('owner','labelList',[str(f[1]) for f in ordered]); listing('neighbour','labelList',[str(f[2]) for f in internal])
    (mesh/'boundary').write_text(header('polyBoundaryMesh','boundary')+f'1\n(\nwalls {{ type patch; nFaces {len(exterior)}; startFace {len(internal)}; }}\n)\n')
    (target/'system/controlDict').write_text(header('dictionary','controlDict')+'application fixture; startFrom startTime; startTime 0; stopAt endTime; endTime 2; deltaT 1; writeControl timeStep; writeInterval 1;\n')
    for t in (0,1,2):
        folder=target/str(t);folder.mkdir()
        for name,cls,dims,value in [('U','volVectorField','[0 1 -1 0 0 0 0]',f'({case["speed"]+case["acceleration"]*t} 0 0)'),('p','volScalarField','[1 -1 -2 0 0 0 0]',str(case['pressure']+case['pressureRate']*t))]:
            (folder/name).write_text(header(cls,name)+f'dimensions {dims};\ninternalField uniform {value};\nboundaryField {{ walls {{ type fixedValue; value uniform {value}; }} }}\n')
    (target/'case.foam').write_text('')
    save(target/'PROVENANCE.json',{'origin':'Generated analytic fixture, not a solved flow','cells':8,'pressureUnits':'Pa','velocityUnits':'m/s','generator':'tools/benchmark_workflows.py'})


def materialise(case, inputs):
    family=case['family']; doc=json.loads((TEMPLATES/(family+'.json')).read_text())
    if family=='rlc':
        circuit=doc['operations'][0]['document'];network=circuit['circuit']
        network['resistors'][0]['resistance']=case['resistance'];network['inductors'][0]['inductance']=case['inductance'];network['capacitors'][0]['capacitance']=case['capacitance']
        for k in ('start','stop','points','amplitude'):circuit[k]=case[k]
    elif family=='mesh':
        opts=doc['operations'][0]['document']['nodes'][0]['options']
        for k in ('length','width','height'):opts[k]=case[k]
        opts=doc['operations'][1]['document']['nodes'][1]['options'];opts['size']=case['meshSize'];opts['faceGroups'][1]['coordinate']=case['length']
    elif family=='table':doc['operations'][0]['document']['nodes'][0]['options']['file']=str(inputs/case['id']/'input.csv')
    else:
        operations=[]
        for ti,t in enumerate(case['times']):
            for fi,f in enumerate(case['fractions']):
                part=copy.deepcopy(doc);part['times']=[t];part['nodes'][0]['options']['file']=str(inputs/case['id']/'case.foam')
                part['nodes'][2]['options']['origin'][0]=f*case['length']
                operations.append({'id':f'slice-{ti}-{fi}','document':part})
        doc={'version':'schemaxis.workflow/1','execution':{},'operations':operations}
    return doc


def prepare(spec, destination):
    validate(spec); destination.mkdir(parents=True,exist_ok=False);save(destination/'coordinator-cases.json',spec)
    for round_name,cases in spec['rounds'].items():
        round_dir=destination/round_name;round_dir.mkdir();inputs=round_dir/'inputs';inputs.mkdir()
        for case in cases:
            target=inputs/case['id']
            if case['family']=='cfd':make_foam(case,target)
            else:
                target.mkdir()
                if case['family']=='table':csv_write(target/'input.csv',case['columns'],case['rows'])
        for arm in ('ordinary','schemaxis'):
            packet=round_dir/arm;packet.mkdir();save(packet/'task.json',{'round':round_name,'cases':cases,'inputs':str(inputs)})
            (packet/'TASK.md').write_text(task_text(arm))
            if arm=='schemaxis':
                folder=packet/'templates';folder.mkdir()
                for case in cases:save(folder/(case['id']+'.json'),materialise(case,inputs))
    return destination


def task_text(arm):
    common='''# Reusable multi-case workflow challenge

Read task.json. Process every case from a reusable procedure and publish under
submission/CASE-ID/. Retain your editable procedure and concise instructions.
The coordinator will rerun identical inputs, then provide a revised task.json
with changed parameters and a new case. Do not embed expected answers or case IDs
in your implementation. Report failures honestly; partial output is not success.

Deliverables by family:
- rlc: source--R--L--output--C--ground, one grounded source. Use ngspice AC linear
  sweep with specified SI values. results.csv columns must be frequency_Hz,
  out_real_V,out_imag_V,out_magnitude_V,out_phase_deg (exp(+j*omega*t), degrees).
  Publish results.ods with the same table, and circuit.cir.
- mesh: FreeCAD box in mm; part.step and editable part.FCStd. First-order Gmsh
  tetrahedra in ASCII MSH 2.2 (mesh.msh). Physical groups: part volume tag 1,
  outside boundary tag 2, fixed at x=0 tag 3, loaded at x=length tag 4.
  Publish volume.vtu and boundary.vtu with cell physicalTag, plus ParaView's
  integrated volume table inspection.csv. Keep all boundary faces covered.
- cfd: read supplied reconstructed OpenFOAM case (these are analytic fixtures,
  NOT solved physics). For each listed time ti and x-fraction fi, publish a
  nonempty x-normal slice as slice-TI-FI.vtp. Preserve cell U and p, physical
  coordinates, and the requested time. Indices follow the input list order.
- table: preserve the supplied CSV's headers and numeric rows in results.csv
  and an editable results.ods. This is a simple overhead-control task.

Use the supplied runtime configuration. This is local serial work. No additional
simulation, installation or external data is required. The evaluator grades real
files, not your success claim. Keep runtime logs. Metrics include correctness,
revision success, elapsed time, tokens (if available), retries and intervention.
'''
    return common+('\nYou may use Schemaxis. templates/ contains materialised starting workflows;\nretain a reusable case-list-to-input procedure. Ordinary tools are also allowed.\nKnown limit: whole-workflow host planning of the CAD STEP handoff currently\nrejects an extensionless placeholder. CLI run resolves actual artifacts, or plan\neach stage after its producer runs. Do not weaken STEP validation.\n' if arm=='schemaxis' else '\nUse ordinary scripting/native APIs and documentation. Do not read or call\nSchemaxis, its templates, coordinator reference code or evaluator implementation.\n')


def locations(config):
    values=json.loads(Path(config).read_text())['locations'];values=dict(values)
    require(values.get('roots'), 'ParaView root required')
    values['pvbatch']=str(Path(values['roots'][0])/'bin/pvbatch')
    return values


def command(args,directory,stage,timeout=180):
    with (directory/(stage+'.stdout')).open('w') as out,(directory/(stage+'.stderr')).open('w') as err:
        process=subprocess.Popen(args,cwd=directory,stdout=out,stderr=err,start_new_session=True,
                                 env={**os.environ,'QT_QPA_PLATFORM':'offscreen','OMP_NUM_THREADS':'1'})
        try:code=process.wait(timeout=timeout)
        except BaseException:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=5)
            raise
    require(code==0, f'{stage} failed; inspect retained logs in {directory}')


def native(action,case,directory,loc,logdir=None):
    logdir=logdir or directory;logdir.mkdir(parents=True,exist_ok=True)
    case_path=logdir/(action+'-input.json');save(case_path,case)
    output=logdir/(action+'-output.json')
    if action in ('cad','cad_info'):
        script=logdir/(action+'.py')
        script.write_text('import sys\nsys.path.insert(0, '+repr(str(NATIVE.parent))+')\nfrom benchmark_native import main\nmain('+','.join(repr(str(v)) for v in (action,case_path,directory,output))+')\n')
        args=[loc['freecad'],str(script)]
    else:args=[loc['gmsh'] if action=='mesh' else loc['pvbatch'],str(NATIVE),action,str(case_path),str(directory),str(output)]
    command(args,logdir,action)
    require(output.is_file(),action+' produced no result')
    return json.loads(output.read_text())


def to_workbook(directory,loc):
    converted=directory/'converted';converted.mkdir()
    command([loc['calc'],'-env:UserInstallation='+str((directory/'profile').as_uri()),'--headless','--convert-to','ods','--outdir',str(converted),str(directory/'results.csv')],directory,'calc')
    shutil.copyfile(converted/'results.ods',directory/'results.ods')


def ordinary(case,inputs,directory,loc):
    family=case['family']
    if family=='rlc':
        text=f'''Benchmark circuit
Vsource in 0 DC {case['amplitude']:.17g} AC {case['amplitude']:.17g}
R1 in mid {case['resistance']:.17g}
L1 mid out {case['inductance']:.17g}
C1 out 0 {case['capacitance']:.17g}
.control
set numdgt=17
set wr_singlescale
set wr_vecnames
ac lin {case['points']} {case['start']:.17g} {case['stop']:.17g}
wrdata native.dat real(v(out)) imag(v(out))
quit
.endc
.end
'''
        (directory/'circuit.cir').write_text(text);command([loc['ngspice'],'-n','-b','circuit.cir'],directory,'ngspice')
        values=[list(map(float,line.split())) for line in (directory/'native.dat').read_text().splitlines()[1:]]
        rows=[[f,re,im,math.hypot(re,im),math.degrees(math.atan2(im,re))] for f,re,im in values]
        csv_write(directory/'results.csv',['frequency_Hz','out_real_V','out_imag_V','out_magnitude_V','out_phase_deg'],rows);to_workbook(directory,loc)
    elif family=='mesh':native('cad',case,directory,loc);native('mesh',case,directory,loc);native('mesh_export',case,directory,loc)
    elif family=='cfd':native('cfd',{**case,'file':str(inputs/case['id']/'case.foam')},directory,loc)
    else:shutil.copyfile(inputs/case['id']/'input.csv',directory/'results.csv');to_workbook(directory,loc)


def schemaxis_run(case,inputs,directory,loc,attempt):
    from schemaxis import workflow
    doc=materialise(case,inputs);save(directory/'workflow.json',doc)
    # Resume accepts only an unchanged authored workflow. Keep revisions as
    # distinct attempts; never pass changed documents to the resume API.
    digest=hashlib.sha256(json.dumps(doc,sort_keys=True).encode()).hexdigest()
    attempt=attempt/digest
    attempt.parent.mkdir(parents=True,exist_ok=True)
    outcome=workflow.execute(doc,attempt,locations={k:v for k,v in loc.items() if k!='pvbatch'},timeout=180,resume=attempt.exists())
    jobs={j['operation']:Path(j['directory']) for j in outcome['jobs']}
    def copy(source,name):shutil.copyfile(source,directory/name)
    family=case['family']
    if family=='rlc':
        copy(jobs['circuit']/'results.csv','results.csv');copy(jobs['circuit']/'circuit.cir','circuit.cir');copy(jobs['workbook']/'analysis.ods','results.ods')
    elif family=='table':copy(jobs['workbook']/'data.csv','results.csv');copy(jobs['workbook']/'analysis.ods','results.ods')
    elif family=='mesh':
        for source,name in [('model.step','part.step'),('model.FCStd','part.FCStd')]:copy(jobs['cad']/source,name)
        for source,name in [('result.msh','mesh.msh'),('volume.vtu','volume.vtu'),('boundary.vtu','boundary.vtu')]:copy(jobs['mesh']/source,name)
        # Both arms publish a native ParaView integration table. The shared
        # geometry workflow retains its own native inspection evidence as well.
        native('mesh_inspect',case,directory,loc)
    else:
        for op,job in jobs.items():
            receipt=json.loads((job/'verification.json').read_text())
            files=[Path(a['file']) for a in receipt['artifacts'] if a.get('identity',{}).get('kind')=='geometry' and Path(a['file']).suffix=='.vtp']
            require(len(files)==1,'expected one slice publication');copy(files[0],op+'.vtp')
    return [{'operation':j['operation'],'reused':j.get('reused',False)} for j in outcome['jobs']]


def workbook_table(path, expected_columns=None):
    with zipfile.ZipFile(path) as archive:
        info=archive.getinfo('content.xml');require(info.file_size<4*1024*1024,'excessive workbook')
        root=ET.fromstring(archive.read(info))
    ns={'t':'urn:oasis:names:tc:opendocument:xmlns:table:1.0','o':'urn:oasis:names:tc:opendocument:xmlns:office:1.0','x':'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
    tables=root.findall('.//t:table',ns)
    if expected_columns is not None:
        tables=[table for table in tables if table.find('t:table-row',ns) is not None and
                [''.join(cell.itertext()) for cell in table.find('t:table-row',ns).findall('t:table-cell',ns) if cell.get('{'+ns['o']+'}value-type') is not None]==expected_columns]
    require(len(tables)==1,'expected exactly one matching data sheet');rows=[]
    for row in tables[0].findall('t:table-row',ns):
        values=[]
        for cell in row.findall('t:table-cell',ns):
            kind=cell.get('{'+ns['o']+'}value-type')
            if kind is None:continue
            require(int(cell.get('{'+ns['t']+'}number-columns-repeated','1'))==1,'repeated cells unsupported')
            values.append(float(cell.get('{'+ns['o']+'}value')) if kind=='float' else ''.join(cell.itertext()))
        if values:
            require(int(row.get('{'+ns['t']+'}number-rows-repeated','1'))==1,'repeated rows unsupported');rows.append(values)
    require(bool(rows),'empty workbook');return rows[0],rows[1:]


def check_table(actual,expected):
    cols,rows=actual;ecols,erows=expected
    require(cols==ecols and len(rows)==len(erows),'table columns/count differ')
    for row,reference in zip(rows,erows):
        require(len(row)==len(reference),'table width differs')
        for a,e in zip(row,reference):near(a,e)


def grade_case(case,directory,loc,grade_dir):
    family=case['family']
    required = (['results.csv','results.ods'] if family in ('rlc','table') else
                ['part.step','part.FCStd','mesh.msh','volume.vtu','boundary.vtu','inspection.csv'] if family=='mesh' else
                [f'slice-{ti}-{fi}.vtp' for ti in range(len(case['times'])) for fi in range(len(case['fractions']))])
    require(directory.is_dir() and not directory.is_symlink(), 'missing or linked case directory')
    for name in required:require((directory/name).is_file() and not (directory/name).is_symlink(), 'missing or linked '+name)
    if family in ('rlc','table'):
        if family=='rlc':
            rows=[]
            for i in range(case['points']):
                f=case['start']+(case['stop']-case['start'])*i/(case['points']-1);w=2*math.pi*f
                z=case['amplitude']/(1-w*w*case['inductance']*case['capacitance']+1j*w*case['resistance']*case['capacitance'])
                rows.append([f,z.real,z.imag,abs(z),math.degrees(math.atan2(z.imag,z.real))])
            expected=(['frequency_Hz','out_real_V','out_imag_V','out_magnitude_V','out_phase_deg'],rows)
            require((directory/'circuit.cir').is_file(),'missing editable netlist')
        else:expected=(case['columns'],case['rows'])
        check_table(csv_read(directory/'results.csv'),expected);check_table(workbook_table(directory/'results.ods',expected[0]),expected)
        return {'rows':len(expected[1]),'workbookReadback':True}
    measured=native('vtk_info',case,directory,loc,grade_dir)
    if family=='mesh':
        volume=case['length']*case['width']*case['height'];area=case['width']*case['height']
        cad=native('cad_info',case,directory,loc,grade_dir);require(cad['stepValid'] and cad['objects']>0,'invalid/noneditable CAD')
        near(cad['stepVolume'],volume);require(any(math.isclose(v,volume,rel_tol=1e-7) for v in cad['nativeVolumes']),'editable CAD volume differs')
        mesh=measured['volume.vtu'];surface=measured['boundary.vtu'];near(mesh['volume'],volume);require(mesh['minimumVolume']>0,'nonpositive mesh cells')
        for a,e in zip(mesh['bounds'],[0,case['length'],0,case['width'],0,case['height']]):near(a,e)
        require(set(surface['groups'])=={'2','3','4'} and set(mesh['groups'])=={'1'},'physical groups differ')
        near(surface['groups']['2']['area'],2*case['length']*(case['width']+case['height']))
        for tag,x in [('3',0),('4',case['length'])]:
            near(surface['groups'][tag]['area'],area)
            for point in surface['groups'][tag]['points']:near(point[0],x)
        msh=mesh_check(directory/'mesh.msh',case)
        require(msh['tetrahedra']==mesh['cells'] and msh['triangles']==surface['cells'],'MSH/VTU cell counts differ')
        columns,rows=csv_read(directory/'inspection.csv');column=columns.index('Volume');require(len(rows)==1,'invalid integration table');near(rows[0][column],volume)
        return {'volume_mm3':volume,'endArea_mm2':area,'cells':mesh['cells']}
    for ti,t in enumerate(case['times']):
        for fi,f in enumerate(case['fractions']):
            data=measured[f'slice-{ti}-{fi}.vtp'];near(data['area'],case['width']*case['height'])
            expected=[f*case['length'],f*case['length'],0,case['width'],0,case['height']]
            for a,e in zip(data['bounds'],expected):near(a,e)
            require(set(data['fields'])=={'U','p'},'missing cell fields')
            require(len(data['fields']['U'])==data['cells'] and len(data['fields']['p'])==data['cells'],'field tuple count differs')
            for row in data['fields']['U']:
                require(len(row)==3,'velocity component count');near(row[0],case['speed']+t*case['acceleration']);near(row[1],0);near(row[2],0)
            for row in data['fields']['p']:near(row[0],case['pressure']+t*case['pressureRate'])
    return {'slices':len(measured),'analyticFixtureOnly':True}


def grade(task,submission,loc,output):
    validate({'version':'schemaxis.benchmark-cases/1','rounds':{'initial':task['cases'],'revision':task['cases']}})
    output.mkdir(parents=True,exist_ok=False);rows=[]
    expected={c['id'] for c in task['cases']}
    actual={p.name for p in submission.iterdir() if p.is_dir()} if submission.is_dir() else set()
    for case in task['cases']:
        try:
            details=grade_case(case,submission/case['id'],loc,output/case['id']);rows.append({'id':case['id'],'passed':True,'details':details})
        except Exception as error:rows.append({'id':case['id'],'passed':False,'error':str(error)})
    report={'kind':'artifact-grade','taskDigest':task_digest(task),'passed':actual==expected and all(r['passed'] for r in rows),'caseSetMatches':actual==expected,'cases':rows}
    save(output/'grade.json',report);return report


def task_digest(task):
    payload={'cases':task['cases'],'resources':{}}
    inputs=Path(task['inputs'])
    for case in task['cases']:
        for path in sorted((inputs/case['id']).rglob('*')):
            if path.is_file():payload['resources'][str(path.relative_to(inputs))]=hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()


def stage(package,round_name,arm,destination):
    """Export one arm/round without the other arm, solutions or grader."""
    source=package/round_name/arm;task=json.loads((source/'task.json').read_text())
    destination.mkdir(parents=True,exist_ok=False)
    shutil.copytree(Path(task['inputs']),destination/'inputs')
    task['inputs']=str(destination/'inputs');save(destination/'task.json',task)
    (destination/'TASK.md').write_text(task_text(arm))
    if arm=='schemaxis':
        (destination/'templates').mkdir()
        for case in task['cases']:save(destination/'templates'/(case['id']+'.json'),materialise(case,destination/'inputs'))
    save(destination/'trial-record.json',{'kind':'autonomous-trial-record','arm':arm,'round':round_name,
        'taskDigest':task_digest(task),'model':None,'modelVersion':None,'reasoning':None,'replicate':None,
        'budget':{'wallSeconds':None,'tokens':None},'measured':{'wallSeconds':None,'inputTokens':None,'outputTokens':None,'cost':None,'retries':None,'humanInterventions':None},
        'transcript':None,'status':'not-run'})


def prove(package,config,destination,families):
    loc=locations(config);destination.mkdir(parents=True,exist_ok=False);report={'kind':'deterministic-reference-proof','autonomousAIComparison':False,'runs':[]}
    try:
        for arm in ('ordinary','schemaxis'):
            for label,round_name in [('initial','initial'),('repeat','initial'),('revision','revision')]:
                packet=package/round_name/arm;task=json.loads((packet/'task.json').read_text());task['cases']=[c for c in task['cases'] if c['family'] in families]
                run=destination/arm/label;submission=run/'submission';submission.mkdir(parents=True)
                entry={'arm':arm,'round':label,'cases':[]};report['runs'].append(entry)
                for case in task['cases']:
                    target=submission/case['id'];target.mkdir();started=time.monotonic()
                    try:
                        reused=(schemaxis_run(case,Path(task['inputs']),target,loc,destination/arm/'attempts'/case['id']) if arm=='schemaxis' else ordinary(case,Path(task['inputs']),target,loc))
                        entry['cases'].append({'id':case['id'],'executed':True,'elapsedSeconds':time.monotonic()-started,'jobs':reused})
                    except Exception as error:
                        entry['cases'].append({'id':case['id'],'executed':False,'elapsedSeconds':time.monotonic()-started,'error':str(error)})
                entry['grade']=grade(task,submission,loc,run/'grade')
                save(destination/'report.json',report)
        report['passed']=all(r['grade']['passed'] and all(c['executed'] for c in r['cases']) for r in report['runs'])
    finally:save(destination/'report.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare');p.add_argument('--cases',type=Path,default=ROOT/'examples/benchmarks/cases.json');p.add_argument('--output-directory',type=Path,required=True)
    p=commands.add_parser('stage');p.add_argument('--package',type=Path,required=True);p.add_argument('--round',choices=('initial','revision'),required=True);p.add_argument('--arm',choices=('ordinary','schemaxis'),required=True);p.add_argument('--output-directory',type=Path,required=True)
    p=commands.add_parser('prove');p.add_argument('--package',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--output-directory',type=Path,required=True);p.add_argument('--family',action='append',choices=FAMILIES)
    p=commands.add_parser('grade');p.add_argument('--task',type=Path,required=True);p.add_argument('--submission',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--output-directory',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='prepare':prepare(json.loads(args.cases.read_text()),args.output_directory.resolve());print(args.output_directory.resolve())
    elif args.command=='stage':stage(args.package.resolve(),args.round,args.arm,args.output_directory.resolve());print(args.output_directory.resolve())
    elif args.command=='prove':
        report=prove(args.package.resolve(),args.config,args.output_directory.resolve(),args.family or FAMILIES);print(json.dumps({'passed':report['passed'],'kind':report['kind']}));return 0 if report['passed'] else 1
    else:
        report=grade(json.loads(args.task.read_text()),args.submission.resolve(),locations(args.config),args.output_directory.resolve());print(json.dumps(report));return 0 if report['passed'] else 1
    return 0


if __name__=='__main__':sys.exit(main())
