"""Native node mapping from the finite reviewed descriptor catalogue."""
import bpy
from .node_catalogue import CATALOGUES
from .settings import matching
from schemaxis.errors import fail


def port(ports,key):
    if type(key) is int:return ports[key]
    try:return ports[key]
    except KeyError:pass
    found=next((p for p in ports if p.name==key),None)
    if found is None:fail('UNSUPPORTED_NATIVE_SOCKET','reviewed socket unavailable',str(key),available=[p.name for p in ports])
    return found


def plain(item):
    from .node_group_native import plain as convert
    return convert(item)


def build(spec,family,images,materials,groups=None,native_groups=None,interface=None,objects=None,collections=None):
    resources={'image':images,'material':materials,'object':objects or {},'collection':collections or {}}
    if family=='material' and interface is None:
        owner=bpy.data.materials.new(spec['id']);owner.use_nodes=True;tree=owner.node_tree;tree.nodes.clear()
        if 'viewportColour' in spec:owner.diffuse_color=(*spec['viewportColour'],1)
        if 'surfacePolicy' in spec:
            owner.displacement_method=spec['surfacePolicy']['displacement']
            owner.thickness_mode=spec['surfacePolicy']['thickness']
            owner.use_raytrace_refraction=spec['surfacePolicy']['raytracedTransmission']
            owner.use_thickness_from_shadow=spec['surfacePolicy']['shadowThickness']
    else:
        tree=bpy.data.node_groups.new(spec['id'],{'material':'ShaderNodeTree','geometry':'GeometryNodeTree','compositor':'CompositorNodeTree'}[family]);owner=tree
        if interface is not None:
            from .node_group_native import create_interface
            create_interface(tree,interface,resources)
        elif family=='geometry':
            for direction in ('INPUT','OUTPUT'):tree.interface.new_socket(name='Geometry',in_out=direction,socket_type='NodeSocketGeometry')
        else:tree.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
    from .node_groups import descriptor
    from .node_group_native import assign
    nodes={}
    for i,authored in enumerate(spec['nodes']):
        desc=descriptor(authored,family,groups,interface)
        try:n=tree.nodes.new(desc['native'])
        except RuntimeError as e:fail('UNSUPPORTED_NATIVE_NODE','reviewed node unavailable in runtime',authored['id'],reason=str(e))
        if authored['kind']=='group':n.node_tree=native_groups[authored['group']]
        n.name=authored['id'];n.label=authored['id'];n.location=(i*200,0);nodes[n.name]=n
        if family=='compositor' and authored['kind']=='mix':n.data_type='RGBA'
        for key,value in authored['properties'].items():
            prop=desc['properties'][key][0]
            if prop in ('outputValue','outputColour'):n.outputs[0].default_value=value
            elif prop=='image':n.image=images[value]
            else:setattr(n,prop,value)
        for key,value in authored['values'].items():
            target=port(n.inputs,desc['inputs'][key]['native'])
            assign(target,value,desc['inputs'][key]['kind'],family,resources)
    for link in spec['links']:
        a,b=link['from'],link['to'];source,target=nodes[a['node']],nodes[b['node']]
        source_desc=descriptor(next(n for n in spec['nodes'] if n['id']==a['node']),family,groups,interface)
        target_desc=descriptor(next(n for n in spec['nodes'] if n['id']==b['node']),family,groups,interface)
        out=port(source.outputs,source_desc['outputs'][a['socket']]['native']);inp=port(target.inputs,target_desc['inputs'][b['socket']]['native'])
        if not out.enabled or not inp.enabled:fail('INACTIVE_SOCKET','linked socket is inactive for chosen node properties',spec['id'])
        tree.links.new(out,inp)
    if 'displayTexture' in spec:
        from .material_display_native import build as build_display
        build_display(tree,spec['displayTexture'],images)
    owner.use_fake_user=True
    return owner


def observe(spec,family,groups=None,interface=None,objects=None,collections=None,features=None):
    from .node_groups import descriptor
    owner=(features.production.materials.get(spec['id']) if features is not None else bpy.data.materials.get(spec['id'])) if family=='material' and interface is None else bpy.data.node_groups.get(spec['id'])
    if owner is None:fail('VERIFICATION_FAILED','node graph missing',spec['id'])
    tree=owner.node_tree if family=='material' and interface is None else owner;records=[];lookup={}
    auxiliary=features.auxiliary(owner) if features is not None and family=='material' and interface is None else ()
    if auxiliary:features.verify_auxiliary(owner)
    auxiliary_names={n['id'] for part in auxiliary for n in part['nodes']}
    if features is not None and family=='compositor':auxiliary_names|=features.compositor_auxiliary(tree)
    if tree.animation_data or owner.animation_data:fail('VERIFICATION_FAILED','undeclared node graph animation',spec['id'])
    if family=='material' and interface is None and not owner.use_nodes:fail('VERIFICATION_FAILED','material node shading disabled',spec['id'])
    resources={'object':objects or {},'collection':collections or {},'material':{m.name:m for m in bpy.data.materials},'image':{i.name:i for i in bpy.data.images}}
    if features is not None:
        resources['material']=features.production.materials;resources['image']=features.production.images
    from .node_group_native import reference_value
    for authored in spec['nodes']:
        n=tree.nodes.get(authored['id']);desc=descriptor(authored,family,groups,interface)
        if n is None or n.bl_idname!=desc['native']:fail('VERIFICATION_FAILED','node identity/type differs',authored['id'])
        if hasattr(n,'is_active_output') and authored['kind']=='output' and not n.is_active_output:fail('VERIFICATION_FAILED','declared node output is inactive',n.name)
        if n.mute:fail('VERIFICATION_FAILED','node graph contains a muted node',n.name)
        if n.bl_idname=='ShaderNodeOutputMaterial' and n.target!='ALL':fail('VERIFICATION_FAILED','material output target changed',n.name)
        if authored['kind']=='group' and (not n.node_tree or n.node_tree.name!=authored['group']):fail('VERIFICATION_FAILED','nested group identity differs',n.name)
        values={key:reference_value(port(n.inputs,desc['inputs'][key]['native']).default_value,authored['values'][key],desc['inputs'][key]['kind'],family,resources) if (desc['inputs'][key]['kind'] in ('object','collection') and objects is not None or features is not None and desc['inputs'][key]['kind'] in ('material','image')) else plain(port(n.inputs,desc['inputs'][key]['native']).default_value) for key in authored['values']}
        for key in values:
            if values[key] is None and desc['inputs'][key]['kind'] in ('object','material','collection','image') and not (family=='compositor' and desc['inputs'][key]['kind']=='image'):values[key]=''
        props={}
        for key in authored['properties']:
            prop=desc['properties'][key][0]
            props[key]=reference_value(n.image,authored['properties'][key],'image',family,resources) if prop=='image' and features is not None else plain(n.outputs[0].default_value if prop in ('outputValue','outputColour') else getattr(n,prop))
        records.append({'id':n.name,'kind':authored['kind'],'values':values,'properties':props,**({'group':n.node_tree.name} if authored['kind']=='group' else {})})
        for direction,ports in [('from',n.outputs),('to',n.inputs)]:
            for semantic,specification in desc['outputs' if direction=='from' else 'inputs'].items():lookup[(direction,n.name,port(ports,specification['native']).identifier)]=semantic
    links=[]
    for link in tree.links:
        if link.from_node.name in auxiliary_names or link.to_node.name in auxiliary_names:continue
        if link.is_muted:fail('VERIFICATION_FAILED','node graph contains a muted link',spec['id'])
        try:links.append({'from':{'node':link.from_node.name,'socket':lookup[('from',link.from_node.name,link.from_socket.identifier)]},'to':{'node':link.to_node.name,'socket':lookup[('to',link.to_node.name,link.to_socket.identifier)]}})
        except KeyError:fail('VERIFICATION_FAILED','undeclared native node link',spec['id'])
    links.sort(key=lambda l:(l['to']['node'],l['to']['socket'],l['from']['node'],l['from']['socket']))
    if len(tree.nodes)!=len(records)+int('displayTexture' in spec)+len(auxiliary_names):fail('VERIFICATION_FAILED','node graph membership differs',spec['id'])
    result={'id':spec['id'],'nodes':records,'links':links}
    if 'viewportColour' in spec:
        if owner.diffuse_color[3]!=1:fail('VERIFICATION_FAILED','viewport material alpha changed',spec['id'])
        result['viewportColour']=list(owner.diffuse_color)[:3]
    if 'displayTexture' in spec:
        from .material_display_native import observe as observe_display
        result['displayTexture']=observe_display(tree)
        if features is not None and result['displayTexture']['kind']=='image':
            identity=spec['displayTexture']['image']
            if tree.nodes['__schemaxis_display_texture'].image!=features.production.images[identity]:fail('VERIFICATION_FAILED','display texture image differs from fresh logical resource',identity)
            result['displayTexture']['image']=identity
    if 'surfacePolicy' in spec:
        result['surfacePolicy']={'displacement':owner.displacement_method,'thickness':owner.thickness_mode,
                                'raytracedTransmission':owner.use_raytrace_refraction,
                                'shadowThickness':owner.use_thickness_from_shadow}
    if interface:
        from .node_group_native import observe_interface
        result.update(family=family,**observe_interface(tree,interface,resources if objects is not None else None))
    return result


def verify(spec,actual):
    expected={**spec,'links':sorted(spec['links'],key=lambda l:(l['to']['node'],l['to']['socket'],l['from']['node'],l['from']['socket']))}
    if not matching(actual,expected):fail('VERIFICATION_FAILED','node graph native values/links differ',spec['id'])
