# Copyright (C) 2026 David L F Gaden
"""Independent ideal-gas NASA7 thermochemistry and equilibrium verification.

Coefficients are public source data, not fitted to native output. No Cantera,
NumPy, YAML parser or native chemistry solver is imported here.
"""
import json
import math
from pathlib import Path
from schemaxis.errors import fail

DATA = json.loads(Path(__file__).with_name('thermochemistry.json').read_text())
SPECIES = tuple(s['name'] for s in DATA['species'])
R = 8314.46261815324  # Exact SI k_B*N_A, J/(kmol K).
P0 = 101325.0
WEIGHTS = [s['molecularWeight'] for s in DATA['species']]
COLUMNS = ['initialTemperature_K','temperature_K','pressure_Pa','density_kg_m3',
           'enthalpy_J_kg','internalEnergy_J_kg','entropy_J_kg_K','cp_J_kg_K',
           'cv_J_kg_K','meanMolecularWeight_kg_kmol'] + ['X_'+s for s in SPECIES] + ['Y_'+s for s in SPECIES]


def check(condition, message):
    if not condition:
        fail('VERIFICATION_FAILED', message)


def close(a,b,relative=2e-8,absolute=2e-7):
    return type(a) in (int,float) and math.isfinite(a) and math.isclose(a,b,rel_tol=relative,abs_tol=absolute)


def fractions(options):
    amounts = {c['species']:c['amount'] for c in options['composition']}
    values = [amounts.get(s,0.0) for s in SPECIES]
    scale = max(values)
    values = [v/scale for v in values]
    if options['basis'] == 'mass':
        values = [v/w for v,w in zip(values,WEIGHTS)]
    total = math.fsum(values)
    return [v/total for v in values]


def nasa(temperature):
    cp, h, entropy = [], [], []
    for species in DATA['species']:
        ranges = species['temperatureRanges']
        a = species['coefficients'][0 if temperature <= ranges[1] else 1]
        t = temperature
        cp.append(a[0]+a[1]*t+a[2]*t*t+a[3]*t**3+a[4]*t**4)
        h.append(a[0]+a[1]*t/2+a[2]*t*t/3+a[3]*t**3/4+a[4]*t**4/5+a[5]/t)
        entropy.append(a[0]*math.log(t)+a[1]*t+a[2]*t*t/2+a[3]*t**3/3+a[4]*t**4/4+a[6])
    return cp,h,entropy


def properties(t,p,x):
    cp,h,s = nasa(t)
    weight = math.fsum(v*w for v,w in zip(x,WEIGHTS))
    heat = R*math.fsum(v*c for v,c in zip(x,cp))/weight
    enthalpy = R*t*math.fsum(v*c for v,c in zip(x,h))/weight
    entropy = R*math.fsum(v*(c-math.log(v*p/P0)) for v,c in zip(x,s) if v > 0)/weight
    return [t,p,p*weight/(R*t),enthalpy,enthalpy-R*t/weight,entropy,heat,heat-R/weight,weight]


def elements(x):
    weight = math.fsum(v*w for v,w in zip(x,WEIGHTS))
    return {e:math.fsum(v*s['atoms'].get(e,0) for v,s in zip(x,DATA['species']))/weight
            for e in DATA['elements']}


def equilibrium_error(t,p,x,initial):
    """Ideal-mixture chemical potentials must be linear in conserved atom counts.

H2/O2 define H/O potentials; N2 and Ar are inert in this mechanism. For every
accessible species, mu/(RT) = sum(n_atoms*lambda). Strictly convex ideal-mixture
Gibbs energy plus element conservation makes this a thermodynamic equilibrium
check independent of the native minimiser and kinetic rate implementation.
"""
    _,h,s = nasa(t)
    inventory = elements(initial)
    mu = {}
    for name,value,hi,si,spec in zip(SPECIES,x,h,s,DATA['species']):
        accessible = all(inventory[e] > 0 for e in spec['atoms'])
        if accessible:
            check(value > 0, 'equilibrium omitted accessible species '+name)
            mu[name] = hi-si+math.log(value*p/P0)
        else:
            check(value <= 1e-25, 'equilibrium created an absent element in '+name)
    potentials = {}
    for element,base,count in [('H','H2',2),('O','O2',2),('N','N2',2),('Ar','AR',1)]:
        if inventory[element] > 0:
            potentials[element] = mu[base]/count
    residuals = [abs(mu[s['name']]-math.fsum(n*potentials[e] for e,n in s['atoms'].items()))
                 for s in DATA['species'] if s['name'] in mu]
    return max(residuals,default=0.0)


def verify_rows(prepared, rows):
    source, operation = prepared['nodes']
    settings = operation['options']; initial = fractions(source['options'])
    expected_elements = elements(initial); pressure = source['options']['pressure']
    check(isinstance(rows,list) and len(rows) == len(settings['temperatures']), 'unexpected table row count')
    errors = []
    for index,(initial_t,row) in enumerate(zip(settings['temperatures'],rows)):
        check(isinstance(row,list) and len(row) == len(COLUMNS) and all(type(v) in (int,float) and math.isfinite(v) for v in row), 'invalid thermochemistry row')
        t,p = row[1:3]; x,y = row[10:20],row[20:30]
        check(close(row[0],initial_t) and close(p,pressure), 'initial temperature or pressure differs')
        check(300-1e-7 <= t <= 3500+1e-7 and all(0 <= v <= 1+1e-12 for v in x+y), 'state outside thermochemistry bounds')
        check(close(math.fsum(x),1,absolute=1e-10) and close(math.fsum(y),1,absolute=1e-10), 'fractions are not normalised')
        expected = properties(t,p,x)
        check(all(close(a,b) for a,b in zip(row[1:10],expected)), 'NASA7/ideal-gas properties differ at row '+str(index))
        weight = expected[-1]
        check(all(close(a,v*w/weight,absolute=1e-11) for a,v,w in zip(y,x,WEIGHTS)), 'mass/mole fractions disagree')
        observed_elements = elements(x)
        error = max(abs(observed_elements[e]-v) for e,v in expected_elements.items())
        check(error <= 1e-9, 'element inventory changed')
        equilibrium = 0.0
        if operation['filter'] == 'thermoSweep':
            check(close(t,initial_t) and all(close(a,b,absolute=1e-12) for a,b in zip(x,initial)), 'frozen state changed')
        else:
            if settings['mode'] == 'TP':
                check(close(t,initial_t), 'TP equilibrium changed temperature')
            else:
                check(close(row[4],properties(initial_t,pressure,initial)[3],relative=2e-8,absolute=0.02), 'HP equilibrium changed specific enthalpy')
            equilibrium = equilibrium_error(t,p,x,initial)
            check(equilibrium <= 2e-5, 'chemical-potential equilibrium residual exceeds 2e-5 RT')
        errors.append({'row':index,'elementError_kmol_kg':error,'equilibriumResidual_RT':equilibrium})
    return errors
