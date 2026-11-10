"""Structural task discovery; declarations remain the executable authority."""
import json
from pathlib import Path


def catalogue():
    return {'application':{'label':'OpenSees','purpose':'Assess elastic planar pin-jointed structural networks from geometry, restraints, material stiffness and loads.','keywords':['OpenSeesPy','CAE','structural engineering','finite element','FEA','truss','pin joint','axial']},
        'groups':{'structures':{'label':'Planar structures','purpose':'Assess small-deformation axial networks.','domain':'mechanics'}},
        'requirements':['Isolated Python with stable OpenSeesPy3.8.0.0 / OpenSees3.8.0.','Use metres, newtons, square metres and pascals; provide a stable small-strain planar pin-jointed network.'],
        'references':['docs/opensees.md','src/schemaxis/adaptors/opensees/readiness.json'],
        'searchCases':json.loads(Path(__file__).with_name('search-cases.json').read_text()),
        'operations':{'trussStatic':{'groups':['structures'],'purpose':'Assess linear elastic planar truss networks: signed axial force and stress, deflection, support reactions and named serviceability limits.','keywords':['truss','pin joint','axial','tension','compression','deflection','displacement','reaction','stress','serviceability','OpenSeesPy'],
            'semantics':['Nodes carry geometry and independent Cartesian restraints; members carry E and area, allowing redundant and mixed-stiffness structures.', 'Host direct stiffness checks stability before execution and independently verifies all native displacements, axial responses and reactions.', 'Fresh-process reconstruction reads the retained model; this is not a native database persistence claim.'],
            'examples':[{'reference':'examples/schemaxis/opensees-triangle.json','purpose':'Triangular pin/roller truss with literal hand-calculation witnesses.'},{'reference':'examples/schemaxis/opensees-redundant.json','purpose':'Redundant mixed-stiffness network.'},{'reference':'examples/schemaxis/opensees-reverse.json','purpose':'Signed uplift and lateral load.'}]}}}
