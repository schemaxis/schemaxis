# Copyright (C) 2026 David L F Gaden
"""Named checks over fixed verified Calc cells, never authored native formulas."""
import math
import re
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail

CELL = {'sheet': {'type':'enum','values':['Data','Summary'],'required':True},
        'cell': {'type':'string','minLength':2,'maxLength':7,'required':True}}
NAME = {'type':'string','minLength':1,'maxLength':64,'required':True}
NUMBER = {'type':'number','minimum':-1e100,'maximum':1e100}
BOUNDS = {'name':NAME,'type':{'type':'enum','values':['cellBounds'],'required':True},
          'cell':{'type':'object','properties':CELL,'required':True},'minimum':NUMBER,'maximum':NUMBER}
RECONCILE = {'name':NAME,'type':{'type':'enum','values':['reconcile'],'required':True},
             'terms':{'type':'array','minItems':2,'maxItems':16,'required':True,'items':{'type':'object','properties':{
                 **CELL,'coefficient':{'type':'number','minimum':-1e6,'maximum':1e6,'required':True}}}},
             'target':{**NUMBER,'default':0},'absoluteTolerance':{'type':'number','minimum':0,'maximum':1e100,'required':True}}


def address(value):
    match = re.fullmatch(r'([A-Z]{1,2})([1-9][0-9]{0,4})', value['cell'])
    if not match: fail('INVALID_SELECTOR','use canonical uppercase A1 notation without ranges or absolute markers', value['cell'])
    column=0
    for char in match[1]:column=column*26+ord(char)-64
    row=int(match[2]);width,height=(64,10001) if value['sheet']=='Data' else (7,65)
    if column>width or row>height:fail('INVALID_SELECTOR','cell exceeds the fixed sheet bounds',value['cell'])
    return row-1,column-1


def prepare(value):
    if not isinstance(value,list) or len(value)>64:fail('INVALID_REQUIREMENTS','requirements must be an array of at most 64 named checks')
    result=[];names=set()
    for index,item in enumerate(value):
        if not isinstance(item,dict) or item.get('type') not in ('cellBounds','reconcile'):fail('INVALID_REQUIREMENTS','select cellBounds or reconcile',str(index))
        spec=BOUNDS if item['type']=='cellBounds' else RECONCILE
        item=validate_arguments(spec,item,location='$.requirements['+str(index)+']')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',item['name']) or item['name'] in names:
            fail('INVALID_REQUIREMENTS','requirement names must be unique bounded identifiers',item['name'])
        names.add(item['name'])
        if item['type']=='cellBounds':
            address(item['cell'])
            if not any(k in item for k in ('minimum','maximum')) or item.get('minimum',-math.inf)>item.get('maximum',math.inf):
                fail('INVALID_REQUIREMENTS','declare at least one bound, with minimum <= maximum',item['name'])
        else:
            identities=[]
            for term in item['terms']:
                address(term);identities.append((term['sheet'],term['cell']))
                if term['coefficient']==0:fail('INVALID_REQUIREMENTS','omit zero-coefficient terms',item['name'])
            if len(set(identities))!=len(identities):fail('INVALID_REQUIREMENTS','reconciliation cells must be distinct',item['name'])
        result.append(item)
    return result


def schema():
    from schemaxis.schema import argument_schema,object_schema
    variants=[]
    for specification in (BOUNDS,RECONCILE):
        props={key:argument_schema(value) for key,value in specification.items()}
        props['name']['pattern']='^[A-Za-z][A-Za-z0-9_-]{0,63}$'
        selector=props['cell']['properties'] if specification is BOUNDS else props['terms']['items']['properties']
        selector['cell']['pattern']='^[A-Z]{1,2}[1-9][0-9]{0,4}$'
        variant=object_schema(props,[key for key,value in specification.items() if value.get('required')])
        if specification is BOUNDS:variant['anyOf']=[{'required':['minimum']},{'required':['maximum']}]
        variants.append(variant)
    return {'type':'array','maxItems':64,'items':{'oneOf':variants}}


def _cell(values,selector):
    row,column=address(selector)
    rows=values.get(selector['sheet'],[])
    if row>=len(rows) or column>=len(rows[row]):return None,'missing'
    value=rows[row][column]
    if type(value) not in (int,float) or not math.isfinite(value):return None,'non-numeric'
    return value,None


def evaluate(requirements,values):
    checks=[]
    for item in requirements:
        selectors=[item['cell']] if item['type']=='cellBounds' else item['terms']
        selected=[_cell(values,s) for s in selectors]
        faults=[{'sheet':s['sheet'],'cell':s['cell'],'condition':error} for s,(_,error) in zip(selectors,selected) if error]
        record={'name':item['name'],'type':item['type'], **{key:item[key] for key in ('minimum','maximum','target','absoluteTolerance') if key in item}}
        if faults:checks.append({**record,'status':'invalid-selection','conditions':faults});continue
        if item['type']=='cellBounds':
            value=selected[0][0]
            margins=([value-item['minimum']] if 'minimum' in item else [])+([item['maximum']-value] if 'maximum' in item else [])
            margin=min(margins)
        else:
            try:value=math.fsum(term['coefficient']*actual for term,(actual,_) in zip(item['terms'],selected))
            except (OverflowError,ValueError):value=math.inf
            margin=item['absoluteTolerance']-abs(value-item['target'])
        if not math.isfinite(value) or not math.isfinite(margin):
            checks.append({**record,'status':'invalid-selection','conditions':[{'condition':'non-finite-reconciliation'}]});continue
        checks.append({**record,'status':'passed' if margin>=0 else 'unmet','value':value,'margin':margin})
    return {'passed':all(item['status']=='passed' for item in checks),'checks':checks}


def report(requirements,observations):
    formats={name:evaluate(requirements,values) for name,values in observations.items()}
    # Compare only observations of the SAME authored requirement. Different
    # checks may have different units and cannot share a meaningful ranking.
    worst=[]
    for item in requirements:
        candidates=[(name,check) for name,result in formats.items() for check in result['checks']
                    if check['name']==item['name'] and 'margin' in check]
        if candidates:
            name,check=min(candidates,key=lambda value:value[1]['margin'])
            worst.append({'name':item['name'],'format':name,'margin':check['margin']})
    return {'version':'schemaxis.calc.requirements/1','requirements':requirements,
            'formats':formats,'worstFormats':worst,
            'passed':all(result['passed'] for result in formats.values()),
            'scope':'Declared fixed-sheet numeric cells only; coefficients/units and absolute tolerances are authored. Worst format compares only the same named requirement. No arbitrary native formulas or general workbook acceptance.'}


def enforce(value,location='requirements.json'):
    invalid=[{'format':name,**item} for name,result in value['formats'].items()
             for item in result['checks'] if item['status']=='invalid-selection']
    unmet=[{'format':name,**item} for name,result in value['formats'].items()
           for item in result['checks'] if item['status']=='unmet']
    if invalid:fail('REQUIREMENT_SELECTION_FAILED','required cells are missing, nonnumeric or non-finite',location,
                    assessment=invalid,recovery='Select an existing numeric Data or Summary cell and retry in a fresh run.')
    if unmet:fail('REQUIREMENTS_UNMET','one or more named Calc requirements are unmet',location,
                  assessment=unmet,recovery='Inspect retained requirements.json and native workbooks; correct the input or declared bounds/tolerance and retry in a fresh run.')
