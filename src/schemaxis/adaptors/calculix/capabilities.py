# Copyright (C) 2026 David L F Gaden
"""Physical member intent; bounded breadth remains distinct from general FEA."""
import json
from pathlib import Path


def catalogue():
    return {
        'application':{'label':'CalculiX','purpose':'Assess linear elastic rectangular members under six signed end resultants with independent physical checks.',
                       'keywords':['structural mechanics','finite element','FEA','elasticity','axial','bending','torsion','serviceability']},
        'groups':{'elasticity':{'label':'Elastic members','purpose':'Assess small-deformation rectangular structural members against explicit measurements.','domain':'mechanics'}},
        'requirements':['Stable CalculiX2.23 CLI; SI metres, newtons, pascals and radians.',
                        'Slenderness20..40, section aspect0.5..2, isotropic Poisson ratio0..0.35 and small deformation/strain.',
                        'Independent displacement/twist, interior normal/torsion stress, separate refinement and force/moment equilibrium checks must pass.'],
        'references':['docs/calculix.md','src/schemaxis/adaptors/calculix/readiness.json'],
        'searchCases':json.loads(Path(__file__).with_name('search-cases.json').read_text()),
        'operations':{'cantileverBeam':{
            'groups':['elasticity'],
            'purpose':'Assess combined axial, biaxial bending and torsion end resultants in a rectangular elastic member; derive quadratic meshes and measure serviceability, sampled stress and equilibrium.',
            'keywords':['cantilever','axial','tension','compression','bending','torsion','torque','end resultants','end couple','displacement','twist','reaction','stress','serviceability','mesh convergence'],
            'semantics':['Six global end resultants map to consistent quadratic face tractions; end couples are distributed force systems, not rotational solid-node constraints.',
                         'Choose a fully clamped face, or pure-axial sliding support allowing Poisson contraction. Every active translation and twist is independently checked, including cancelling loads.',
                         'Interior normal stress and antisymmetric torsion shear are compared against axial/Euler-Bernoulli/Prandtl theory. Native von Mises samples are measurements, not peak stress or yield certification.',
                         'Fresh processes reopen the exact retained editable deck; arbitrary imported decks, nonrectangular sections and general FEA remain unsupported.'],
            'examples':[{'reference':'examples/schemaxis/calculix-combined.json','purpose':'Combined six-resultant member with translation, twist and sampled equivalent-stress limits.'},
                        {'reference':'examples/schemaxis/calculix-axial-slide.json','purpose':'Compress a pure-axial member while allowing transverse Poisson contraction.'},
                        {'reference':'examples/schemaxis/calculix-torsion-wide.json','purpose':'Twist a nonsquare rectangular section and verify its warping-sensitive compliance.'},
                        {'reference':'examples/schemaxis/calculix-beam.json','purpose':'Legacy vertical bending baseline.'}]}}}
