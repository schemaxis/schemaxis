# Copyright (C) 2026 David L F Gaden
"""Named finite-sample circuit requirements, separate from solver correctness."""
import math
import re

from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail
from . import circuit

AXES={'dcSweep':'sourceVoltage_V','acSweep':'frequency_Hz','rcStep':'time_s'}
QUANTITIES={'dcSweep':['voltage_V'],'acSweep':['magnitude_V','gainMagnitude','gain_dB','phase_deg','currentMagnitude_A','activePower_W','reactivePower_var','impedanceMagnitude_Ohm'],'rcStep':['voltage_V']}
NONNEGATIVE={'magnitude_V','gainMagnitude','currentMagnitude_A','impedanceMagnitude_Ohm'}
UNITS={'voltage_V':'V','magnitude_V':'V','gainMagnitude':'V/V','gain_dB':'dB','phase_deg':'deg','currentMagnitude_A':'A','activePower_W':'W','reactivePower_var':'var','impedanceMagnitude_Ohm':'ohm'}
NUMBER={'type':'number','minimum':-1e12,'maximum':1e12}
SPECIFICATION={'type':'array','minItems':1,'maxItems':32,'items':{'type':'object','properties':{
    'name':{'type':'string','minLength':1,'maxLength':64,'required':True},
    'probe':{'type':'string','minLength':1,'maxLength':32,'required':True},
    'quantity':{'type':'enum','values':sorted(set(sum(QUANTITIES.values(),[]))),'required':True},
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
        voltage_quantities={'voltage_V','magnitude_V','gainMagnitude','gain_dB','phase_deg'}
        available=(prepared['circuit']['probes'] if entry['quantity'] in voltage_quantities else
                   (['$input'] if entry['quantity']=='impedanceMagnitude_Ohm' else prepared['circuit'].get('branchProbes',[])+['$input']))
        if entry['probe'] not in available or entry['probe']=='$input' and not prepared.get('portMetrics'):
            fail('INVALID_REQUIREMENT','select a published voltage or branch probe, or enable portMetrics for $input',location+'.probe')
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
        if entry['quantity'] in NONNEGATIVE and any(entry.get(key,0)<0 for key in ('minimum','maximum')):
            fail('INVALID_REQUIREMENT','magnitude bounds must be nonnegative',location)
        if entry['quantity']=='phase_deg' and any(not -180<=entry[key]<=180 for key in ('minimum','maximum') if key in entry):
            fail('INVALID_REQUIREMENT','phase bounds use the principal interval [-180,180] degrees; split a wrapping interval into separate windows',location)
        if entry['quantity'] in ('phase_deg','gain_dB'):
            for index in selected:
                axis_value=axis[index];v=circuit.expected(prepared,axis_value)[entry['probe']]
                if abs(v/prepared['amplitude'])<=1e-30:
                    fail('UNDEFINED_OBSERVABLE','phase/gain dB is undefined at zero response; choose a nonzero probe or magnitude bound',location+'.quantity')
    return requirements


def requirement_schema(operation):
    from schemaxis.schema import argument_schema
    result=argument_schema(SPECIFICATION)
    fields=result['items']['properties']
    fields['name']['pattern']='^[a-z][a-z0-9_]{0,63}$'
    fields['quantity']={'enum':QUANTITIES[operation]}
    fields['axis']={'const':AXES[operation]}
    if operation=='acSweep':
        result['items']['allOf']=[
            {'if':{'properties':{'quantity':{'enum':sorted(NONNEGATIVE)}}},
             'then':{'properties':{key:{'minimum':0} for key in ('minimum','maximum')}}},
            {'if':{'properties':{'quantity':{'const':'phase_deg'}}},
             'then':{'properties':{key:{'minimum':-180,'maximum':180} for key in ('minimum','maximum')}}}]

    result['items']['anyOf']=[{'required':['minimum']},{'required':['maximum']}]
    return result


def assess(prepared,rows):
    """Measure actual checked native values; never substitute analytic predictions."""
    requirements=[]
    for entry in prepared['requirements']:
        axis,selected,epsilon=window_samples(prepared,entry['window'])
        column=prepared['nodes'].index(entry['probe']) if prepared['operation']!='acSweep' else None
        values=[]
        for index in selected:
            row=rows[index]
            if prepared['operation']=='acSweep':
                measured=circuit.observables(prepared,row)
                if entry['quantity'] not in measured.get(entry['probe'],{}):
                    fail('VERIFICATION_FAILED','required phase/gain is undefined in native observations')
                value=measured[entry['probe']][entry['quantity']]
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
        requirements.append({**entry,'units':UNITS[entry['quantity']],
            'samplesChecked':len(selected),'endpointTolerance':epsilon,
            'minimumObserved':minimum,'maximumObserved':maximum,'checks':checks,'accepted':accepted,
            'nextAction':'Accept the requirement at the declared samples.' if accepted else
                'Inspect the worst sampled condition and revise component values, excitation or the stated bounds; rerun a fresh attempt.'})
    return {'version':'schemaxis.ngspice.performance/1','accepted':all(r['accepted'] for r in requirements),
        'coverage':'Only declared samples in each window; no continuous-frequency/time or all-component-tolerance guarantee.',
        'requirements':requirements}
