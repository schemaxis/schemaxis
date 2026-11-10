# Copyright (C) 2026 David L F Gaden
"""Independent h2o2 mass-action kinetics and closed-reactor thermal histories.

Rate parameters are the public upstream mechanism data retained unchanged in
kinetics.json. The host evaluates elementary, three-body and Troe falloff rates,
reverse rates from NASA7 equilibrium constants and the constant-pressure
or constant-volume energy equation including optional fixed-bath heat exchange,
then integrates them with its own L-stable Rosenbrock method. No Cantera, NumPy, SUNDIALS or YAML parser is imported here.
"""
import json
import math
from pathlib import Path

from . import thermo
from .thermo import check
from schemaxis.core.faults import SchemaxisError

DATA = json.loads(Path(__file__).with_name('kinetics.json').read_text())
SPECIES = thermo.SPECIES
N = len(SPECIES)
INDEX = {name:i for i,name in enumerate(SPECIES)}
WEIGHTS = thermo.WEIGHTS
R = thermo.R
P0 = thermo.P0
ENERGY = 4184.0  # cal/mol activation energy to J/kmol (thermochemical calorie).
VOLUME = 1e-3    # One cm3/mol concentration order expressed in m3/kmol.
SMALL = 1e-300
MODELS = {'constantPressure':'IdealGasConstPressureReactor','constantVolume':'IdealGasReactor'}
# Independent integration and comparison bounds. They are verification policy,
# not authored solver settings, and are recorded in every reactor summary.
RTOL, ATOL, MAX_STEPS = 1e-7, (1e-5, 1e-12), 50000
SHIFT = 0.01  # Relative sample-time window for steep ignition fronts.


def _arrhenius(parameters,order):
    return (parameters['A']*VOLUME**(order-1),parameters['b'],parameters['Ea']*ENERGY/R)


def _prepare():
    reactions = []
    for record in DATA['reactions']:
        reactants = [(INDEX[k],v) for k,v in record['reactants'].items()]
        products = [(INDEX[k],v) for k,v in record['products'].items()]
        order = math.fsum(v for _,v in reactants)
        efficiencies = None
        if record['type'] in ('three-body','falloff'):
            efficiencies = [record['efficiencies'].get(s,1.0) for s in SPECIES]
        entry = {'type':record['type'],'reactants':reactants,'products':products,
                 'change':math.fsum(v for _,v in products)-order,'efficiencies':efficiencies}
        if record['type'] == 'falloff':
            entry['low'] = _arrhenius(record['low-P-rate-constant'],order+1)
            entry['high'] = _arrhenius(record['high-P-rate-constant'],order)
            entry['troe'] = record['Troe']
        else:
            entry['rate'] = _arrhenius(record['rate-constant'],order+(record['type'] == 'three-body'))
        check(record['type'] in ('elementary','three-body','falloff'),'unsupported reaction type')
        reactions.append(entry)
    return reactions


REACTIONS = _prepare()


def _k(parameters,t):
    a,b,ea = parameters
    return a*t**b*math.exp(-ea/t)


def _centre(parameters,t):
    a = parameters['A']
    centre = (1-a)*math.exp(-t/parameters['T3'])+a*math.exp(-t/parameters['T1'])
    if 'T2' in parameters: centre += math.exp(-parameters['T2']/t)
    return math.log10(max(centre,SMALL))


def coefficients(t):
    """Temperature-dependent NASA7 and per-reaction rate/equilibrium coefficients."""
    cp,h,s = thermo.nasa(t)
    gibbs = [a-b for a,b in zip(h,s)]
    standard = P0/(R*t)
    values = []
    for reaction in REACTIONS:
        delta = sum(v*gibbs[i] for i,v in reaction['products'])-sum(v*gibbs[i] for i,v in reaction['reactants'])
        # Reverse rate constant = forward/Kc with Kc = Kp*(P0/RT)**change.
        inverse = math.exp(delta)*standard**(-reaction['change'])
        if reaction['type'] == 'falloff':
            values.append((_k(reaction['high'],t),_k(reaction['low'],t),_centre(reaction['troe'],t),inverse))
        else:
            values.append((_k(reaction['rate'],t),None,None,inverse))
    return cp,h,values


def rates(coefficient,concentrations):
    """Net species production rates (kmol/m3/s) and their gross rate scale."""
    result = [0.0]*N; scale = 0.0
    for reaction,(k,low,centre,inverse) in zip(REACTIONS,coefficient[2]):
        efficiencies = reaction['efficiencies']
        if efficiencies is not None:
            collider = sum(e*c for e,c in zip(efficiencies,concentrations))
            if low is None:
                k *= collider
            else:
                # Troe falloff blending, with log10 terms bounded as in the public formulation.
                reduced = low*collider/k
                c = -0.4-0.67*centre; n = 0.75-1.27*centre
                shifted = math.log10(max(reduced,SMALL))+c
                f = shifted/(n-0.14*shifted)
                k *= reduced/(1+reduced)*10**(centre/(1+f*f))
        forward = k; reverse = k*inverse
        for i,v in reaction['reactants']: forward *= concentrations[i]**v
        for i,v in reaction['products']: reverse *= concentrations[i]**v
        net = forward-reverse; scale += abs(forward)+abs(reverse)
        for i,v in reaction['reactants']: result[i] -= v*net
        for i,v in reaction['products']: result[i] += v*net
    return result,scale


def production(t,concentrations):
    """Net species production rates (kmol/m3/s) and their gross rate scale."""
    return rates(coefficients(t),concentrations)


def state(model,constant,y):
    """Return density, pressure, mean weight and concentrations for [T, Y...]."""
    t = y[0]; fractions = y[1:N+1]
    weight = 1/sum(v/w for v,w in zip(fractions,WEIGHTS))
    if model == 'constantPressure':
        pressure = constant; density = pressure*weight/(R*t)
    else:
        density = constant; pressure = density*R*t/weight
    return density,pressure,weight,[density*v/w for v,w in zip(fractions,WEIGHTS)]


def derivative(model,constant,y,coefficient=None,thermal=None):
    """Closed ideal-gas reactor: d[T, Y_k, optional bath heat J/kg]/dt."""
    t = y[0]
    density,_,weight,concentrations = state(model,constant,y)
    coefficient = coefficient or coefficients(t)
    cp,h,_ = coefficient
    production,_ = rates(coefficient,concentrations)
    heat = R*sum(v/w*c for v,w,c in zip(y[1:N+1],WEIGHTS,cp))
    if model == 'constantPressure':
        release = R*t*sum(e*w for e,w in zip(h,production))
    else:
        heat -= R/weight
        release = R*t*sum((e-1)*w for e,w in zip(h,production))
    heat_input_rate = 0.0 if thermal is None else thermal[0]*(thermal[1]-t)/thermal[2]
    result = [-release/(density*heat)+heat_input_rate/heat]+[w*m/density for w,m in zip(production,WEIGHTS)]
    return result if thermal is None else result+[heat_input_rate]


def _factor(matrix):
    """In-place LU factorisation with partial pivoting of a small dense matrix."""
    n = len(matrix); a = [row[:] for row in matrix]; order = list(range(n))
    for column in range(n):
        pivot = max(range(column,n),key=lambda r:abs(a[r][column]))
        check(abs(a[pivot][column]) > 0,'singular independent reactor Jacobian')
        a[column],a[pivot] = a[pivot],a[column]; order[column],order[pivot] = order[pivot],order[column]
        diagonal = a[column][column]; top = a[column]
        for row in range(column+1,n):
            factor = a[row][column]/diagonal; a[row][column] = factor
            if factor:
                current = a[row]
                for k in range(column+1,n): current[k] -= factor*top[k]
    return a,order


def _solve(factored,vector):
    a,order = factored; n = len(a); x = [vector[i] for i in order]
    for row in range(n):
        x[row] -= sum(a[row][k]*x[k] for k in range(row))
    for row in range(n-1,-1,-1):
        x[row] = (x[row]-sum(a[row][k]*x[k] for k in range(row+1,n)))/a[row][row]
    return x


# Shampine's four-stage L-stable Rosenbrock parameters (order 4, embedded order 3).
GAMMA = 0.5
A21,A31,A32 = 2.0,48/25,6/25
C21,C31,C32 = -8.0,372/25,12/5
C41,C42,C43 = -112/125,-54/125,-2/5
B = (19/9,1/2,25/108,125/108)
E = (17/54,7/36,0.0,125/108)


def _step(function,y,h,f0,jacobian):
    n = len(y)
    factored = _factor([[(1/(GAMMA*h) if i == j else 0.0)-jacobian[i][j] for j in range(n)] for i in range(n)])
    g1 = _solve(factored,f0)
    f2 = function([a+A21*b for a,b in zip(y,g1)])
    g2 = _solve(factored,[f+C21*a/h for f,a in zip(f2,g1)])
    f3 = function([a+A31*b+A32*c for a,b,c in zip(y,g1,g2)])
    g3 = _solve(factored,[f+(C31*a+C32*b)/h for f,a,b in zip(f3,g1,g2)])
    g4 = _solve(factored,[f+(C41*a+C42*b+C43*c)/h for f,a,b,c in zip(f3,g1,g2,g3)])
    stages = (g1,g2,g3,g4)
    new = [v+sum(c*g[i] for c,g in zip(B,stages)) for i,v in enumerate(y)]
    error = [sum(c*g[i] for c,g in zip(E,stages)) for i in range(n)]
    return new,error


def _jacobian(function,y,f0,frozen):
    """Forward-difference Jacobian; frozen coefficients serve columns that keep T."""
    n = len(y); jacobian = [[0.0]*n for _ in range(n)]
    for j in range(n):
        delta = 1e-7*max(abs(y[j]),1e-7 if j else 1.0)
        shifted = y[:]; shifted[j] += delta
        column = function(shifted,frozen) if j and frozen is not None else function(shifted)
        for i in range(n): jacobian[i][j] = (column[i]-f0[i])/delta
    return jacobian


def integrate(function,y,start,stops,*,rtol,atol,max_steps,observe=None,freeze=None):
    """Adaptive Rosenbrock integration landing exactly on each requested stop.

``function(y, frozen=None)`` returns dy/dt. ``freeze(y)`` may return reusable
state-independent data for Jacobian columns that leave y[0] unchanged.
"""
    t = start; h = None; steps = 0; result = []
    scales = [atol[0]]+[atol[1]]*(len(y)-1)
    for stop in stops:
        while t < stop:
            frozen = freeze(y) if freeze else None
            f0 = function(y,frozen) if frozen is not None else function(y)
            if h is None:
                rate = max(abs(d)/(s+rtol*abs(v)) for d,v,s in zip(f0,y,scales))
                h = min(stop-start,1e-3/max(rate,1e-300),1e-6)
            jacobian = _jacobian(function,y,f0,frozen)
            while True:
                trial = min(h,stop-t)
                new,error = _step(function,y,trial,f0,jacobian)
                norm = max(abs(e)/(s+rtol*max(abs(a),abs(b))) for e,a,b,s in zip(error,y,new,scales))
                steps += 1
                check(steps <= max_steps,'independent reactor integration exceeded its step budget')
                if norm <= 1: break
                h = trial*max(0.2,0.9*norm**-0.25) if math.isfinite(norm) else trial*0.2
            previous = (t,y); t = stop if trial == stop-t else t+trial; y = new
            if observe: observe(previous,(t,y))
            # A step clipped to land on a stop does not shrink the next proposed step.
            h = max(h if trial < h else trial,trial)*min(4.0,0.9*max(norm,1e-12)**-0.25)
        result.append((t,y))
    return result


def initial(prepared):
    """Initial temperature, pressure, mole and mass fractions of the planned reactor."""
    source,operation = prepared['nodes']
    x = thermo.fractions(source['options'])
    weight = math.fsum(v*w for v,w in zip(x,WEIGHTS))
    return operation['options']['temperature'],source['options']['pressure'],x,[v*w/weight for v,w in zip(x,WEIGHTS)]


def crossing(points,threshold,end):
    """First time T reaches threshold, linear in time between consecutive steps.

This is the declared ignition-delay criterion. A crossing after the final sample
time ``end`` is outside the requested history and is reported as None.
"""
    for (ta,a),(tb,b) in zip(points,points[1:]):
        if a < threshold <= b:
            value = ta+(threshold-a)*(tb-ta)/(b-a)
            return value if value <= end else None
    return None


_HISTORIES = {}


def history(prepared):
    """Independently integrate the planned reactor; cached per effective plan."""
    key = json.dumps(prepared,sort_keys=True)
    if key not in _HISTORIES:
        if len(_HISTORIES) > 8: _HISTORIES.clear()
        _HISTORIES[key] = _history(prepared)
    return _HISTORIES[key]


def _history(prepared):
    settings = prepared['nodes'][1]['options']; model = settings['model']
    t0,pressure,x0,y0 = initial(prepared)
    constant = pressure if model == 'constantPressure' else pressure*math.fsum(v*w for v,w in zip(x0,WEIGHTS))/(R*t0)
    mass = pressure*math.fsum(v*w for v,w in zip(x0,WEIGHTS))/(R*t0)*prepared['reactor']['volume_m3']
    thermal = (settings.get('thermalConductance',0),settings.get('bathTemperature',300),mass) if settings.get('thermalConductance',0) > 0 else None
    function = lambda value,frozen=None: derivative(model,constant,value,frozen,thermal)
    initial_state = [t0]+y0+([] if thermal is None else [0.0])
    trajectory = [(0.0,initial_state)]
    stops = sorted({t*(1+s*SHIFT) for t in settings['times'] for s in (-1,0,1) if t > 0})
    integrate(function,initial_state,0.0,stops,rtol=RTOL,atol=ATOL,max_steps=MAX_STEPS,
              observe=lambda previous,current:trajectory.append(current),
              freeze=lambda value:coefficients(value[0]))
    return {'trajectory':trajectory,'ignition':crossing([(t,y[0]) for t,y in trajectory],
            t0+settings['ignitionTemperatureRise'],settings['times'][-1])}


def _moles(y):
    moles = [v/w for v,w in zip(y,WEIGHTS)]; total = math.fsum(moles)
    return [v/total for v in moles]


def _jump(low,high):
    """Largest NASA7 range-boundary enthalpy discontinuity crossed, J/kg."""
    largest = 0.0
    for species,weight in zip(thermo.DATA['species'],WEIGHTS):
        middle = species['temperatureRanges'][1]
        if low <= middle < high:
            values = []
            for a in species['coefficients']:
                t = middle
                values.append(a[0]+a[1]*t/2+a[2]*t*t/3+a[3]*t**3/4+a[4]*t**4/5+a[5]/t)
            largest = max(largest,abs(values[1]-values[0])*R*middle/weight)
    return largest


def _equilibrium(t,p,x,initial_x):
    try:
        return thermo.equilibrium_error(t,p,x,initial_x)
    except SchemaxisError:
        return None


TOLERANCES = {'elementRelative':1e-9,'energyRelative_cpT0':1e-7,'densityRelative':1e-10,
              'massRelative':1e-10,'rateRelative_grossRate':1e-10,'sampleTimeWindowRelative':SHIFT,
              'thermalEnergyRelative_cpT0':1e-6,'temperature_K':0.5,'moleFraction':1e-6,'ignitionDelayRelative':SHIFT}


def verify_history(prepared,rows,native,reopened=None):
    """Check a reactor time history against conservation laws and independent kinetics."""
    settings = prepared['nodes'][1]['options']; model = settings['model']; times = settings['times']
    t0,pressure,x0,_ = initial(prepared)
    start = thermo.properties(t0,pressure,x0)
    expected_elements = thermo.elements(x0); inventory = max(expected_elements.values())
    reactor = native['reactor']; samples = reactor['samples']
    check(isinstance(rows,list) and isinstance(samples,list) and len(rows) == len(times) == len(samples),'unexpected reactor row count')
    check(reopened is None or (isinstance(reopened,list) and len(reopened) == len(rows)),'missing fresh-process reactor rate readback')
    # Every native number is a finite real (never bool) before any arithmetic.
    check(all(isinstance(row,list) and len(row) == len(thermo.COLUMNS) and real(*row) for row in rows),'invalid reactor row')
    check(all(isinstance(s,dict) and real(s.get('time'),s.get('mass'),s.get('volume'))
          and _vector(s.get('rates')) for s in samples) and (reopened is None or all(_vector(r) for r in reopened)),
          'native reactor sample, mass, volume or rate evidence is not a finite real table')
    check(isinstance(reactor.get('initial'),dict) and real(reactor['initial'].get('mass'),reactor['initial'].get('volume')),
          'native initial reactor mass or volume is not a finite real')
    check(isinstance(reactor.get('steps'),list) and all(isinstance(s,list) and len(s) == 2 and real(*s) and 300 <= s[1] <= 3500 for s in reactor['steps']),
          'native integrator step record is not a finite real table')
    check(reactor['solver'] == {'reactorType':MODELS[model],'rtol':settings['relativeTolerance'],
          'atol':settings['absoluteTolerance'],'maxSteps':settings['maxSteps'],'energy':True,'chemistry':True},
          'native reactor solver readback differs from the plan')
    temperatures = [t0]+[r[1] for r in rows]
    energy_bound = TOLERANCES['energyRelative_cpT0']*start[6]*t0+_jump(min(temperatures),max(temperatures))
    # Cantera's default reactor volume is 1 m3, so the initial mass equals the
    # independently computed initial density; every sample must keep that mass.
    mass = reactor['initial']['mass']
    check(abs(reactor['initial']['volume']-prepared['reactor']['volume_m3']) <= 1e-12 and
          abs(mass/(start[2]*prepared['reactor']['volume_m3'])-1) <= TOLERANCES['massRelative'],'initial reactor volume or mass differs')
    conductance = settings.get('thermalConductance',0)
    bath = settings.get('bathTemperature',300)
    if conductance > 0:
        wall = reactor.get('thermal')
        check(isinstance(wall,dict) and real(*wall.values()) and
              wall == {'conductance_W_K':conductance,'area_m2':1.0,
              'bathTemperature_K':bath,'emissivity':0.0,'expansionRateCoeff':0.0},
              'native thermal wall readback differs from the plan')
    else:
        check('thermal' not in reactor,'adiabatic reactor has unexpected thermal exchange')
    independent = history(prepared); trajectory = independent['trajectory']
    results = []
    for index,(time,row,sample) in enumerate(zip(times,rows,samples)):
        t,p,x,y = row[1],row[2],row[10:20],row[20:30]
        check(close_time(row[0],time) and close_time(sample['time'],time),'reactor sample time differs from the plan')
        check(300-1e-7 <= t <= 3500+1e-7 and all(0 <= v <= 1+1e-12 for v in x+y),'reactor state outside thermochemistry bounds')
        check(thermo.close(math.fsum(x),1,absolute=1e-10) and thermo.close(math.fsum(y),1,absolute=1e-10),'fractions are not normalised')
        values = thermo.properties(t,p,x)
        check(all(thermo.close(a,b) for a,b in zip(row[1:10],values)),'NASA7/ideal-gas properties differ at reactor row '+str(index))
        check(all(thermo.close(a,v*w/values[-1],absolute=1e-11) for a,v,w in zip(y,x,WEIGHTS)),'mass/mole fractions disagree')
        if index == 0 and time == 0:
            check(thermo.close(t,t0) and all(thermo.close(a,b,absolute=1e-12) for a,b in zip(x,x0)),'reactor initial state differs')
        observed = thermo.elements(x)
        element_error = max(abs(observed[e]-v) for e,v in expected_elements.items())/inventory
        check(element_error <= TOLERANCES['elementRelative'],'reactor element inventory changed')
        if model == 'constantPressure':
            check(thermo.close(p,pressure),'constant-pressure reactor changed pressure')
            energy_error = abs(row[4]-start[3])
            if not conductance: check(energy_error <= energy_bound,'adiabatic constant-pressure reactor changed specific enthalpy')
            density_error = 0.0
        else:
            density_error = abs(row[3]/start[2]-1)
            check(density_error <= TOLERANCES['densityRelative'],'constant-volume reactor changed density')
            energy_error = abs(row[5]-start[4])
            if not conductance: check(energy_error <= energy_bound,'adiabatic constant-volume reactor changed specific internal energy')
        heat_input = 0.0
        if conductance > 0:
            check(real(sample.get('heatRateOut_W'),sample.get('bathTemperature_K'),sample.get('expansionRate_m3_s')) and
                  thermo.close(sample['heatRateOut_W'],conductance*(t-bath),absolute=1e-7) and
                  sample['bathTemperature_K'] == bath and sample['expansionRate_m3_s'] == 0,
                  'native thermal heat-rate or reservoir readback differs')
            exact = next((v for stamp,v in trajectory if stamp == time),None)
            check(exact is not None,'independent heat balance did not reach sample time')
            heat_input = exact[-1]
            energy_error = abs(row[4 if model == 'constantPressure' else 5]-start[3 if model == 'constantPressure' else 4]-heat_input)
            thermal_bound = TOLERANCES['thermalEnergyRelative_cpT0']*start[6]*t0+_jump(min(temperatures),max(temperatures))
            check(energy_error <= thermal_bound,'reactor energy change differs from independently integrated bath heat')
        check(abs(sample['mass']/mass-1) <= TOLERANCES['massRelative'] and
              abs(sample['mass']/(row[3]*sample['volume'])-1) <= TOLERANCES['massRelative'],'reactor mass is not conserved')
        if model == 'constantVolume':
            check(abs(sample['volume']-prepared['reactor']['volume_m3']) <= 1e-12,'constant-volume reactor changed volume')
        concentrations = [p/(R*t)*v for v in x]
        independent_rates,scale = production(t,concentrations)
        for observed_rates in [sample['rates']]+([reopened[index]] if reopened is not None else []):
            check(len(observed_rates) == N and all(abs(a-b) <= TOLERANCES['rateRelative_grossRate']*scale+1e-300
                  for a,b in zip(observed_rates,independent_rates)),'native net production rates differ from independent kinetics')
        low,high = time*(1-SHIFT),time*(1+SHIFT)
        window = [(v[0],_moles(v[1:N+1])) for s,v in trajectory if low <= s <= high]
        check(window,'independent reactor history did not reach a sample window')
        deviation = _outside(t,[w[0] for w in window],TOLERANCES['temperature_K'])
        for k in range(N):
            deviation_x = _outside(x[k],[w[1][k] for w in window],TOLERANCES['moleFraction'])
            check(deviation_x == 0,'reactor composition differs from independent kinetics near t='+repr(time))
        check(deviation == 0,'reactor temperature differs from independent kinetics near t='+repr(time))
        results.append({'row':index,'elementError_relative':element_error,'energyError_J_kg':energy_error,
                        'densityError_relative':density_error,**({} if not conductance else {'independentHeatInput_J_kg':heat_input,'nativeHeatRateOut_W':sample['heatRateOut_W']})})
    threshold = t0+settings['ignitionTemperatureRise']
    steps = reactor['steps']
    check(isinstance(steps,list) and len(steps) >= 2 and steps[0] == [0.0,t0] and
          all(b[0] > a[0] for a,b in zip(steps,steps[1:])) and steps[-1][0] >= times[-1],'invalid native integrator step record')
    delay = crossing([tuple(s) for s in steps],threshold,times[-1])
    reference = independent['ignition']
    if delay is None or reference is None:
        check(delay == reference or (delay or reference) >= times[-1]*(1-SHIFT),'ignition delay differs from independent kinetics')
    else:
        check(abs(delay/reference-1) <= TOLERANCES['ignitionDelayRelative'],'ignition delay differs from independent kinetics')
    final = rows[-1]
    return results,{'criterion':'first time T >= initial T + ignitionTemperatureRise, linear in time between consecutive native integrator steps',
                    'interpretation':'Temperature-rise crossing; external bath heating can trigger it even for inert gas, so it does not by itself prove chemical ignition.',
                    'rise_K':settings['ignitionTemperatureRise'],'threshold_K':threshold,'delay_s':delay},{
        'finalEquilibriumResidual_RT':_equilibrium(final[1],final[2],final[10:20],x0),
        'independentIgnitionDelay_s':reference}


def real(*values):
    """True when every value is a finite int or float; bool is rejected."""
    return all(type(v) in (int,float) and math.isfinite(v) for v in values)


def _vector(values):
    return isinstance(values,list) and len(values) == N and real(*values)


def close_time(a,b):
    return type(a) in (int,float) and math.isfinite(a) and abs(a-b) <= 1e-12*max(abs(b),1e-300)


def _outside(value,window,absolute):
    """Distance of value outside the independent window envelope widened by absolute."""
    low,high = min(window)-absolute,max(window)+absolute
    return max(0.0,low-value,value-high)
