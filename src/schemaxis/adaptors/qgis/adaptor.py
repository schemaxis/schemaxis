# Copyright (C) 2026 David L F Gaden
"""Host-safe vector GIS contracts; QGIS imports live only in native_worker.py."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import time
from schemaxis.core.declarations import validate_arguments
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.errors import fail, keys
from schemaxis.dispatch import cancellation_requested
from schemaxis.native_command import execute
from . import attributes

PATH={'type':'string','minLength':1,'maxLength':4096,'required':True}
CRS={'type':'string','minLength':8,'maxLength':11,'required':True}
DECLARATIONS={op:{'native':native,'kinds':['geospatialVector'],
    'inputs':{} if op=='readVector' else {'input':{'required':True,'kind':'geospatialVector'}},
    'options':{k:{'value':v} for k,v in options.items()}}
    for op,native,options in [
        ('readVector','QgsVectorLayer',{'file':PATH}),
        ('reproject','QgsCoordinateTransform',{'crs':CRS}),
        ('centroid','QgsGeometry.centroid',{}),
        ('buffer','QgsGeometry.buffer',{'distance':{'type':'number','minimum':0.001,'maximum':100000,'required':True},
            'segments':{'type':'integer','minimum':4,'maximum':64,'default':16}}),
        ('clip','QgsGeometry.intersection',{'bounds':{'type':'array','items':{'type':'number','minimum':-1e9,'maximum':1e9},
            'minItems':4,'maxItems':4,'required':True}})]}
DECLARATIONS.update({op: {'native': 'QgsFeature.attribute' if op == 'selectAttributes' else 'QgsVectorDataProvider.addFeatures',
    'kinds': ['geospatialVector', 'table'] if op == 'summariseAttributes' else ['geospatialVector'],
    'inputs': {'input': {'required': True, 'kind': 'geospatialVector'}},
    'options': {key: {'value': value} for key, value in options.items()}} for op, options in attributes.OPTIONS.items()})
MAX_INPUT=64*1024*1024


def plan(document):
    from schemaxis.pipeline import name
    from schemaxis.documents import resolve_document
    document, _ = resolve_document(document)
    keys(document,('version','nodes','output','preview','dimensions','settings','definitions'),'$')
    if document.get('version')!='schemaxis.qgis/1':fail('UNSUPPORTED_VERSION','expected schemaxis.qgis/1')
    nodes=document.get('nodes')
    if not isinstance(nodes,list) or not 1<=len(nodes)<=32:fail('INVALID_DOCUMENT','declare 1 to 32 vector nodes')
    if type(document.get('preview',True))is not bool:fail('INVALID_ARGUMENT','preview must be Boolean')
    prepared=[];seen=set()
    for node in nodes:
        keys(node,('id','filter','options','inputs'),'node')
        identity=name(node.get('id'),'node.id');op=node.get('filter')
        if identity in seen:fail('DUPLICATE_NODE','node id is repeated',identity)
        if not isinstance(op,str) or op not in DECLARATIONS:fail('UNKNOWN_FILTER','unsupported vector operation',identity)
        decl=DECLARATIONS[op]
        options=validate_arguments({k:v['value'] for k,v in decl['options'].items()},node.get('options',{}),location=identity+'.options')
        if op in attributes.OPTIONS:
            try: attributes.validate_options(op, options, identity + '.options')
            except attributes.ContractError as error: fail(error.code, str(error), error.location)
        inputs=node.get('inputs',{});keys(inputs,tuple(decl['inputs']),identity+'.inputs')
        if set(inputs)!=set(decl['inputs']) or any(not isinstance(v,str) or v not in seen for v in inputs.values()):
            fail('INVALID_DEPENDENCY','inputs must reference earlier vector nodes',identity)
        if op=='readVector' and not Path(options['file']).is_absolute():fail('INVALID_RESOURCE','vector input must be an absolute path',identity)
        if op=='reproject' and re.fullmatch(r'EPSG:[1-9][0-9]{2,5}',options['crs']) is None:
            fail('INVALID_ARGUMENT','crs must be an EPSG authority identifier',identity)
        if op=='clip' and not (options['bounds'][0]<options['bounds'][2] and options['bounds'][1]<options['bounds'][3]):
            fail('INVALID_ARGUMENT','bounds are xmin,ymin,xmax,ymax with positive extent',identity)
        prepared.append({'id':identity,'filter':op,'options':options,'inputs':inputs});seen.add(identity)
    output=document.get('output')
    if not isinstance(output,str) or output not in seen:fail('INVALID_SELECTION','output must name a vector node')
    return {'version':'schemaxis.qgis.plan/1','nodes':prepared,'output':output,'preview':document.get('preview',True),
            'limits':{'features':10000,'vertices':1000000},
            'losses':['2D vector geometry only','GeoPackage feature ids are regenerated','one selected output layer',
                      'buffer distances require a projected CRS in metres','PNG is a presentation, not georeferenced raster']}


def schema():
    from schemaxis.schema import DRAFT,object_schema,argument_schema,NAME,json_value_schema
    variants=[]
    for op,decl in DECLARATIONS.items():
        variants.append(object_schema({'id':NAME,'filter':{'const':op},
            'options':object_schema({k:argument_schema(v['value']) for k,v in decl['options'].items()},
                [k for k,v in decl['options'].items() if v['value'].get('required')]),
            'inputs':object_schema({k:NAME for k in decl['inputs']},list(decl['inputs']))},
            ['id','filter','options']+(['inputs'] if decl['inputs'] else [])))
    return {'$schema':DRAFT, '$defs': {'json': json_value_schema()}, **object_schema({'version':{'const':'schemaxis.qgis/1'},'nodes':{'type':'array','minItems':1,'maxItems':32,'items':{'oneOf':variants}},
        'output':NAME,'preview':{'type':'boolean','default':True},
        **{key: json_value_schema() for key in ('dimensions','definitions','settings')}},['version','nodes','output'])}


def reusableInputs(document):
    paths=[n['options']['file'] for n in plan(document)['nodes'] if n['filter']=='readVector']
    total=0
    for path in paths:
        if Path(path).suffix.lower() not in ('.geojson','.gpkg'):
            fail('UNSUPPORTED_RESOURCE','only single-file GeoJSON and GeoPackage inputs are supported',path)
        try: info=Path(path).stat()
        except OSError as error: fail('RESOURCE_NOT_FOUND',str(error),path)
        if not stat.S_ISREG(info.st_mode):fail('INVALID_RESOURCE','vector input must be a regular file',path)
        total+=info.st_size
        if total>MAX_INPUT:fail('RESOURCE_LIMIT','vector input budget exceeds 64 MiB',path)
        if any(Path(path+s).exists() for s in ('-wal','-shm','-journal')):
            fail('UNSUPPORTED_RESOURCE','close/checkpoint the GeoPackage before reading it',path)
    try:
        return {p:file_digest(p) for p in paths}
    except OSError as error:
        fail('RESOURCE_NOT_FOUND',str(error),str(error.filename))


def resources(document,spec,identity):
    if spec.get('threads',1)!=1:fail('INVALID_EXECUTION','vector GIS currently uses one allocated thread',identity)
    return {'threads':1}


def manifest(directory,prepared):
    files=[('result.gpkg','geospatialVector'),('project.qgz','project')]
    if prepared['preview']:files.append(('preview.png','image'))
    summaries=[node['id'] for node in prepared['nodes'] if node['filter']=='summariseAttributes']
    files += [('summary-'+identity+extension,kind) for identity in summaries
              for extension,kind in (('.csv','table'),('.json','text'),('.gpkg','table'))]
    observed = json.loads((directory/'reopened.json').read_text())['snapshot']
    preview = json.loads((directory/'built.json').read_text()).get('previewSpatial')
    result=[]
    for name,kind in files:
        record={'file':str(directory/name),'kind':kind,'sha256':file_digest(directory/name)}
        if name.startswith('summary-'):
            table=json.loads((directory/(name.rsplit('.',1)[0]+'.json')).read_text())
            record.update(rows=len(table['rows']),columns=table['columns'])
        else:
            record.update(features=observed['count'],spatial=preview if kind=='image' and preview else {
                'state':'known','frame':'CRS','crs':observed['crs'],'extent':observed['bounds'],
                'extentOrder':['xmin','ymin','xmax','ymax'],'dimensions':2,
                'scope':'dataset extent; map preview viewport may include padding',
                'units':'CRS-defined; no Cartesian 3D transform asserted'})
        result.append(record)
    return result


def evidence_files(prepared):
    names=['built.json','reopened.json','sources.json','worker.py']
    if any(node['filter'] in attributes.OPTIONS for node in prepared['nodes']):
        names += ['attribute_contract.py','attribute_worker.py']
    return names


def run(document,directory,*,executable=None,timeout=300):
    prepared=plan(document)
    executable=executable or os.environ.get('QGIS_PYTHON')
    if not executable or not Path(executable).is_absolute() or not os.access(executable,os.X_OK):
        fail('INTERPRETER_NOT_FOUND','provide a Python launcher configured for QGIS via --qgis or QGIS_PYTHON')
    if type(timeout)not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:fail('INVALID_ARGUMENT','timeout must be in (0,3600]')
    directory=Path(directory).absolute()
    if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','choose a fresh directory',str(directory))
    source_hashes=reusableInputs(document)
    directory.mkdir(parents=True)
    atomic_json(directory/'authored.json',document);atomic_json(directory/'plan.json',prepared)
    atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
    try:
        sources={};total=0
        for node in prepared['nodes']:
            if node['filter']!='readVector':continue
            path=Path(node['options']['file'])
            if path.suffix.lower()not in ('.geojson','.gpkg'):fail('UNSUPPORTED_RESOURCE','only single-file GeoJSON and GeoPackage inputs are supported',str(path))
            with path.open('rb') as stream:data=stream.read(MAX_INPUT+1)
            total+=len(data)
            if total>MAX_INPUT:fail('RESOURCE_LIMIT','vector input budget exceeds 64 MiB')
            target='input-'+node['id']+path.suffix.lower();(directory/target).write_bytes(data)
            if hashlib.sha256(data).hexdigest()!=source_hashes[str(path)]:fail('INPUT_CHANGED','source changed during capture',str(path))
            sources[node['id']]={'file':str(path),'retained':target,'sha256':source_hashes[str(path)]}
        atomic_json(directory/'sources.json',sources)
        shutil.copyfile(Path(__file__).with_name('native_worker.py'),directory/'worker.py')
        if any(node['filter'] in attributes.OPTIONS for node in prepared['nodes']):
            for source,target in (('attributes.py','attribute_contract.py'),('attribute_worker.py','attribute_worker.py')):
                shutil.copyfile(Path(__file__).with_name(source),directory/target)
        deadline=time.monotonic()+timeout
        for stage in ('build','reopen'):
            try:
                execute([executable,str(directory/'worker.py'),str(directory),stage],directory,stage,
                        deadline-time.monotonic(),{'QT_QPA_PLATFORM':'offscreen','QT_LOGGING_RULES':'qt.qpa.*=false'})
            except SchemaxisError:
                if (directory/'native-fault.json').is_file():
                    fault=json.loads((directory/'native-fault.json').read_text())
                    fail(fault['code'],fault['message'],fault.get('location',''))
                raise
        receipt={'artifacts':manifest(directory,prepared),'evidence':{n:file_digest(directory/n) for n in
            evidence_files(prepared)}}
        atomic_json(directory/'verification.json',receipt)
        result=verify(directory,require_result=False)
        if cancellation_requested():fail('RUNNER_CANCELLED','GIS publication cancelled')
        result.update(status='succeeded',project=str(directory/'project.qgz'))
        atomic_json(directory/'result.json',result)
        return result
    except Exception as error:
        if not isinstance(error,SchemaxisError):
            try: fail('NATIVE_EXECUTION_FAILED',str(error),str(directory))
            except SchemaxisError as wrapped: error=wrapped
        atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':error.fault.to_dict() if isinstance(error,SchemaxisError) else {'message':str(error)}})
        raise error


def reject(location,message):
    """A retained-evidence fault; the code is stable for genuine legacy receipts."""
    raise SchemaxisError(Fault('VERIFICATION_FAILED',message,location,'verification',recovery=
        'Do not trust this directory. Restore the complete original output directory from its retained copy, '
        'or rerun the workflow into a fresh directory; verification never repairs evidence.'))


def verify(directory, require_result=True):
    directory=Path(directory).absolute()
    try:
        def read(name):
            path=directory/name
            if not path.is_file() or path.is_symlink():reject(name,'retained evidence file is missing or not a regular file')
            try:value=json.loads(path.read_text())
            except (ValueError,RecursionError):reject(name,'retained evidence is not valid JSON')
            if not isinstance(value,dict):reject(name,'retained evidence must be a JSON object')
            return value
        def check(condition,message):
            if not condition:fail('VERIFICATION_FAILED',message)
        prepared=plan(read('authored.json'));result=read('result.json');receipt=read('verification.json')
        if require_result:
            check(result.get('verified')is True and result.get('status')=='succeeded','execution did not complete')
        check(read('plan.json')==prepared,'plan differs')
        sources=read('sources.json')
        nodes={n['id']:n for n in prepared['nodes'] if n['filter']=='readVector'}
        check(set(sources)==set(nodes),'source membership differs')
        for identity,record in sources.items():
            expected='input-'+identity+Path(nodes[identity]['options']['file']).suffix.lower()
            check(record['retained']==expected and record['file']==nodes[identity]['options']['file']
                  and file_digest(directory/expected)==record['sha256'],'source provenance differs')
        required=['result.gpkg','project.qgz','authored.json','plan.json','result.json','verification.json',
                  'built.json','reopened.json','sources.json','worker.py']
        if prepared['preview']:required.append('preview.png')
        required += [name for name in evidence_files(prepared) if name not in required]
        required += ['summary-'+node['id']+extension for node in prepared['nodes'] if node['filter']=='summariseAttributes' for extension in ('.csv','.json','.gpkg')]
        required += [record['retained'] for record in sources.values()]
        for name in required:
            path=directory/name
            if not path.is_file() or path.is_symlink():reject(name,'required regular file missing: '+name)
        built=read('built.json');reopened=read('reopened.json')
        check(built['stage']=='build' and reopened['stage']=='reopen' and built['pid']!=reopened['pid'],'missing fresh-process readback')
        check(built['plan']==prepared and reopened['plan']==prepared,'native plan differs')
        check(built['snapshot']==reopened['snapshot'] and built['runtime']==reopened['runtime'],'native vector round trip differs')
        check(reopened.get('projectReopened')is True,'project did not reopen')
        if any(node['filter'] in attributes.OPTIONS for node in prepared['nodes']):
            from .attribute_evidence import verify as verify_attributes
            verify_attributes(directory,prepared,sources,built,reopened)
        snap=reopened['snapshot']
        check(0<snap['count']<=prepared['limits']['features'] and len(snap['features'])==snap['count'],'invalid feature count')
        check(re.fullmatch(r'EPSG:[1-9][0-9]{2,5}',snap['crs'])is not None,'missing CRS authority')
        check(receipt=={'artifacts':manifest(directory,prepared),'evidence':{n:file_digest(directory/n) for n in
            evidence_files(prepared)}},'artifact/evidence digests differ')
        if prepared['preview']:
            from schemaxis.png import read as read_png
            w,h,pixels=read_png(directory/'preview.png')
            check((w,h)==(640,480) and len(set(pixels[i:i+4] for i in range(0,len(pixels),4)))>1,'map preview is blank or wrong size')
        return {'verified':True,'artifacts':len(receipt['artifacts']),'features':snap['count'],'crs':snap['crs'],'runtime':reopened['runtime']}
    except (OSError,ValueError,KeyError,TypeError,AttributeError,ArithmeticError,RecursionError,sqlite3.Error) as error:
        reject('$','missing or invalid GIS evidence: '+type(error).__name__+': '+str(error))


# Shared authored-input, analytic-visit and verification boundary.
from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
