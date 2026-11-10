"""Closed pointed-depth, holder and explicit physical-clearance authoring choices."""
import copy
from schemaxis.schema import object_schema as obj


def expand(schema):
    schema=copy.deepcopy(schema);props=schema['properties']
    def number(low,high):return {'type':'number','minimum':low,'maximum':high}
    holder=obj({'stickOut':number(.1,2000),'steps':{'type':'array','minItems':1,'maxItems':8,
        'items':obj({'diameter':number(.1,500),'length':number(.1,2000)},['diameter','length'])}},['stickOut','steps'])
    holder['title']='Stepped holder envelope'
    props['tool']['properties']['holder']=copy.deepcopy(holder)
    flat=props['tools']['items'];flat['title']='Flat endmill'
    flat['properties']['holder']=copy.deepcopy(holder)
    identifier=copy.deepcopy(flat['properties']['id'])
    drill=obj({'id':identifier,'kind':{'const':'drill'},'diameter':number(.1,100),
        'tipAngle':number(1,179),'cuttingReach':number(.1,1000),'length':number(.1,2000),
        'flutes':{'type':'integer','minimum':1,'maximum':12,'default':2},
        'rpm':number(1,100000),'feed':number(.01,100000),'plunge':number(.01,100000),
        'holder':copy.deepcopy(holder)},['id','kind','diameter','tipAngle','cuttingReach','length','rpm','feed','plunge'])
    drill['title']='Pointed drill'
    drill['properties']['shankDiameter']=number(.1,100)
    props['tools']['items']={'oneOf':[flat,drill]}
    positive={'type':'number','exclusiveMinimum':0,'maximum':1000}
    props['setup']['properties']['toolClearance']={'oneOf':[
        {**obj({'kind':{'const':'aboveBlank'},'axialClearance':positive},['kind','axialClearance']),'title':'Above original blank'},
        {**obj({'kind':{'const':'evolvingStock'},'minimumSeparation':copy.deepcopy(positive)},['kind','minimumSeparation']),'title':'Ordered remaining stock'}]}
    pointed=copy.deepcopy(props['operations']['items']['oneOf'][1])
    pointed['title']='Pointed drilling';pointed['properties'].update(
        depthReference={'enum':['tip','fullDiameter']},throughClearance=copy.deepcopy(positive))
    pointed['required'].append('depthReference')
    props['operations']['items']['oneOf'][1]['title']='Flat-bottom drilling'
    props['operations']['items']['oneOf'].append(pointed)
    physical={'anyOf':[
        {'required':['tool'],'properties':{'tool':{'required':['holder']}}},
        {'required':['tools'],'properties':{'tools':{'contains':{'anyOf':[
            {'required':['kind'],'properties':{'kind':{'const':'drill'}}}, {'required':['holder']}]}}}},
        {'required':['operations'],'properties':{'operations':{'contains':{'required':['depthReference']}}}}]}
    schema.setdefault('allOf',[]).append({'if':physical,'then':{'required':['setup'],
        'properties':{'setup':{'required':['toolClearance']}}}})
    return schema
