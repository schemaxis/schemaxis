"""Curate concepts for the three started Blender feature families.

Only the named new feature fields are changed. Existing accepted explanations
outside those fields must survive seeding byte-for-byte as JSON records.
"""
import json
import re
from pathlib import Path

from studio_guidance import seed, report
from blender_cache_guidance import explain as cache_explanation
from blender_npr_guidance import explain as npr_explanation
from schemaxis.adaptors import registry
from schemaxis.studio_guidance import fields


FAMILIES = {
    'viewLayers': 'Reusable views of one production scene. Each logical layer selects collection participation, effective material/World overrides and the passes that may be published. It does not duplicate authored geometry.',
    'renderAovs': 'Named additional render passes. Declare their scalar or colour component type here, enable them on a view layer, and supply materialAovs writers for the intended effective shader owners.',
    'materialAovs': 'Typed additional-pass writers on declared material, World or original captured material owners. A writer adds data output while retaining the surface graph; it is not a replacement surface or a per-part mask.',
    'renderLightgroups': 'Disjoint named contributions from declared lights and optionally the World. Enable group outputs on a layer before publishing them. Unassigned emission or lighting prevents a complete radiance sum.',
    'renderBundles': 'Managed publications of selected cameras and frames: display images or named raw EXR planes. Logical output identities generate relative destinations inside the run; they are not arbitrary paths.',
    'worlds': 'Reusable typed constant-colour or captured-image environment lighting. Select sceneWorld for the scene, or worldOverride on a layer. Lighting, ray visibility, mist and importance sampling are distinct settings.',
    'sceneWorld': 'Logical ID from production.worlds for the ordinary scene World. An empty value keeps the historical render World policy; layer worldOverride can select another declared resource.',
}
FEATURES = {*FAMILIES, 'npr', 'simulationCaches'}
LAYER = {
    'id': 'Logical view-layer identity referenced by bundles, compositor pass sources and NPR layer configurations. It is distinct from a native data-block name.',
    'enabled': 'Include this view in rendering. A disabled layer cannot supply a published pass; disabling a layer does not remove its original scene geometry.',
    'samples': 'Layer sample override. Zero inherits the render sample policy; a positive value requests this layer sampling count where the renderer supports it.',
    'collections': 'Participation rules for declared collections or exact captured asset collection occurrences. Parent exclusions affect descendants; a more specific child rule refines the inherited policy without deleting source data.',
    'target': 'Select a declared collection, or an original nested collection path within one captured asset occurrence. Repeated asset instances can have separate policies.',
    'collection': 'Logical production collection ID. The compiler resolves its actual LayerCollection membership; this is not arbitrary native-name lookup.',
    'asset': 'Logical captured asset occurrence ID. Its path is resolved from freshly captured original collection handles, independently of import suffixes or mutable saved tags.',
    'path': 'Ordered original collection names below this asset root, for example [Assembly, Body]. The path identifies one supported occurrence; ambiguous or unsupported projections are refused.',
    'mode': 'include keeps ordinary participation; exclude removes the selected subtree from this layer; holdout cuts visible surfaces out of it; indirectOnly retains indirect effects while hiding the collection from camera rays.',
    'materialOverride': 'Logical declared material replacing effective surface owners on this layer. Field and AOV checks follow the replacement material actually used after render-time evaluation.',
    'worldOverride': 'Logical production.worlds ID replacing the scene World for this layer. Other layers retain their own World choice; the reference is not a free shader-tree selector.',
    'passes': 'Standard passes to enable: combined/alpha previews, optical-axis depth, world position/normal, motion, UV, indices and renderer-specific lighting components. Engine availability and component types are checked before publication.',
    'aovs': 'Additional pass IDs from renderAovs enabled on this layer. Declaring a writer alone does not enable or publish its pass.',
    'lightgroups': 'IDs from renderLightgroups enabled on this layer. Group membership and enabled group passes are separately checked.',
    'cryptomatte': 'Enable object, material or asset identity coverage with complete rank planes and a full name/hash manifest. This preserves overlapping contributions rather than selecting one winning ID.',
    'object': 'Enable object identity coverage. FLOAT EXR retains the encoded IDs and all declared coverage ranks; this is different from an ordinary object-index number.',
    'material': 'Enable material identity coverage for the effective materials used by this layer, including overrides.',
    'levels': 'Even number of retained Cryptomatte identity/coverage contributions. More levels preserve more overlap and require more channels and output memory.',
    'accurate': 'Request the renderer accurate Cryptomatte mode. This concerns native identity/coverage sampling, not a claim that a single coverage rank is lossless.',
    'alphaThreshold': 'Surface-alpha threshold used by supported data passes. It affects which partially transparent surfaces contribute to those passes, independently of colour-managed preview alpha.',
    'denoisingData': 'Enable the renderer auxiliary denoising planes so explicit denoising pass sources can be published. It does not itself apply a denoiser to scientific outputs.',
}
WRITER = {
    'id': 'Logical writer identity. Every actual shader owner may write a particular AOV once; aliases to the same material cannot create competing writers.',
    'aov': 'ID declared in renderAovs. The writer source must match its scalar or colour component type, and the consuming layer must enable that AOV.',
    'target': 'Choose the actual material or World owner receiving the writer. A captured object/slot nominates its original shared Material owner before Object palettes; it does not isolate a single part.',
    'material': 'Logical declared material ID, including expert graphs or artist surfaces. The compiler uses its actual native handle, even when an imported material has a colliding name.',
    'world': 'Logical World resource ID. A World has no mesh attribute domain; only sources supported by that World owner may be used.',
    'asset': 'Logical captured asset ID containing the original object and material slot nominated by this target.',
    'sourceObject': 'Original captured object name identifying the material owner nomination. It is resolved only from fresh admitted source construction, before later palettes or assignments.',
    'sourceSlot': 'Zero-based original source material slot. Its shared Material writes for all effective users; use layer masks or Cryptomatte for part isolation.',
    'source': 'Choose a numeric constant, named geometry attribute, declared graph output or artist surface channel. A tap reuses the compiled input; arbitrary shader code, native sockets and RNA are not available.',
    'value': 'Numeric scalar or linear RGBA constant matching the selected source and declared AOV component type. A display PNG changes representation; FLOAT EXR is used to preserve numeric planes.',
    'name': 'Stored generic geometry attribute name. Cycles standard names such as temperature, density, color and velocity are refused because they select renderer built-ins instead of a same-named mesh field. Rename both stored field and source, for example sx_temperature; the logical AOV pass name can stay temperature. Required fields are checked on actual render-evaluated geometry after layer/material overrides, including supported instances.',
    'channel': 'For attributes choose factor, alpha, colour or vector output. Artist surfaceChannel instead selects the compiled physical input such as roughness, baseColour, metallic or emissionStrength; component types must agree.',
    'missing': 'error requires the named attribute on effective participating geometry; zero deliberately selects the native zero fallback. This decision does not give a World mesh attributes.',
    'node': 'Logical node ID in the target declared material graph. Imported native node names and unrelated material graphs cannot be guessed or addressed here.',
    'socket': 'Reviewed logical output port on the declared graph node. Shader closures are not numeric AOV data, and unknown or mismatched ports are refused.',
}
PUBLICATION = {
    'id': 'Logical identity unique in this bundle/output scope. It is used to generate a managed file stem or EXR plane name and cannot select an external destination.',
    'frames': 'Explicit unique frame numbers within the production timeline. Omission selects currentFrame. Each frame creates the declared output set and contributes to the aggregate render/output budget.',
    'camera': 'Logical production camera used for this bundle. An empty reference keeps the current supported scene camera policy; arbitrary native camera lookup is not available.',
    'outputs': 'Display-image or multilayer-EXR publications for each requested frame. Their exact channel layouts and managed files are verified before publication.',
    'layers': 'Named semantic planes inside one multilayer EXR. Each plane has an enabled pass/AOV/lightgroup/matte/denoising/compositor source; complete matte ranks may expand into several native slots.',
    'source': 'Choose a pass from an enabled logical view layer, or a declared compositor output. The exact source component type determines the published plane layout.',
    'layer': 'Logical enabled view-layer ID. This reference cannot silently enable an undeclared pass or create a hidden view layer.',
    'pass': 'Standard enabled pass or declared denoising auxiliary plane selected by this source kind. Depth, normals, motion and radiance have different numeric meanings and engine availability.',
    'aov': 'ID from renderAovs, also enabled on the selected layer. Its component type and effective shader writers remain part of verification.',
    'lightgroup': 'ID from renderLightgroups enabled on the selected layer. Raw RGB contains that group contribution; alpha is not an additive radiance value.',
    'matte': 'Select object, material or asset Cryptomatte coverage already enabled on the layer. All requested coverage ranks and the complete identity manifest are retained together.',
    'node': 'Logical node in the declared compositor graph supplying this publication. It is not an arbitrary native compositor-node name.',
    'socket': 'Reviewed logical compositor output port. Its declared component type is used when validating the file layout.',
    'encoding': 'PNG is a colour-managed display preview. EXR retains raw linear/scientific channels with an explicit precision and lossless compression choice.',
    'precision': 'float uses full FLOAT EXR components; half deliberately reduces ordinary component precision. Encoded matte IDs and object/material numeric indices require float.',
    'depth': 'PNG integer precision, 8 or 16 bits per channel. This does not turn a colour-managed preview into raw scientific data.',
    'channels': 'Choose RGB or RGBA PNG storage. Omitting alpha loses that display coverage channel; it does not change the underlying scene participation.',
    'compression': 'Lossless storage setting: PNG uses its integer compression level; EXR chooses none, single-scanline zips or multi-scanline zip. Compression does not change numeric intent.',
}
WORLD = {
    'id': 'Logical reusable World identity. sceneWorld and per-layer worldOverride refer to this resource, independently of surface-material IDs and native names.',
    'lighting': 'Constant linear RGB illumination or a captured image environment, with independent nonnegative strength. This finite resource does not expose a general World node editor or scripts.',
    'colour': 'Linear RGB environment colour before output display mapping. Strength controls illumination independently; image colour interpretation belongs to the captured image resource.',
    'strength': 'Nonnegative environment illumination multiplier. Zero is a useful neutral-light control and does not remove the declared World resource.',
    'image': 'ID from production.images, capturing the original environment image bytes and declared colour interpretation. Keep numeric HDR lighting separate from an sRGB display preview.',
    'rotation': 'XYZ environment orientation in radians, applied to the environment lookup. This rotates lighting directions, not geometry or the camera.',
    'projection': 'equirectangular interprets a latitude/longitude panorama; mirrorBall uses the native mirrored-ball image mapping. Choose the projection in which the image was authored.',
    'interpolation': 'Nearest, linear or cubic native environment-image filtering. This is separate from image colour space and from general surface-material sampler options.',
    'visibility': 'Cycles ray-class visibility for this World: camera, diffuse, glossy, transmission, shadow and scatter. Hiding a background from camera rays need not remove its lighting.',
    'camera': 'Allow the World on direct camera/background rays. Other visibility classes independently control lighting paths.',
    'diffuse': 'Allow this World on diffuse reflection paths, independently of direct camera visibility.',
    'glossy': 'Allow this World on glossy reflection paths, independently of diffuse and direct background visibility.',
    'transmission': 'Allow this World on transmitted/refraction paths through surfaces.',
    'shadow': 'Allow this World in the supported shadow-ray visibility class; other ray classes retain their declared values.',
    'scatter': 'Allow this World on volume-scattering paths supported by the renderer; this setting does not create a volume.',
    'mist': 'No mist contribution, or the finite distance-based mist pass policy. Enable the layer mist pass to publish the result; this is not a physical scattering-volume constructor.',
    'start': 'Scene-coordinate distance where the distance mist ramp begins. Use the same geometric coordinate scale as the scene and camera.',
    'depth': 'Positive scene-coordinate distance over which the mist ramp develops after start. It is independent of PNG bit depth and optical depth output.',
    'height': 'Native height influence on the distance mist policy. It affects the mist pass, not object height or a mesh transformation.',
    'falloff': 'Choose the native quadratic, linear or inverse-quadratic mist ramp shape. This controls the pass response, not image colour management.',
    'sampling': 'automatic, manual or none World importance-sampling intent. It affects how environment illumination is sampled, independently of camera visibility or image interpolation.',
    'samplingResolution': 'Importance-map resolution for supported World sampling. Higher resolution can represent more lighting detail but uses additional bounded memory; it does not resize captured image bytes.',
}


def meaning(names, node):
    family = next((name for name in names if name in FEATURES), None)
    if family == 'npr':
        return npr_explanation(names, node)
    if family == 'simulationCaches':
        return cache_explanation(names, node)
    if family is None:
        return None
    tail = names[names.index(family) + 1:]
    if not tail:
        return FAMILIES[family]
    key = tail[-1]
    kind = node.get('const')
    if kind is None and len(node.get('enum', [])) == 1:
        kind = node['enum'][0]
    if key == 'kind':
        choices = {
            'collection': 'Select a declared logical production collection for this layer rule.',
            'asset': 'Select one captured asset occurrence and its original nested collection path for this layer rule.',
            'material': 'Nominate a declared material owner for this AOV writer.',
            'world': 'Nominate a declared World resource owner for this AOV writer.',
            'captured': 'Nominate the original captured object/slot Material owner, shared by every effective user; this is not a per-part mask.',
            'value': 'Write an explicit numeric scalar constant into a value AOV.',
            'colour': 'Use a linear colour constant or constant-colour environment, as indicated by this enclosing writer/World record.',
            'attribute': 'Read a named stored attribute on effective render geometry with explicit channel and missing-field policy.',
            'graphOutput': 'Tap an existing reviewed logical material-graph output port without replacing the surface graph.',
            'surfaceChannel': 'Tap an artist surface physical channel, reusing its existing constant or linked input.',
            'pass': 'Publish a standard pass already enabled on the selected logical view layer.',
            'aov': 'Publish an additional typed pass declared and enabled on the selected logical view layer.',
            'lightgroup': 'Publish the raw contribution of a declared disjoint lighting group enabled on the layer.',
            'cryptomatte': 'Publish all declared identity/coverage ranks together with the complete name/hash manifest.',
            'denoising': 'Publish an enabled denoising auxiliary plane without substituting it for a scientific pass.',
            'compositor': 'Publish a reviewed output of the declared compositor graph.',
            'image': 'Write one selected semantic source as a display PNG or explicitly encoded EXR image.',
            'multilayer': 'Write named semantic planes together in one EXR, preserving the declared full channel layout.',
            'png': 'Write a colour-managed integer display preview; scientific planes require raw EXR for numeric fidelity.',
            'exr': 'Write raw linear/scientific components with explicit FLOAT/HALF precision and lossless compression.',
            'environment': 'Light the scene from a captured environment image with explicit mapping, rotation, interpolation and strength.',
            'none': 'Disable this optional World mist contribution while retaining the ordinary World lighting resource.',
            'distance': 'Use the declared finite start/depth/height/falloff policy for a distance mist pass.',
        }
        return choices.get(kind)
    if family == 'viewLayers':
        if key == 'asset' and 'cryptomatte' in tail:
            return 'Enable asset identity coverage with all requested FLOAT EXR ranks and the complete original identity manifest.'
        return LAYER.get(key)
    if family == 'renderAovs':
        return {'id': 'Logical additional-pass name, distinct from reserved built-in pass names. Use it in writers, view-layer AOV enables and publication references.',
                'type': 'value stores scalar numeric data; colour stores colour/vector components. Writer source and published layout must agree; these are not display colour-management choices.'}.get(key)
    if family == 'materialAovs':
        return WRITER.get(key)
    if family == 'renderLightgroups':
        return {'id': 'Logical lighting contribution ID referenced by enabled layers and bundle sources.',
                'lights': 'Declared production light IDs assigned to this contribution. A light cannot belong to two groups; mutable native names or saved membership claims are not authority.',
                'world': 'Include the effective World contribution in this group. Assign the World to at most one group, and account for all radiance contributors before testing a beauty sum.'}.get(key)
    if family == 'renderBundles':
        return PUBLICATION.get(key)
    if family == 'worlds':
        return WORLD.get(key)
    return None


def main():
    target = Path('src/schemaxis/adaptors/blender/guidance.json')
    before = json.loads(target.read_text())
    seed('blender')
    guide = json.loads(target.read_text())
    changed = 0
    unknown = []
    for version, route in registry.metadata('blender')['routes'].items():
        entries = guide['routes'][version]['fields']
        for address, node in fields(registry.binding(route['schema'])()):
            names = re.findall(r'/properties/([^/]+)', address)
            family = next((name for name in names if name in FEATURES), None)
            if family is None:
                continue
            explanation = meaning(names, node)
            if explanation is None:
                unknown.append((version, address))
                continue
            docs = ('docs/blender-freestyle.md' if family == 'npr' else
                    'docs/blender-simulation-caches.md' if family == 'simulationCaches' else
                    'docs/blender-render-bundles.md')
            entries[address] = {'status': 'reviewed', 'explanation': explanation,
                                'sources': [docs, 'src/schemaxis/adaptors/blender/render_features.py']}
            changed += 1
    if unknown:
        raise RuntimeError('New fields need explicit conceptual review: ' + repr(unknown))
    for version, route in before['routes'].items():
        for address, old in route['fields'].items():
            names = re.findall(r'/properties/([^/]+)', address)
            if not any(name in FEATURES for name in names) and old.get('status') != 'pending':
                if guide['routes'][version]['fields'].get(address) != old:
                    raise RuntimeError('Accepted guidance outside the new features changed: ' + address)
    target.write_text(json.dumps(guide, ensure_ascii=False, indent=2) + '\n')
    audit = report('blender')
    print(json.dumps({'reviewedFeatureFields': changed, 'counts': audit['counts'],
                      'complete': audit['complete'], 'stale': len(audit['stale']),
                      'linkIssues': len(audit['linkIssues'])}))


if __name__ == '__main__':
    main()
