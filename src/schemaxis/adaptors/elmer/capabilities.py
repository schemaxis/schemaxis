"""Curated discovery language for Elmer solid conduction."""
import json
from importlib.resources import files

def catalogue():
    return {'application':{'label':'Elmer FEM','purpose':'Evaluate steady solid thermal conduction and insulation with layered materials, sources and independently verified native temperatures.','keywords':['finite element thermal analysis','FEM','solid heat transfer']},
        'requirements':['Configure stable ElmerSolver; no GUI, Gmsh, native Python imports or fluid solver is needed.','Use kelvin and SI layer/source/film values. Perfect contact and constant area only.','Optional limits gate sampled native temperatures and derived flux; retain thermal-summary.json for heat-balance interpretation.'],
        'references':['docs/elmer.md'],'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'operations':{'steadyHeat':{'purpose':'Predict steady solid wall temperature, heater rise and heat loss through ordered material layers with fixed temperature, outward flux or convection films.',
        'keywords':['Fourier','thermal resistance','insulation','heat loss','volumetric heater','steady heat','conductivity','Elmer HeatSolver','solid conduction'],
        'semantics':['Linear nodal finite elements are checked against exact layered conduction and source-corrected conservation.','Heat flux is outward at boundaries and along +x in the derived element table; temperatures use kelvin.','One-dimensional constant-property solid model only; independent saved-result reopening is mandatory.'],
        'examples':[{'reference':'examples/schemaxis/elmer-composite.json','purpose':'Evaluate series thermal resistance and insulation.'},{'reference':'examples/schemaxis/elmer-source.json','purpose':'Check heater peak temperature and generation balance.'}]}}}
