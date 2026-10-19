"""Host-safe dimensional part discovery; no native import."""
import json
from importlib.resources import files


def catalogue():
    return {'application':{'label':'OpenSCAD','purpose':'Construct dimensioned mounting plates and annular spacers with independently verified polygon geometry.','keywords':['OpenSCAD','constructive CAD','CSG','STL','millimetre','parametric part']},
      'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
      'requirements':['Stable OpenSCAD 2021.01 in a separate POSIX process; explicit millimetre dimensions and bounded polygon resolution.','Only plate and spacer recipes; no authored SCAD, libraries, scripts or arbitrary constructive trees.'],
      'references':['docs/openscad.md','src/schemaxis/adaptors/openscad/readiness.json'],
      'operations':{
       'plate':{'purpose':'Construct a rectangular mounting plate with positioned circular through-holes and checked wall clearance.','keywords':['mounting plate','drilled plate','through-hole','bolt holes','rectangular slab','constructive CAD','STL','CSG'],'semantics':['Dimensions and XY hole centres are mm; all holes traverse the complete height.','Circular holes are inscribed regular polygons; nominal circles remain at least 0.5 mm apart and inside the plate.'],'examples':[{'reference':'examples/schemaxis/openscad-plate.json','purpose':'Make a 40 by 30 by 3 mm plate with two unequal bores.'}]},
       'spacer':{'purpose':'Construct a concentric annular spacer or sleeve from outer diameter, bore diameter and height.','keywords':['annular spacer','sleeve','washer','bore','bushing','constructive CAD','STL','CSG'],'semantics':['Dimensions are mm, centred on XY origin and extending upwards from Z=0.','Nominal radial wall is at least 0.5 mm; across-flats bore diameter is smaller than nominal polygon vertex diameter.'],'examples':[{'reference':'examples/schemaxis/openscad-spacer.json','purpose':'Make a 20 mm outer / 8 mm bore / 10 mm high spacer.'}]}}}
