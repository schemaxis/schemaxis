"""Public CAM2 evidence checks plus fresh whole-state/material authority."""
import math
from pathlib import Path
from schemaxis.artifacts import file_digest
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .cam_names import operation_names
from .adaptor import close
from .cam_native import POST_ARGS
from .cam_evidence2 import read,same,text
from .document_xml import Document


def numeric(actual,expected):
    if isinstance(expected,dict):
        return isinstance(actual,dict) and actual.keys()==expected.keys() and all(numeric(actual[k],v) for k,v in expected.items())
    if isinstance(expected,list):
        return isinstance(actual,list) and len(actual)==len(expected) and all(numeric(a,b) for a,b in zip(actual,expected))
    if type(expected) in (int,float):return type(actual) in (int,float) and math.isfinite(actual) and close(actual,expected)
    return same(actual,expected)


def counts(record):
    """Semantic counters stay integral/exact; geometric metrics use numeric()."""
    values={key:record[key] for key in ('sweeps','tracks','motions')}
    values['footprints']=[slab['footprints'] for slab in record['slabs']]
    if any(type(value) is not int or value<0 for value in [*values['footprints'],*(values[key] for key in ('sweeps','tracks','motions'))]):
        raise ValueError('CAM2 material counters must be nonnegative integers')
    return values


def verify(directory,require_result=True,fresh=True):
    from .cam_state2 import admit
    from .cam_code2 import parse
    from .cam_cycles2 import validate
    from .cam_paths2 import commands,readback
    directory=Path(directory);remaining_timeout()
    def require(condition,message):
        if not condition:fail('VERIFICATION_FAILED',message,str(directory))
    p=read(directory/'plan.json');admit(directory,p)
    native_sha=file_digest(directory/'machining.FCStd');program_sha=file_digest(directory/'program.ngc')
    if require_result:require(read(directory/'result.json').get('verified') is True,'CAM2 execution is incomplete')
    built=read(directory/'built.json');reopened=read(directory/'reopened.json');material=read(directory/'material.json')
    require(all(type(r.get('pid')) is int and r['pid']>0 for r in (built,reopened,material))
            and len({r['pid'] for r in (built,reopened,material)})==3,'CAM2 build/reopen/material require three separate native processes')
    require(all(r.get('runtime')=='1.1.4' for r in (built,reopened,material)),'CAM2 runtime differs from qualified FreeCAD1.1.4')
    saved=Document(directory/'machining.FCStd')
    tools={t['id']:t for t in p['tools']}
    expected_bounds=[v-p['origin'][i//2] for i,v in enumerate(p['source']['bounds'])]
    expected_com=[v-p['origin'][i] for i,v in enumerate(p['source']['centreOfMass'])]
    job={'operations':[operation_names(p)[s['id']] for s in p['operations']],'tools':[t['controller'] for t in p['tools']],
         'fixtures':['G54'],'order':'Operation','split':False,'postprocessor':'linuxcnc','postArgs':POST_ARGS}
    expected_tools=[{k:t[k] for k in ('id','controller','number','diameter','cuttingLength','length','shankDiameter','flutes','rpm','feed','plunge')}
                    |{'tool':t['nativeTool'],'direction':'Forward'} for t in p['tools']]
    for report,stage in ((built,'build'),(reopened,'reopen')):
        require(report['stage']==stage and report['objects']==saved.types,'CAM2 native stage/object membership differs')
        require(same(report['job'],job) and numeric(report['tools'],expected_tools),'CAM2 native job order or declared tools differ')
        require(all(type(t['number']) is type(t['flutes']) is int for t in report['tools']),'CAM2 native tool numbers/flutes must retain integral types')
        require(numeric(report['source'],{'bounds':expected_bounds,'volume':p['source']['volume'],'centreOfMass':expected_com}),'CAM2 native source or work frame differs')
        require(numeric(report['model'],{'group':['Clone'],'bounds':expected_bounds,'volume':p['source']['volume']}),'CAM2 native source clone differs')
        b=p['stockBounds'];require(numeric(report['stock'],{'bounds':b,'volume':(b[1]-b[0])*(b[3]-b[2])*(-b[4])}),'CAM2 blank differs')
        require(len(report['operations'])==len(p['operations']),'CAM2 operation readback is incomplete')
        for actual,spec in zip(report['operations'],p['operations']):
            identity=operation_names(p)[spec['id']];tool=tools[spec['tool']];drill=spec['operation']=='drill'
            require(actual['id']==spec['id'] and actual['name']==identity and actual['type']=='Path::FeaturePython'
                    and actual['valid'] is True and actual['tool']==tool['controller'],'CAM2 operation identity/tool/validity differs')
            for key,value in (('start',spec['start']),('finish',spec['finish']),('clearance',p['setup']['clearance']),('safe',p['setup']['clearance' if drill else 'safe'])):
                require(numeric(actual[key],value),'CAM2 operation depth or traverse plane differs')
            refs=saved.child(identity,'Base','LinkSubList','App::PropertyLinkSubListGlobal');owner='Stock' if spec['operation']=='faceStock' else 'Clone'
            require(refs.get('count')==str(len(refs)) and len(refs)==(len(spec['centres']) if drill else 1)
                    and all(r.get('obj')==owner for r in refs),'CAM2 geometric target owner/count differs')
            require(same(actual['base'],[[owner,[r.get('sub') for r in refs]]]),'CAM2 native Base readback differs from persisted targets')
            if drill:
                c=spec['cycle'];require(numeric(actual['retract'],c['retract']) and numeric(actual['peck'],c['peck']) and numeric(actual['dwell'],c['dwell']),'CAM2 cycle parameter readback differs')
                flags={'keepToolDown':c['return']=='retract','peckEnabled':c['kind'] in ('peck','chipBreak'),
                       'dwellEnabled':c['kind']=='dwell','chipBreakEnabled':c['kind']=='chipBreak',
                       'feedRetractEnabled':c['kind']=='feedRetract','addTipLength':False}
                require(all(same(actual[k],v) for k,v in flags.items()) and actual['extraOffset']=='None'
                        and actual['locations']==[] and actual['disabled']==[],'CAM2 drilling strategy or target suppression differs')
                # Native1.1.4 derives this read-only enum from KeepToolDown
                # during generation. Bind both it and the independent NC state.
                require(actual['retractMode']==('G99' if c['return']=='retract' else 'G98'),'CAM2 native retract enum differs from typed return intent')
            else:
                require(numeric(actual['stepDown'],spec['stepDown']) and actual['stepOver']==round(spec['stepOver']*100)
                        and actual['clearingPattern']==('ZigZag' if spec['operation']=='faceStock' else 'ZigZagOffset'),'CAM2 milling strategy differs')
            require(readback(actual['commands'],commands(directory,saved,identity)),'CAM2 native readback differs from exact six-decimal saved Path serialization')
    require(same(built['tools'],reopened['tools']),'CAM2 tool data changed on fresh reopen')
    for a,b in zip(built['operations'],reopened['operations']):
        require(same({k:v for k,v in a.items() if k!='commands'},{k:v for k,v in b.items() if k!='commands'}),'CAM2 non-Path operation settings changed on fresh reopen')
    replay=parse(text(directory/'program.ngc'),p['tools'],p['setup']['safe']);validate(p,replay)
    require(same(replay,read(directory/'replay.json')),'CAM2 retained NC replay differs')
    counters=counts(material)
    require(counters['motions']==len(replay['motions']),'CAM2 material motion count differs from independent NC replay')
    require(material.get('verified') is True and material['method']=='continuous-multitool-flat-endmill-sections'
            and material['programSha256']==program_sha and material['nativeSha256']==native_sha,'CAM2 material evidence is bound to different or unfinished outputs')
    require(numeric(material['targetVolume'],p['source']['volume']) and material['assessedResidualVolume']<=p['quality']['residualVolume']
            and material['assessedGougeVolume']<=p['quality']['gougeVolume'] and math.isfinite(material['balanceErrorVolume']) and material['balanceErrorVolume']>=0,'CAM2 independent material does not satisfy finish limits')
    for filename in ('remaining.brep','residual.brep','gouge.brep'):
        require(file_digest(directory/filename)==material['publications'][filename]['sha256'],'CAM2 published material geometry differs')
    from .cam_publication import verify as publications
    artifacts=publications(directory)
    require(same(read(directory/'verification.json'),{'runtime':'1.1.4','artifacts':artifacts}),'CAM2 publication membership differs')
    if fresh:
        from .cam_verify import fresh_material
        current=fresh_material(directory)
        require(same(counts(current),counters),'Fresh CAM2 material counters differ from retained evidence')
        require(numeric({k:v for k,v in current.items() if k!='pid'},{k:v for k,v in material.items() if k!='pid'}),'Fresh CAM2 complete-state/material proof differs from retained evidence')
    require(file_digest(directory/'machining.FCStd')==native_sha and file_digest(directory/'program.ngc')==program_sha,'CAM2 publication changed during public verification')
    admit(directory,p);remaining_timeout()
    return {'verified':True,'artifacts':artifacts,'runtime':'1.1.4','operations':len(p['operations']),'tools':len(p['tools']),
            'cycles':len(replay['cycles']),'motions':len(replay['motions']),'residualVolume':material['residualVolume'],
            'gougeVolume':material['gougeVolume'],'nativeFile':str(directory/'machining.FCStd'),
            'programFile':str(directory/'program.ngc'),'sourceHistoryPreserved':False}
