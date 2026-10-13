"""Isolated Cantera worker; authored input never supplies executable code."""
import csv
import hashlib
import json
import os
from pathlib import Path
import sys


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
    def row(initial):
        return [initial,gas.T,gas.P,gas.density,gas.enthalpy_mass,gas.int_energy_mass,
                gas.entropy_mass,gas.cp_mass,gas.cv_mass,gas.mean_molecular_weight]+gas.X.tolist()+gas.Y.tolist()
    rows = []
    if stage == 'build':
        composition = {c['species']:c['amount'] for c in options['composition']}
        scale = max(composition.values())
        composition = {name:amount/scale for name,amount in composition.items()}
        for t in settings['temperatures']:
            if options['basis'] == 'mole': gas.TPX = t,options['pressure'],composition
            else: gas.TPY = t,options['pressure'],composition
            if operation['filter'] == 'equilibrate':
                gas.equilibrate(settings['mode'],solver='element_potential',rtol=1e-10,max_steps=2000,max_iter=200,log_level=0)
            rows.append(row(t))
    elif stage == 'reopen':
        with (directory/'results.csv').open(newline='') as stream:
            reader = csv.reader(stream); next(reader)
            for values in reader:
                saved = list(map(float,values))
                gas.TPX = saved[1],saved[2],saved[10:20]
                rows.append(row(saved[0]))
    else:
        raise ValueError('unknown native stage')
    receipt = {'stage':stage,'pid':os.getpid(),'plan':prepared,'rows':rows,
               'mechanismSHA256':hashlib.sha256(mechanism.read_bytes()).hexdigest(),
               'species':gas.species_names,'phase':gas.name,
               'runtime':{'name':'Cantera','version':ct.__version__,'executable':sys.executable}}
    (directory/('built.json' if stage == 'build' else 'reopened.json')).write_text(json.dumps(receipt,indent=2,allow_nan=False))


if __name__ == '__main__':
    directory, stage = Path(sys.argv[1]),sys.argv[2]
    try:
        main(directory,stage)
    except Exception as error:
        (directory/'native-fault.json').write_text(json.dumps({'code':'NATIVE_EXECUTION_FAILED','message':str(error)}))
        raise
