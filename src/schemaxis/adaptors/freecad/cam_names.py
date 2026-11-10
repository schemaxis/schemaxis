"""Compile authored CAM identities to distinct, exact native object names."""
from schemaxis.errors import fail
from schemaxis.pipeline import name


def operation_names(plan):
    """Preserve existing safe names; allocate around *all* reserved safe names.

    FreeCAD sanitizes hyphens and may append numeric suffixes. Neither behaviour
    establishes identity. This finite mapping is derived from admitted authored
    operation IDs, never from submitted native names or editable observations.
    """
    operations=plan.get('operations')
    if not isinstance(operations,list) or not 1<=len(operations)<=16:
        fail('INVALID_MACHINING','Declare one to sixteen ordered operations')
    identities=[]
    for index,operation in enumerate(operations):
        if not isinstance(operation,dict):fail('INVALID_MACHINING','Expected a typed operation')
        identity=name(operation.get('id'),'$.operations['+str(index)+'].id')
        if identity in identities:fail('INVALID_MACHINING','Operation identities must be unique')
        identities.append(identity)
    result={identity:'Op_'+identity for identity in identities if '-' not in identity}
    reserved=set(result.values());ordinal=0
    for identity in identities:
        if identity in result:continue
        while 'Op_SCX'+str(ordinal) in reserved:ordinal+=1
        native='Op_SCX'+str(ordinal);result[identity]=native;reserved.add(native);ordinal+=1
    return {identity:result[identity] for identity in identities}


def require_free(document,identity):
    if document.getObject(identity) is not None:
        fail('NATIVE_IDENTITY_COLLISION','Compiled machining object name is already occupied',identity)


def require_created(document,operation,identity):
    if operation.Name!=identity or document.getObject(identity) is not operation:
        fail('NATIVE_IDENTITY_COLLISION','Native machining object identity differs from its compiled name',identity)
