# Copyright (C) 2026 David L F Gaden
"""Domain intent, physical scope and measured acceptance for elastic beams."""
def catalogue():
    return {'groups':{'elasticity':{'label':'Elastic cantilevers','purpose':'Assess a bounded rectangular cantilever against explicit serviceability limits.','domain':'mechanics'}},
            'requirements':['Stable CalculiX 2.23 CLI; SI metres, newtons and pascals throughout.',
                            'Slenderness 20..40, section aspect 0.5..2, isotropic Poisson ratio 0..0.35 and small deformation/strain.',
                            'Separate axial and transverse refinement, force/moment balance and independent beam-theory checks must pass.'],
            'references':['docs/calculix.md','src/schemaxis/adaptors/calculix/readiness.json'],
            'operations':{'cantileverBeam':{'groups':['elasticity'],'purpose':'Derive a quadratic solid mesh from beam/material/load intent, solve and independently assess deflection, equilibrium and interior normal stress.',
                'keywords':['cantilever','elastic','mesh convergence','deflection','reaction','stress'],
                'semantics':['A fully fixed clamp at x = 0 and consistent quadratic end-face shear loading model a rectangular elastic cantilever.',
                             'Native area-mean tip displacement, actual root reactions and Gauss stress samples are measured; requirements can reject otherwise numerically valid solves.',
                             'A fresh native process reopens the exact retained editable fine deck. No general imported deck or surface/root peak-stress certification.'],
                'examples':[{'reference':'examples/schemaxis/calculix-beam.json','purpose':'Steel beam with deflection and interior sampled stress limits.'},
                            {'reference':'examples/schemaxis/calculix-beam-material.json','purpose':'Change elastic stiffness and measure the resulting compliance.'}]}}}
