"""Host checks for typed mixed physical CAM and ordered remaining-stock proof."""
import math
from pathlib import Path
from schemaxis.artifacts import file_digest
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .adaptor import close
from .cam_evidence2 import read,same,text


def numeric(actual,expected):
    """Integral/semantic values are exact; geometric floats retain close()."""
    if type(actual) is not type(expected):return False
    if isinstance(expected,dict):return actual.keys()==expected.keys() and all(numeric(actual[k],v) for k,v in expected.items())
    if isinstance(expected,list):return len(actual)==len(expected) and all(numeric(a,b) for a,b in zip(actual,expected))
    if type(expected) is float:return math.isfinite(actual) and close(actual,expected)
    return actual==expected


def counters(material):
    values={k:material[k] for k in ('sweeps','tracks','motions','work')}
    work=values['work']
    ordered=material.get('method')=='continuous-ordered-physical-stock'
    keys={'booleans','nativeFacePairs','identityComparisons','distances'} if ordered else {'booleans','booleanFacePairs','identityComparisons'}
    if not isinstance(work,dict) or set(work)!=keys:
        raise ValueError('Mixed material work inventory differs')
    if ordered:values.update({k:material[k] for k in ('events','toolTransitions','clearanceChecks','temporalCredits','reusedRapidMasks')})
    if any(type(v) is not int or v<0 for v in [*(v for k,v in values.items() if k!='work'),*work.values()]):
        raise ValueError('Mixed material counters must be nonnegative exact integers')
    return values


def verify(directory,require_result=True,fresh=True):
    from .cam_state2 import admit
    from .cam_code2 import parse
    from .cam_cycles2 import validate
    from .cam_pointed import admit_reach,admit_tip_clearance
    from .cam_paths2 import commands,readback
    from .cam_names import operation_names
    from .document_xml import Document
    directory=Path(directory);remaining_timeout()
    def require(value,message):
        if not value:fail('VERIFICATION_FAILED',message,str(directory))
    prepared=read(directory/'plan.json')
    require(prepared.get('version')=='schemaxis.freecad.cam.plan/3','Expected physical CAM plan/3')
    admit(directory,prepared);native=file_digest(directory/'machining.FCStd');program=file_digest(directory/'program.ngc')
    if require_result:require(read(directory/'result.json').get('verified') is True,'Physical CAM execution is incomplete')
    built=read(directory/'built.json');reopened=read(directory/'reopened.json');material=read(directory/'material.json')
    require(all(type(r.get('pid')) is int and r['pid']>0 for r in (built,reopened,material))
            and len({r['pid'] for r in (built,reopened,material)})==3,'Physical build/reopen/material need three separate native processes')
    require(all(r.get('runtime')=='1.1.4' for r in (built,reopened,material)),'Physical CAM runtime differs from qualified1.1.4')
    saved=Document(directory/'machining.FCStd');canonical=material['authoritativeNativeReadback']
    require(canonical['objects']==saved.types,'Physical CAM object membership differs')
    # This witness is accepted only with fresh complete reconstruction below.
    # No submitted proxy is restored to establish these native facts.
    for record,stage in ((built,'build'),(reopened,'reopen')):
        require(record.get('stage')==stage,'Physical native stage differs')
        current={k:v for k,v in record.items() if k not in ('stage','pid','operations')}
        expected={k:v for k,v in canonical.items() if k!='operations'}
        require(numeric(current,expected),'Physical native readback differs from trusted construction')
        require(len(record['operations'])==len(prepared['operations'])==len(canonical['operations']),'Physical operation readback is incomplete')
        for observed,trusted,spec in zip(record['operations'],canonical['operations'],prepared['operations']):
            require(numeric({k:v for k,v in observed.items() if k!='commands'},
                            {k:v for k,v in trusted.items() if k!='commands'}),'Physical native operation settings differ')
            name=operation_names(prepared)[spec['id']]
            require(readback(observed['commands'],commands(directory,saved,name)),
                    'Physical native commands differ from exact six-decimal saved Path')
    ordered=prepared['setup']['toolClearance']['kind']=='evolvingStock'
    replay=parse(text(directory/'program.ngc'),prepared['tools'],prepared['setup']['safe'],ordered=ordered)
    validate(prepared,replay)
    if ordered:
        from .cam_ordered import preflight_ordered
        preflight_ordered(prepared,replay)
    else:admit_reach(prepared,replay)
    admit_tip_clearance(prepared,replay)
    require(same(replay,read(directory/'replay.json')),'Physical retained replay differs from actual program')
    counts=counters(material);require(counts['motions']==len(replay['motions']),'Physical material motion count differs')
    method='continuous-ordered-physical-stock' if ordered else 'continuous-mixed-physical-solid-union'
    require(material.get('verified') is True and material.get('method')==method
            and material['nativeSha256']==native and material['programSha256']==program,'Physical material is unfinished or bound to different bytes')
    for key in ('targetVolume','stockVolume','remainingVolume','removedVolume','residualVolume','gougeVolume',
                'balanceErrorVolume','assessedResidualVolume','assessedGougeVolume'):
        require(type(material[key]) is float and math.isfinite(material[key]) and material[key]>=0,
                'Physical material needs finite nonnegative geometric metrics')
    require(close(material['targetVolume'],prepared['source']['volume'])
            and material['assessedResidualVolume']<=prepared['quality']['residualVolume']
            and material['assessedGougeVolume']<=prepared['quality']['gougeVolume'],'Physical material finish limits are not satisfied')
    for filename in ('remaining.brep','residual.brep','gouge.brep'):
        require(file_digest(directory/filename)==material['publications'][filename]['sha256'],'Physical material publication differs')
    from .cam_publication import verify as publications
    artifacts=publications(directory,prepared)
    require(same(read(directory/'verification.json'),{'runtime':'1.1.4','artifacts':artifacts}),'Physical publication membership differs')
    if fresh:
        from .cam_verify import fresh_material
        current=fresh_material(directory)
        require(same(counters(current),counts),'Fresh physical material counters differ')
        require(numeric({k:v for k,v in current.items() if k!='pid'},
                        {k:v for k,v in material.items() if k!='pid'}),'Fresh whole-state physical material proof differs')
    require(file_digest(directory/'machining.FCStd')==native and file_digest(directory/'program.ngc')==program,
            'Physical CAM publication changed during verification')
    admit(directory,prepared);remaining_timeout()
    return {'verified':True,'artifacts':artifacts,'runtime':'1.1.4','operations':len(prepared['operations']),
            'tools':len(prepared['tools']),'cycles':len(replay['cycles']),'motions':len(replay['motions']),
            'residualVolume':material['residualVolume'],'gougeVolume':material['gougeVolume'],
            'nativeFile':str(directory/'machining.FCStd'),'programFile':str(directory/'program.ngc'),
            'sourceHistoryPreserved':False}
