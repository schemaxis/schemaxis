"""Pinned single-file checkpoints for the two checked solid import readers."""
import copy

from schemaxis.errors import fail


READERS={'importMesh':'STL','importSTEP':'STEP'}


def accept_resource(document,pointer,resource):
    """Admit file selection only; the typed importer still checks its bytes."""
    parts=pointer.split('/')
    node=None
    if (document.get('version')=='schemaxis.freecad/1' and len(parts)==5
            and parts[:2]==['','nodes'] and parts[3:]==['options','file']):
        token=parts[2];nodes=document.get('nodes')
        # Bound conversion before int(), require the actual array container and
        # canonical ASCII indices. A dict keyed by '0' is not a feature list.
        if (isinstance(nodes,list) and token.isascii() and token.isdecimal()
                and len(token)<=3):
            index=int(token)
            if str(index)==token and index<min(len(nodes),200):node=nodes[index]
    reader=node.get('filter') if isinstance(node,dict) else None
    if (not isinstance(reader,str) or reader not in READERS
            or not isinstance(node.get('options'),dict) or 'file' not in node['options']):
        fail('UNSUPPORTED_RESOURCE','Choose options.file on checked importMesh or importSTEP',pointer)
    member=resource.get('member')
    if (resource.get('kind')!='file' or not isinstance(member,str) or not member
            or resource.get('files')!=[member]):
        fail('UNSUPPORTED_RESOURCE','Checked CAD imports require a complete single-file snapshot',pointer)
    return {'reader':reader,'artifactKind':'cad','format':READERS[reader],
            'scope':'one pinned original file; existing bounded checked geometry admission remains mandatory',
            'units':'explicit typed importer units; native output millimetres',
            'losses':('faceted BREP; no scan repair or smooth surface reconstruction' if reader=='importMesh'
                      else 'solid geometry; no recovery of the source feature history')}


def captured_schema(schema,reference):
    """Add workflow references to exactly the same checked-reader file fields."""
    def literal(value):
        while 'anyOf' in value and any(item.get('$ref') in
                ('#/$defs/composition','#/$defs/artifact','#/$defs/analytic')
                for item in value['anyOf']):value=value['anyOf'][0]
        return value
    nodes=literal(schema['properties']['nodes'])
    choices=literal(nodes['items'])
    for wrapped in choices.get('oneOf',choices.get('anyOf',[])):
        node=literal(wrapped)
        reader=literal(node['properties']['filter']).get('const')
        if reader in READERS:
            options=literal(node['properties']['options'])['properties']
            previous=options['file']
            options['file']={'anyOf':[previous,copy.deepcopy(reference)]}
