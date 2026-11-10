"""Apply the curated scene-production conceptual glossary to schema addresses.

The glossary is maintained with the typed production contract. It intentionally
refuses unknown semantic names, rather than labelling generated type text reviewed.
"""
import json
import re
from pathlib import Path
from schemaxis.adaptors.blender.schema import document_schema
from schemaxis.studio_guidance import fields

MEANINGS={
 'intents':'Reusable presentation tasks that lower into native controls, parenting and keyframes. A turntable infers its pivot from actual selected geometry bounds and retains editable motion.',
 'axis':'World X, Y or Z axis around which the presentation control rotates. This axis is independent of object local axes.',
 'angleDegrees':'Signed total presentation rotation in degrees over the specified interval. Positive follows the right-hand convention around the chosen world axis.',
 'startFrame':'First frame of the presentation motion, within the production timeline. The generated control has zero rotation at this frame.',
 'endFrame':'Last frame of the presentation motion, after startFrame and within the production timeline. The control reaches angleDegrees with linear interpolation.',
 'pivot':'Presentation pivot in production world units, or boundsCentre to infer the midpoint of actual selected geometry bounds at the neutral start frame. Off-centre assets therefore rotate around their own geometric extent.',
 'assets':'Reusable self-contained source scenes imported below a named asset root. Complete GLB/embedded glTF and packed local native projects retain hierarchy/materials; native project child animation is retained. Geometry-only STL/PLY/OBJ and bounded baked USD have explicit unit and loss contracts.',
 'sourceUnits':'Physical source length units before placement in production coordinates. glTF and supported baked USD use metres; STL/PLY/OBJ and native blend units are explicitly declared rather than inferred from filenames.',
 'includeLights':'Retain imported asset lights as active render lights. False disables imported emitters so the production lighting controls appearance; objects remain for hierarchy/reference integrity.',
 'production':'Compose named scene assets, hierarchy, motion, rigs, node graphs and frame publications around the mesh graph. The saved project stays editable; the strategic family map lists remaining workflows.',
 'frameStart':'First integer frame of the production timeline and sequential simulation evaluation. Use the same origin for imported motion and requested publications.',
 'frameEnd':'Last integer frame of the production timeline. Keys, renders, exports and simulation samples must lie within the inclusive start/end range.',
 'currentFrame':'Frame retained in the saved project and used for exports that omit their frame. If omitted it is frameStart; output jobs restore this frame after evaluation.',
 'fps':'Timeline frames per second. Together with frame numbers this sets motion duration and physical simulation elapsed time; it does not resample authored keyframes.',
 'gravity':'World acceleration vector for native physics. The default points down world Z at9.81metres per second squared; Blender applies the scene physical unit scale.',
 'units':'Physical length represented by one numerical scene coordinate. The blend retains these numbers and its scene scale. GLB/USD export in metres; OBJ/PLY/STL retain the declared numerical units with explicit metadata.',
 'collections':'Named reusable scene collections, optionally nested. Declare contents through object collection references, and reuse the complete contents through collectionInstance assets.',
 'id':'Stable authored identity within this record family. Use names in references instead of native list positions; duplicate identities in the same namespace are refused.',
 'parent':'Named parent in the same hierarchy. Collection and bone parents must exist; object parenting may reference mesh-graph outputs or production objects. Cyclic relationships are refused.',
 'hierarchy':'Object parenting relationships. Each object has at most one parent; keepWorld decides whether parenting preserves its original world pose or its authored local pose.',
 'object':'Named target object. Mesh graph outputs and declared production assets share the object reference space; materials cannot be substituted for geometry.',
 'keepWorld':'Preserve the initial world pose when assigning the parent. False retains the local transform so the parent contributes immediately to the world pose.',
 'materialBindings':'Replace the target geometric object material with a named graph material or mesh-graph material. Shared object data also shares material slots.',
 'material':'Named material resource to assign. It must refer to a mesh-graph material or production material graph; mesh exchange formats can lose this appearance.',
 'geometryBindings':'Attach a named Geometry Nodes graph to a geometric object as an editable modifier. Procedural topology expansion is bounded before native evaluation.',
 'graph':'Named geometry graph to attach to this object. Graph references are checked before launching Blender; shader and compositor graphs have different roles.',
 'images':'File-backed image assets for material graphs. Original and retained bytes are hashed; packing embeds the image in the saved project rather than relying on an external path.',
 'file':'Input image path. The file must exist and remain byte-identical during capture and verification. Use an image asset identity in shader image nodes rather than repeating the path.',
 'colourSpace':'How Blender interprets image samples. sRGB decodes colour textures; Non-Color preserves numeric data such as normals or masks.',
 'pack':'Embed image bytes into the saved project. False retains an external dependency whose bytes are still captured and verified; portable projects normally use true.',
 'rigs':'Editable armatures with named rest bones. Bone heads/tails define the rest frame, hierarchy defines joint chains and skin bindings define deformation weights.',
 'bones':'Named bones in the armature rest pose. Head and tail must differ; a connected child needs an existing parent and native connectivity can adjust its head.',
 'head':'Bone rest head in armature coordinates. This is a geometric point, not an Euler rotation or pose offset.',
 'tail':'Bone rest tail in armature coordinates. Head-to-tail defines local Y; pose translations therefore follow the bone rest frame rather than world XYZ.',
 'connected':'Join the bone head to its parent tail. Use for continuous chains; an unparented bone cannot be connected.',
 'deform':'Allow this bone to deform vertices through an Armature modifier. Control bones can disable deformation while retaining hierarchy and animation.',
 'skin':'Explicit mesh-to-armature deformation bindings. Vertex indices identify base mesh vertices before procedural modifiers; this does not generate automatic weights.',
 'rig':'Named armature that deforms the mesh. Every weight group must name one of this rig bones.',
 'weights':'Explicit bone weight groups. Each record assigns one weight to its listed base-mesh vertices; the native project retains editable groups and an Armature modifier.',
 'bone':'Named bone in the referenced rig or animation target. Pose channels use its local rest frame; absent or wrong-rig bone identities are refused.',
 'vertices':'For a mesh, ordered local [x,y,z] coordinates referenced by face indices. For skin weights, base-mesh vertex indices receiving the declared weight. These are different roles shown by their schema variants.',
 'weight':'Dimensionless skin influence from0to1 assigned to the listed vertices. Explicit groups are not an automatic anatomical weighting or retargeting system.',
 'rigidBodies':'Active/passive rigid-body physics for declared meshes. Collision shape, mass, friction and restitution influence native motion; sequential frame samples expose the evaluated result.',
 'type':'Choose the native role described by this variant: light emission shape or active/passive rigid-body behaviour. Other variant-specific fields define its physical meaning.',
 'mass':'Mass used by the selected physics model. Rigid bodies use kilograms; cloth uses Blender cloth vertex mass. Solver settings do not prove a scientifically validated material model.',
 'friction':'Dimensionless rigid-body contact friction. Zero is frictionless; larger values resist tangential sliding according to the native contact solver.',
 'restitution':'Dimensionless rigid-body bounciness from0to1. Zero dissipates normal contact motion; one approximates an elastic rebound within solver limitations.',
 'shape':'Collision proxy used by rigid-body contact. Simple primitives and convex hulls are efficient approximations; MESH uses detailed geometry and has native stability/performance tradeoffs.',
 'kinematic':'Make an active rigid body follow authored animation rather than dynamic free motion. Use for driven collision participants; it does not create a joint.',
 'cloth':'Native cloth modifiers on explicit meshes, with mass/stiffness, collision options and optional pinned vertices. Sequential evaluation is bounded; portable baked cache publication remains unfinished.',
 'quality':'Native solver quality or reviewed node quality selection. For cloth it is the bounded quality-step count; more steps cost more computation and do not alone prove convergence.',
 'tension':'Native cloth tensile stiffness. Higher values resist stretching; this is the Blender solver control rather than a general material Young modulus.',
 'compression':'Native cloth compression stiffness, resisting in-plane compression. Keep material interpretation and mesh resolution in mind when comparing simulations.',
 'shear':'Native cloth shear stiffness, resisting in-plane angular distortion of the mesh.',
 'bending':'Native cloth bending stiffness, resisting changes in surface curvature; its effect depends on topology and native bending formulation.',
 'collision':'Enable cloth collision against declared collision objects. Interpenetration and convergence still require appropriate mesh resolution and solver controls.',
 'selfCollision':'Enable cloth contact with itself. This can greatly increase cost and needs geometry appropriate to the native collision solver.',
 'pinVertices':'Base-mesh vertex indices fixed by a unit-weight pin group. Omit for an unpinned cloth object; duplicate/out-of-range geometry requires correction.',
 'collisionObjects':'Named objects receiving native Collision modifiers for cloth interaction. This is separate from rigid-body collision proxies.',
 'simulationFrames':'Ordered distinct timeline frames whose evaluated geometry is sampled. The runner evaluates from frameStart sequentially and repeats after reopening, with a1000-frame maximum span.',
 'objects':'Named production assets that complement mesh graph outputs: geometry, labels, lights, cameras, controls and instances. Each variant has a closed typed field set.',
 'kind':'Select the reviewed object, node or constraint variant. This chooses a finite trusted native mapping; arbitrary class names and property paths are refused.',
 'location':'Object local translation in production length units. Parent transforms contribute to world placement; bone-track translations use the bone rest frame.',
 'rotation':'XYZ Euler rotation in radians in the local parent/rest frame. This is not degrees and is not a quaternion.',
 'scale':'Dimensionless XYZ scale for object/vector transforms, or the named procedural texture frequency input in a node variant. Object components must be positive; applied mesh modifiers operate in local coordinates.',
 'collection':'Named collection containing the new object. Omit or use empty to link it directly to the scene; it does not copy collection contents.',
 'hidden':'Hide this object from renders while retaining editable scene data. This is independent of mesh graph visible selection and viewport editing.',
 'displaySize':'Viewport size of an empty control in production length units. It provides an editing handle and does not create renderable geometry.',
 'body':'Text contents retained in an editable native font object. This is literal text, not a file or executable expression.',
 'size':'Length or node kernel extent defined by the selected variant: text character size, light emitter size, procedural primitive size, or compositor blur/glare extent. Refer to the variant and production guide for units.',
 'extrude':'Text solid extrusion depth in local production units. Zero retains a flat glyph surface.',
 'align':'Text paragraph horizontal alignment. It controls glyph placement relative to the text object origin.',
 'points':'Ordered local curve points. Consecutive points form a polyline; bevel creates thickness and closed connects the final point to the first.',
 'closed':'Close the curve loop by connecting its final point to its first. This does not cap arbitrary mesh boundaries.',
 'bevel':'Curve bevel radius/depth in production length units. Zero produces an unthickened curve.',
 'resolution':'Bounded geometric sampling count/resolution. For native curve bevel it controls rounded cross-section detail; for geometry circle nodes it is polygonal point count.',
 'faces':'Ordered polygon vertex-index lists. Each index refers to vertices, must exist, and must be distinct within its face; face winding affects normals.',
 'uv':'One dimensionless [u,v] pair per face corner in face/corner order. This authors explicit mapping coordinates and does not unwrap or pack islands.',
 'smooth':'Use smooth interpolated polygon shading. Geometry and topology remain unchanged.',
 'energy':'Light output using Blender native light energy conventions: watts for point/spot/area, irradiance for sun. Emission shape and scene scale affect appearance.',
 'colour':'Linear RGBA/RGB colour for the selected object or shader socket. Values are numeric linear shader/light inputs, not sRGB hexadecimal codes.',
 'angle':'Angular extent in radians: spotlight cone, sun angular diameter, or a selected compositor transformation. It is inactive for area/point lights and nondefault unused settings are refused.',
 'projection':'Perspective or orthographic camera projection. Perspective uses lens; orthographic uses orthographicSize to set view width.',
 'lens':'Camera focal length in millimetres for perspective projection. It is separate from production scene length units.',
 'orthographicSize':'Camera orthographic width in production length units. It does not scale the camera object or the geometry.',
 'clipStart':'Positive near camera clipping distance in production units. It must be smaller than clipEnd; too large a value removes nearby geometry.',
 'clipEnd':'Far camera clipping distance in production units. It must exceed clipStart and cover the intended subject.',
 'focusDistance':'Depth-of-field focus distance in production length units. It affects rendering when depthOfField is enabled.',
 'aperture':'Camera aperture f-number. Lower values create shallower depth of field; this is dimensionless.',
 'depthOfField':'Enable camera depth-of-field rendering with the declared focusDistance and aperture.',
 'source':'Named object-data or collection source for an instance. Object-data reuse shares geometry and material slots; collection instances retain the declared collection contents.',
 'linked':'Share source object data instead of copying it. False permits independent data/material edits; modifier stacks are copied, while parenting, animation and constraints must be declared explicitly.',
 'materialGraphs':'Named editable shader graphs built from reviewed nodes and semantic socket links. Apply through materialBindings; every graph needs one output.',
 'geometryGraphs':'Named editable procedural Geometry Nodes graphs. Bind to geometric objects through geometryBindings; topology-expanding counts require bounded literals.',
 'compositor':'One editable native compositor graph applied to the scene output. It processes rendered images; it is separate from surface shading.',
 'nodes':'Named reviewed nodes in this graph. Each kind declares its accepted literal sockets and properties; arbitrary native constructors are not accepted.',
 'values':'Literal defaults for reviewed input sockets. A socket link overrides its literal during evaluation. Numeric, vector, colour, material and geometry sockets have distinct roles.',
 'properties':'Reviewed node behaviour settings such as arithmetic operation, texture interpolation or image asset. These settings can enable/disable sockets, and inactive linked sockets are refused.',
 'links':'Explicit graph connections from an output socket to an input socket. Node and socket identities must exist and have compatible declared kinds; dependency cycles fail.',
 'from':'Source output endpoint of a node link. It references a node ID and one of that kind semantic output sockets.',
 'to':'Destination input endpoint of a node link. Ordinary inputs accept one link; geometry join deliberately accepts multiple geometry inputs.',
 'node':'Named node inside this same graph. References cannot point to another material or arbitrary native data path.',
 'socket':'Reviewed semantic socket identity on the selected node. It is not a native numeric list index; type and active-state compatibility are checked.',
 'tracks':'Animation channels with strictly increasing frame/value keys. Transform values use local coordinates; light/camera channels require matching object types.',
 'channel':'Semantic property to animate: location, rotation, scale, render visibility, light energy or camera lens/orthographic size. Arbitrary RNA paths are excluded.',
 'interpolation':'How motion or image samples are interpolated in this variant. Tracks use LINEAR/BEZIER/CONSTANT; texture interpolation uses reviewed native image sampling modes.',
 'keys':'Ordered animation keys inside the timeline. Repeated frames are invalid; linear/constant values are independently checked at keys and integer midpoints.',
 'frame':'Integer timeline frame for a key or publication. Exports default to currentFrame; keys and outputs must remain within the inclusive timeline range.',
 'value':'Value for this semantic animation channel or node scalar. Its units/shape follow the selected channel/socket; transforms do not accept arbitrary native values.',
 'constraints':'Ordered editable object or pose-bone relationships. Targets are named objects, IK requires a pose bone and path following requires a curve.',
 'targetBone':'Optional target pose-bone identity within the target armature. It is separate from bone, which selects the constraint owner; missing or wrong-rig references fail before execution.',
 'target':'Named target object for a constraint. Most constraints require it; local limit constraints instead use explicit minimum/maximum bounds.',
 'influence':'Dimensionless constraint influence from0to1. Zero disables its effect while retaining the editable constraint; one applies its full native behaviour.',
 'axes':'Enabled XYZ components of a copy-location constraint. Each boolean selects whether that component follows the target.',
 'offset':'Add the copied location/scale to the owner rather than replacing it, or the vector displacement socket on a procedural geometry node. Meaning follows the selected kind.',
 'mix':'How the selected copy transform/rotation combines with the existing pose. Choose a reviewed native composition order; parent/rest frames remain significant.',
 'trackAxis':'Local object/bone axis aimed toward the target. Negative axes reverse the pointing direction.',
 'upAxis':'Local axis used as up in an oriented track constraint. It must be compatible with the tracking direction.',
 'factor':'Dimensionless blend amount or fixed path parameter. Zero selects the first/start state and one the second/end state in the selected operation.',
 'follow':'Rotate the constrained object along its path tangent in addition to changing its position.',
 'chainLength':'Number of ancestor bones included in an IK solve. Zero uses the full available chain; solver behaviour depends on rest hierarchy.',
 'iterations':'Bounded native IK solver iteration count. More iterations can improve the solve but do not guarantee a reachable target.',
 'stretch':'Permit the IK chain to stretch toward the target. Disable when bone segment lengths must remain fixed.',
 'minimum':'Local XYZ lower limits of the selected transform constraint. Positions use production units, rotations radians and scales dimensionless.',
 'maximum':'Local XYZ upper limits of the selected transform constraint. They should bound the intended local motion rather than world coordinates.',
 'exports':'Selected frame geometry publications with stable IDs, explicit formats and object membership. World-space evaluated geometry is exported; rig history and native procedural materials are not preserved.',
 'format':'Frame geometry format: GLB/USD use physical metres; OBJ/PLY/STL retain production numerical units. Consult publication metadata and documented material/history losses.',
 'renderFrames':'Unique integer frames to render as additional PNGs. The saved current frame and active camera are restored afterward; these publications are separate from the legacy static camera images.',
 'camera':'Named camera for production frame rendering. Omit to use the existing automatically framed camera; a mesh/light cannot be substituted.',
 'a':'First scalar/vector/colour/image operand of this node operation. A link overrides the literal; the operation determines whether it is added, multiplied, mixed or otherwise combined.',
 'b':'Second scalar/vector/colour/image operand of this node operation. It must match the socket kind; linked output replaces its literal default.',
 'c':'Third scalar/vector operand used by operations that require one, such as multiply-add. Links to inactive operation sockets are refused.',
 'operation':'Reviewed arithmetic/vector operation. It selects native behaviour and which operands/results are active; inactive linked sockets fail explicitly.',
 'clamp':'Clamp the selected numeric operation result to its native bounded range. This is a numeric control and does not repair geometry or provide solver convergence.',
 'vector':'Three-component input/output vector interpreted by this node, such as coordinates, normals or arithmetic operands. Coordinate units and normalization depend on the selected kind.',
 'x':'X component for a vector-composition node, or horizontal compositor translation. Vector components follow their parent quantity; image translation is in pixels.',
 'y':'Y component for a vector-composition node, or vertical compositor translation. Vector components follow their parent quantity; image translation is in pixels.',
 'z':'Z component of a vector-composition/separation node in that vector coordinate convention.',
 'fromMin':'Lower source interval endpoint for remapping a scalar. Keep the source interval nonzero to obtain a meaningful map.',
 'fromMax':'Upper source interval endpoint for remapping a scalar; mapRange normalizes relative to fromMin/fromMax.',
 'toMin':'Lower destination interval endpoint for a remapped scalar.',
 'toMax':'Upper destination interval endpoint for a remapped scalar.',
 'detail':'Procedural texture detail level. Higher values add smaller-scale variation and computation; it is not mesh resolution.',
 'roughness':'Shader microsurface roughness or procedural noise amplitude roughness. Zero gives a smoother surface/noise contribution; socket meaning follows the node.',
 'distortion':'Procedural coordinate distortion or compositor lens distortion. Use the selected node context; this is not an object-space deformation modifier.',
 'randomness':'Dimensionless Voronoi point randomness. Zero regularizes the point pattern; larger values vary feature positions.',
 'phase':'Wave texture phase offset, advancing the periodic pattern without moving geometry.',
 'surface':'Surface shader closure connected to the material output. Colour or geometry sockets cannot replace a shader closure.',
 'volume':'Volumetric shader closure connected to the material output. It describes interior scattering/absorption, separate from polygon geometry.',
 'displacement':'Material displacement vector input. Actual geometric displacement depends on Blender material/render evaluation; it is not an exported topology guarantee.',
 'metallic':'Principled metal fraction from0to1. Metals use base colour as reflectance and differ from dielectric transmission.',
 'ior':'Index of refraction for the selected dielectric shader. This dimensionless optical ratio influences Fresnel reflection and transmission.',
 'alpha':'Surface opacity or image alpha. One is opaque; zero is transparent within the selected shader/compositing operation.',
 'normal':'Normal direction used for shading or procedural geometry. A normal map should be decoded with normalMap before connecting its colour data here.',
 'transmission':'Principled transmission weight from0to1. Rendering transmitted light does not change exported mesh geometry.',
 'coat':'Principled clearcoat weight from0to1, adding an upper reflective layer.',
 'emission':'Linear emitted colour. Emission strength controls magnitude separately; it does not create a light datablock.',
 'emissionStrength':'Magnitude of shader emission. Larger values emit more light and can require more render samples.',
 'strength':'Magnitude of emission, bump/normal influence or compositor glare in the selected node. These native controls have different physical interpretations.',
 'density':'Volumetric shader density in the native renderer. This is not the mass density of a physics mesh.',
 'anisotropy':'Directional scattering bias of a volume shader. Its interpretation is optical rather than object scale.',
 'translation':'Procedural local coordinate translation. Geometry values use production units; texture mapping changes sampled coordinates rather than moving the object.',
 'image':'Named production image asset for a texture node, or the image socket in a compositor graph. File paths belong to the image asset declaration.',
 'extension':'Texture sampling behaviour outside the image domain: repeat, mirror, extend edge pixels or clip. UV values remain dimensionless.',
 'height':'Bump height input or procedural grid length, as defined by the selected node. Bump affects shading; grid dimensions create geometry.',
 'distance':'Distance or threshold in the selected node coordinate space, such as bump scale or merge tolerance. It is not a global object measurement.',
 'invert':'Reverse the bump direction or selected colour operation. It changes the operation output, not polygon winding.',
 'blend':'Reviewed colour/image blend rule such as mix, multiply or screen. A factor controls its contribution where the node exposes one.',
 'position':'Position field/vector used for procedural geometry. Position fields are evaluated per geometry element rather than a single object location.',
 'seconds':'Timeline time in seconds supplied by the scene-time node, derived from frame timing.',
 'geometry':'Geometry stream input/output of a Geometry Nodes operation. Links carry native geometry sets; they are not file paths or arbitrary object handles.',
 'selection':'Boolean field selecting geometry elements affected by this operation. A literal true selects all applicable elements.',
 'xVertices':'Bounded literal number of primitive vertices along local X. Counts determine topology and are included in conservative expansion checks.',
 'yVertices':'Bounded literal number of primitive vertices along local Y. Higher counts cost memory; they do not change physical size.',
 'zVertices':'Bounded literal number of primitive vertices along local Z. Topology-count sockets cannot be linked to unbounded fields.',
 'width':'Physical width of a geometry grid in its local coordinates, separate from vertex resolution.',
 'radius':'Local radius for the selected procedural sphere or circular curve primitive. Geometry sampling is controlled separately.',
 'subdivisions':'Bounded literal icosphere subdivision count. Face count grows approximately by four per level and is budgeted before allocation.',
 'mesh':'Mesh geometry stream for conversion or topology operations. A shader/image socket is incompatible.',
 'curve':'Curve geometry stream to resample or convert; profile controls the cross-section when converting to mesh.',
 'profile':'Curve geometry used as a swept cross-section. Curve-to-mesh expansion multiplies path/profile resolution and is budgeted.',
 'fillCaps':'Close the ends of a curve-to-mesh extrusion where supported by the native geometry operation.',
 'count':'Bounded literal resampling count. It changes the number of points along each curve rather than the curve length.',
 'level':'Bounded literal mesh subdivision level. Each increase can multiply topology substantially; conservative limits prevent runaway allocations.',
 'instance':'Geometry set instanced on input points. Scale/rotation apply per point; realiseInstances converts the references to actual geometry.',
 'individual':'Extrude selected mesh faces individually rather than treating a connected region as one extrusion.',
 'offsetScale':'Scalar magnitude for native extrusion displacement. It combines with the vector offset according to the native extrusion mode.',
 'name':'Name of the geometry attribute to read. The selected dataType must match the intended field interpretation.',
 'dataType':'Reviewed named-attribute value type. It changes the native field socket type; links still need compatible declared sockets.',
 'exposure':'Image exposure adjustment in stops: each positive unit doubles linear brightness before display conversion.',
 'gamma':'Gamma adjustment for image colour values. One retains the native input response; this is not a declaration of output file colour space.',
 'brightness':'Native compositor brightness adjustment. It affects image samples, not scene light energy.',
 'contrast':'Native compositor contrast adjustment. Excessive contrast can clip image detail.',
 'hue':'Hue shift control of the compositor;0.5is the neutral native setting.',
 'saturation':'Colour saturation factor; one preserves saturation and zero removes it in the native compositor.',
 'dispersion':'Chromatic lens dispersion in the compositor. It separates colour channels near image boundaries and does not alter scene geometry.',
 'threshold':'Linear brightness threshold for compositor glare. Highlights above it contribute to the glare effect.',
}


def main():
    root=Path(__file__).resolve().parents[1];path=root/'src/schemaxis/adaptors/blender/guidance.json';guide=json.loads(path.read_text());route=guide['routes']['schemaxis.blender/1']['fields'];schema=document_schema();allfields=dict(fields(schema));base='/properties/scenes/items/properties/production';count=0
    for address,spec in allfields.items():
        if not address.startswith(base):continue
        parts=address.split('/');semantic=next((parts[i+1] for i in range(len(parts)-2,-1,-1) if parts[i]=='properties'),'production')
        if semantic not in MEANINGS:raise ValueError('unreviewed semantic field '+semantic+' at '+address)
        explanation=MEANINGS[semantic]
        if '/assets/' in address and address.endswith('/properties/format'):explanation='Source asset type: complete binary or embedded-resource glTF, packed local native blend, geometry-only STL/PLY/OBJ, or bounded static baked USD. Source units and external dependency limitations are explicit; this is not the complete upstream import catalogue.'
        if 'const' in spec:explanation+=' This variant selects '+str(spec['const'])+'.'
        if address.endswith('/items'):explanation+=' This record describes one ordered entry/component of that field.'
        record={'status':'reviewed','explanation':explanation,'sources':['docs/blender-production.md','src/schemaxis/adaptors/blender/production.py','src/schemaxis/adaptors/blender/node_catalogue.py']}
        if 'default' in spec:record['defaultMeaning']='Omitting this setting assigns '+json.dumps(spec['default'],ensure_ascii=False)+'. A link overrides a node socket literal during evaluation.' if '/values/' in address else 'Omitting this setting assigns '+json.dumps(spec['default'],ensure_ascii=False)+'.'
        elif spec.get('type')=='array':record['defaultMeaning']='Omit this optional collection when no entries of this kind are needed; required variant collections are identified by the schema.'
        if semantic=='currentFrame':record['defaultMeaning']='Omitting currentFrame uses frameStart, which is1by default.'
        if 'enum' in spec:record['explanation']+=' Choose among '+', '.join(map(str,spec['enum']))+'.'
        route[address]=record;count+=1
    from schemaxis.adaptors.blender.production_job import document_schema as production_job_schema
    target=guide['routes'].setdefault('schemaxis.blender.production/1',{'fields':{}})['fields']
    top_meanings={None:'Compose complete scene production from named assets, motion, appearance and reusable presentation intent, without authoring a mesh DAG. The same native executor preserves original authored input and verifies the deterministic lowered scene.', 'version':'Scene-production document contract version, separate from the Blender application release. This route accepts complete typed scene records without authored graph scaffolding.','id':'Stable scene identity retained in the lowered execution and publications.','visible':'Named geometric assets or scene roots used for framing and geometry observations. Omit to select declared assets and geometric production objects; root selection includes evaluated descendants. Individual production hidden flags still govern rendering.','prepareOnly':'Save an editable project without the legacy static preview image. Explicit renderFrames and exports still publish their requested outputs.','size':'PNG output dimensions [width,height] in pixels for both the preview and requested frame renders. The default is320by240; each side is32–2048.','cameras':'Optional automatic-framing camera views for the static preview; omission uses one oblique view. A named production camera can independently control renderFrames.','maxPublications':'Positive publication budget covering the native project, static previews, requested frame PNGs and every selected geometry export. Exceeding it refuses before native execution.'}
    for address,spec in fields(production_job_schema()):
        if address.startswith('/properties/production'):origin='/properties/scenes/items'+address
        elif address.startswith('/properties/render'):origin='/properties/scenes/items'+address
        elif address.startswith('/properties/cameras'):origin='/properties/scenes/items/properties/images/items'+address
        else:origin=None
        if origin not in route and address.startswith('/properties/cameras'):
            normalized=re.sub(r'/(?:anyOf|oneOf)/[0-9]+','',origin)
            origin=next((key for key in route if re.sub(r'/(?:anyOf|oneOf)/[0-9]+','',key)==normalized),origin)
        if origin in route:
            record={**route[origin],'sources':['docs/blender-production.md','src/schemaxis/adaptors/blender/production_job.py']}
        else:
            parts=address.split('/');semantic=next((parts[i+1] for i in range(len(parts)-2,-1,-1) if parts[i]=='properties'),None)
            camera_origin='/properties/scenes/items/properties/images/items/properties/cameras/items/properties/'+str(semantic)
            if address.startswith('/properties/cameras') and camera_origin in route:explanation=route[camera_origin]['explanation']
            elif semantic in top_meanings:explanation=top_meanings[semantic]
            else:raise ValueError('unreviewed direct scene field '+address)
            record={'status':'reviewed','explanation':explanation,'sources':['docs/blender-production.md','src/schemaxis/adaptors/blender/production_job.py']}
        if '/assets/' in address and address.endswith('/properties/format'):record['explanation']='Source asset format: complete binary/embedded glTF, packed local native blend, geometry-only STL/PLY/OBJ, or bounded static baked USD. External OBJ material libraries, external glTF resources, linked native libraries and stateful caches require captured dependency workflows that remain unfinished.'
        target[address]=record;count+=1
    path.write_text(json.dumps(guide,indent=2,ensure_ascii=False)+'\n');print('Reviewed production addresses',count)

if __name__=='__main__':main()
