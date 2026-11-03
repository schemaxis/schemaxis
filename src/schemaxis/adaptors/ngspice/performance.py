# Copyright (C) 2026 David L F Gaden
"""Named finite-sample circuit requirements, separate from solver correctness."""
import math
import re

from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from . import circuit

AXES={'dcSweep':'sourceVoltage_V','acSweep':'frequency_Hz','rcStep':'time_s'}
QUANTITIES={'dcSweep':['voltage_V'],'acSweep':['magnitude_V','gainMagnitude'],'rcStep':['voltage_V']}
NUMBER={'type':'number','minimum':-1e12,'maximum':1e12}
SPECIFICATION={'type':'array','minItems':1,'maxItems':32,'items':{'type':'object','properties':{
    'name':{'type':'string','minLength':1,'maxLength':64,'required':True},
    'probe':{'type':'string','minLength':1,'maxLength':32,'required':True},
    'quantity':{'type':'enum','values':['voltage_V','magnitude_V','gainMagnitude'],'required':True},
    'axis':{'type':'enum','values':list(AXES.values()),'required':True},
    'window':{'type':'array','items':NUMBER,'minItems':2,'maxItems':2,'required':True},
    'minimum':NUMBER,'maximum':NUMBER}}}


def window_samples(prepared,window):
    axis=circuit.samples(prepared)
    # Eight representable-coordinate steps include mathematically identical
    # authored endpoints without adding a physical performance tolerance.
    epsilon=8*math.ulp(max(map(abs,[axis[0],axis[-1],*window])))
    selected=[i for i,value in enumerate(axis) if window[0]-epsilon<=value<=window[1]+epsilon]
    return axis,selected,epsilon


def validate(prepared,value):
    requirements=validate_arguments({'requirements':SPECIFICATION},{'requirements':value},
        location='$')['requirements']
    names=set()
    for index,entry in enumerate(requirements):
        location=f'$.requirements[{index}]'
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',entry['name']) or entry['name'] in names:
            fail('INVALID_REQUIREMENT','requirement names must be unique lowercase identifiers',location+'.name')
        names.add(entry['name'])
        if entry['probe'] not in prepared['circuit']['probes']:
            fail('INVALID_REQUIREMENT','select a published circuit probe',location+'.probe')
        if entry['quantity'] not in QUANTITIES[prepared['operation']]:
            fail('INVALID_REQUIREMENT','quantity is not supported by this analysis',location+'.quantity')
        if entry['axis']!=AXES[prepared['operation']]:
            fail('INVALID_REQUIREMENT','axis units must match the analysis',location+'.axis')
        lower,upper=entry['window'];axis,selected,epsilon=window_samples(prepared,entry['window'])
        if lower>upper or lower<axis[0]-epsilon or upper>axis[-1]+epsilon or not selected:
            fail('INVALID_REQUIREMENT','use an ordered window inside the sweep containing a declared sample',location+'.window')
        if not any(key in entry for key in ('minimum','maximum')):
            fail('INVALID_REQUIREMENT','declare a lower or upper performance bound',location)
        if entry.get('minimum',-math.inf)>entry.get('maximum',math.inf):
            fail('INVALID_REQUIREMENT','minimum must not exceed maximum',location)
        if entry['quantity']!='voltage_V' and any(entry.get(key,0)<0 for key in ('minimum','maximum')):
            fail('INVALID_REQUIREMENT','magnitude and gain bounds must be nonnegative',location)
    return requirements


def requirement_schema(operation):
    from schemaxis.schema import argument_schema
    result=argument_schema(SPECIFICATION)
    fields=result['items']['properties']
    fields['name']['pattern']='^[a-z][a-z0-9_]{0,63}$'
    fields['quantity']={'enum':QUANTITIES[operation]}
    fields['axis']={'const':AXES[operation]}
    if operation=='acSweep':
        for field in ('minimum','maximum'):fields[field]['minimum']=0
    result['items']['anyOf']=[{'required':['minimum']},{'required':['maximum']}]
    return result


def assess(prepared,rows):
    """Measure actual checked native values; never substitute analytic predictions."""
    requirements=[]
    for entry in prepared['requirements']:
        axis,selected,epsilon=window_samples(prepared,entry['window'])
        column=prepared['nodes'].index(entry['probe'])
        values=[]
        for index in selected:
            row=rows[index]
            if prepared['operation']=='acSweep':
                value=abs(complex(row[1+2*column],row[2+2*column]))
                if entry['quantity']=='gainMagnitude':value/=abs(prepared['amplitude'])
            else:value=row[1+column]
            values.append({'value':value,'sampleIndex':index,'coordinate':axis[index],'nativeCoordinate':row[0]})
        minimum=min(values,key=lambda value:value['value']);maximum=max(values,key=lambda value:value['value'])
        checks=[]
        for bound,worst in (('minimum',minimum),('maximum',maximum)):
            if bound not in entry:continue
            margin=worst['value']-entry[bound] if bound=='minimum' else entry[bound]-worst['value']
            checks.append({'bound':bound,'expected':entry[bound],'observed':worst['value'],
                'margin':margin,'passed':margin>=0,'worstCondition':worst})
        accepted=all(check['passed'] for check in checks)
        requirements.append({**entry,'units':'V/V' if entry['quantity']=='gainMagnitude' else 'V',
            'samplesChecked':len(selected),'endpointTolerance':epsilon,
            'minimumObserved':minimum,'maximumObserved':maximum,'checks':checks,'accepted':accepted,
            'nextAction':'Accept the requirement at the declared samples.' if accepted else
                'Inspect the worst sampled condition and revise component values, excitation or the stated bounds; rerun a fresh attempt.'})
    return {'version':'schemaxis.ngspice.performance/1','accepted':all(r['accepted'] for r in requirements),
        'coverage':'Only declared samples in each window; no continuous-frequency/time or all-component-tolerance guarantee.',
        'requirements':requirements}
