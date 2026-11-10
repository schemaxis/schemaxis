"""Conceptual review of artist layers, sampler roles and stored UV transforms."""
import json,re
from pathlib import Path
from studio_guidance import seed,report
from schemaxis.adaptors import registry
from schemaxis.studio_guidance import fields

MEANINGS={
 'surfaceMaterials':'Reusable layered physical surfaces in the same material-ID namespace as expert material graphs and mesh-graph materials. Assign them through objects, material bindings, logical face/spline/text slots or typed Geometry Nodes material handles. Defaults give opaque grey rough dielectric; Workbench uses independent display controls.',
 'id':'Unique material identity within the production material namespace. Define a finish once and reference it from several objects or logical palettes; changing its layers updates every user of that material.',
 'samplers':'Locally named image lookup roles. Reuse a captured production image with different coordinate, projection, wrap or filtering intent; scalar and colour expressions reference these local sampler IDs.',
 'image':'ID of a captured production.images resource. That resource owns original bytes, colour space, alpha interpretation and packing; a sampler cannot select an arbitrary native image or external path.',
 'coordinates':'Choose a stored UV set or generated/object coordinates. Stored named UVs are the consistent route for matching base/ORM/normal orientation. A sampler lookup transform changes lookup only, not the encoded tangent-normal frame.',
 'set':'Use the render-active evaluated UV map, or an explicitly named stored UV set. Missing sets on actually used evaluated faces refuse. Active editing selection is distinct from the render-active UV map.',
 'name':'Exact stored UV map name. Named sets can be authored with meshData or retained from an admitted original asset. Native list position, appended collision names and mutable witness data do not identify a UV source.',
 'transform':'Coordinate transform for this sampler lookup. UV transforms translate, rotate around the coordinate origin and tile; spatial transforms use local XYZ translation, Euler degrees and component scale. This does not automatically correct normal vectors by a texture Jacobian.',
 'offset':'Dimensionless UV lookup translation. Repeat/mirror wrapping is applied after lookup; offset does not move mesh vertices or a normal map tangent basis.',
 'tile':'Dimensionless U/V lookup scale, including signed mirroring or zero for constant lookup. To transform normal orientation together with colour/data maps, use a named stored meshData UV transform instead.',
 'rotationDegrees':'UV or spatial sampler lookup rotation in degrees. Specular-layer rotation instead rotates anisotropic highlights in degrees. Stored UV transforms rotate counterclockwise about their explicit pivot before translation.',
 'translation':'Spatial lookup XYZ translation in the selected generated/object coordinate frame. Generated coordinates are normalized by the source texture space; object coordinates follow the object-local geometry frame.',
 'scale':'Spatial lookup component scale. This changes image sampling coordinates; it does not apply Object scale or add mesh tessellation.',
 'projection':'Flat reads XY as image coordinates. Box projects spatial coordinates from several directions with an optional blend; sphere and tube wrap spatial coordinates around the texture origin. UV samplers require flat projection.',
 'blend':'Box projection transition blend. Zero preserves hard projection transitions; increasing it mixes neighbouring axis projections. It has no meaning for flat, sphere or tube projection.',
 'wrap':'Repeat tiles the image; mirror alternates reflected tiles; extend holds the edge; clip yields transparent outside. EEVEE box projection only supports repeat/mirror and refuses the documented clip/extend substitution.',
 'filter':'Nearest preserves discrete texels, linear interpolates nearby texels, cubic smooths interpolation and Smart selects the fixed native option with Cycles built-in OSL. Smart requires renderer.shadingSystem=osl and CPU or OptiX; default SVM and EEVEE refuse Smart. Cubic magnification is qualified; adaptive minification and portable mip-cache ownership remain open. Large tiled-image probes alias even with native-generated unpacked caches. Projection seams retain the fixed renderer limitations.',
 'baseColour':'Linear base albedo/tint shared by diffuse, subsurface, metal and transmission layers. A sample can tint a captured colour image; a constant is linear RGB rather than sRGB bytes.',
 'metallic':'Blend between a dielectric base and a metal surface. Zero retains diffuse/transmission plus dielectric reflection; one gives tinted metal reflection. Packed metallic maps normally use a Non-Color channel.',
 'roughness':'Surface microfacet roughness. Zero gives sharp reflection/refraction; higher values broaden them. Coat and sheen have their own roughness controls; diffuse roughness selects the Cycles rough diffuse model.',
 'ior':'Index of refraction: about1 for air,1.5 for common glass. It controls dielectric reflection and transmission. Coat and skin subsurface IOR belong to their own interfaces; skin IOR is unavailable for other scattering methods.',
 'coverage':'Surface opacity, separate from transmission through a covered surface. One is fully present; zero is transparent. Image alpha can drive coverage without changing the artist colour interpretation of that same sampler.',
 'wall':'Solid models bulk scattering/refraction. Thin models sheets and uses its separate thin-scattering layer; the compiler connects zero EEVEE thickness in slab mode. A thin wall cannot also author bulk radii or explicit bulk thickness.',
 'diffuse':'Diffuse reflection layer controls. Its roughness is a Cycles-only rough-diffuse effect and is refused when nonzero under EEVEE.',
 'subsurface':'Choose no scattering, diffusion approximation, volumetric random walk, skin random walk with custom IOR, or thin-sheet scattering. Use closed sensible geometry for bulk random walk; holes/overlaps are a modelling concern.',
 'weight':'Layer contribution from zero to one, constant or sampled from an image channel. Zero is the neutral control; a shared material definition retains this intent for every object using it.',
 'relativeRadius':'Relative RGB scattering distances. Red/green/blue travel different distances below the surface; multiply these ratios by the bulk distance. Thin scattering does not use them.',
 'distance':'Distance in production units. Bulk subsurface scales relative RGB radii; bump offsets the shading normal; displacement offsets geometry; EEVEE thickness approximates object-space inner distance and follows Object scale.',
 'anisotropy':'Signed directional scattering/reflection bias. Specular anisotropy stretches highlights; positive/negative subsurface values bias scattering forward/backward. These effects require Cycles.',
 'specular':'Dielectric and metal reflection controls, including normal-incidence level, tint, anisotropy, tangent direction and microfacet energy model.',
 'level':'Adjustment to the IOR-derived dielectric reflection level. The default0.5 retains physical Fresnel strength; zero removes it and one doubles normal-incidence strength.',
 'tint':'Linear RGB multiplier for a sampled image or layer reflection. White preserves colour; coloured values tint the sampled/layer contribution. Associated zero-alpha artist colour is explicitly black.',
 'tangent':'Choose the native automatic anisotropy tangent, a stored UV tangent, or a radial object-axis tangent. This is highlight orientation, distinct from choosing a normal-map coordinate space.',
 'axis':'Object axis around which a radial anisotropy tangent circulates. It does not change mesh coordinates, the light direction or a UV-map normal frame.',
 'energy':'Choose multiple-scattering GGX for improved rough-surface energy retention, or single-scattering GGX for the native faster approximation.',
 'coat':'Independent clear coat above the base, with its own weight, roughness, IOR, tint and normal choice. It can retain a smooth top layer over a detailed base surface.',
 'normal':'Surface detail normal: geometric, RGB normal map, height bump, or a chained normal map and bump. Coat can follow the base normal or use a separate detail chain. These shade the surface; only geometry displacement changes its silhouette.',
 'sheen':'Soft grazing fabric-like reflection, controlled by weight, roughness and tint. EEVEE implements an approximate sheen layer rather than the full Cycles result.',
 'emission':'Light emitted by the surface, with linear RGB colour and nonnegative strength. Constant emission colours are bounded; sampled HDR colour is retained without the base-albedo clamp.',
 'colour':'Linear RGB colour source for this layer. Sampled sRGB colour is canonically associated so another alpha consumer cannot silently darken/brighten it; Non-Color and channel-packed data keep their numeric interpretation.',
 'strength':'Nonnegative emission brightness or normal/bump influence. Strength0 neutralizes that effect; normal strength can exceed1 to exaggerate encoded detail.',
 'thinFilm':'Cycles thin-film interference layer. Thickness is explicitly nanometres and its IOR is independent of the base interface. Zero thickness is the neutral control; EEVEE does not support this layer.',
 'thicknessNanometres':'Optical film thickness in nanometres, independent of production length units. It changes wavelength interference above the base material; it does not thicken mesh geometry.',
 'map':'RGB encoded normal-map role: local sampler, strength, tangent/object/world encoding, OpenGL/DirectX convention and original/displaced base. Numeric normal RGB requires a Non-Color image.',
 'sampler':'Local sampler ID defined in this material. Expressions share its captured image/lookup; scalar RGB data requires Non-Color, while alpha and explicit linear luminance can reuse a colour image.',
 'space':'Choose tangent, object or world encoding for normal vectors, or object/world displacement distance. Tangent normals follow a stored UV basis; object normals transform with the object; world normals retain world orientation.',
 'uv':'Tangent basis: follow the normal sampler stored UV set, the render-active set, or an explicit named set. Shader lookup rotation is separate from this basis; use a shared transformed stored map to orient the full finish.',
 'convention':'OpenGL uses positive green for the tangent Y direction; DirectX reverses that direction. Choose the convention in which the image was authored, rather than editing captured pixel bytes.',
 'base':'Use original undisplaced surface normal/tangents when a normal map matches the displacement map, or displaced surface normal/tangents to add further detail after displacement.',
 'bump':'Height-derived shading normal, optionally layered after the encoded RGB normal. Distance follows production units; invert swaps raised/depressed interpretation and filter width controls derivative smoothing.',
 'height':'Scalar height source, constant or an image channel. Bump differentiates height to shade normals; displacement compares it to midlevel and multiplies distance to move the surface.',
 'invert':'Reverse the sign of the height-bump shading effect without rewriting or reinterpreting the captured source image.',
 'filterWidth':'Native bump derivative filter width. Wider filtering smooths high-frequency height detail; it does not increase mesh resolution.',
 'displacement':'Choose none, shading-only bump, actual render geometry displacement, or both. Geometry modes require Cycles and use the existing bounded tessellation. Stored/exported mesh vertices retain the base; typed mesh edits are needed for a geometric handoff.',
 'midlevel':'Height that produces zero displacement. Values above/below it move along/opposite the surface normal after applying distance.',
 'realtime':'Retained EEVEE-specific approximation controls for transmission and inner thickness. Cycles uses its path-traced material model; these named EEVEE policies remain available when changing engines.',
 'transmission':'Light transmitted through the covered surface, separate from opacity. The realtime transmission policy chooses probe approximation or screen ray tracing; screen mode requires render.renderer.rayTracing.screen.',
 'thickness':'EEVEE inner-geometry approximation. Automatic uses the object minimum dimension; explicit sphere/slab distances are connected to the output and scale in object space. Thin walls always connect zero slab thickness.',
 'shadowThickness':'Use shadow-derived thickness in the EEVEE approximation. This is a bulk-material policy and is refused for thin walls; it does not change the stored mesh.',
 'channel':'Select red/green/blue/alpha or linear Rec.709 luminance. Scalar RGB reads numeric Non-Color data; luminance uses0.2126/0.7152/0.0722 on linear RGB. Alpha cannot be sampled from a resource that ignores it.',
 'range':'Map a sampled input interval[0,1] to these two output endpoints with clamping. Reverse the endpoints for inversion. The range uses the controlled quantity units, such as IOR, degrees or nanometres.',
 'value':'Constant value for the selected physical quantity. Colour values are linear RGB; scalar units and useful defaults are defined by their layer or role.',
 'viewportColour':'Independent linear RGB material swatch used by Workbench material previews. It does not replace the physical shader, tint image pixels or change linked geometry.',
 'displayTexture':'Independent Workbench preview image selection. None chooses the swatch fallback; an image selects a captured production resource, using render-active UVs. Physical PBR sampling remains separate.',
}

UV={
 'source':'Original or earlier declared stored UV map copied before applying the transform. Self/forward references refuse; the source is freshly reconstructed from trusted inputs, not from a mutable readback witness.',
 'transform':'Stored UV affine transform: scale about pivot, rotate counterclockwise, then add offset. Reuse the resulting named set in base/ORM/normal samplers and the NormalMap basis. Transform a separate copy after packing; native precision-loss checks protect local features.',
 'offset':'Dimensionless UV translation after pivoted scaling/rotation. Very large offsets can collapse local corners in float32 storage and are refused when that loss occurs.',
 'pivot':'Dimensionless UV point about which scaling and rotation operate. It does not change the original map or the mesh Object origin.',
 'scale':'Signed nonzero U/V scale of stored coordinates about the pivot. Negative components mirror the tangent basis as well as texture lookup; zero or native feature collapse refuses.',
 'rotationDegrees':'Counterclockwise rotation of stored UV coordinates about pivot, in degrees. This affects the native tangent frame when the resulting map is selected by NormalMap.',
}


EXPERT={
 'thinWall':'Treat transmission as a thin sheet without bulk refraction, instead of a solid volume. Cycles uses the Principled thin-wall socket; EEVEE inner thickness is a separate finite artist policy.',
 'diffuseRoughness':'Cycles rough diffuse layer roughness, independent of microfacet reflection roughness. A nonzero authored EEVEE value refuses because that engine does not implement the effect.',
 'subsurface':'Subsurface scattering layer weight, separate from transmitted light and opacity. Choose the scattering method and meaningful distances; thin walls ignore bulk distances.',
 'subsurfaceRadius':'Relative RGB scattering distances: components control how far each colour travels inside the surface. Multiply by subsurfaceScale for the overall distance; not used by thin walls.',
 'subsurfaceScale':'Overall scattering distance in production geometry units, multiplied by the RGB radius. It does not tessellate or move the stored mesh and is inactive on thin walls.',
 'subsurfaceIor':'Skin random-walk interior IOR, available only with RANDOM_WALK_SKIN. It is distinct from the main surface IOR and is refused for other methods.',
 'subsurfaceAnisotropy':'Directional bias for scattering inside the material, from backward through isotropic to forward scattering. This is distinct from anisotropic specular highlights.',
 'specularLevel':'Dielectric interface reflection strength relative to its IOR-based value. Default0.5 preserves the physical IOR response; metallic reflection has separate base-colour semantics.',
 'specularTint':'Linear RGBA tint of the dielectric specular layer; the physical artist route uses RGB. This does not tint a captured image resource in place.',
 'anisotropy':'Signed directional stretching of Cycles specular highlights. Choose a tangent basis to orient the effect. Nonzero EEVEE effects refuse.',
 'anisotropyRotation':'Native fractional-turn rotation of the anisotropic reflection direction. The artist specular layer exposes degrees and converts them to turns.',
 'tangent':'Explicit local tangent vector input for orienting anisotropic highlights. A reviewed tangent node can derive UV or radial directions from the source geometry.',
 'coatRoughness':'Roughness of the independent outer coat reflection. This is separate from the underlying base microfacet roughness.',
 'coatIor':'IOR of the outer coat interface. Its reflection and refraction are separate from the main material IOR.',
 'coatTint':'Linear RGBA coat tint, attenuating the layers underneath the coat. The physical artist route uses RGB.',
 'coatNormal':'Independent coat shading normal vector. Connect a reviewed NormalMap or Bump output; leaving the socket unlinked uses its native surface normal.',
 'sheen':'Strength of the fabric-like grazing sheen layer above the diffuse base. EEVEE approximates this layer; it is not a metal reflection.',
 'sheenRoughness':'Roughness of the fabric sheen response, independent from coat and base roughness.',
 'sheenTint':'Linear RGBA fabric sheen tint. Artist colour expressions use RGB; this socket follows the native colour representation.',
 'thinFilmThickness':'Thin optical coating thickness in nanometres. This controls interference colours in Cycles; nonzero EEVEE thin-film effects refuse.',
 'thinFilmIor':'IOR of the optical thin film, distinct from coat and bulk material IOR. Its interference depends on film thickness in nanometres.',
 'distribution':'GGX or multiple-scattering GGX specular model. MULTI_GGX retains multiple microfacet scattering energy; no arbitrary shader model name is accepted.',
 'subsurfaceMethod':'Burley diffusion, random walk or skin random walk. Only skin random walk admits its separate subsurface IOR; EEVEE supports the documented diffusion approximation.',
 'projection':MEANINGS['projection'], 'projectionBlend':MEANINGS['blend'],
 'uvMap':'Exact named stored UV set for the UV tangent or tangent-space normal basis; empty selects the native render-active set. A named basis is inactive for radial tangents or object/world normal encoding.',
 'convention':MEANINGS['convention'], 'base':MEANINGS['base'], 'filterWidth':MEANINGS['filterWidth'],
 'clamp':'Clamp the colour-mix result to the native unit colour range. This controls the output, not image file bytes, source colour management or texture wrapping.',
 'direction':'Derive a tangent from a named/render-active stored UV map, or use the reviewed radial tangent direction. UV maps and radial axes apply to their respective choices only.',
 'axis':'Object-local radial tangent axis X, Y or Z. This is not an active control for UV-derived tangents.',
 'type':'Transform a direction VECTOR without translation, a POINT including translation, or a NORMAL using inverse-transpose semantics under nonuniform scale.',
 'from':'Coordinate frame of the input vector, point or normal: object-local, world or the active camera frame.',
 'to':'Destination object-local, world or active-camera frame. Normal and direction interpretation follows the separate transform type.',
 'vector':'Input vector/point/normal in the selected source frame. Transform type determines translation and inverse-transpose handling.',
 'height':MEANINGS['height'], 'midlevel':MEANINGS['midlevel'],
 'scale':'Displacement distance in the selected object/world interpretation. Height minus midlevel is multiplied by this value; tessellation remains separately bounded.',
 'normal':'Surface normal direction used to construct the displacement vector. The default unlinked native socket uses the actual surface normal.',
 'colour':'Linear RGBA colour to split into red, green and blue scalar outputs. Use Non-Color image resources when those channels encode numeric data.',
}
CONSTRUCTORS={
 'separateColour':'Split a linear colour into independently linkable red, green and blue scalar channels, useful for packed surface maps.',
 'tangent':'Derive a reviewed UV or radial tangent for directional specular shading.',
 'vectorTransform':'Convert a vector, point or normal between object, world and camera frames with the selected mathematical interpretation.',
 'displacement':'Construct a displacement vector from height, midlevel, distance and normal. Connect it to the material displacement output; actual geometry displacement requires the artist material policy and Cycles.',
}


def main():
    seed('blender');target=Path('src/schemaxis/adaptors/blender/guidance.json');guide=json.loads(target.read_text());changed=0
    for version,route in registry.metadata('blender')['routes'].items():
        entries=guide['routes'][version]['fields']
        for address,node in fields(registry.binding(route['schema'])()):
            names=re.findall(r'/properties/([^/]+)',address);key=names[-1] if names else None
            artist='surfaceMaterials' in names
            # Reconcile the established native minification boundary even on
            # earlier reviewed sampler entries; do not preserve a stale claim.
            if entries[address]['status']!='pending' and not (artist and key=='filter'):continue
            mesh_uv='meshData' in names and 'uvMaps' in names
            expert='materialGraphs' in names or 'nodeGroups' in names
            backend=key=='shadingSystem'
            if not artist and not mesh_uv and not expert and not backend:continue
            if expert:
                branches=[prefix for prefix in entries if address.startswith(prefix+'/') or address==prefix]
                schema=dict(fields(registry.binding(route['schema'])()))
                kind=next((schema[prefix].get('properties',{}).get('kind',{}).get('const')
                           for prefix in reversed(branches) if schema[prefix].get('properties',{}).get('kind',{}).get('const')),None)
                if key in ('id','kind','values','properties') or node.get('properties',{}).get('kind',{}).get('const') in CONSTRUCTORS:
                    meaning=CONSTRUCTORS[kind]
                    if key=='id':meaning+=' This node ID is local to its graph; links use it as a stable identity.'
                    elif key=='values':meaning+=' Only the listed typed sockets are accepted; links override their defaults.'
                    elif key=='properties':meaning+=' Only the listed finite constructor choices are accepted.'
                elif key=='space':
                    meaning=('Normal-map RGB encodes a tangent-space direction, an object-local direction or a world direction. Named UV frames apply only to tangent mode.' if kind=='normalMap' else 'Interpret displacement distance/vector in object-local or world space; nonuniform Object scale distinguishes these modes.')
                else:meaning=EXPERT[key]
                entries[address]={'status':'reviewed','explanation':meaning,'sources':['docs/blender-surface-materials.md','src/schemaxis/adaptors/blender/surface_nodes.py','src/schemaxis/adaptors/blender/node_native.py']};changed+=1;continue
            if backend:
                entries[address]={'status':'reviewed','explanation':'Cycles built-in shader execution backend. Omission or svm selects historical SVM. osl enables built-in Open Shading Language nodes on CPU or OptiX and is required for Smart image filtering; no Script node or authored shader code is enabled. The configured runtime must include OSL.','sources':['docs/blender-surface-materials.md','src/schemaxis/adaptors/blender/render_policy.py','https://docs.blender.org/manual/en/5.2/render/cycles/render_settings/index.html']};changed+=1;continue
            branch=node.get('properties',{}).get('kind',{}).get('const')
            if artist:
                if key=='kind':
                    choice=node.get('const','');meaning='Choose '+str(choice)+' for this physical role. '+MEANINGS.get(names[-2],MEANINGS['surfaceMaterials'])
                elif key=='id' and 'samplers' in names:meaning='Locally unique sampler role ID, reused by this material scalar, colour and normal expressions. It does not rename the global captured image.'
                else:meaning=MEANINGS[key]
                if branch:meaning+=' This alternative selects '+branch+' and admits only its meaningful fields.'
            else:
                if key=='uvMaps':meaning='Copy an original or earlier stored UV map into a distinct named target, with optional stored affine transform. The face-corner topology stays source-bound.'
                elif key=='name':meaning=MEANINGS['name']
                elif key=='pack':meaning='Pack native UV islands before publication. A transformed copy must be authored after a separately packed base; applying pack and transform to one map refuses.'
                elif key=='textureSize':meaning='Target texture width and height in pixels used for UV packing margin. This does not resize captured image bytes.'
                elif key=='paddingPixels':meaning='Requested island padding in target texture pixels. Packing uses the fixed native solver; independent clearance qualification covers retained fixtures rather than arbitrary polygon proofs.'
                elif key=='rotate':meaning='Allow native island rotation during packing. It does not replace the explicit stored UV affine rotation or tangent basis.'
                elif key=='method':meaning='Copy an original or earlier declared stored UV set, optionally applying the explicit affine transform. A copy uses the same face-corner topology and an independently retained target map name.'
                elif key in UV:meaning=UV[key]
                else:continue
            entries[address]={'status':'reviewed','explanation':meaning,'sources':['docs/blender-surface-materials.md',
                'src/schemaxis/adaptors/blender/surface_materials_schema.py','src/schemaxis/adaptors/blender/surface_compile.py',
                'src/schemaxis/adaptors/blender/mesh_data.py','https://docs.blender.org/manual/en/5.2/render/shader_nodes/shader/principled.html']}
            changed+=1
    target.write_text(json.dumps(guide,ensure_ascii=False,indent=2)+'\n');audit=report('blender')
    print(json.dumps({'reviewedArtistFields':changed,'counts':audit['counts'],'complete':audit['complete'],
                      'stale':len(audit['stale']),'linkIssues':len(audit['linkIssues'])}))


if __name__=='__main__':main()
