# Copyright (C) 2026 David L F Gaden
"""Curated navigation and authored examples; executable contracts stay in adaptor.py."""
import json
from importlib.resources import files


def catalogue():
    bracket = {'reference': 'examples/schemaxis/freecad-bracket.json',
               'purpose': 'Boolean bracket with drilled holes; repository example.'}
    box = {'version': 'schemaxis.freecad/1', 'units': 'mm',
           'nodes': [{'id': 'body', 'filter': 'box', 'options': {'length': 20, 'width': 10, 'height': 5}}],
           'output': 'body'}
    extrusion = {'version': 'schemaxis.freecad/1', 'units': 'mm', 'nodes': [
        {'id': 'profile', 'filter': 'rectangle', 'options': {'width': 20, 'height': 10}},
        {'id': 'body', 'filter': 'extrude', 'inputs': {'profile': 'profile'}, 'options': {'length': 5}}],
        'output': 'body'}
    result = {
        'application': {'label':'FreeCAD','purpose':'Build editable parametric parts with constrained sketches, Body/Pad/Pocket history, persistent named length drivers, solid operations and verified geometry exports; import a supplier or vendor STEP part with declared units, orientation, placement and checked facts; assemble shared primitive parts or verified modelled parts at named mounts with fixed native joints.', 'keywords':['computer aided design','CAD','FreeCAD','parametric parts','native length drivers','mechanical parts','sketch to solid','feature history','rigid assembly','named mounts','fixed joints','rigid assembly of modelled parts at named mounts','checked STEP import','supplier STEP part','vendor STEP part','vendor part']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'groups': {
            'solids': {'label': 'Solid primitives', 'purpose': 'Construct dimensioned solid geometry.', 'domain': 'geometry'},
            'profiles': {'label': 'Profiles and extrusion', 'purpose': 'Construct closed profiles and extend them into solids.', 'domain': 'geometry'},
            'partdesign': {'label':'Sketch-based mechanical parts','purpose':'Keep a constrained sketch and additive/subtractive feature history in one Body.','domain':'geometry'},
            'booleans': {'label': 'Boolean solids', 'purpose': 'Subtract or unite existing solid geometry.', 'domain': 'geometry'},
            'import': {'label': 'Checked external parts', 'purpose': 'Bring external STEP solids in with declared units, orientation, placement and checked facts.', 'domain': 'geometry'}},
        'requirements': [
            'Lengths use millimetres. Authored document references resolve before literal option validation.',
            'Inputs reference earlier nodes of the declared kind; select a solid output.',
            'Run requires one valid positive-volume output solid. Native geometry can fail after host planning.',
            'Optional named measurements publish volume, surface area, extents, uniform-density centre, bounds and selected-edge aggregates as verified values with explicit units; see docs/freecad-measurements.md.',
            'Optional batch designStudy brackets one CAD length to reach a named scalar measurement target with explicit units, tolerance, response direction and finite limits. It changes one resolved option; native links recompute. See docs/freecad-design-studies.md.',
            'Optional parameters and node-local drive preserve affine length relationships in a native VarSet for primitive, extrusion, sketch and Pad dimensions. Batch variants only; live editing and designStudy explicitly reject this contract. See docs/freecad-parameters.md.',
            'Native output includes FCStd, STEP and tessellated STL; verify reopens artifacts and checks geometry.'],
        'references': ['docs/cad-and-mesh-workflows.md', 'docs/generated/freecad-operations.md',
                       'src/schemaxis/adaptors/freecad/operations.py:validate',
                       'src/schemaxis/adaptors/freecad/adaptor.py:plan'],
        'operations': {
            'box': {'purpose': 'Create a rectangular solid from length, width and height in mm.',
                    'groups': ['solids'], 'keywords': ['block', 'cuboid', 'dimensions'],
                    'related': ['rectangle', 'extrude', 'cut'],
                    'examples': [{'purpose': 'A 1000 cubic millimetre box.', 'document': box}]},
            'cylinder': {'purpose': 'Create a cylinder with radius, height, origin and axis.',
                         'groups': ['solids'], 'keywords': ['drill', 'hole', 'round'], 'related': ['cut'],
                         'semantics': ['The axis must be nonzero.'], 'examples': [bracket]},
            'rectangle': {'purpose': 'Create a fully constrained rectangular sketch, optionally owned by a Body on its origin XY plane.',
                          'groups': ['profiles'], 'related': ['extrude'],
                          'semantics': ['A profile cannot be the final solid output.'],
                          'examples': [{'purpose': 'Extrude a rectangular profile.', 'document': extrusion}]},
            'circle': {'purpose': 'Create a fully constrained circular sketch with radius and optional offset centre; optionally own it in a Body.',
                       'groups': ['profiles'], 'related': ['extrude'],
                       'semantics': ['A profile cannot be the final solid output.']},
            'extrude': {'purpose': 'Extend a closed profile into a solid along a direction.',
                        'groups': ['profiles', 'solids'], 'keywords': ['extrusion', 'extend', 'length'],
                        'related': ['rectangle', 'circle'], 'semantics': ['The extrusion direction must be nonzero.'],
                        'examples': [{'purpose': 'Extrude a rectangular profile.', 'document': extrusion}]},
            'cut': {'purpose': 'Subtract a tool solid from a base solid.', 'groups': ['booleans'],
                    'keywords': ['subtract', 'hole', 'drill'], 'related': ['box', 'cylinder', 'fuse'],
                    'examples': [bracket]},
            'fuse': {'purpose': 'Unite two solids; the final output must remain one solid.',
                     'groups': ['booleans'], 'keywords': ['union', 'join'], 'related': ['cut'], 'examples': [bracket]}}}

    additions = {
        'sphere': ('Create a sphere with a radius and origin in millimetres.', 'A primitive solid; the final selected output must remain one valid positive-volume solid.'),
        'cone': ('Create an axial tapered solid with two radii and a height.', 'The second radius may be zero for a pointed cone; the axis must be nonzero.'),
        'torus': ('Create a ring solid from major and minor radii.', 'The minor radius must be smaller than the major radius; a self-intersecting ring is unsupported.'),
        'common': ('Retain the intersecting volume of two solids.', 'Disjoint operands cannot produce the required positive-volume final solid.'),
        'polygon': ('Create a closed planar profile from ordered two-dimensional vertices.', 'Closure is automatic. Repeated vertices, zero area and self-intersection are rejected.'),
        'revolve': ('Revolve a planar profile about an axis to form a solid.', 'Angles are degrees up to 360. Axis and profile placement determine native geometric validity.'),
        'fillet': ('Round edges selected by geometric intent or explicit indices.', 'edges accepts one-based indices or a where/expect selector over straight/circular curves, direction, plane and length. Every native application resolves predicates again; exact cardinality is required. See docs/freecad-selections.md.'),
        'chamfer': ('Bevel edges selected by geometric intent or explicit indices.', 'Geometric selectors reject missing or ambiguous matches. Explicit indices remain topology-dependent; oversized or intersecting chamfers can fail native checks.'),
        'readSTEP': ('Import a STEP solid for further declared CAD operations.', 'The input is captured and hashed, and saved verification uses the retained copy. FreeCAD applies the unit the file assigns (millimetres when none is assigned); use importSTEP for declared units, orientation and checked facts.'),
        'loft': ('Build a solid through an ordered list of closed profiles.', 'Provide 2–32 distinct earlier profile nodes; section order matters. Native compatibility still needs verification.'),
        'multiFuse': ('Unite a list of existing solids with optional refinement.', 'Provide 2–32 distinct earlier solid nodes. The final union must still be one valid solid.')}
    result['operations'].update({name: {'purpose': purpose, 'semantics': [semantics]}
                                 for name, (purpose, semantics) in additions.items()})
    result['operations'].update({
        'body': {'purpose':'Create the native PartDesign container for one mechanical part and its feature history.', 'groups':['partdesign'], 'semantics':['A Body is a container, not a solid output. This slice supports one Body at the world origin, one first Pad and a linear Pocket chain.'], 'related':['rectangle','circle','pad','pocket']},
        'pad': {'purpose':'Turn an owned constrained sketch into the first solid of its Body, extruded along +Z.', 'groups':['partdesign'], 'semantics':['Requires an earlier Body and a profile owned by that Body. The first Pad has no native BaseFeature; length may use a persistent driver.'], 'related':['body','rectangle','circle','pocket']},
        'pocket': {'purpose':'Cut a through hole from the current Body tip using an unused sketch in the same Body.', 'groups':['partdesign'], 'semantics':['The XY sketch cuts along +Z through all stock. Fixed depth and other side modes are unsupported. Select the final solid tip as output.'], 'related':['body','pad','circle']}})
    result['operations']['importSTEP'] = {
        'purpose': 'Bring one external STEP solid into the model with its declared unit, axis orientation and placement, checked against facts you know from its drawing, with optional parametric face refinement.',
        'groups': ['import'],
        'semantics': ['units must equal the length unit the file assigns (mm, cm, m or inch); it never rescales. Expectations are in the part frame (after units and orientation, before placement) and need volume plus a centre of mass or inside and outside points; they check declared facts only, not identity of symmetric parts.',
                      'Planning reads at most 32 MiB, 100000 entities and 2000 oriented edges per loop and refuses assemblies, transformed or unreferenced representations, several solids and presentation records. The run keeps a byte-identical copy; saved verification never reopens the original.',
                      'The import is a static solid without sketches or feature history; its placement and an optional Part::Refine output stay editable. See docs/freecad.md.'],
        'related': ['readSTEP', 'cut', 'fillet'],
        'examples': [{'reference': 'examples/schemaxis/freecad-import-step.json', 'purpose': 'Inch, Y-up supplier bracket checked by volume, centre and points, refined, placed and drilled.'},
                     {'reference': 'examples/schemaxis/freecad-import-step-variant.json', 'purpose': 'A revised supplier file with deliberately updated expectations.'}]}
    for operation in ('body','pad','pocket'):
        result['operations'][operation]['examples']=[{'reference':'examples/schemaxis/freecad-part-design.json','purpose':'Constrained sketch, Pad and offset through-hole with persistent dimensions.'}]
    terms = {
        'body':['mechanical part','feature history','PartDesign Body','sketch based modelling'],
        'pad':['sketch to solid','add thickness','PartDesign Pad','native length driver'],
        'pocket':['through hole','through all','remove material','PartDesign Pocket'],
        'box':['block','cuboid','stock blank','plate','native length driver','Part::Box'],
        'cylinder':['circular cylinder','drill tool','bore','native length driver','Part::Cylinder'],
        'extrude':['extrusion','extend profile','native length driver','Part::Extrusion'],
        'rectangle':['rectangular profile','centred sketch','Sketcher rectangle'],
        'circle':['circular profile','sketch radius'], 'cut':['subtract','difference','drill hole'],
        'fuse':['union','join solids','boolean fuse'], 'sphere':['ball','spherical solid','Part::Sphere'],
        'cone':['taper','conical solid','frustum'], 'torus':['ring solid','doughnut','major radius'],
        'common':['intersection','overlap volume','boolean common'],
        'polygon':['closed profile','polygon vertices','planar wire'],
        'revolve':['revolution','lathe','axisymmetric solid'],
        'fillet':['round edges','edge radius','rounded corners'],
        'chamfer':['bevel edges','edge chamfer'], 'readSTEP':['STEP import','ISO 10303','read solid'],
        'importSTEP':['supplier part','supplier STEP part','vendor part','vendor STEP part','checked STEP import','STEP units','Y-up STEP','refine faces','Part::Refine'],
        'loft':['section transition','loft profiles','ruled loft'],
        'multiFuse':['multi union','join many solids','multiple fuse']}
    for operation, keywords in terms.items(): result['operations'][operation]['keywords']=keywords
    for operation in ('box','cylinder','extrude'):
        result['operations'][operation].setdefault('semantics',[]).append('Declare a native length driver through parameters and drive to retain an affine relationship in FCStd; omit the corresponding literal option. Batch parts only.')
        result['operations'][operation].setdefault('examples',[]).append({'reference':'examples/schemaxis/freecad-parameters-extrude.json' if operation=='extrude' else 'examples/schemaxis/freecad-parameters.json','purpose':'Persist a named length relationship and edit it after native reopening.'})
    result['references'].append('docs/freecad-part-design.md')
    result['references'].extend(['src/schemaxis/adaptors/freecad/readiness.json','docs/freecad-parameters.md','docs/freecad.md'])
    return result
