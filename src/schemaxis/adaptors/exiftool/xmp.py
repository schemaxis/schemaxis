"""Hardened bounded XMP (RDF/XML) property reader on the standard library.

Packets with a DOCTYPE or entity declaration are refused before any parse, non-UTF-8 packets are unsupported, and size, element count and
nesting are bounded. Properties are returned by canonical ``prefix:Name`` for known namespaces. Every occurrence is kept, so duplicate
properties are reported as ambiguity rather than collapsed.
"""
import re
import xml.etree.ElementTree as ET

MAX_BYTES = 4 * 1024 * 1024
MAX_ELEMENTS = 20000
MAX_DEPTH = 24
RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
XML_LANG = '{http://www.w3.org/XML/1998/namespace}lang'
PREFIXES = {'http://purl.org/dc/elements/1.1/': 'dc', 'http://ns.adobe.com/xap/1.0/': 'xmp', 'http://ns.adobe.com/photoshop/1.0/': 'photoshop',
            'http://ns.adobe.com/tiff/1.0/': 'tiff', 'http://ns.adobe.com/exif/1.0/': 'exif', 'http://ns.adobe.com/exif/1.0/aux/': 'aux',
            'http://ns.adobe.com/xap/1.0/rights/': 'xmpRights', 'http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/': 'Iptc4xmpCore',
            'http://ns.adobe.com/xap/1.0/mm/': 'xmpMM', 'http://cipa.jp/exif/1.0/': 'exifEX'}
FORBIDDEN = re.compile(rb'<!\s*(DOCTYPE|ENTITY|ELEMENT|ATTLIST|NOTATION)', re.I)


class Problem(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def name(tag):
    if tag.startswith('{'):
        uri, _, local = tag[1:].partition('}')
        return (PREFIXES.get(uri) + ':' + local) if uri in PREFIXES else '{' + uri + '}' + local
    return tag


def text_of(element):
    return element.text or ''


def item(element, depth):
    """One rdf:li or simple property element as ('text', value) or ('struct', None)."""
    children = list(element)
    if element.get('{%s}parseType' % RDF) == 'Resource' or (len(children) == 1 and children[0].tag == '{%s}Description' % RDF) or any(
            c.tag not in ('{%s}Alt' % RDF, '{%s}Bag' % RDF, '{%s}Seq' % RDF) for c in children):
        return 'struct', None
    return 'text', text_of(element)


def prop(element, depth):
    if depth > MAX_DEPTH:
        raise Problem('XMP_BOUND', 'XMP nesting exceeds %d levels' % MAX_DEPTH)
    children = list(element)
    containers = [c for c in children if c.tag in ('{%s}Alt' % RDF, '{%s}Bag' % RDF, '{%s}Seq' % RDF)]
    if len(containers) == 1 and len(children) == 1:
        kind = containers[0].tag.rpartition('}')[2]
        lis = list(containers[0])
        if any(li.tag != '{%s}li' % RDF for li in lis):
            raise Problem('XMP_MALFORMED', 'an rdf:%s holds an element other than rdf:li' % kind)
        parts = [(li.get(XML_LANG), *item(li, depth + 1)) for li in lis]
        if any(k == 'struct' for _, k, _ in parts):
            return {'kind': 'struct', 'container': kind}
        if kind == 'Alt':
            langs = [lang or 'x-default' for lang, _, _ in parts]
            if len(set(langs)) != len(langs):
                return {'kind': 'langAlt', 'value': None, 'duplicateLanguage': True}
            return {'kind': 'langAlt', 'value': {langs[i]: parts[i][2] for i in range(len(parts))}}
        return {'kind': 'list', 'container': kind, 'value': [value for _, _, value in parts]}
    if element.get('{%s}parseType' % RDF) == 'Resource' or children:
        return {'kind': 'struct'}
    return {'kind': 'text', 'value': text_of(element)}


def parse(data):
    """``{property: [occurrence, ...]}`` for one packet; raises Problem."""
    if len(data) > MAX_BYTES:
        raise Problem('XMP_BOUND', 'XMP packet exceeds %d bytes' % MAX_BYTES)
    if data[:3] == b'\xef\xbb\xbf':
        data = data[3:]
    if data[:2] in (b'\xff\xfe', b'\xfe\xff') or b'\x00' in data[:8]:
        raise Problem('XMP_ENCODING_UNSUPPORTED', 'only UTF-8 XMP packets are read')
    if FORBIDDEN.search(data):
        raise Problem('XMP_DOCTYPE_REFUSED', 'a DOCTYPE or entity declaration is refused before parsing')
    try:
        root = ET.fromstring(data.rstrip(b'\x00 \t\r\n'))
    except ET.ParseError as error:
        raise Problem('XMP_MALFORMED', 'the XMP packet is not well-formed XML: ' + str(error)[:120])
    count = 0
    for _ in root.iter():
        count += 1
        if count > MAX_ELEMENTS:
            raise Problem('XMP_BOUND', 'XMP has more than %d elements' % MAX_ELEMENTS)
    rdf = root if root.tag == '{%s}RDF' % RDF else root.find('{%s}RDF' % RDF)
    if rdf is None:
        raise Problem('XMP_MALFORMED', 'no rdf:RDF element in the XMP packet')
    found = {}
    for description in rdf:
        if description.tag != '{%s}Description' % RDF:
            raise Problem('XMP_MALFORMED', 'rdf:RDF holds an element other than rdf:Description')
        for attribute, value in description.attrib.items():
            if attribute.startswith('{%s}' % RDF) or attribute == XML_LANG:
                continue
            found.setdefault(name(attribute), []).append({'kind': 'text', 'value': value})
        for child in description:
            found.setdefault(name(child.tag), []).append(prop(child, 1))
    return found


def qualifiers(data, wanted):
    """``{property: count}`` of the qualifiers that rewriting each wanted property would drop: attributes of array items or of the property
    itself (``xml:lang`` is the identity of a language alternative, but a qualifier of an unordered or ordered array item) and qualifier structures."""
    if data[:3] == b'\xef\xbb\xbf':
        data = data[3:]
    try:
        root = ET.fromstring(data.rstrip(b'\x00 \t\r\n'))
    except ET.ParseError:
        return {}
    rdf = root if root.tag == '{%s}RDF' % RDF else root.find('{%s}RDF' % RDF)
    found = {}
    parse_type = '{%s}parseType' % RDF
    for description in rdf if rdf is not None else ():
        for child in description:
            key = name(child.tag)
            if key not in wanted:
                continue
            count = sum(1 for a in child.attrib if not a.startswith('{%s}' % RDF) and a != XML_LANG)
            for container in child:
                alt = container.tag == '{%s}Alt' % RDF
                if container.tag not in ('{%s}Alt' % RDF, '{%s}Bag' % RDF, '{%s}Seq' % RDF):
                    continue
                for li in container:
                    count += sum(1 for a in li.attrib if a != parse_type and not (alt and a == XML_LANG))
                    count += sum(1 for c in li if c.tag == '{%s}Description' % RDF and any(g.tag != '{%s}value' % RDF for g in c))
            if count:
                found[key] = count
    return found
