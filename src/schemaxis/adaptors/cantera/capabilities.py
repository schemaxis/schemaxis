"""Selection guidance for the bounded Cantera thermochemistry route."""


def catalogue():
    return {'requirements':[
        'Use one gas source and one thermoSweep/equilibrate node; output selects its numeric table.',
        'Temperature is K, pressure is Pa. Gas composition amounts use an explicit mole or mass basis and are normalised.',
        'Only the qualified h2o2.yaml ideal-gas ohmech phase: ten species, inert N2 and Ar, no carbon or NOx.',
        'Retain chemistry-summary.json with results.csv; it records mechanism identity and interpretation limits.'],
        'references':['docs/cantera.md','src/schemaxis/adaptors/cantera/readiness.json'],
        'operations':{
            'gas':{'purpose':'Declare a supported hydrogen/oxygen/inert gas composition and pressure with explicit mole or mass basis.',
                   'semantics':['Each species appears once with a nonnegative amount; total must be positive.',
                                'Amounts need not sum to one. Supported species are H2,H,O,O2,OH,H2O,HO2,H2O2,AR,N2.']},
            'thermoSweep':{'purpose':'Evaluate frozen-composition ideal-gas properties across independent temperatures.',
                           'semantics':['Composition and pressure stay fixed; no reaction equilibrium or time integration occurs.',
                                        'Each temperature is 300–3500 K; keep numeric output column units when handing data to Calc.'],
                           'examples':[{'reference':'examples/schemaxis/cantera-minimal.json','purpose':'Verify monatomic argon heat capacity and density analytically.'}]},
            'equilibrate':{'purpose':'Compute TP or adiabatic HP chemical equilibrium for each initial temperature.',
                           'semantics':['TP holds temperature and pressure; HP holds initial specific enthalpy and pressure and solves final temperature.',
                                        'Rows are independent starting states, not a transient trajectory. Initial and final temperatures must stay in 300–3500 K.',
                                        'Independent verification checks element inventories, NASA7 properties and all accessible species chemical potentials.'],
                           'examples':[{'reference':'examples/schemaxis/cantera-equilibrium.json','purpose':'Inspect temperature-dependent hydrogen/oxygen equilibrium.'},
                                       {'reference':'examples/schemaxis/cantera-adiabatic.json','purpose':'Inspect adiabatic equilibrium temperatures for hydrogen/air.'}]}}}
