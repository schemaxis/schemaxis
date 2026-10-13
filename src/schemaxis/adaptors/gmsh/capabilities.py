"""Selection guidance; executable schemas and the delivery bundle remain normative."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'Gmsh',
                'purpose': 'Create or import one CAD solid and generate a verified first-order tetrahedral volume mesh in millimetres, with physical volume and boundary names.',
                'keywords': ['CAD meshing', 'finite element pre-processing', 'Gmsh', 'MSH', 'VTU']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':[
        'Use explicit mm units; STEP geometry is normalised to mm by the native importer.',
        'Select one source and one tetrahedral node. Names identify the whole volume, optional disjoint planar faces and the remaining boundary.',
        'nearBoundaries expresses local size and transition distance using declared boundary names; overlapping sizing effects take the smaller size.',
        'Optional top-level refinement selects the first tested mesh satisfying declared global or boundary edge lengths, minimum mean ratio and/or volume error, within bounded iterations and cell acceptance budget.',
        'Read study.html for acceptance checks and stopping reasons. Smaller elements do not guarantee better shape quality or solver convergence.',
        'Inspect CAD/mesh volume error, closed boundary and positive cell volumes before using the mesh. No solver or boundary conditions are supplied.'],
        'references':['docs/gmsh.md','src/schemaxis/adaptors/gmsh/readiness.json'],
        'operations':{
            'box':{'purpose':'Construct an axis-aligned rectangular solid in millimetres for meshing.',
                   'keywords': ['cuboid', 'rectangular prism', 'make box', 'gmsh.model.occ.addBox'],
                   'semantics':['size contains positive x/y/z extents; origin is the minimum corner.'],
                   'examples':[{'reference':'examples/schemaxis/gmsh-minimal.json','purpose':'Mesh a 10 mm cube and independently verify its 1000 mm^3 volume.'}]},
            'readSTEP':{'purpose':'Import one CAD solid from a captured single-file STEP document and normalise its length units to mm.',
                        'keywords': ['import cad', 'STEP', 'STP', 'OpenCASCADE', 'gmsh.model.occ.importShapes'],
                        'semantics':['Absolute .step/.stp path, at most 16 MiB; execution rejects multi-solid input. Feature history and original labels are lost.']},
            'tetrahedral':{'purpose':'Mesh the earlier solid with first-order tetrahedra and declared physical volume/boundary names.',
                           'keywords': ['tetrahedralise', 'volume mesh', 'tet mesh', 'generate tetrahedra', 'physical groups', 'finite element mesh', 'FEM', 'gmsh.model.mesh.generate'],
                           'semantics':['faceGroups selects whole axis-aligned faces by name, axis, coordinate and tolerance in mm; names are unique, selections disjoint and a nonempty remainder is required.',
                                        'size is a target edge length in mm, not a guarantee of element count or quality.',
                                        'nearBoundaries entries contain boundary, size and distance in mm. Local size must not exceed the global size. Refinement scales local sizes with the global size while keeping transition distances fixed.',
                                        'volumeTolerance bounds relative volume difference from CAD (maximum 2%); refine size if it fails.',
                                        'MSH keeps names. The separate VTU volume/boundary files preserve numeric physicalTag; retain mesh-summary.json for names and units.']}}}
