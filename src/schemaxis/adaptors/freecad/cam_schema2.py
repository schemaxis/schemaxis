"""Closed authoring schema for named tools, reusable hole layouts and cycles."""
import copy
from schemaxis.schema import object_schema as obj


def expand(schema):
    schema=copy.deepcopy(schema);props=schema['properties'];identifier={'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]*$'}
    tool=copy.deepcopy(props['tool']);tool['properties'].update(id=identifier,kind={'const':'flatEndmill'})
    tool['required']+=['id','kind'];props['tools']={'type':'array','minItems':1,'maxItems':8,'items':tool}
    xy={'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':2,'maxItems':2}
    positive={'type':'number','minimum':.001,'maximum':100000}
    count={'type':'integer','minimum':1,'maximum':64}
    locations={'oneOf':[
        obj({'kind':{'const':'explicit'},'centres':{'type':'array','minItems':1,'maxItems':256,'items':xy}},['kind','centres']),
        obj({'kind':{'const':'grid'},'columns':{**count,'default':2},'rows':{**count,'default':2},
             'xPitch':positive,'yPitch':positive,'centre':{**xy,'default':[0,0]}},['kind','xPitch','yPitch']),
        obj({'kind':{'const':'pitchCircle'},'count':{**count,'minimum':2,'default':4},'radius':positive,
             'phase':{'type':'number','minimum':-180,'maximum':180,'default':0},'centre':{**xy,'default':[0,0]}},['kind','radius'])]}
    for choice,title in zip(locations['oneOf'],('Explicit centres','Rectangular grid','Pitch circle')):choice['title']=title
    strategies=[]
    for kind in ('drill','dwell','peck','chipBreak','feedRetract'):
        properties={'kind':{'const':kind},'return':{'enum':['initial','retract'],'default':'initial'}}
        required=[] if kind=='drill' else ['kind']
        if kind=='drill':properties['kind']['default']='drill'
        if kind=='dwell':
            properties['dwell']={'type':'number','minimum':.001,'maximum':3600};required.append('dwell')
        elif kind in ('peck','chipBreak'):
            properties['peck']={'type':'number','minimum':.001,'maximum':1000};required.append('peck')
        strategies.append({**obj(properties,required),'title':{'drill':'Drill','dwell':'Dwell','peck':'Peck','chipBreak':'Chip break','feedRetract':'Feed retract'}[kind]})
    cycle={'oneOf':strategies}
    mill=copy.deepcopy(props['operations']['items']);mill['properties']['tool']=identifier;mill['title']='Facing or pocket'
    drill=obj({'id':identifier,'operation':{'const':'drill'},'tool':identifier,'locations':locations,
               'bottom':{'type':'number','minimum':-100000,'maximum':100000},'cycle':cycle},['id','operation','locations','bottom'])
    drill['title']='Drilling';props['operations']['items']={'oneOf':[mill,drill]}
    schema['required'].remove('tool')
    schema['oneOf']=[{'title':'Single tool','required':['tool'],'not':{'required':['tools']}},
                     {'title':'Named tool table','required':['tools'],'not':{'required':['tool']}}]
    return schema
