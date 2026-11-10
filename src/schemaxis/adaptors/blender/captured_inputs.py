"""Pinned single-file inputs at declared Blender resource positions."""
import copy
from schemaxis.errors import fail

READERS={'readGltf','readSTL','readPLY','curveFromCSV'}


def _item(sequence,token):
    if not isinstance(sequence,list) or not token.isascii() or not token.isdecimal() or len(token)>20:return None
    index=int(token)
    return sequence[index] if str(index)==token and index<len(sequence) else None


def accept_resource(document,pointer,resource):
    parts=pointer.split('/')[1:];version=document.get('version');reader=None
    production=None;tail=[]
    if version=='schemaxis.blender.render/1' and parts==['sceneFile']:
        reader='saved scene'
    elif version=='schemaxis.blender.production/1' and parts[:1]==['production']:
        production=document.get('production');tail=parts[1:]
    elif version=='schemaxis.blender/1':
        if len(parts)==4 and parts[0]=='nodes' and parts[1].isdigit() and parts[2:]==['options','file']:
            node=_item(document.get('nodes'),parts[1])
            if isinstance(node,dict) and isinstance(node.get('filter'),str) and node['filter'] in READERS:reader=node['filter']
        elif len(parts)>=3 and parts[0]=='scenes' and parts[1].isdigit() and parts[2]=='production':
            scene=_item(document.get('scenes'),parts[1])
            if isinstance(scene,dict):production=scene.get('production');tail=parts[3:]
    if isinstance(production,dict) and len(tail)==3 and tail[0] in ('images','assets') and tail[1].isdigit() and tail[2]=='file':
        if isinstance(_item(production.get(tail[0]),tail[1]),dict):reader='image' if tail[0]=='images' else 'asset'
    if reader is None:fail('UNSUPPORTED_RESOURCE','this Blender field is not a declared file input',pointer)
    if resource['kind']!='file' or resource['member'] is None:
        fail('UNSUPPORTED_RESOURCE','Blender captured inputs require a single file snapshot',pointer)
    return {'reader':reader,'scope':'selected file; existing native self-contained dependency and resource admission still apply'}


def captured_schema(schema,reference):
    """Expose references only where accept_resource permits consumption."""
    def literal(node):
        while 'anyOf' in node and 'type' not in node:node=node['anyOf'][0]
        return node
    def member(node,name):return literal(node)['properties'][name]
    def array_item(node):return literal(node)['items']
    def admit(node):
        if 'anyOf' in node:node['anyOf'].append(copy.deepcopy(reference))
        else:
            value=copy.deepcopy(node);node.clear();node['anyOf']=[value,copy.deepcopy(reference)]
    def production(node):
        for name in ('images','assets'):admit(member(array_item(member(node,name)),'file'))
    props=schema['properties']
    if 'sceneFile' in props:admit(props['sceneFile'])
    elif 'production' in props:production(props['production'])
    else:
        production(member(array_item(props['scenes']),'production'))
        for reader in READERS:
            options=schema['$defs'].get('options-'+reader)
            if options is not None:admit(member(options,'file'))
