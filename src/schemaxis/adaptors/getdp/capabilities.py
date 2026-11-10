"""Domain intent and honest application boundaries for GetDP conduction."""
import json
from importlib.resources import files

def catalogue():
    return {'application':{'label':'GetDP','purpose':'Solve and assess layered steady heat walls or DC electrical resistors with independent exact field and energy/current conservation checks.','keywords':['GetDP','layered conduction','finite element','conductivity','Fourier','heat loss']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'groups':{'conduction':{'label':'Layered scalar conduction','purpose':'Assess steady thermal walls or electrical resistors from material and boundary intent.','domain':'engineering'}},
        'requirements':['Stable GetDP 3.5.0 executable; no Gmsh runtime required.','SI constant-area perfectly contacting layers and constant properties; serial only.'],
        'references':['docs/getdp.md','src/schemaxis/adaptors/getdp/readiness.json'],
        'operations':{op:{'groups':['conduction'],'purpose':purpose,'keywords':keywords,
            'semantics':['Generates a bounded line finite element mesh and scalar diffusion weak formulation.',
                'Native node field and element-midpoint flux are checked against independent piecewise-quadratic exact conduction and global/interface source conservation.',
                'Optional sampled field/flux limits block unmet results; generated inputs and explicit losses remain inspectable.'],
            'examples':[{'reference':example,'purpose':purpose}]} for op,purpose,keywords,example in [
            ('steadyHeat','Evaluate temperature and heat loss through a layered wall with volumetric heat and prescribed temperature, outward heat flux or convection ends.',['heat','thermal','wall','insulation','temperature','convection','Fourier','Poisson','heat loss','conductivity'],'examples/schemaxis/getdp-composite.json'),
            ('steadyCurrent','Evaluate potential and current through layered DC resistors with fixed potential or outward current density ends.',['electrical','resistor','potential','current density','Ohm','conductivity','resistance'],'examples/schemaxis/getdp-current.json')]}}
