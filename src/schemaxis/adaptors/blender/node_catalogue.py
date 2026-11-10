"""Reviewed node constructors, semantic sockets and properties; no native imports.

Authored names are semantic identifiers from this catalogue, never RNA paths.
The same descriptors drive schema, validation, native assignment and readback.
"""
from schemaxis.core.declarations import validate_arguments
from schemaxis.schema import arguments_schema, object_schema
from schemaxis.errors import fail


from .node_specs import (number,integer,vector,colour,choice,boolean,text,
                         socket,node,S,V,C,G,H,I)

MATH=['ADD','SUBTRACT','MULTIPLY','DIVIDE','MULTIPLY_ADD','POWER','LOGARITHM','SQRT','ABSOLUTE','MINIMUM','MAXIMUM','LESS_THAN','GREATER_THAN','COMPARE','SINE','COSINE','TANGENT','ARCTAN2','FLOOR','CEIL','FRACT','MODULO','PINGPONG','SMOOTH_MIN','SMOOTH_MAX','WRAP','SNAP']
SHARED={
 'value':node('ShaderNodeValue',outputs={'value':S('Value')},properties={'value':('outputValue',number())}),
 'colour':node('ShaderNodeRGB',outputs={'colour':C('Color')},properties={'colour':('outputColour',colour())}),
 'math':node('ShaderNodeMath',{'a':S(0),'b':S(1),'c':S(2)},{'value':S('Value')},{'operation':('operation',choice('MULTIPLY',MATH)),'clamp':('use_clamp',boolean())}),
 'vectorMath':node('ShaderNodeVectorMath',{'a':V(0),'b':V(1),'c':V(2),'scale':S('Scale',1)}, {'vector':V('Vector'),'value':S('Value')},{'operation':('operation',choice('ADD',['ADD','SUBTRACT','MULTIPLY','DIVIDE','CROSS_PRODUCT','DOT_PRODUCT','DISTANCE','LENGTH','SCALE','NORMALIZE','ABSOLUTE','MINIMUM','MAXIMUM','FLOOR','CEIL','FRACTION','MODULO','WRAP','SNAP','SINE','COSINE','TANGENT']))}),
 'combineXYZ':node('ShaderNodeCombineXYZ',{'x':S('X'),'y':S('Y'),'z':S('Z')},{'vector':V('Vector')}),
 'separateXYZ':node('ShaderNodeSeparateXYZ',{'vector':V('Vector')},{'x':S('X'),'y':S('Y'),'z':S('Z')}),
 'mapRange':node('ShaderNodeMapRange',{'value':S('Value'),'fromMin':S('From Min'),'fromMax':S('From Max',1),'toMin':S('To Min'),'toMax':S('To Max',1)}, {'value':S('Result')},{'clamp':('clamp',boolean(True))}),
 'noise':node('ShaderNodeTexNoise',{'vector':V('Vector'),'scale':S('Scale',5),'detail':S('Detail',2),'roughness':S('Roughness',.5),'distortion':S('Distortion')},{'factor':S('Factor'),'colour':C('Color')}),
 'voronoi':node('ShaderNodeTexVoronoi',{'vector':V('Vector'),'scale':S('Scale',5),'randomness':S('Randomness',1)},{'distance':S('Distance'),'colour':C('Color'),'position':V('Position')}),
 'wave':node('ShaderNodeTexWave',{'vector':V('Vector'),'scale':S('Scale',5),'distortion':S('Distortion'),'phase':S('Phase Offset')},{'factor':S('Fac'),'colour':C('Color')},{'type':('wave_type',choice('BANDS',['BANDS','RINGS']))}),
}
MATERIAL={**SHARED,
 'output':node('ShaderNodeOutputMaterial',{'surface':H('Surface'),'volume':H('Volume'),'displacement':V('Displacement')}),
 'principled':node('ShaderNodeBsdfPrincipled',{'colour':C('Base Color'),'metallic':S('Metallic'),'roughness':S('Roughness',.5),'ior':S('IOR',1.5),'alpha':S('Alpha',1),'normal':V('Normal'),'transmission':S('Transmission Weight'),'coat':S('Coat Weight'),'emission':C('Emission Color',(0,0,0,1)),'emissionStrength':S('Emission Strength')},{'shader':H('BSDF')}),
 'diffuse':node('ShaderNodeBsdfDiffuse',{'colour':C('Color'),'roughness':S('Roughness'),'normal':V('Normal')},{'shader':H('BSDF')}),
 'glass':node('ShaderNodeBsdfGlass',{'colour':C('Color',(1,1,1,1)),'roughness':S('Roughness'),'ior':S('IOR',1.45),'normal':V('Normal')},{'shader':H('BSDF')}),
 'transparent':node('ShaderNodeBsdfTransparent',{'colour':C('Color',(1,1,1,1))},{'shader':H('BSDF')}),
 'emission':node('ShaderNodeEmission',{'colour':C('Color'),'strength':S('Strength',1)},{'shader':H('Emission')}),
 'mixShader':node('ShaderNodeMixShader',{'factor':S(0,.5),'a':H(1),'b':H(2)},{'shader':H('Shader')}),
 'addShader':node('ShaderNodeAddShader',{'a':H(0),'b':H(1)},{'shader':H('Shader')}),
 'volume':node('ShaderNodeVolumePrincipled',{'colour':C('Color'),'density':S('Density',1),'anisotropy':S('Anisotropy')},{'shader':H('Volume')}),
 'coordinates':node('ShaderNodeTexCoord',outputs={k:V(n) for k,n in [('generated','Generated'),('normal','Normal'),('uv','UV'),('object','Object'),('camera','Camera'),('reflection','Reflection')]}),
 'mapping':node('ShaderNodeMapping',{'vector':V('Vector'),'translation':V('Location'),'rotation':V('Rotation'),'scale':V('Scale',(1,1,1))},{'vector':V('Vector')}),
 'checker':node('ShaderNodeTexChecker',{'vector':V('Vector'),'a':C('Color1',(.1,.1,.1,1)),'b':C('Color2'),'scale':S('Scale',5)},{'colour':C('Color'),'factor':S('Fac')}),
 'image':node('ShaderNodeTexImage',{'vector':V('Vector')},{'colour':C('Color'),'alpha':S('Alpha')},{'image':('image',text()),'interpolation':('interpolation',choice('Linear',['Linear','Closest','Cubic','Smart'])),'extension':('extension',choice('REPEAT',['REPEAT','EXTEND','CLIP','MIRROR']))}),
 'normalMap':node('ShaderNodeNormalMap',{'strength':S('Strength',1),'colour':C('Color',(.5,.5,1,1))},{'normal':V('Normal')}),
 'bump':node('ShaderNodeBump',{'strength':S('Strength',1),'distance':S('Distance',.1),'height':S('Height'),'normal':V('Normal')},{'normal':V('Normal')},{'invert':('invert',boolean())}),
 'mixColour':node('ShaderNodeMixRGB',{'factor':S(0,.5),'a':C(1),'b':C(2)},{'colour':C('Color')},{'blend':('blend_type',choice('MIX',['MIX','ADD','MULTIPLY','SUBTRACT','SCREEN','OVERLAY','DIFFERENCE','DIVIDE','DARKEN','LIGHTEN','SOFT_LIGHT','LINEAR_LIGHT','HUE','SATURATION','VALUE','COLOR']))}),
}
MATERIAL.update({
 'uvMap':node('ShaderNodeUVMap',outputs={'uv':V('UV')},properties={'name':('uv_map',text())}),
 'attribute':node('ShaderNodeAttribute',outputs={'colour':C('Color'),'vector':V('Vector'),'factor':S('Fac'),'alpha':S('Alpha')},properties={'name':('attribute_name',text())}),
})
GEOMETRY={**{k:v for k,v in SHARED.items() if k!='colour'},
 'input':node('NodeGroupInput',outputs={'geometry':G('Geometry')}),
 'output':node('NodeGroupOutput',{'geometry':G('Geometry')}),
 'position':node('GeometryNodeInputPosition',outputs={'position':V('Position')}),
 'normal':node('GeometryNodeInputNormal',outputs={'normal':V('Normal')}),
 'index':node('GeometryNodeInputIndex',outputs={'index':S('Index')}),
 'sceneTime':node('GeometryNodeInputSceneTime',outputs={'seconds':S('Seconds'),'frame':S('Frame')}),
 'transform':node('GeometryNodeTransform',{'geometry':G('Geometry'),'translation':V('Translation'),'rotation':V('Rotation'),'scale':V('Scale',(1,1,1))},{'geometry':G('Geometry')}),
 'setPosition':node('GeometryNodeSetPosition',{'geometry':G('Geometry'),'selection':socket('Selection','boolean',boolean(True)),'position':V('Position'),'offset':V('Offset')},{'geometry':G('Geometry')}),
 'join':node('GeometryNodeJoinGeometry',{'geometry':G('Geometry')},{'geometry':G('Geometry')}),
 'cube':node('GeometryNodeMeshCube',{'size':V('Size',(1,1,1)),'xVertices':S('Vertices X',2),'yVertices':S('Vertices Y',2),'zVertices':S('Vertices Z',2)},{'geometry':G('Mesh')}),
 'grid':node('GeometryNodeMeshGrid',{'width':S('Size X',1),'height':S('Size Y',1),'xVertices':S('Vertices X',2),'yVertices':S('Vertices Y',2)},{'geometry':G('Mesh')}),
 'icoSphere':node('GeometryNodeMeshIcoSphere',{'radius':S('Radius',1),'subdivisions':S('Subdivisions',1)},{'geometry':G('Mesh')}),
 'meshToCurve':node('GeometryNodeMeshToCurve',{'mesh':G('Mesh')},{'curve':G('Curve')}),
 'curveCircle':node('GeometryNodeCurvePrimitiveCircle',{'resolution':S('Resolution',32),'radius':S('Radius',1)},{'curve':G('Curve')}),
 'curveToMesh':node('GeometryNodeCurveToMesh',{'curve':G('Curve'),'profile':G('Profile Curve'),'fillCaps':socket('Fill Caps','boolean',boolean())},{'mesh':G('Mesh')}),
 'resampleCurve':node('GeometryNodeResampleCurve',{'curve':G('Curve'),'count':S('Count',10)},{'curve':G('Curve')}),
 'subdivide':node('GeometryNodeSubdivideMesh',{'mesh':G('Mesh'),'level':S('Level',1)},{'mesh':G('Mesh')}),
 'triangulate':node('GeometryNodeTriangulate',{'mesh':G('Mesh')},{'mesh':G('Mesh')}),
 'mergeByDistance':node('GeometryNodeMergeByDistance',{'geometry':G('Geometry'),'distance':S('Distance',.001)},{'geometry':G('Geometry')}),
 'instanceOnPoints':node('GeometryNodeInstanceOnPoints',{'points':G('Points'),'instance':G('Instance'),'rotation':V('Rotation'),'scale':V('Scale',(1,1,1))},{'instances':G('Instances')}),
 'realiseInstances':node('GeometryNodeRealizeInstances',{'geometry':G('Geometry')},{'geometry':G('Geometry')}),
 'setMaterial':node('GeometryNodeSetMaterial',{'geometry':G('Geometry'),'material':socket('Material','material',text())},{'geometry':G('Geometry')}),
 'deleteGeometry':node('GeometryNodeDeleteGeometry',{'geometry':G('Geometry'),'selection':socket('Selection','boolean',boolean())},{'geometry':G('Geometry')}),
 'extrudeMesh':node('GeometryNodeExtrudeMesh',{'mesh':G('Mesh'),'offset':V('Offset'),'offsetScale':S('Offset Scale',1),'individual':socket('Individual','boolean',boolean(True))},{'mesh':G('Mesh'),'top':socket('Top','boolean'),'side':socket('Side','boolean')}),
 'namedAttribute':node('GeometryNodeInputNamedAttribute',{'name':socket('Name','string',text())},{'attribute':S('Attribute'),'exists':socket('Exists','boolean')},{'dataType':('data_type',choice('FLOAT',['FLOAT','INT','FLOAT_VECTOR','FLOAT_COLOR','BOOLEAN','QUATERNION']))}),
}
GEOMETRY.update({
 'objectInfo':node('GeometryNodeObjectInfo',{'object':socket('Object','object',text()),'asInstance':socket('As Instance','boolean',boolean())},{'geometry':G('Geometry'),'location':V('Location'),'rotation':socket('Rotation','rotation'),'scale':V('Scale'),'transform':socket('Transform','matrix')},{'space':('transform_space',choice('ORIGINAL',['ORIGINAL','RELATIVE']))}),
 'collectionInfo':node('GeometryNodeCollectionInfo',{'collection':socket('Collection','collection',text()),'separateChildren':socket('Separate Children','boolean',boolean()),'resetChildren':socket('Reset Children','boolean',boolean())},{'instances':G('Instances')},{'space':('transform_space',choice('ORIGINAL',['ORIGINAL','RELATIVE']))}),
})
COMPOSITOR={
 'render':node('CompositorNodeRLayers',outputs={'image':I('Image'),'alpha':S('Alpha')}),
 'output':node('NodeGroupOutput',{'image':I('Image')}),
 'blur':node('CompositorNodeBlur',{'image':I('Image'),'size':socket('Size','vector2',{'type':'array','items':{'type':'number','minimum':0,'maximum':256},'minItems':2,'maxItems':2,'default':[4,4]})},{'image':I('Image')}),
 'glare':node('CompositorNodeGlare',{'image':I('Image'),'threshold':S('Threshold',1),'strength':S('Strength',1),'size':S('Size',.5)},{'image':I('Image')}),
 'exposure':node('CompositorNodeExposure',{'image':I('Image'),'exposure':S('Exposure')},{'image':I('Image')}),
 'gamma':node('ShaderNodeGamma',{'image':I('Color'),'gamma':S('Gamma',1)},{'image':I('Color')}),
 'brightContrast':node('CompositorNodeBrightContrast',{'image':I('Image'),'brightness':S('Bright'),'contrast':S('Contrast')},{'image':I('Image')}),
 'hueSaturation':node('CompositorNodeHueSat',{'image':I('Image'),'hue':S('Hue',.5),'saturation':S('Saturation',1),'value':S('Value',1),'factor':S('Fac',1)},{'image':I('Image')}),
 'invert':node('CompositorNodeInvert',{'factor':S('Fac',1),'image':I('Color')},{'image':I('Color')}),
 'mix':node('ShaderNodeMix',{'factor':S(0,.5),'a':I(6),'b':I(7)},{'image':I(2)},{'blend':('blend_type',choice('MIX',['MIX','ADD','MULTIPLY','SUBTRACT','SCREEN','OVERLAY','DIFFERENCE','DIVIDE','DARKEN','LIGHTEN']))}),
 'alphaOver':node('CompositorNodeAlphaOver',{'factor':S('Factor',1),'a':I('Background'),'b':I('Foreground')},{'image':I('Image')}),
 'transform':node('CompositorNodeTransform',{'image':I('Image'),'x':S('X'),'y':S('Y'),'angle':S('Angle'),'scale':S('Scale',1)},{'image':I('Image')}),
 'lensDistortion':node('CompositorNodeLensdist',{'image':I('Image'),'distortion':S('Distortion'),'dispersion':S('Dispersion')},{'image':I('Image')}),
}
# Bounds precede native assignment: native integer sockets otherwise clamp or
# allow explosive topology requests that cannot safely be evaluated first.
for _kind,_fields in {
 'cube':{'xVertices':(2,2,64),'yVertices':(2,2,64),'zVertices':(2,2,64)},
 'grid':{'xVertices':(2,2,128),'yVertices':(2,2,128)},
 'icoSphere':{'subdivisions':(1,1,5)},
 'curveCircle':{'resolution':(32,3,4096)},
 'resampleCurve':{'count':(10,2,4096)},
 'subdivide':{'level':(1,0,4)},
}.items():
 for _key,(_default,_minimum,_maximum) in _fields.items():
  GEOMETRY[_kind]['inputs'][_key]['value']=integer(_default,minimum=_minimum,maximum=_maximum)
for _key in ('metallic','roughness','alpha','transmission','coat'):
 MATERIAL['principled']['inputs'][_key]['value']=number(MATERIAL['principled']['inputs'][_key]['value']['default'],minimum=0,maximum=1)
MATERIAL['principled']['inputs']['ior']['value']=number(1.5,minimum=1,maximum=4)

# Keep historical group/schema variant positions when appending surface nodes.
GROUP_AT={'material':list(MATERIAL).index('uvMap'),'geometry':list(GEOMETRY).index('objectInfo')}
from .surface_nodes import extend as extend_surface_nodes
extend_surface_nodes(MATERIAL)

CATALOGUES={'material':MATERIAL,'geometry':GEOMETRY,'compositor':COMPOSITOR}


def material_display_fields():
    from .render_policy import rgb,union,variant
    return {'viewportColour':rgb((.8,.8,.8)),
            'displayTexture':union([variant('none',{}),variant('image',{'image':{'type':'string','minLength':1,'maxLength':128,'required':True}})],{'kind':'none'})}


def graph_schema(family,material_display=False):
    catalogue=CATALOGUES[family];variants=[]
    for kind,desc in catalogue.items():
        values=arguments_schema({k:v['value'] for k,v in desc['inputs'].items() if 'value' in v})
        props=arguments_schema({k:v[1] for k,v in desc['properties'].items()})
        variants.append(object_schema({'id':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_-]*$'},'kind':{'const':kind},'values':values,'properties':props},['id','kind']))
    from .node_groups import group_node_schema
    # Preserve existing conceptual-guidance addresses when appending constructors.
    variants.insert(GROUP_AT.get(family,len(variants)),group_node_schema())
    endpoint=object_schema({'node':{'type':'string'},'socket':{'type':'string'}},['node','socket'])
    result=object_schema({'id':{'type':'string'},'nodes':{'type':'array','minItems':1,'maxItems':256,'items':{'oneOf':variants}},'links':{'type':'array','maxItems':1024,'items':object_schema({'from':endpoint,'to':endpoint},['from','to'])}},['id','nodes','links'])
    if material_display:
        result['properties'].update(arguments_schema(material_display_fields())['properties'])
    return result


def validate_graph(value,family,where,groups=None,interface=None,material_display=False):
    from schemaxis.errors import keys
    keys(value,('id','nodes','links',*(material_display_fields() if material_display else [])),where)
    from schemaxis.pipeline import name
    name(value.get('id'),where+'.id')
    catalogue=CATALOGUES[family]
    from .node_groups import descriptor
    if not isinstance(value.get('nodes'),list) or not 1<=len(value['nodes'])<=256:fail('INVALID_NODE_GRAPH','graph needs1–256 nodes',where)
    result={'id':value['id'],'nodes':[],'links':[]};nodes={}
    if material_display:
        fields=material_display_fields()
        result.update(validate_arguments(fields,{k:v for k,v in value.items() if k in fields},location=where))
    for i,authored in enumerate(value['nodes']):
        loc=f'{where}.nodes[{i}]';keys(authored,('id','kind','group','values','properties'),loc);name(authored.get('id'),loc+'.id')
        kind=authored.get('kind')
        desc=descriptor(authored,family,groups,interface)
        if authored['id'] in nodes:fail('DUPLICATE_ID','graph node identities must be distinct',loc+'.id')
        v=validate_arguments({k:s['value'] for k,s in desc['inputs'].items() if 'value' in s},authored.get('values',{}),location=loc+'.values')
        p=validate_arguments({k:s[1] for k,s in desc['properties'].items()},authored.get('properties',{}),location=loc+'.properties')
        if family=='material':
            from .surface_nodes import validate_node
            validate_node(kind,v,p,loc)
        if kind=='collectionInfo' and v['resetChildren'] and not v['separateChildren']:fail('INVALID_NODE_GRAPH','resetChildren requires separateChildren',loc+'.values.resetChildren')
        node={'id':authored['id'],'kind':kind,'values':v,'properties':p,**({'group':authored['group']} if kind=='group' else {})};result['nodes'].append(node);nodes[node['id']]=node
    if sum(n['kind']=='output' for n in nodes.values())!=1:fail('INVALID_NODE_GRAPH','graph requires exactly one output',where)
    links=value.get('links');seen=set();deps={n:set() for n in nodes}
    if not isinstance(links,list) or len(links)>1024:fail('INVALID_NODE_GRAPH','links must be an array within1024 entries',where+'.links')
    for i,link in enumerate(links):
        loc=f'{where}.links[{i}]';keys(link,('from','to'),loc);ends=[]
        for field,ports in [('from','outputs'),('to','inputs')]:
            end=link.get(field);keys(end,('node','socket'),loc+'.'+field)
            if end.get('node') not in nodes:fail('UNKNOWN_REFERENCE','link node is absent',loc+'.'+field)
            desc=descriptor(nodes[end['node']],family,groups,interface)[ports]
            if end.get('socket') not in desc:fail('UNKNOWN_SOCKET','socket is not declared for this node',loc+'.'+field+'.socket')
            ends.append(desc[end['socket']])
        if ends[0]['kind']!=ends[1]['kind'] and {ends[0]['kind'],ends[1]['kind']} not in ({'integer','number'},{'number','vector'},{'number','colour'},{'colour','vector'},{'rotation','vector'}):fail('TYPE_MISMATCH','incompatible socket kinds',loc)
        dest=(link['to']['node'],link['to']['socket'])
        if dest in seen and not (family=='geometry' and nodes[dest[0]]['kind']=='join'):fail('INVALID_NODE_GRAPH','input socket has multiple links',loc)
        seen.add(dest);deps[dest[0]].add(link['from']['node']);result['links'].append(link)
    # A link-only interface has no authored literal fallback. Require its
    # connection at each instance and reusable output, rather than silently
    # accepting an unbound native colour/matrix default.
    for authored in nodes.values():
        if authored['kind']=='group' or interface and authored['kind']=='output':
            desc=descriptor(authored,family,groups,interface)
            for key,port in desc['inputs'].items():
                if 'value' not in port and (authored['id'],key) not in seen:fail('MISSING_NODE_LINK','link-only group socket requires a connection',where,socket=key,node=authored['id'])
    pending=set(nodes);ordered=[]
    while pending:
        ready=sorted(n for n in pending if not deps[n]&pending)
        if not ready:fail('DEPENDENCY_CYCLE','node graph contains a cycle',where)
        ordered.extend(ready);pending.difference_update(ready)
    if family=='geometry':
        cost_fields={('cube',k) for k in ('xVertices','yVertices','zVertices')}|{('grid',k) for k in ('xVertices','yVertices')}|{('icoSphere','subdivisions'),('curveCircle','resolution'),('resampleCurve','count'),('subdivide','level')}
        for link in result['links']:
            target=nodes[link['to']['node']]
            if (target['kind'],link['to']['socket']) in cost_fields:fail('UNSUPPORTED_NODE_LINK','topology counts require bounded literal values',where)
        geometry_budget(result,0,groups=groups,interface=interface)
    return result


def geometry_budget(graph,source_vertices,maximum=2_000_000,groups=None,interface=None,resource_counts=None):
    """Conservative topology expansion bound before allocating evaluated meshes."""
    from .node_groups import descriptor
    nodes={n['id']:n for n in graph['nodes']};counts={};pending=set(nodes)
    while pending:
        ready=sorted(k for k in pending if all(l['from']['node'] in counts for l in graph['links'] if l['to']['node']==k))
        if not ready:fail('DEPENDENCY_CYCLE','cannot estimate cyclic geometry graph')
        for identity in ready:
            n=nodes[identity];kind=n['kind'];values=n['values'];inputs={}
            for link in graph['links']:
                if link['to']['node']==identity:inputs.setdefault(link['to']['socket'],[]).append(counts[link['from']['node']])
            desc=descriptor(n,'geometry',groups,interface)
            count=sum(sum(inputs.get(k,[0])) for k,p in desc['inputs'].items() if p['kind']=='geometry')
            if kind=='input':count=source_vertices
            elif kind in ('objectInfo','collectionInfo'):
                # Zero at structural graph validation only. Runtime admission
                # supplies actual conservative resource counts before modifiers.
                resource_kind='object' if kind=='objectInfo' else 'collection';key=resource_kind
                linked=any(l['to']=={'node':identity,'socket':key} for l in graph['links'])
                count=(resource_counts or {}).get((resource_kind,'*' if linked else values[key]),0)
            elif kind=='group':
                group=groups[n['group']];sub=geometry_budget(group,count,maximum,groups,group,resource_counts)
                count=sub[next(n['id'] for n in group['nodes'] if n['kind']=='output')]
            elif kind=='cube':count=values['xVertices']*values['yVertices']*values['zVertices']
            elif kind=='grid':count=values['xVertices']*values['yVertices']
            elif kind=='icoSphere':count=10*4**values['subdivisions']+2
            elif kind=='curveCircle':count=values['resolution']
            elif kind=='resampleCurve':count=max(1,count)*values['count']
            elif kind=='subdivide':count=max(1,count)*6*4**values['level']
            elif kind=='extrudeMesh':count*=10
            elif kind=='instanceOnPoints':count=max(1,count)*max(1,sum(inputs.get('instance',[0])))
            elif kind=='curveToMesh':count=max(1,count)*max(1,sum(inputs.get('profile',[0])))*2
            elif kind=='triangulate':count*=6
            if count>maximum:fail('RESOURCE_BUDGET_EXCEEDED','procedural geometry exceeds two million conservative vertices',graph['id'],estimatedVertices=count)
            counts[identity]=count
        pending.difference_update(ready)
    return counts
