# Copyright (C) 2026 David L F Gaden
"""Selection guidance; executable schemas and the delivery bundle remain normative."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'Gmsh',
                'purpose': 'Construct a box, cylinder, hollow cylinder or sphere, or import one CAD solid and generate a verified first-order tetrahedral volume mesh in millimetres, with physical volume and boundary names including separately named planar faces and cylindrical bore and shaft walls.',
                'keywords': ['CAD meshing', 'finite element pre-processing', 'Gmsh', 'MSH', 'VTU']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':[
        'Use explicit mm units; STEP geometry is normalised to mm by the native importer.',
        'Select one source and one tetrahedral node. Names identify the whole volume, optional disjoint planar faces, optional whole analytic cylindrical walls with a stated material side, and the remaining boundary (which may be empty when named groups cover everything).',
        'cylinderGroups select whole typed analytic cylinders on a world axis by axis, axis point, radius and inner/outer side; the host independently re-proves membership, side and chord deviation from mesh coordinates. Read cadSurfaces in mesh-summary.json to discover a STEP part\'s planes and cylinders.',
        'nearBoundaries expresses local size and transition distance using declared boundary names; overlapping sizing effects take the smaller size.',
        'Optional top-level refinement selects the first tested mesh satisfying declared global or boundary edge lengths, cylinder chord deviation, minimum mean ratio and/or volume error, within bounded iterations and cell acceptance budget.',
        'Read study.html for acceptance checks and stopping reasons. Smaller elements do not guarantee better shape quality or solver convergence.',
        'Inspect CAD/mesh volume error, closed boundary and positive cell volumes before using the mesh. No solver or boundary conditions are supplied.'],
        'references':['docs/gmsh.md','src/schemaxis/adaptors/gmsh/readiness.json'],
        'operations':{
            'cylinder':{'purpose':'Construct a full right circular cylinder in millimetres for a verified rod or cylindrical specimen mesh.',
                'keywords':['rod','round bar','cylindrical specimen','gmsh.model.occ.addCylinder'],
                'semantics':['origin is the starting cap centre; axis selects positive x/y/z; radius and height are mm. Circular cap groups need an explicit areaTolerance.'],
                'examples':[{'reference':'examples/schemaxis/gmsh-cylinder.json','purpose':'Mesh a translated cylinder with named circular end caps and a measured area-loss budget.'}]},
            'hollowCylinder':{'purpose':'Construct one annular cylindrical solid with a coaxial through bore for a verified tube or sleeve mesh.',
                'keywords':['tube','sleeve','annulus','hollow cylinder','through bore','gmsh.model.occ.cut'],
                'semantics':['Subtract a complete inner cylinder; radius minus innerRadius must be at least 0.001 mm. This is a bounded single-solid CSG operation, not a general boolean tree.'],
                'examples':[{'reference':'examples/schemaxis/gmsh-hollow-cylinder.json','purpose':'Mesh a bored sleeve with HXT and independently checked annular caps.'}]},
            'sphere':{'purpose':'Construct a complete spherical solid in millimetres for a verified ball or curved-boundary mesh.',
                'keywords':['ball','spherical specimen','make sphere','gmsh.model.occ.addSphere'],
                'semantics':['centre is the ball centre, radius is positive mm; no spherical sectors, shells or planar cap groups.'],
                'examples':[{'reference':'examples/schemaxis/gmsh-sphere.json','purpose':'Mesh a translated ball and compare volume against 4*pi*r^3/3.'}]},
            'box':{'purpose':'Construct an axis-aligned rectangular solid in millimetres for meshing.',
                   'keywords': ['cuboid', 'rectangular prism', 'make box', 'gmsh.model.occ.addBox'],
                   'semantics':['size contains positive x/y/z extents; origin is the minimum corner.'],
                   'examples':[{'reference':'examples/schemaxis/gmsh-minimal.json','purpose':'Mesh a 10 mm cube and independently verify its 1000 mm^3 volume.'}]},
            'readSTEP':{'purpose':'Import one CAD solid from a captured single-file STEP document and normalise its length units to mm.',
                        'keywords': ['import cad', 'STEP', 'STP', 'OpenCASCADE', 'gmsh.model.occ.importShapes'],
                        'semantics':['Absolute .step/.stp path, at most 16 MiB; execution rejects multi-solid input. Feature history and original labels are lost.']},
            'tetrahedral':{'purpose':'Mesh the earlier solid with first-order tetrahedra and declared physical volume/boundary names.',
                           'keywords': ['tetrahedralise', 'volume mesh', 'tet mesh', 'generate tetrahedra', 'physical groups', 'finite element mesh', 'FEM', 'bore wall', 'hole wall', 'shaft surface', 'cylindrical wall', 'named cylinder', 'chord deviation', 'HXT', 'Delaunay', 'mesh optimisation', 'gmsh.model.mesh.generate'],
                           'semantics':['faceGroups selects whole axis-aligned faces by name, axis, coordinate and tolerance in mm; names are unique, selections disjoint and a nonempty remainder is required.',
                                        'size is a target edge length in mm, not a guarantee of element count or quality.',
                                        'nearBoundaries entries contain boundary, size and distance in mm. Local size must not exceed the global size. Refinement scales local sizes with the global size while keeping transition distances fixed.',
                                        'algorithm selects Delaunay or HXT; optimise controls the Mesh.Optimize option and both are read back. Quality remains measured, not guaranteed.',
                                        'areaTolerance separately bounds selected cap area loss; the default 1e-10 remains strict for polygon faces. Circular caps require an explicit bounded area budget.',
                                        'volumeTolerance bounds relative volume difference from CAD (maximum 2%); refine size if it fails.',
                                        'cylinderGroups (up to 12 together with faceGroups) name whole analytic cylindrical faces by name, axis, axis point in mm, radius in mm and side inner (bore) or outer (shaft or tube exterior); only world-axis cylinders are selectable and the remainder may be empty when they cover the boundary.',
                                        'refinement boundaryMaximumChordDeviation bounds, per cylinder wall, the largest gap in mm between the true cylinder and its flat facets, measured from mesh coordinates.',
                                        'MSH keeps names. The separate VTU volume/boundary files preserve numeric physicalTag; retain mesh-summary.json for names and units.']}}}
