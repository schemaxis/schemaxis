"""Strict, bounded readers for the new native design-intent metadata only."""
import struct
import zlib
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile, LargeZipFile, ZIP_STORED, ZIP_DEFLATED


class UnsupportedArchive(ValueError):
    """A file-controlled archive or XML form that native FCStd files never use."""


# Decoding failures of an untrusted saved archive or its XML members: a corrupt or
# truncated ZIP, an undecodable compressed member, unsupported member encodings and
# malformed XML. Callers map these to a structured verification fault; programmer
# errors are deliberately not included.
ARCHIVE_ERRORS = (BadZipFile, LargeZipFile, zlib.error, EOFError, ET.ParseError, UnsupportedArchive)

# FreeCAD writes stored or deflated members only.
METHODS = {ZIP_STORED, ZIP_DEFLATED}
# General-purpose flags: 0 encrypted, 5 compressed patched data, 6 strong encryption, 13 masked local headers.
REFUSED_FLAGS = (1 << 0) | (1 << 5) | (1 << 6) | (1 << 13)


def read_member(archive, name, limit):
    """Exactly one bounded, unencrypted, stored-or-deflated member, validated before decoding."""
    if archive.namelist().count(name) != 1:
        raise ValueError(name+' is missing or duplicated')
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise ValueError(name+' is oversized')
    if info.flag_bits & REFUSED_FLAGS:
        raise UnsupportedArchive(name+' uses encryption or an unsupported ZIP feature')
    if info.compress_type not in METHODS:
        raise UnsupportedArchive(name+' uses an unsupported compression method')
    # The local header must agree with the central directory before anything is decoded.
    archive.fp.seek(info.header_offset)
    header = archive.fp.read(30)
    if len(header) != 30 or header[:4] != b'PK\x03\x04':
        raise BadZipFile(name+' local header is missing or truncated')
    flags, method = struct.unpack_from('<HH', header, 6)
    if flags & REFUSED_FLAGS or method != info.compress_type:
        raise UnsupportedArchive(name+' local header uses encryption, an unsupported feature or a different method')
    try:
        return archive.read(info)
    except (RuntimeError, NotImplementedError) as error:
        # zipfile reports some local-header-only encryption/feature flags this way; only this call is mapped.
        raise UnsupportedArchive(name+' could not be decoded: '+str(error)) from None


def parse_xml(data, name):
    """Refuse any DOCTYPE or entity declaration in whatever encoding the member declares, then parse.

    FreeCAD never writes a DTD or entities. expat applies the declared or BOM encoding,
    so the refusal does not depend on raw byte patterns; nothing is expanded.
    """
    from xml.parsers import expat
    scanner = expat.ParserCreate()
    def refuse(*_):
        raise UnsupportedArchive(name+' declares a DOCTYPE or entity')
    scanner.StartDoctypeDeclHandler = refuse
    scanner.EntityDeclHandler = refuse
    scanner.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        scanner.Parse(data, True)
    except expat.ExpatError as error:
        raise ET.ParseError(name+': '+str(error)) from None
    except LookupError as error:
        # expat looks up the encoding the member declares; an unknown one is file-controlled.
        raise UnsupportedArchive(name+' declares an unsupported encoding: '+str(error)) from None
    return ET.fromstring(data)


class Document:
    def __init__(self,path):
        with ZipFile(path) as archive:
            data=read_member(archive,'Document.xml',32*1024*1024)
            # Retained raw check; parse_xml enforces the same policy for every encoding.
            if b'<!doctype' in data.lower() or b'<!entity' in data.lower():
                raise UnsupportedArchive('Document.xml declares a DOCTYPE or entity')
            self.root=parse_xml(data,'Document.xml')
        entries=self.root.findall('./Objects/Object')
        self.types={o.attrib['name']:o.attrib['type'] for o in entries}
        if len(self.types)!=len(entries):raise ValueError('duplicate saved object')
        records=self.root.findall('./ObjectData/Object');self.properties={}
        if len(records)!=len(self.types) or {o.get('name') for o in records}!=set(self.types):
            raise ValueError('saved object data membership differs')
        for obj in records:
            entries=obj.findall('./Properties/Property');props={p.attrib['name']:p for p in entries}
            if len(props)!=len(entries):raise ValueError('duplicate saved property')
            self.properties[obj.attrib['name']]=props

    def child(self,name,prop,tag,typeid):
        value=self.properties[name][prop]
        if value.get('type')!=typeid or len(value)!=1 or value[0].tag!=tag:
            raise ValueError('saved property type or cardinality differs: '+name+'.'+prop)
        return value[0]

    def string(self,name,prop):return self.child(name,prop,'String','App::PropertyString').attrib['value']
    def number(self,name,prop,typeid='App::PropertyLength'):return float(self.child(name,prop,'Float',typeid).attrib['value'])
    def boolean(self,name,prop):
        value=self.child(name,prop,'Bool','App::PropertyBool').attrib['value']
        if value not in ('true','false'):raise ValueError('invalid native boolean')
        return value=='true'
    def link(self,name,prop):return self.child(name,prop,'Link','App::PropertyLink').attrib['value'] or None
    def links(self,name,prop):
        value=self.child(name,prop,'LinkList','App::PropertyLinkList')
        if any(c.tag!='Link' for c in value) or int(value.attrib['count'])!=len(value):raise ValueError('invalid saved link list')
        return [c.attrib['value'] for c in value]
    def engine(self,name):
        value=self.child(name,'ExpressionEngine','ExpressionEngine','App::PropertyExpressionEngine')
        if any(c.tag!='Expression' for c in value):raise ValueError('invalid saved expression record')
        # Existing hand-authored test documents omit count; native files provide it.
        if 'count' in value.attrib and int(value.attrib['count'])!=len(value):raise ValueError('saved expression count differs')
        return [[c.attrib['path'],c.attrib['expression']] for c in value]
    def constraint(self,name,identity):
        value=self.child(name,'Constraints','ConstraintList','Sketcher::PropertyConstraintList')
        if any(c.tag!='Constrain' for c in value) or int(value.attrib['count'])!=len(value):raise ValueError('invalid constraint list')
        matches=[c for c in value if c.get('Name')==identity]
        if len(matches)!=1:raise ValueError('missing or duplicate named constraint')
        c=matches[0]
        if c.get('IsDriving')!='1' or c.get('IsActive')!='1':raise ValueError('constraint is not active and driving')
        expected='11' if identity=='radius' else '6'
        if c.get('Type')!=expected:raise ValueError('constraint dimensional type differs')
        return float(c.attrib['Value'])

    def constraints(self,name):
        from .part_design import CONSTRAINT_TYPES
        value=self.child(name,'Constraints','ConstraintList','Sketcher::PropertyConstraintList')
        if any(c.tag!='Constrain' for c in value) or int(value.attrib['count'])!=len(value):raise ValueError('invalid constraint list')
        result=[]
        for c in value:
            if c.get('IsDriving')!='1' or c.get('IsActive')!='1':raise ValueError('constraint is not active and driving')
            result.append({'name':c.attrib['Name'],'type':CONSTRAINT_TYPES[int(c.attrib['Type'])],'value':float(c.attrib['Value']),
                **{k:int(c.attrib[k[0].upper()+k[1:]]) for k in ('first','firstPos','second','secondPos','third','thirdPos')}})
        return result
