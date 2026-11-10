"""Trusted interface and resource mappings for reusable native node groups."""
import bpy
from schemaxis.errors import fail
from .node_groups import kind_descriptor


def assign(target,value,kind,family,resources):
    if kind in ('object','material','collection','image') and not (family=='compositor' and kind=='image'):
        target.default_value=resources[kind][value] if value else None
    else:target.default_value=value


def plain(value):
    if isinstance(value,bpy.types.ID):return value.name
    if isinstance(value,(int,float,str,bool)) or value is None:return value
    return [plain(v) for v in value]


def create_interface(tree,spec,resources):
    for direction,field in [('INPUT','inputs'),('OUTPUT','outputs')]:
        for item in spec[field]:
            native,kind,_=kind_descriptor(item['kind'],spec['family'])
            socket=tree.interface.new_socket(name=item['id'],in_out=direction,socket_type=native);socket.description=item['description']
            if item['kind'] in ('number','integer'):
                socket.min_value=item['minimum'];socket.max_value=item['maximum']
            if 'default' in item:assign(socket,item['default'],kind,spec['family'],resources)


def observe_interface(tree,spec,resources=None):
    records={'inputs':[],'outputs':[]}
    for item in tree.interface.items_tree:
        if item.item_type!='SOCKET':fail('VERIFICATION_FAILED','undeclared interface panel or nesting',tree.name)
        field='inputs' if item.in_out=='INPUT' else 'outputs';authored=next((s for s in spec[field] if s['id']==item.name),None)
        if authored is None:fail('VERIFICATION_FAILED','undeclared interface socket',tree.name)
        native,kind,_=kind_descriptor(authored['kind'],spec['family'])
        if item.socket_type!=native or item.hide_value or item.hide_in_modifier or item.force_non_field or item.default_attribute_name or item.attribute_domain!='POINT' or item.default_input!='VALUE' or item.structure_type!='AUTO' or item.is_panel_toggle or item.layer_selection_field:fail('VERIFICATION_FAILED','node interface type or value availability differs',item.name)
        record={'id':item.name,'kind':authored['kind'],'description':item.description}
        if authored['kind'] in ('number','integer'):record.update(minimum=item.min_value,maximum=item.max_value)
        if 'default' in authored:
            value=reference_value(item.default_value,authored['default'],kind,spec['family'],resources) if resources else plain(item.default_value)
            record['default']='' if value is None and kind in ('object','material','collection','image') else value
        records[field].append(record)
    return records


def reference_value(native,authored,kind,family,resources):
    if kind in ('object','collection','material','image') and not (family=='compositor' and kind=='image'):
        expected=resources.get(kind,{}).get(authored) if authored else None
        if native!=expected:fail('VERIFICATION_FAILED','node resource pointer differs from the resolved declaration',authored,kind=kind)
        return authored
    return plain(native)
