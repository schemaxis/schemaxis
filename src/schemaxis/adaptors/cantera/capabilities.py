"""Selection guidance for the bounded Cantera thermochemistry and reactor route."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'Cantera',
                'purpose': 'Compute ideal-gas hydrogen/oxygen thermodynamic tables, TP/HP chemical equilibrium and closed adiabatic reactor ignition histories with the h2o2 mechanism, independently verified on the host.',
                'keywords': ['chemical kinetics', 'combustion chemistry', 'thermochemistry', 'equilibrium', 'hydrogen combustion']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':[
        'Use one gas source and one thermoSweep, equilibrate or reactorHistory node; output selects its numeric table.',
        'Temperature is K, pressure is Pa and reactor time is s. Gas composition amounts use an explicit mole or mass basis and are normalised.',
        'Only the qualified h2o2.yaml ideal-gas ohmech phase and its 29 reactions: ten species, inert N2 and Ar, no carbon or NOx.',
        'Retain chemistry-summary.json with results.csv; it records mechanism identity, reactor model, ignition criterion and interpretation limits.'],
        'references':['docs/cantera.md','src/schemaxis/adaptors/cantera/readiness.json'],
        'operations':{
            'gas':{'purpose':'Declare a supported hydrogen/oxygen/inert gas composition and pressure with explicit mole or mass basis.',
                   'keywords':['gas mixture', 'initial composition', 'mole fraction', 'mass fraction', 'fuel air mixture'],
                   'semantics':['Each species appears once with a nonnegative amount; total must be positive.',
                                'Amounts need not sum to one. Supported species are H2,H,O,O2,OH,H2O,HO2,H2O2,AR,N2.']},
            'thermoSweep':{'purpose':'Evaluate frozen-composition ideal-gas properties across independent temperatures.',
                           'keywords':['frozen composition', 'property table', 'heat capacity', 'specific heat', 'enthalpy', 'NASA polynomials'],
                           'semantics':['Composition and pressure stay fixed; no reaction equilibrium or time integration occurs.',
                                        'Each temperature is 300–3500 K; keep numeric output column units when handing data to Calc.'],
                           'examples':[{'reference':'examples/schemaxis/cantera-minimal.json','purpose':'Verify monatomic argon heat capacity and density analytically.'}]},
            'equilibrate':{'purpose':'Compute TP or adiabatic HP chemical equilibrium for each initial temperature.',
                           'keywords':['chemical equilibrium', 'equilibrium composition', 'adiabatic flame temperature', 'dissociation', 'Gibbs minimisation'],
                           'related':['reactorHistory'],
                           'semantics':['TP holds temperature and pressure; HP holds initial specific enthalpy and pressure and solves final temperature.',
                                        'Rows are independent starting states, not a transient trajectory. Initial and final temperatures must stay in 300–3500 K.',
                                        'Independent verification checks element inventories, NASA7 properties and all accessible species chemical potentials.'],
                           'examples':[{'reference':'examples/schemaxis/cantera-equilibrium.json','purpose':'Inspect temperature-dependent hydrogen/oxygen equilibrium.'},
                                       {'reference':'examples/schemaxis/cantera-adiabatic.json','purpose':'Inspect adiabatic equilibrium temperatures for hydrogen/air.'}]},
            'reactorHistory':{'purpose':'Integrate a closed adiabatic constant-pressure or constant-volume ideal-gas reactor in time and sample its state, with an explicit temperature-rise ignition delay.',
                              'keywords':['ignition delay', 'autoignition', 'time history', 'reaction kinetics', 'batch reactor',
                                          'zero-dimensional reactor', '0D reactor', 'homogeneous reactor', 'ReactorNet', 'induction time'],
                              'related':['equilibrate'],
                              'semantics':['constantPressure uses IdealGasConstPressureReactor (enthalpy conserved); constantVolume uses IdealGasReactor (internal energy and density conserved).',
                                           'times lists 2–100 strictly increasing sample times, each in seconds between 0 and 1. relativeTolerance (1e-12–1e-8), absoluteTolerance (1e-20–1e-12) and maxSteps are assigned to ReactorNet and read back.',
                                           'Ignition delay is the first time T reaches the initial T plus ignitionTemperatureRise, linear between native integrator steps; null if not reached by the last sample.',
                                           'Host Python integrates the same 29 reactions independently; samples must agree within a 1% time window and the delay within 1%. Long histories approach equilibrium.'],
                              'examples':[{'reference':'examples/schemaxis/cantera-reactor.json','purpose':'Stoichiometric hydrogen/air at 1000 K and 1 atm ignites after about 0.31 ms at constant pressure.'}]}}}
