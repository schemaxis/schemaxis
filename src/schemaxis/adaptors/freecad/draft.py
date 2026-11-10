"""Mould-release Draft intent with measured, exact-cardinality face selection."""
import math
from schemaxis.errors import fail

VECTOR={'type':'array','items':{'type':'number','minimum':-100000,'maximum':100000},'minItems':3,'maxItems':3}
SURFACE={'type':'union','options':[
    {'type':'object','title':'Planar wall','properties':{'surface':{'type':'enum','values':['plane'],'required':True},
        'normal':{**VECTOR,'required':True},'position':{'type':'enum','values':['outermost','innermost'],'default':'outermost'}}},
    {'type':'object','title':'Cylindrical wall','properties':{'surface':{'type':'enum','values':['cylinder'],'required':True},
        'axis':{**VECTOR,'required':True},'axisPoint':{**VECTOR,'default':[0,0,0]},
        'radius':{'type':'number','minimum':0,'exclusiveMinimum':True,'maximum':100000,'required':True}}}]}


def declaration(factory):
    result=factory('PartDesign::Draft',{'angle':{'type':'number','minimum':0,'exclusiveMinimum':True,
        'maximum':90,'exclusiveMaximum':True,'default':3},'reversed':{'type':'boolean','default':False},
        'faces':{'type':'array','items':SURFACE,'minItems':1,'maxItems':32,'required':True}},('base','neutralPlane'))
    result['inputs']['neutralPlane']['kind']='profile'
    result['inputs']['axis']={'kind':'axis','required':False}
    return result


def validate(options,identity):
    for index,selection in enumerate(options['faces']):
        key='normal' if selection['surface']=='plane' else 'axis'
        if abs(math.hypot(*selection[key])-1)>1e-8:
            fail('INVALID_DRAFT_SELECTION','Draft normals and cylinder axes must be unit vectors',identity+'.faces['+str(index)+'].'+key)


def cross(a,b):
    return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]


def selected(options,inventory,identity):
    if not isinstance(inventory,list) or not 1<=len(inventory)<=10000:
        fail('VERIFICATION_FAILED','Draft source face inventory is missing or oversized',identity)
    fields={'index','surface','normal','centre','area','axis','axisPoint','radius'}
    for index,face in enumerate(inventory,1):
        if not isinstance(face,dict) or set(face)!=fields or type(face['index']) is not int or face['index']!=index or face['surface'] not in ('plane','cylinder','other'):
            fail('VERIFICATION_FAILED','Draft source face inventory membership differs',identity)
        for key in ('area','radius'):
            value=face[key]
            if type(value) not in (int,float) or not math.isfinite(value) or value<0 or (key=='area' or face['surface']=='cylinder') and value==0:
                fail('VERIFICATION_FAILED','Draft source face measurement is invalid',identity)
        for key in ('normal','centre','axis','axisPoint'):
            value=face[key]
            if not isinstance(value,list) or len(value)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in value):
                fail('VERIFICATION_FAILED','Draft source face vector is invalid',identity)
        direction='normal' if face['surface']=='plane' else 'axis'
        if face['surface']!='other' and abs(math.hypot(*face[direction])-1)>1e-7:
            fail('VERIFICATION_FAILED','Draft measured face direction is not unit',identity)
    indices=[]
    for index,selection in enumerate(options['faces']):
        matches=[]
        for face in inventory:
            if selection['surface']!=face['surface']:continue
            if face['surface']=='plane':
                if math.dist(selection['normal'],face['normal'])<1e-7:matches.append(face)
            elif (math.hypot(*cross(selection['axis'],face['axis']))<1e-7
                  and math.hypot(*cross([a-b for a,b in zip(selection['axisPoint'],face['axisPoint'])],selection['axis']))<1e-6
                  and abs(selection['radius']-face['radius'])<1e-6):matches.append(face)
        if matches and selection['surface']=='plane':
            n=selection['normal'];coordinate=(max if selection['position']=='outermost' else min)(sum(a*b for a,b in zip(n,face['centre'])) for face in matches)
            matches=[face for face in matches if abs(sum(a*b for a,b in zip(n,face['centre']))-coordinate)<1e-6]
        if len(matches)!=1:
            fail('EMPTY_SELECTION' if not matches else 'AMBIGUOUS_SELECTION','Draft face intent requires exactly one matching face; refine its geometry or base feature',identity+'.faces['+str(index)+']',matched=len(matches))
        indices.append(matches[0]['index'])
    if len(set(indices))!=len(indices):fail('INVALID_DRAFT_SELECTION','Draft face intents resolve to the same face',identity)
    return ['Face'+str(index) for index in indices]
