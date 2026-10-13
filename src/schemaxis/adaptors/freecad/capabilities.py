"""Curated navigation and authored examples; executable contracts stay in adaptor.py."""


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
        'groups': {
            'solids': {'label': 'Solid primitives', 'purpose': 'Construct dimensioned solid geometry.', 'domain': 'geometry'},
            'profiles': {'label': 'Profiles and extrusion', 'purpose': 'Construct closed profiles and extend them into solids.', 'domain': 'geometry'},
            'booleans': {'label': 'Boolean solids', 'purpose': 'Subtract or unite existing solid geometry.', 'domain': 'geometry'}},
        'requirements': [
            'Lengths use millimetres. Authored document references resolve before literal option validation.',
            'Inputs reference earlier nodes of the declared kind; select a solid output.',
            'Run requires one valid positive-volume output solid. Native geometry can fail after host planning.',
            'Optional named measurements publish volume, surface area, extents, uniform-density centre, bounds and selected-edge aggregates as verified values with explicit units; see docs/freecad-measurements.md.',
            'Optional batch designStudy brackets one CAD length to reach a named scalar measurement target with explicit units, tolerance, response direction and finite limits. It changes one resolved option; native links recompute. See docs/freecad-design-studies.md.',
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
            'rectangle': {'purpose': 'Create a closed rectangular profile on XY, XZ or YZ.',
                          'groups': ['profiles'], 'related': ['extrude'],
                          'semantics': ['A profile cannot be the final solid output.'],
                          'examples': [{'purpose': 'Extrude a rectangular profile.', 'document': extrusion}]},
            'circle': {'purpose': 'Create a closed circular profile on XY, XZ or YZ.',
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
        'readSTEP': ('Import a STEP solid for further declared CAD operations.', 'The input is captured and hashed. Native solid validity is checked at execution; no automatic unit inference or multi-solid selection is promised.'),
        'loft': ('Build a solid through an ordered list of closed profiles.', 'Provide 2–32 distinct earlier profile nodes; section order matters. Native compatibility still needs verification.'),
        'multiFuse': ('Unite a list of existing solids with optional refinement.', 'Provide 2–32 distinct earlier solid nodes. The final union must still be one valid solid.')}
    result['operations'].update({name: {'purpose': purpose, 'semantics': [semantics]}
                                 for name, (purpose, semantics) in additions.items()})
    result['references'].append('src/schemaxis/adaptors/freecad/readiness.json')
    return result
