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
        'application': {'label':'FreeCAD','purpose':'Build editable parametric parts with constrained sketches, Body/Pad/Pocket history, persistent named length drivers, solid operations and verified geometry exports; import a supplier or vendor STEP part with declared units, orientation, placement and checked facts; assemble shared primitive parts or verified modelled parts at named mounts with fixed native joints; prescribe checked constant-speed hinge or slider motion through the separate mechanism route.', 'keywords':['native spreadsheet','engineering table','spreadsheet aliases','mixed-unit dimensions','computer aided design','CAD','FreeCAD','parametric parts','native length drivers','mechanical parts','sketch to solid','feature history','rigid assembly','named mounts','fixed joints','prescribed mechanisms','hinge motion','slider travel','rigid assembly of modelled parts at named mounts','checked STEP import','supplier STEP part','vendor STEP part','vendor part']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'groups': {
            'solids': {'label': 'Solid primitives', 'purpose': 'Construct dimensioned solid geometry.', 'domain': 'geometry'},
            'profiles': {'label': 'Profiles and extrusion', 'purpose': 'Construct closed profiles and extend them into solids.', 'domain': 'geometry'},
            'partdesign': {'label':'Sketch-based mechanical parts','purpose':'Keep a constrained sketch and additive/subtractive feature history in one Body.','domain':'geometry'},
            'booleans': {'label': 'Boolean solids', 'purpose': 'Subtract or unite existing solid geometry.', 'domain': 'geometry'},
            'import': {'label': 'Checked external parts', 'purpose': 'Bring external STEP solids or closed STL meshes in with explicit units, orientation, placement and checked geometry.', 'domain': 'geometry'}},
        'requirements': [
            'Lengths use millimetres. Authored document references resolve before literal option validation.',
            'Inputs reference earlier nodes of the declared kind; select a solid output.',
            'Run requires one valid positive-volume output solid. Native geometry can fail after host planning.',
            'Optional named measurements publish volume, surface area, extents, uniform-density centre, bounds and selected-edge aggregates as verified values with explicit units; see docs/freecad-measurements.md.',
            'Optional batch designStudy brackets one CAD length to reach a named scalar measurement target with explicit units, tolerance, response direction and finite limits. It changes one resolved option; native links recompute. See docs/freecad-design-studies.md.',
            'Optional parameters and node-local drive preserve affine length relationships in a native VarSet for primitive, extrusion, sketch, Pad and finite-depth Pocket dimensions. Batch variants only; live editing and designStudy explicitly reject this contract. See docs/freecad-parameters.md.',
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

    result['requirements'].append('Optional spreadsheet inputs preserve mixed-unit native engineering tables and affine formula aliases for the same finite length targets as VarSet parameters; choose one storage contract. See docs/freecad-spreadsheets.md.')

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
        'pocket': {'purpose':'Remove material to a declared depth or through all stock, retaining editable blind-pocket and counterbore intent in one Body.', 'groups':['partdesign'], 'semantics':['The origin XY sketch cuts along +Z: throughAll follows stock thickness; length requires a positive depth in mm or drive.length. A finite cut is blind only when its depth is less than the remaining stock thickness. Other side/attachment modes are unsupported. Select the final solid tip as output.'], 'related':['body','pad','circle']}})
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
    result['operations']['pocket']['examples'].append({'reference':'examples/schemaxis/freecad-counterbore.json','purpose':'Through bore with a finite-depth counterbore cut from the origin XY face, driven by persistent depth and radius.'})
    history_operations = {
        'sketch': ('Solve a named planar sketch from typed lines, circles, arcs and geometric or dimensional relations.', ['general sketch','constrained profile','named geometry','Sketcher constraints']),
        'slot': ('Create a fully constrained capsule slot with editable straight span and end radius.', ['capsule slot','slotted mounting hole','obround','slot profile']),
        'datumAxis': ('Keep an arbitrary rotation axis editable in its Body for turned features.', ['datum line','reference axis','rotation axis']),
        'bodyRevolve': ('Create an editable turned Body feature from a profile and a named rotation axis.', ['PartDesign Revolution','turned part','axisymmetric body']),
        'groove': ('Remove an editable revolved recess from the current Body tip.', ['PartDesign Groove','turned recess','annular groove']),
        'bodyFillet': ('Round selected edges while retaining the native Body feature history.', ['PartDesign Fillet','body edge radius','editable edge rounding']),
        'bodyChamfer': ('Bevel selected edges with an equal-distance native Body feature.', ['PartDesign Chamfer','body edge bevel','deburr']),
        'linearPattern': ('Repeat one additive or subtractive sketch feature along a Body origin axis.', ['linear pattern','hole row','feature array','equal spacing']),
        'polarPattern': ('Repeat one additive or subtractive sketch feature around a Body origin axis.', ['bolt circle','polar pattern','radial hole pattern']),
        'mirror': ('Reflect one additive or subtractive feature across a Body origin plane.', ['mirrored feature','symmetric holes','PartDesign Mirrored']),
        'additiveLoft': ('Add a changing cross-section through ordered Body profiles.', ['PartDesign AdditiveLoft','lofted boss','transition body']),
        'subtractiveLoft': ('Remove a changing cross-section through ordered Body profiles.', ['PartDesign SubtractiveLoft','tapered cavity','lofted cut'])}
    for operation,(purpose,keywords) in history_operations.items():
        result['operations'][operation]={'purpose':purpose,'groups':['partdesign' if operation not in ('sketch','slot') else 'profiles'],
            'keywords':keywords,'semantics':['Lengths are millimetres; angles are degrees. The Body feature must continue its current tip and leave one valid solid. See docs/freecad-histories.md for ownership, frames, native settings, verification and remaining gaps.'],
            'examples':[{'reference':'examples/schemaxis/freecad-parametric-enclosure.json','purpose':'An editable enclosure with wall/floor drivers, face-attached mounting bosses and bores.'}]}
    for name,purpose,keywords in [
        ('holeLocations','Locate drilling from explicit local centres without duplicating drill dimensions.',['drill centres','hole locations','drilling positions']),
        ('boltGrid','Lay out a centred rectangular fastening grid with native editable pitch constraints.',['bolt grid','rectangular bolt pattern','hole pitch']),
        ('boltCircle','Lay out equally spaced fasteners with editable pitch-circle radius and phase.',['pitch circle','bolt circle layout','PCD']),
        ('hole','Drill plain, blind, counterbored or countersunk holes with one native editable Hole feature.',['PartDesign Hole','counterbore drilling','countersunk holes','conical drill tip','counterdrill'])]:
        result['operations'][name]={'purpose':purpose,'groups':['partdesign' if name=='hole' else 'profiles'],'keywords':keywords,
            'semantics':['The Body-owned location sketch and Hole continue the current solid tip. Dimensions are millimetres and angles are degrees. Unthreaded drilling only; every location must reach stock. See docs/freecad-drilling.md.'],
            'examples':[{'reference':'examples/schemaxis/freecad-drilling.json','purpose':'Persist grid pitch, drill diameter and head depth as editable native dimensions.'},
                        {'reference':'examples/schemaxis/freecad-drilled-enclosure.json','purpose':'Compose one fastening grid/Hole with enclosure cavity, attached bosses and a second Body lid.'}]}
    result['operations']['body']['semantics']=['Each Body has independent ownership and a current solid tip. Several Bodies may share a document; the selected final tip exports one solid.']
    result['operations']['pad']['purpose']='Add stock, a boss or a rib from a Body-owned constrained profile, preserving its editable history.'
    result['operations']['pad']['semantics']=['Start a Body without base, or continue its current tip with an explicit base. Profiles may have explicit frames or checked native planar-face attachments; forward, backward and symmetric extents are available.']
    result['operations']['pocket']['semantics']=['Remove material along the profile normal or its reverse. A top-face sketch normally cuts backward. Finite extent needs length; throughAll omits length. Profiles can attach to a checked extreme planar face of the current Body tip.']
    result['operations']['rectangle']['purpose']='Create a fully constrained rectangular profile with editable width and height in an explicit frame or checked planar-face attachment.'
    result['application']['purpose']='Build editable parametric mechanical parts and enclosures with named dimensions, constrained sketches, explicit frames, checked face attachments, ordered multi-Body histories, turned features, dress-ups, patterns and lofts; publish verified CAD/mesh handoffs and assemble separately admitted parts.'
    result['application']['keywords'].extend(['parametric enclosure','multi Body feature history','face attached sketch','mounting bosses','wall thickness','capsule slot'])
    result['application']['keywords'].extend(['bolt grid','pitch circle','native Hole','counterbore drilling','countersunk holes'])
    result['operations']['shell']={'purpose':'Make a uniform-wall housing, cup or tube with exact planar opening intent and native editable Thickness.',
        'groups':['partdesign'],'keywords':['uniform wall thickness','hollow cup','shell enclosure','PartDesign Thickness','open tube','inward wall','outward offset'],
        'semantics':['Thickness is positive millimetres. Opening directions select exactly one extreme planar face each; missing/ambiguous/duplicate selections fail. Inward/outward offsets and sharp/rounded joins retain native settings. Only native Skin mode is implemented upstream; general surfaces/variable thickness remain open. See docs/freecad-shells.md.'],
        'examples':[{'reference':'examples/schemaxis/freecad-shell-enclosure.json','purpose':'One uniform wall/floor/lid driver composes a shell, attached bosses and native grid drilling in two Bodies.'}]}
    result['application']['keywords'].extend(['uniform wall thickness','shell enclosure','hollow cup','native Thickness'])
    for operation,purpose,keywords in [
        ('arcPath','Create a dimensioned bend path from one native radius and sweep angle.',['dimensioned bend path','bend radius','editable elbow path','centreline arc']),
        ('additivePipe','Sweep closed profiles into an editable Body feature, composing hollow tubes and attached flanged elbows.',['flanged elbow','additive sweep','pipe bend','orientation guide','varying section sweep']),
        ('subtractivePipe','Cut an editable swept channel or bore through the current Body tip.',['swept channel','subtractive sweep','hollow elbow bore','tapered swept passage'])]:
        result['operations'][operation]={'purpose':purpose,'groups':['profiles' if operation=='arcPath' else 'partdesign'],'keywords':keywords,
            'semantics':['Paths are connected same-Body sketch wires and sections are closed unused profiles. Native orientation/transition/section settings remain editable. Binormal directions are world coordinates; new centroid attachments follow moving face centres. See docs/freecad-sweeps.md for coordinate frames, native export limitations and open3D/spline-path gaps.'],
            'examples':[{'reference':'examples/schemaxis/freecad-flanged-elbow.json','purpose':'One bend/wall/flange parameter set drives an editable hollow elbow and attached flange bores.'}]}
    result['application']['keywords'].extend(['flanged elbow','dimensioned bend path','swept channel','native Pipe','face centroid attachment'])
    result['references'].append('docs/freecad-sweeps.md')
    result['references'].append('docs/freecad-shells.md')
    result['references'].append('docs/freecad-drilling.md')
    terms = {
        'body':['mechanical part','feature history','PartDesign Body','sketch based modelling'],
        'pad':['sketch to solid','add thickness','PartDesign Pad','native length driver'],
        'pocket':['through hole','through all','remove material','PartDesign Pocket','blind pocket','blind hole','counterbore','counterbored hole','finite depth','machined recess'],
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
    result['application']['purpose']+=' Analyse one checked homogeneous CAD solid with typed linear-static FEM material, tetrahedral mesh, geometric supports and force/pressure intent, then verify actual solver fields, equilibrium and energy.'
    result['application']['keywords'].extend(['solid elasticity','FreeCAD FEM','linear static analysis','CalculiX bridge','face pressure','displacement support','finite element analysis','enclosure analysis'])
    result['references'].append('docs/freecad-analysis.md')
    result['references'].append('docs/freecad-part-design.md')
    result['references'].extend(['src/schemaxis/adaptors/freecad/readiness.json','docs/freecad-parameters.md','docs/freecad.md'])
    result['application']['purpose'] += ' Publish editable TechDraw mechanical sheets with checked frozen geometry, geometric dimensions and native SVG/PDF.'
    result['application']['keywords'].extend(['technical drawing','TechDraw','manufacturing drawing','orthographic views','dimensioned drawing','drawing publication'])
    result['references'].append('docs/freecad-drawings.md')
    result['operations']['bodyDraft']={
        'purpose':'Taper moulded part walls about an explicit neutral profile plane, retaining editable native Draft.',
        'groups':['partdesign'],'keywords':['mould release draft','mold release draft','draft angle','moulded enclosure','conical cup','wall taper'],
        'semantics':['Continue the current Body tip. Select each planar face by outward unit normal/extreme position or each cylinder by axis line and pre-draft radius; exact cardinality is required. Neutral plane and optional pull datum axis belong to the same Body. Positive angle is degrees; reversed changes slope sign. Compose with native shell/boss/Hole histories. See docs/freecad-draft.md.'],
        'related':['shell','pad','datumAxis','hole'],
        'examples':[{'reference':'examples/schemaxis/freecad-draft-enclosure.json','purpose':'Moulded release walls with driven uniform shell, attached bosses, bores and a separate lid.'},
                    {'reference':'examples/schemaxis/freecad-draft-cup.json','purpose':'Translated pull axis, reversed cylindrical draft and uniform cup walls.'}]}
    result['application']['keywords'].extend(['mould release draft','draft angle','moulded enclosure'])
    result['references'].append('docs/freecad-draft.md')
    for operation in ('box','cylinder','extrude','rectangle','circle','pad','pocket','shell','hole'):
        if operation in result['operations']:
            entry=result['operations'][operation]
            entry.setdefault('keywords',[]).extend(['native spreadsheet','engineering table','unitful formula'])
            entry.setdefault('semantics',[]).append('A native spreadsheet can retain mixed-unit length inputs and affine formula aliases for supported drive targets; see docs/freecad-spreadsheets.md.')
    result['operations']['importMesh']={
        'purpose':'Prepare a closed STL mesh as a faceted Part solid with explicit length units, winding and frame, then compose native refinement and solid machining.',
        'groups':['import'],'keywords':['STL to solid','mesh preparation','faceted BREP','mesh to Part','binary STL','ASCII STL'],
        'semantics':['STL has no assigned unit: units scales coordinates from mm, cm, m or inch into millimetres. Explicit reverseWinding flips every facet; it does not repair inconsistent local winding.',
                     'Planning admits at most 32 MiB per file and 20000 facets across the document. Closed directed edges and vertex fans are necessary; native valid-solid/BOP checks also refuse disconnected or intersecting material and incorrect cavity winding.',
                     'The source becomes a static faceted Part::Feature with editable Placement and optional linked Part::Refine. Continue it with Part cuts or bodySeed and an ordered Body history. Original analytical surfaces, colours and mesh-feature history are not recovered; mesh repair and scan fitting remain unfinished.',
                     'Saved verification reconstructs the complete typed Part graph in a trusted private worker and binds source triangles to independently parsed retained STL. It never restores the submitted native document. See docs/freecad-mesh-preparation.md.'],
        'related':['importSTEP','cut','common','fuse'],
        'examples':[{'reference':'examples/schemaxis/freecad-mesh-bracket.json','purpose':'Closed faceted L bracket refined and drilled through its base.'},
                    {'reference':'examples/schemaxis/freecad-mesh-cavity.json','purpose':'Binary centimetre STL with globally inverted winding, an offset cavity and a tilted placed frame.'}]}
    result['application']['keywords'].extend(['STL to solid','mesh preparation','faceted BREP'])
    result['references'].append('docs/freecad-mesh-preparation.md')
    result['operations']['draftProfile']={
        'purpose':'Keep an ordered straight-edged outline editable as a native Draft Wire, then compose Part extrusion and booleans.',
        'groups':['profiles'],'keywords':['Draft polygon','editable outline','Draft Wire','concave profile'],
        'semantics':['Supply3–256 distinct local XY points in millimetres, omit the repeated closing point, and retain boundary order. Crossings, nonadjacent touches, doubling-back edges and zero area are refused.',
                     'plane selects XY/XZ/YZ; angle rotates about its positive local normal before world origin translation. Extrusion direction remains a world vector. Both boundary windings are supported.',
                     'The native Points and Placement remain editable. This is a batch Part profile, not a constrained Sketcher object or PartDesign Body seed. Curves, holes in one outline, broader Draft drafting and an assembly-history bridge remain missing. See docs/freecad-draft-profiles.md.'],
        'related':['polygon','extrude','cut','loft'],
        'examples':[{'reference':'examples/schemaxis/freecad-draft-profile-bracket.json','purpose':'Concave L outline, native extrusion and through drilling.'},
                    {'reference':'examples/schemaxis/freecad-draft-profile-turned.json','purpose':'Translated and clocked YZ U outline with a world-X extrusion.'}]}
    result['application']['keywords'].extend(['Draft polygon','editable outline','Draft Wire'])
    result['references'].append('docs/freecad-draft-profiles.md')
    result['operations']['bodySeed']={
        'purpose':'Continue imported Body stock as an editable native PartDesign history.',
        'groups':['partdesign','import'],'keywords':['imported Body stock','BaseFeature','solid to Body','seed imported part'],
        'semantics':['Make the seed the first member of an empty Body and refer to an earlier external solid. Continue with supported Body sketches and ordered features; select the final solid tip as output.',
                     'The source Placement is Body-local. An optional Body frame places the completed part in world coordinates for part exports. Sourced assembly mounts and component frames are Body-local for all admitted Body sources, while copied source layout remains editable history.',
                     'Checked importSTEP/importMesh sources retain original admitted geometry, source links and a compiled Placement relation. Portable sourced histories bind typed intent, originals and the entire saved archive against fresh trusted reconstruction before submitted restoration.',
                     'Authored native expressions, arbitrary foreign FCStd histories and the legacy readSTEP reader are refused. A direct Draft Wire bridge, world-frame assembly mode and broader reverse engineering remain unfinished. See docs/freecad-body-seeds.md.'],
        'related':['body','importMesh','importSTEP','pocket'],
        'examples':[{'reference':'examples/schemaxis/freecad-body-stock.json','purpose':'Continue a faceted L-bracket as a seeded Body with a through Pocket.'},
                    {'reference':'examples/schemaxis/freecad-body-stock-turned.json','purpose':'Separate source Placement, tilted Body layout and local assembly coordinates.'},
                    {'reference':'examples/schemaxis/freecad-body-step-stock.json','purpose':'Continue an analytical checked STEP bracket as a native Body history.'}]}
    result['operations']['body']['semantics'].append('An explicit frame places a seeded Body in world coordinates. Its import Placement and feature profiles remain Body-local; source assembly components use their own Body-local frames.')
    result['application']['keywords'].extend(['imported Body stock','solid to Body','BaseFeature'])
    result['references'].append('docs/freecad-body-seeds.md')
    return result
