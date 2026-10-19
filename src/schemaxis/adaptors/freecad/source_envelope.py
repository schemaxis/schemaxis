"""Closed, bounded host inspection of one phase-one Body source before any native open.

Only the saved form that the qualified schemaxis.freecad/1 PartDesign route writes is
admitted: a fixed XML prolog, a closed element vocabulary, closed per-type property
and extension sets, references that stay inside the source, archive members that are
exactly the payloads the document names, and syntactically valid payloads. Anything
else (Python objects, external links, DOCTYPE/entities, dynamic properties, unknown
types, extra or missing members) is refused before FreeCAD could restore it.

Payload syntax is checked here; payload *meaning* is checked later by the native
capture stage, which must reproduce every stored history shape by recompute.
"""
import re
import zipfile
from xml.etree import ElementTree as ET

from schemaxis.errors import fail

PROLOG = (b"<?xml version='1.0' encoding='utf-8'?>\n<!--\n FreeCAD Document, see https://www.freecad.org "
          b"for more information...\n-->\n<Document ")
GUI_PROLOG = b"<?xml version='1.0' encoding='utf-8'?>\n<Document "
MEMBER_BYTES = 32*1024*1024
BREP_HEADER = b'\nCASCADE Topology V1, (c) Matra-Datavision\n'
MAP_HEADER = b'BeginElementMap v1\n'
TAG_REFERENCE = re.compile(rb';:H-?([0-9a-f]+)')
HASH_REFERENCE = re.compile(rb'#([0-9a-f]+)')
ROOT_CHILDREN = ['StringHasher', 'StringHasher2', 'Properties', 'Objects', 'ObjectData']

# Element vocabulary and attribute keys written by the qualified phase-one route.
ATTRIBUTES = {
    'Document': [{'FileVersion', 'ProgramVersion', 'SchemaVersion', 'StringHasher'}],
    'StringHasher': [{'count', 'new', 'saveall', 'threshold'}], 'StringHasher2': [{'file'}],
    'Properties': [{'Count', 'TransientCount'}], '_Property': [{'name', 'status', 'type'}],
    'Property': [{'name', 'type'}, {'name', 'status', 'type'}, {'attr', 'doc', 'group', 'hide', 'name', 'ro', 'status', 'type'}],
    'String': [{'value'}], 'Map': [{'count'}], 'Bool': [{'value'}], 'Uuid': [{'value'}],
    'Integer': [{'value'}, {'CustomEnum', 'value'}], 'CustomEnumList': [{'count'}], 'Enum': [{'value'}],
    'Objects': [{'Count', 'Dependencies'}], 'ObjectDeps': [{'Count', 'Name'}], 'Dep': [{'Name'}],
    'Object': [{'id', 'name', 'type'}, {'name'}, {'Extensions', 'name'}], 'ObjectData': [{'Count'}],
    'ExpressionEngine': [{'count'}], 'Expression': [{'expression', 'path'}], 'Float': [{'value'}],
    'Extensions': [{'Count'}], 'Extension': [{'name', 'type'}], 'Link': [{'value'}, {'obj', 'sub'}],
    'LinkList': [{'count'}], 'LinkSub': [{'count', 'value'}], 'LinkSubList': [{'count'}],
    'PropertyPlacement': [{'A', 'Ox', 'Oy', 'Oz', 'Px', 'Py', 'Pz', 'Q0', 'Q1', 'Q2', 'Q3'}],
    'Part': [{'ElementMap', 'file'}, {'ElementMap', 'HasherIndex', 'file'}], 'ElementMap': [set(), {'count', 'new'}],
    'Element': [{'key', 'value'}], 'ElementMap2': [{'file'}], 'PropertyMaterial': [{'uuid'}],
    'ConstraintList': [{'count'}],
    'Constrain': [{'ElementIds', 'ElementPositions', 'First', 'FirstPos', 'IsActive', 'IsDriving', 'IsInVirtualSpace',
                   'IsVisible', 'LabelDistance', 'LabelPosition', 'Name', 'Second', 'SecondPos', 'Third', 'ThirdPos',
                   'Type', 'Value'}],
    'GeometryList': [{'count'}], 'Geometry': [{'id', 'migrated', 'type'}], 'GeoExtensions': [{'count'}],
    'GeoExtension': [{'Flags', 'Ref', 'type'}, {'geometryLayer', 'geometryModeFlags', 'id', 'internalGeometryType', 'type'}],
    'LineSegment': [{'EndX', 'EndY', 'EndZ', 'StartX', 'StartY', 'StartZ'}], 'Construction': [{'value'}],
    'IntegerList': [{'count'}], 'I': [{'v'}], 'PropertyVector': [{'valueX', 'valueY', 'valueZ'}],
    'Circle': [{'AngleXU', 'CenterX', 'CenterY', 'CenterZ', 'NormalX', 'NormalY', 'NormalZ', 'Radius'}],
}
DOCUMENT_PROPERTIES = {
    'Comment': 'App::PropertyString', 'Company': 'App::PropertyString', 'CreatedBy': 'App::PropertyString',
    'CreationDate': 'App::PropertyString', 'FileName': 'App::PropertyString', 'Id': 'App::PropertyString',
    'Label': 'App::PropertyString', 'LastModifiedBy': 'App::PropertyString', 'LastModifiedDate': 'App::PropertyString',
    'License': 'App::PropertyString', 'LicenseURL': 'App::PropertyString', 'Material': 'App::PropertyMap',
    'Meta': 'App::PropertyMap', 'ShowHidden': 'App::PropertyBool', 'Tip': 'App::PropertyLink',
    'TipName': 'App::PropertyString', 'TransientDir': 'App::PropertyString', 'Uid': 'App::PropertyUUID',
    'UnitSystem': 'App::PropertyEnumeration', 'UseHasher': 'App::PropertyBool'}
_COMMON = {'ExpressionEngine': 'App::PropertyExpressionEngine', 'Label': 'App::PropertyString',
           'Label2': 'App::PropertyString', 'Visibility': 'App::PropertyBool'}
_HELPER = {**_COMMON, 'Placement': 'App::PropertyPlacement', 'Role': 'App::PropertyString'}
_FEATURE = {**_COMMON, 'AddSubShape': 'Part::PropertyPartShape', 'AllowMultiFace': 'App::PropertyBool',
            'AlongSketchNormal': 'App::PropertyBool', 'BaseFeature': 'App::PropertyLink', 'Direction': 'App::PropertyVector',
            'FuzzyTolerance': 'App::PropertyFloatConstraint', 'Length': 'App::PropertyLength', 'Length2': 'App::PropertyLength',
            'Midplane': 'App::PropertyBool', 'Offset': 'App::PropertyLength', 'Offset2': 'App::PropertyLength',
            'Placement': 'App::PropertyPlacement', 'Profile': 'App::PropertyLinkSub', 'ReferenceAxis': 'App::PropertyLinkSub',
            'Refine': 'App::PropertyBool', 'Reversed': 'App::PropertyBool', 'Shape': 'Part::PropertyPartShape',
            'ShapeMaterial': 'Materials::PropertyMaterial', 'SideType': 'App::PropertyEnumeration',
            'Suppressed': 'App::PropertyBool', 'SuppressedShape': 'Part::PropertyPartShape', 'TaperAngle': 'App::PropertyAngle',
            'TaperAngle2': 'App::PropertyAngle', 'Type': 'App::PropertyEnumeration', 'Type2': 'App::PropertyEnumeration',
            'UpToFace': 'App::PropertyLinkSub', 'UpToFace2': 'App::PropertyLinkSub', 'UpToShape': 'App::PropertyLinkSubList',
            'UpToShape2': 'App::PropertyLinkSubList', 'UseCustomVector': 'App::PropertyBool'}
PROPERTIES = {
    'App::Line': _HELPER, 'App::Plane': _HELPER, 'App::Point': _HELPER,
    'App::Origin': {**_COMMON, 'OriginFeatures': 'App::PropertyLinkList', 'Placement': 'App::PropertyPlacement'},
    'App::VarSet': _COMMON,
    'PartDesign::Body': {**_COMMON, 'AllowCompound': 'App::PropertyBool', 'BaseFeature': 'App::PropertyLink',
                         'Group': 'App::PropertyLinkList', 'Origin': 'App::PropertyLink', 'Placement': 'App::PropertyPlacement',
                         'Shape': 'Part::PropertyPartShape', 'ShapeMaterial': 'Materials::PropertyMaterial',
                         'Tip': 'App::PropertyLink'},
    'PartDesign::Pad': _FEATURE, 'PartDesign::Pocket': _FEATURE,
    'Sketcher::SketchObject': {**_COMMON, 'ArcFitTolerance': 'App::PropertyPrecision',
        'AttacherEngine': 'App::PropertyEnumeration', 'AttacherType': 'App::PropertyString',
        'AttachmentOffset': 'App::PropertyPlacement', 'AttachmentSupport': 'App::PropertyLinkSubList',
        'Constraints': 'Sketcher::PropertyConstraintList', 'Exports': 'App::PropertyLinkListHidden',
        'ExternalGeo': 'Part::PropertyGeometryList', 'ExternalGeometry': 'App::PropertyLinkSubList',
        'ExternalTypes': 'App::PropertyIntegerList', 'FullyConstrained': 'App::PropertyBool',
        'Geometry': 'Part::PropertyGeometryList', 'InternalShape': 'Part::PropertyPartShape',
        'MakeInternals': 'App::PropertyBool', 'MapMode': 'App::PropertyEnumeration',
        'MapPathParameter': 'App::PropertyFloat', 'MapReversed': 'App::PropertyBool',
        'Placement': 'App::PropertyPlacement', 'Shape': 'Part::PropertyPartShape',
        'ShapeMaterial': 'Materials::PropertyMaterial', '_ExternalGeoVersion': 'App::PropertyInteger'}}
EXTENSIONS = {'PartDesign::Body': ['App::OriginGroupExtension'], 'App::Origin': ['App::GeoFeatureGroupExtension'],
              'Sketcher::SketchObject': ['Part::AttachExtension'],
              'PartDesign::Pad': ['App::SuppressibleExtension', 'Part::PreviewExtension'],
              'PartDesign::Pocket': ['App::SuppressibleExtension', 'Part::PreviewExtension']}
# Transient records are written by name and type only, with no saved value.
_MAP_VERSION = {'_ElementMapVersion': 'App::PropertyString'}
TRANSIENT = {'App::VarSet': {}, 'App::Line': _MAP_VERSION, 'App::Plane': _MAP_VERSION, 'App::Point': _MAP_VERSION,
             'Sketcher::SketchObject': _MAP_VERSION,
             'PartDesign::Body': {**_MAP_VERSION, '_GroupTouched': 'App::PropertyBool'},
             'App::Origin': {**_MAP_VERSION, 'Group': 'App::PropertyLinkList', '_GroupTouched': 'App::PropertyBool'},
             'PartDesign::Pad': {**_MAP_VERSION, 'PreviewShape': 'Part::PropertyPartShape', '_Body': 'App::PropertyLinkHidden'},
             'PartDesign::Pocket': {**_MAP_VERSION, 'PreviewShape': 'Part::PropertyPartShape', '_Body': 'App::PropertyLinkHidden'}}


def prolog(data, location, code, *, gui=False):
    """Fixed FreeCAD prolog; any other declaration, DOCTYPE, entity or comment is refused."""
    head = GUI_PROLOG if gui else PROLOG
    if not data.startswith(head) or data.count(b'<!') != (0 if gui else 1) or data.count(b'<?') != 1:
        fail(code, 'Saved FreeCAD XML must have the fixed prolog and no DOCTYPE, entity or extra declaration', location)


def _attributes(root, location, code, vocabulary):
    for element in root.iter():
        allowed = vocabulary.get(element.tag)
        if allowed is None or set(element.attrib) not in allowed:
            fail(code, 'Saved element or attribute is outside the qualified source vocabulary', location,
                 element=element.tag, attributes=sorted(element.attrib))


def read_members(path, location, code):
    """Bounded read of every archive member (bounds already checked by check_archive)."""
    from .assembly_sources import check_archive
    check_archive(path, location, code=code)
    with zipfile.ZipFile(path) as archive:
        members = {}
        for info in archive.infolist():
            if info.file_size > MEMBER_BYTES or info.is_dir():
                fail(code, 'Archive member is a directory or exceeds 32 MiB', location, member=info.filename)
            members[info.filename] = archive.read(info)
            if len(members[info.filename]) != info.file_size:
                fail(code, 'Archive member size differs from its header', location, member=info.filename)
    return members


def brep(data, location, code, member):
    """OpenCASCADE text BREP syntax, or an empty payload for a null shape."""
    if not data:
        return
    try:
        text = data.decode('ascii')
    except UnicodeDecodeError:
        fail(code, 'BREP payload is not ASCII text', location, member=member)
    # The text ends with the root shape reference, for example '+1 1 ' (no newline).
    if not data.startswith(BREP_HEADER) or not re.fullmatch(r'[+-]\d+ \d+ ', text.split('\n')[-1]):
        fail(code, 'BREP payload header or termination is malformed', location, member=member)
    sections = [line.split(' ')[0] for line in text.split('\n')[2:] if line and line[0].isalpha() and line.split(' ')[0] in
                ('Locations', 'Curve2ds', 'Curves', 'Polygon3D', 'PolygonOnTriangulations', 'Surfaces', 'Triangulations', 'TShapes')]
    if sections != ['Locations', 'Curve2ds', 'Curves', 'Polygon3D', 'PolygonOnTriangulations', 'Surfaces', 'Triangulations', 'TShapes']:
        fail(code, 'BREP payload sections are missing or out of order', location, member=member)


def element_map(data, location, code, member):
    """Parse the element-map skeleton; return (postfix id, postfixes, maps, tags, hash references)."""
    def bad(reason):
        fail(code, 'Element map payload is malformed: '+reason, location, member=member)
    try:
        lines = data.decode('ascii').split('\n')
    except UnicodeDecodeError:
        bad('not ASCII')
    if not data.startswith(MAP_HEADER) or lines[-1] != '':
        bad('header or termination')
    position = [1]

    def take(pattern=None):
        if position[0] >= len(lines):
            bad('truncated')
        line = lines[position[0]]
        position[0] += 1
        if pattern is not None:
            match = re.fullmatch(pattern, line)
            if not match:
                bad('unexpected line '+repr(line[:40]))
            return match
        return line
    head = take(r'(\d+) PostfixCount (\d+)')
    postfix_id, count = int(head[1]), int(head[2])
    postfixes = [take(r'\S+')[0] for _ in range(count)]
    take(r'')
    maps = []
    for index in range(1, int(take(r'MapCount (\d+)')[1]) + 1):
        take(r'')
        # ElementMap <index> <postfix table id, document-wide> <section count>
        header = take(r'ElementMap (\d+) (\d+) (\d+)')
        if int(header[1]) != index:
            bad('map index sequence differs')
        sections = []
        for _ in range(int(header[3])):
            take(r'')
            kind = take(r'[A-Z][a-z]+')[0]
            take(r'')
            children = [take(r'[^\n]*\S[^\n]*')[0] for _ in range(int(take(r'ChildCount (\d+)')[1]))]
            take(r'')
            names = [take(r'[^\n]*\S[^\n]*')[0] for _ in range(int(take(r'NameCount (\d+)')[1]))]
            sections.append((kind, len(children), len(names), children, names))
        take(r'')
        take(r'EndMap')
        maps.append((int(header[2]), sections))
    if position[0] != len(lines) - 1:
        bad('content after EndMap')
    return {'postfixId': postfix_id, 'postfixes': postfixes, 'maps': maps,
            'tags': {int(t, 16) for t in TAG_REFERENCE.findall(data)},
            'hashes': [int(h, 16) for h in HASH_REFERENCE.findall(data)]}


def string_table(data, location, code, member):
    try:
        lines = data.decode('ascii').split('\n')
    except UnicodeDecodeError:
        fail(code, 'String table is not ASCII text', location, member=member)
    match = re.fullmatch(r'StringTableStart v1 (\d+)', lines[0])
    if not match or len(lines) != int(match[1]) + 2 or lines[-1] != '' or any(not line or len(line) > 4096 for line in lines[1:-1]):
        fail(code, 'String table header, entry count or termination is malformed', location, member=member)
    return int(match[1])


def gui_record(data, objects, location, code):
    """Phase-one minimal view record: one Visibility property per source object, nothing else."""
    prolog(data, location, code, gui=True)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        fail(code, 'GuiDocument.xml is malformed', location, detail=str(error))
    providers = root.findall('./ViewProviderData/ViewProvider')
    if (root.tag != 'Document' or root.attrib != {'SchemaVersion': '1'} or len(root) != 1
            or root[0].attrib != {'Count': str(len(providers))} or {p.get('name') for p in providers} != set(objects)
            or len(providers) != len(objects)):
        fail(code, 'GuiDocument.xml membership differs from the minimal source view record', location)
    for provider in providers:
        props = provider.findall('./Properties/Property')
        if (provider.attrib != {'name': provider.get('name'), 'expanded': '0'} or len(provider) != 1 or len(props) != 1
                or props[0].attrib != {'name': 'Visibility', 'type': 'App::PropertyBool', 'status': '1'}
                or [c.tag for c in props[0]] != ['Bool'] or props[0][0].get('value') not in ('true', 'false')):
            fail(code, 'GuiDocument.xml carries state outside the minimal visibility record', location, provider=provider.get('name'))


def inspect(path, facts, location, code='UNSUPPORTED_SOURCE'):
    """Return a bounded description of a source that passes the closed envelope."""
    members = read_members(path, location, code)
    if 'Document.xml' not in members:
        fail(code, 'Source archive lacks Document.xml', location)
    document = members['Document.xml']
    prolog(document, location, code)
    try:
        root = ET.fromstring(document)
    except ET.ParseError as error:
        fail(code, 'Source Document.xml is malformed', location, detail=str(error))
    _attributes(root, location, code, ATTRIBUTES)
    if root.tag != 'Document' or [c.tag for c in root] != ROOT_CHILDREN:
        fail(code, 'Source document structure differs from the qualified phase-one form', location)
    props = {p.get('name'): p.get('type') for p in root.find('Properties')}
    if props != DOCUMENT_PROPERTIES or len(root.find('Properties')) != len(DOCUMENT_PROPERTIES):
        fail(code, 'Source document properties differ from the qualified phase-one set', location)
    objects = {o.get('name'): o.get('type') for o in root.find('Objects').findall('Object')}
    if objects != facts['objects'] or len(root.find('Objects').findall('Object')) != len(objects):
        fail(code, 'Source object membership or types differ from its verified plan', location)
    ids = {int(o.get('id')) for o in root.find('Objects').findall('Object')}
    references = set()
    for record in root.find('Objects').findall('ObjectDeps'):
        references.update([record.get('Name')] + [d.get('Name') for d in record])
    data = root.find('ObjectData').findall('Object')
    if [o.get('name') for o in data] != list(objects):
        fail(code, 'Source object data membership differs', location)
    parameters = {'dim_'+k: 'App::PropertyLength' for k in facts['parameters']}
    files = {}
    for obj in data:
        name, kind = obj.get('name'), objects[obj.get('name')]
        expected = dict(PROPERTIES.get(kind, {}))
        if kind == 'App::VarSet':
            expected.update(parameters)
        container = obj.find('Properties')
        found = {p.get('name'): p.get('type') for p in container.findall('Property')}
        transient = {p.get('name'): p.get('type') for p in container.findall('_Property')}
        if (not expected or found != expected or len(container.findall('Property')) != len(found)
                or transient != TRANSIENT.get(kind) or len(container.findall('_Property')) != len(transient)
                or any(len(p) for p in container.findall('_Property')) or len(container) != len(found) + len(transient)
                or container.get('Count') != str(len(found)) or container.get('TransientCount') != str(len(transient))):
            fail(code, 'Source object properties differ from the qualified set for its type', location, object=name)
        extensions = [e.get('type') for e in obj.findall('./Extensions/Extension')]
        if extensions != EXTENSIONS.get(kind, []) or (('Extensions' in obj.attrib) != bool(extensions)):
            fail(code, 'Source object extensions differ from the qualified set for its type', location, object=name)
        for prop in obj.find('Properties').findall('Property'):
            if set(prop.attrib) == {'attr', 'doc', 'group', 'hide', 'name', 'ro', 'status', 'type'} and prop.get('name') not in parameters:
                fail(code, 'Only declared VarSet parameters may be dynamic properties', location, object=name)
            for element in prop.iter():
                for key in ('value', 'obj'):
                    if element.tag in ('Link', 'LinkSub') and element.get(key):
                        references.add(element.get(key))
                # No qualified reference names a sub-element, so element-map names are never consumed.
                if (element.tag == 'Link' and element.get('sub', '') != '') or (
                        element.tag == 'LinkSub' and (element.get('count') != '0' or len(element))):
                    fail(code, 'Source references a sub-element by name; the qualified route references whole objects only',
                         location, object=name, property=prop.get('name'))
                if element.tag == 'Expression' and ('<<' in element.get('expression') or '#' in element.get('expression')):
                    fail(code, 'Source expressions may not use label or cross-document references', location, object=name)
                if element.get('file'):
                    if element.get('file') in files:
                        fail(code, 'Source payload member is referenced twice', location, member=element.get('file'))
                    files[element.get('file')] = (name, prop.get('name'), element.tag)
    if references - set(objects) - {''}:
        fail(code, 'Source references objects outside itself', location, objects=sorted(references - set(objects)))
    table_member = root.find('StringHasher2').get('file')
    expected_members = {'Document.xml', table_member, *files}
    if set(members) - {'GuiDocument.xml'} != expected_members:
        fail(code, 'Source archive members differ from the payloads its document names', location,
             extra=sorted(set(members) - expected_members - {'GuiDocument.xml'}), missing=sorted(expected_members - set(members)))
    table = string_table(members[table_member], location, code, table_member)
    postfix_tables, used_tables = {}, set()
    for member, (owner, prop, tag) in files.items():
        if tag == 'Part' and member.endswith('.brp'):
            brep(members[member], location, code, member)
        elif tag == 'ElementMap2' and member.endswith('.Map.txt'):
            parsed = element_map(members[member], location, code, member)
            if not parsed['tags'] <= ids or any(h > table for h in parsed['hashes']):
                fail(code, 'Element map refers outside its source or string table', location, member=member)
            if parsed['postfixId'] in postfix_tables:
                fail(code, 'Element map postfix table is defined twice', location, member=member)
            postfix_tables[parsed['postfixId']] = member
            used_tables.update(table_id for table_id, _ in parsed['maps'])
        else:
            fail(code, 'Source payload member kind is not qualified', location, member=member)
    if not used_tables <= set(postfix_tables):
        fail(code, 'Element maps use a postfix table that this source does not define', location)
    if 'GuiDocument.xml' in members:
        gui_record(members['GuiDocument.xml'], objects, location, code)
    return {'members': {k: len(v) for k, v in sorted(members.items())}, 'payloads': files, 'table': table_member,
            'expandedBytes': sum(len(v) for v in members.values())}
