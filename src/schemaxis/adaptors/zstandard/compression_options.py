"""Typed streaming and scheduling choices from the stable Zstandard CLI."""
from schemaxis.errors import fail

LIMIT=64*1024*1024
FIELDS={
 'contentSize':{'type':'enum','values':['automatic','omit','require'],'default':'automatic'},
 'pledgedBytes':{'type':'integer','minimum':0,'maximum':LIMIT},
 'sizeHintBytes':{'type':'integer','minimum':1,'maximum':LIMIT},
 'targetBlockBytes':{'type':'integer','minimum':0,'maximum':131072,'default':0},
 'jobBytes':{'type':'integer','minimum':0,'maximum':LIMIT,'default':0},
 'adaptive':{'type':'object','properties':{
     'minLevel':{'type':'integer','minimum':1,'maximum':22,'default':1},
     'maxLevel':{'type':'integer','minimum':1,'maximum':22,'default':19}}},
}
TUNING={
 'overlapLog':{'type':'integer','minimum':0,'maximum':9},
 'ldmHashRateLog':{'type':'integer','minimum':0,'maximum':20},
 'ldmHashLog':{'type':'integer','minimum':6,'maximum':24},
 'ldmMinMatch':{'type':'integer','minimum':4,'maximum':4096},
 'ldmBucketSizeLog':{'type':'integer','minimum':1,'maximum':8},
}


def validate(p,document):
    if p['format']!='zstd':
        if (p['contentSize']!='automatic' or p['jobBytes'] or p['targetBlockBytes']
                or any(key in p for key in ('pledgedBytes','sizeHintBytes','adaptive'))):
            fail('INVALID_ZSTANDARD_OPTION','Advanced streaming and adaptive controls require Zstandard format')
        return
    if any(key in p for key in ('pledgedBytes','sizeHintBytes')) and not p['streamInput']:
        fail('INVALID_ZSTANDARD_OPTION','Pledged size and size hints apply to standard-input streams')
    if 'pledgedBytes' in p and ('sizeHintBytes' in p or p['chunkBytes']):
        fail('INVALID_ZSTANDARD_OPTION','An exact stream pledge uses one frame and replaces an approximate size hint')
    if p['contentSize']=='require' and p['streamInput'] and 'pledgedBytes' not in p:
        fail('INVALID_ZSTANDARD_OPTION','A required stream content size needs an exact pledgedBytes value')
    if p['targetBlockBytes'] and p['targetBlockBytes']<64:
        fail('INVALID_ZSTANDARD_OPTION','Target block size is zero or at least 64 bytes')
    if p['jobBytes'] and p['jobBytes']<512*1024:
        fail('INVALID_ZSTANDARD_OPTION','Compression jobs must be at least 512 KiB')
    tuning=p['tuning'];strategy=tuning.get('strategy')
    if p['singleThread'] and (p['jobBytes'] or 'overlapLog' in tuning or 'adaptive' in p):
        fail('INVALID_ZSTANDARD_OPTION','Job overlap, scheduling and adaptation require worker-based compression')
    nonfast=('doubleFast','greedy','lazy','lazy2','btlazy2','btopt','btultra','btultra2')
    if 'chainLog' in tuning and strategy not in nonfast:
        fail('INVALID_ZSTANDARD_OPTION','A match-chain table requires an explicit non-fast strategy')
    if 'searchLog' in tuning and strategy not in nonfast[1:]:
        fail('INVALID_ZSTANDARD_OPTION','Search effort requires an explicit greedy, lazy or binary-tree strategy; fast/doubleFast ignore it')
    if tuning.get('minMatch')==3 and strategy not in ('btopt','btultra','btultra2'):
        fail('INVALID_ZSTANDARD_OPTION','Three-byte minimum matching requires an explicit optimal binary-tree strategy')
    if tuning.get('minMatch')==7 and strategy!='fast':
        fail('INVALID_ZSTANDARD_OPTION','Seven-byte minimum matching requires explicit fast strategy; other strategies clamp it to six')
    if tuning.get('targetLength',0) and strategy not in ('fast','btopt','btultra','btultra2'):
        fail('INVALID_ZSTANDARD_OPTION','A nonzero target length requires an explicit fast or optimal binary-tree strategy')
    if ('searchLog' in tuning and 'windowLog' in tuning
            and tuning['searchLog']>=tuning['windowLog']):
        fail('INVALID_ZSTANDARD_OPTION','Search log must be smaller than the explicit history window log')
    if any(key.startswith('ldm') for key in tuning) and not p['longWindowLog']:
        fail('INVALID_ZSTANDARD_OPTION','Long-distance table controls require explicit longWindowLog')
    if tuning.get('ldmBucketSizeLog',1)>tuning.get('ldmHashLog',24):
        fail('INVALID_ZSTANDARD_OPTION','Long-distance buckets cannot exceed their hash table')
    overlap=tuning.get('overlapLog',0);window=tuning.get('windowLog',p['longWindowLog'])
    if p['jobBytes'] and not window:
        fail('INVALID_ZSTANDARD_OPTION','An explicit job size requires tuning.windowLog or longWindowLog to bound native overlap','$.jobBytes')
    # Zero means native automatic overlap. Its maximum is the full window;
    # reserve that bound rather than admitting a silently increased job size.
    effective_overlap=overlap or 9
    if p['jobBytes'] and p['jobBytes']<max(512*1024,(1<<window)>>(9-effective_overlap)):
        fail('INVALID_ZSTANDARD_OPTION','Job size must cover the explicitly requested history overlap')
    if 'adaptive' in p:
        adaptive=p['adaptive']
        if p['fast'] or not adaptive['minLevel']<=p['level']<=adaptive['maxLevel']:
            fail('INVALID_ZSTANDARD_OPTION','Adaptive bounds must include the initial level, with fast mode disabled')


def arguments(p):
    result=[]
    if p['contentSize']=='omit':result.append('--no-content-size')
    elif p['contentSize']=='require':result.append('--content-size')
    for key,flag in (('pledgedBytes','--stream-size='),('sizeHintBytes','--size-hint=')):
        if key in p:result.append(flag+str(p[key]))
    if p['targetBlockBytes']:result.append('--target-compressed-block-size='+str(p['targetBlockBytes']))
    if p['jobBytes']:result.append('-B'+str(p['jobBytes']))
    if 'adaptive' in p:
        a=p['adaptive']
        if a['maxLevel']>19 and p['level']<=19:result.append('--ultra')
        result.append('--adapt=min='+str(a['minLevel'])+',max='+str(a['maxLevel']))
    return result


def declared_sizes(p,lengths):
    unknown=p['contentSize']=='omit' or p['streamInput'] and 'pledgedBytes' not in p
    return [None]*len(lengths) if unknown else lengths
