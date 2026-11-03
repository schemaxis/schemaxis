# Copyright (C) 2026 David L F Gaden
"""Isolated Cantera worker; authored input never supplies executable code."""
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

REACTORS = {'constantPressure':'IdealGasConstPressureReactor','constantVolume':'IdealGasReactor'}
STEP_LIMIT = 200000


class UnsupportedState(ValueError):
    """A reactor state left the qualified NASA7 temperature range."""


def main(directory,stage):
    import cantera as ct
    if ct.__version__.split('.')[:2] != ['3','2']:
        raise ValueError('this adaptor requires qualified Cantera 3.2.x')
    prepared = json.loads((directory/'plan.json').read_text())
    source, operation = prepared['nodes']
    options, settings = source['options'], operation['options']
    mechanism = directory/'mechanism.yaml'
    if stage == 'build':
        native_source = Path(ct.__file__).parent/'data/h2o2.yaml'
        data = native_source.read_bytes()
        if hashlib.sha256(data).hexdigest() != prepared['mechanism']['sha256']:
            raise ValueError('installed h2o2.yaml differs from qualified mechanism; qualify the new data before use')
        mechanism.write_bytes(data)
    gas = ct.Solution(str(mechanism),'ohmech',transport_model=None)
    def row(first,phase=gas):
        return [first,phase.T,phase.P,phase.density,phase.enthalpy_mass,phase.int_energy_mass,
                phase.entropy_mass,phase.cp_mass,phase.cv_mass,phase.mean_molecular_weight]+phase.X.tolist()+phase.Y.tolist()
    def initial(t):
        composition = {c['species']:c['amount'] for c in options['composition']}
        scale = max(composition.values())
        composition = {name:amount/scale for name,amount in composition.items()}
        if options['basis'] == 'mole': gas.TPX = t,options['pressure'],composition
        else: gas.TPY = t,options['pressure'],composition
    rows = []; extra = {}
    if stage == 'build':
        if operation['filter'] == 'reactorHistory':
            rows, extra = reactor(ct,gas,initial,settings,row)
        else:
            for t in settings['temperatures']:
                initial(t)
                if operation['filter'] == 'equilibrate':
                    gas.equilibrate(settings['mode'],solver='element_potential',rtol=1e-10,max_steps=2000,max_iter=200,log_level=0)
                rows.append(row(t))
    elif stage == 'reopen':
        rates = []
        with (directory/'results.csv').open(newline='') as stream:
            reader = csv.reader(stream); next(reader)
            for values in reader:
                saved = list(map(float,values))
                gas.TPX = saved[1],saved[2],saved[10:20]
                rows.append(row(saved[0])); rates.append(gas.net_production_rates.tolist())
        if operation['filter'] == 'reactorHistory': extra = {'rates':rates}
    else:
        raise ValueError('unknown native stage')
    receipt = {'stage':stage,'pid':os.getpid(),'plan':prepared,'rows':rows,
               'mechanismSHA256':hashlib.sha256(mechanism.read_bytes()).hexdigest(),
               'species':gas.species_names,'phase':gas.name,
               'runtime':{'name':'Cantera','version':ct.__version__,'executable':sys.executable},**extra}
    (directory/('built.json' if stage == 'build' else 'reopened.json')).write_text(json.dumps(receipt,indent=2,allow_nan=False))


def reactor(ct,gas,initial,settings,row):
    """Sample an adiabatic closed reactor, then repeat it step by step for ignition."""
    times = settings['times']
    def network():
        initial(settings['temperature'])
        vessel = getattr(ct,REACTORS[settings['model']])(gas,clone=True,energy='on')
        net = ct.ReactorNet([vessel])
        net.rtol = settings['relativeTolerance']; net.atol = settings['absoluteTolerance']
        net.max_steps = settings['maxSteps']
        solver = {'reactorType':vessel.type,'rtol':net.rtol,'atol':net.atol,'maxSteps':net.max_steps,
                  'energy':vessel.energy_enabled,'chemistry':vessel.chemistry_enabled}
        expected = {'reactorType':REACTORS[settings['model']],'rtol':settings['relativeTolerance'],
                    'atol':settings['absoluteTolerance'],'maxSteps':settings['maxSteps'],'energy':True,'chemistry':True}
        if solver != expected:
            raise ValueError('native reactor settings readback differs: '+json.dumps(solver))
        return vessel,net,solver
    def bounded(t,temperature):
        if not 300 <= temperature <= 3500:
            raise UnsupportedState(f'reactor temperature {temperature:.6g} K at {t:.6g} s left the qualified 300-3500 K NASA7 range')
    vessel,net,solver = network(); rows = []; reactor_rows = []
    start = {'mass':vessel.mass,'volume':vessel.volume}
    for t in times:
        if t > net.time: net.advance(t)
        if abs(net.time-t) > 1e-12*max(t,1e-300):
            raise ValueError('reactor network did not stop at the requested sample time')
        phase = vessel.phase; bounded(t,phase.T)
        rows.append(row(t,phase))
        reactor_rows.append({'time':net.time,'mass':vessel.mass,'volume':vessel.volume,
                             'rates':phase.net_production_rates.tolist()})
    stats = net.solver_stats
    vessel,net,_ = network(); steps = [[net.time,vessel.phase.T]]
    while net.time < times[-1]:
        if len(steps) > STEP_LIMIT:
            raise ValueError('ignition pass exceeded the native step limit')
        net.step(); steps.append([net.time,vessel.phase.T]); bounded(net.time,vessel.phase.T)
    return rows,{'reactor':{'native':'cantera.ReactorNet','solver':solver,'initial':start,'samples':reactor_rows,
                            'solverStats':{k:int(v) for k,v in stats.items()},'steps':steps}}


if __name__ == '__main__':
    directory, stage = Path(sys.argv[1]),sys.argv[2]
    try:
        main(directory,stage)
    except Exception as error:
        code = 'UNSUPPORTED_STATE' if isinstance(error,UnsupportedState) else 'NATIVE_EXECUTION_FAILED'
        (directory/'native-fault.json').write_text(json.dumps({'code':code,'message':str(error)}))
        raise
