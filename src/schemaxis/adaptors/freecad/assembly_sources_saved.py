"""Independent saved-file verification of a sourced assembly (no FreeCAD imports).

Each embedded source must be the producer's own saved objects under one bijective
rename: identical types, properties, dependencies and expressions, with every
object reference staying inside that source. The only accepted differences are
the adaptor-set labels and visibility, mounts appended to the Body group, the
sketch attacher engine FreeCAD selects when copying (Engine 3D -> Engine Plane),
property status bits, and last-digit differences in fixed origin-helper placements.
"""
from .document_xml import ARCHIVE_ERRORS
import math
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, LargeZipFile

from schemaxis.errors import fail

IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
REFERENCES = {('Link', 'value'), ('Link', 'obj'), ('LinkSub', 'value'), ('XLink', 'name'),
              ('Dep', 'Name'), ('ObjectDeps', 'Name')}
FILES = {('Part', 'file'), ('ElementMap2', 'file')}
ORIGIN_TYPES = {'App::Origin', 'App::Line', 'App::Plane', 'App::Point'}
JOINT_STATE = {'value': 'bnVsbA==', 'encoded': 'yes', 'module': 'JointObject'}


class Saved:
    """Document.xml plus dependency records, read through the bounded app reader."""

    def __init__(self, path):
        from .document_xml import Document
        self.xml = Document(path)
        self.root = self.xml.root
        self.objects = {o.get('name'): o for o in self.root.findall('./Objects/Object')}
        self.data = {o.get('name'): o for o in self.root.findall('./ObjectData/Object')}
        self.deps = {}
        for record in self.root.findall('./Objects/ObjectDeps'):
            if record.get('Name') in self.deps:
                raise ValueError('duplicate saved dependency record')
            self.deps[record.get('Name')] = record

    def placement(self, name, prop):
        item = self.xml.child(name, prop, 'PropertyPlacement', 'App::PropertyPlacement')
        x, y, z, w = (float(item.attrib[k]) for k in ('Q0', 'Q1', 'Q2', 'Q3'))
        p = [float(item.attrib[k]) for k in ('Px', 'Py', 'Pz')]
        norm = math.sqrt(x*x+y*y+z*z+w*w)
        if not all(math.isfinite(v) for v in (x, y, z, w, *p)) or abs(norm-1) > 1e-9:
            raise ValueError('saved placement is not a finite rigid transform: '+name+'.'+prop)
        r = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
             [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
        return [*r[0], p[0], *r[1], p[1], *r[2], p[2], 0.0, 0.0, 0.0, 1.0]


def _rename(text, own, foreign, where):
    def replace(match):
        token = match.group(0)
        if token in own:
            return own[token]
        if token in foreign:
            raise ValueError('cross-owner object reference '+token+' in '+where)
        return token
    return IDENTIFIER.sub(replace, text)


def _canonical(element, own, foreign, where):
    """Rename this source's references back to producer names; refuse foreign ones."""
    attributes = {}
    for key, value in element.attrib.items():
        if key == 'status':
            continue
        if (element.tag, key) in REFERENCES:
            if value in foreign:
                raise ValueError('cross-owner object reference '+value+' in '+where)
            value = own.get(value, value)
        elif (element.tag, key) in FILES or (element.tag, key) == ('Expression', 'expression'):
            if '<<' in value:
                raise ValueError('label references are outside the embedded source contract: '+where)
            value = _rename(value, own, foreign, where)
        attributes[key] = value
    return (element.tag, tuple(sorted(attributes.items())), (element.text or '').strip(),
            tuple(_canonical(child, own, foreign, where) for child in element))


def isomorphic(producer, assembly, mapping, foreign, mounts, label):
    """Prove one embedded source equals its producer under the recorded rename."""
    back = {new: old for old, new in mapping.items()}
    if set(producer.objects) != set(mapping) or set(producer.data) != set(mapping):
        raise ValueError(label+': producer object membership differs from the rename map')
    if set(producer.deps) - set(mapping):
        raise ValueError(label+': producer dependency records name unknown objects')
    for old, new in mapping.items():
        where = label+'.'+old
        if new not in assembly.objects or producer.objects[old].get('type') != assembly.objects[new].get('type'):
            raise ValueError(where+': embedded object is absent or has another type')
        p_attr = {k: v for k, v in producer.objects[old].attrib.items() if k not in ('name', 'id')}
        a_attr = {k: v for k, v in assembly.objects[new].attrib.items() if k not in ('name', 'id')}
        if p_attr != a_attr or {k: v for k, v in producer.data[old].attrib.items() if k != 'name'} \
                != {k: v for k, v in assembly.data[new].attrib.items() if k != 'name'}:
            raise ValueError(where+': object record attributes differ')
        p_dep, a_dep = producer.deps.get(old), assembly.deps.get(new)
        if (p_dep is None) != (a_dep is None):
            raise ValueError(where+': saved dependency record differs')
        if p_dep is not None:
            a_dep = ET.fromstring(ET.tostring(a_dep))
            if producer.objects[old].get('type') == 'PartDesign::Body' and mounts:
                tail = [d.get('Name') for d in list(a_dep)[-len(mounts):]]
                if tail != mounts or a_dep.get('Count') != str(int(p_dep.get('Count'))+len(mounts)):
                    raise ValueError(where+': Body dependencies do not end with the declared mounts')
                for item in list(a_dep)[-len(mounts):]:
                    a_dep.remove(item)
                a_dep.set('Count', p_dep.get('Count'))
            if _canonical(p_dep, {}, set(), where) != _canonical(a_dep, back, foreign, where):
                raise ValueError(where+': saved dependency record differs')
        p_props, a_props = producer.xml.properties[old], assembly.xml.properties[new]
        if set(p_props) != set(a_props):
            raise ValueError(where+': property membership differs')
        kind = producer.objects[old].get('type')
        for prop, element in p_props.items():
            if prop in ('Label', 'Visibility'):
                continue
            ours = a_props[prop]
            if prop == 'Group' and kind == 'PartDesign::Body':
                links = [l.get('value') for l in ours.find('LinkList')]
                appended = links[len(links)-len(mounts):] if mounts else []
                if appended != mounts or ours.find('LinkList').get('count') != str(len(links)):
                    raise ValueError(where+': Body group does not end with the declared mounts')
                original = [l.get('value') for l in element.find('LinkList')]
                if [back.get(v) for v in links[:len(links)-len(mounts)]] != original:
                    raise ValueError(where+': Body group differs from its producer')
                continue
            if prop == 'AttacherEngine' and kind == 'Sketcher::SketchObject':
                p_value, a_value = element.find('Integer'), ours.find('Integer')
                if p_value.get('value') not in ('0', '1') or a_value.get('value') != '1':
                    raise ValueError(where+': sketch attacher engine changed unexpectedly')
                strip = lambda e: _canonical(e, back, foreign, where)[:2]+((),)  # noqa: E731
                if [_canonical(c, back, foreign, where) for c in element if c.tag != 'Integer'] \
                        != [_canonical(c, back, foreign, where) for c in ours if c.tag != 'Integer'] or strip(element) != strip(ours):
                    raise ValueError(where+': sketch attacher engine list differs')
                continue
            if prop == 'Placement' and kind in ORIGIN_TYPES:
                a, b = producer.placement(old, prop), assembly.placement(new, prop)
                if any(abs(x-y) > 1e-12 for x, y in zip(a, b)):
                    raise ValueError(where+': origin helper placement differs')
                continue
            if _canonical(element, {}, set(), where) != _canonical(ours, back, foreign, where):
                raise ValueError(where+': property '+prop+' differs from its producer')
    return True


LINK_PROPERTIES = {'ColoredElements', 'ElementCount', 'ElementList', 'ExpressionEngine', 'Label', 'Label2', 'LinkClaimChild',
                   'LinkCopyOnChange', 'LinkCopyOnChangeGroup', 'LinkCopyOnChangeSource', 'LinkCopyOnChangeTouched',
                   'LinkExecute', 'LinkPlacement', 'LinkTransform', 'LinkedObject', 'Placement', 'PlacementList', 'Scale',
                   'ScaleList', 'ScaleVector', 'ShowElement', 'Visibility', 'VisibilityList', '_LinkOwner'}
MOUNT_PROPERTIES = {'AttacherEngine', 'AttacherType', 'AttachmentOffset', 'AttachmentSupport', 'ExpressionEngine', 'Label',
                    'Label2', 'MapMode', 'MapPathParameter', 'MapReversed', 'Placement', 'Shape', 'ShapeMaterial', 'Visibility'}


def _single(xml, name, prop, tag, typeid, attributes):
    element = xml.child(name, prop, tag, typeid)
    if {k: element.get(k) for k in attributes} != attributes:
        raise ValueError(name+'.'+prop+' differs from the adaptor-created state')
    return element


def _link_state(saved, name):
    """An App::Link exactly as the adaptor creates it: one plain, unscaled instance."""
    xml = saved.xml
    if set(xml.properties[name]) != LINK_PROPERTIES:
        raise ValueError(name+': component property membership differs')
    _single(xml, name, 'ElementCount', 'Integer', 'App::PropertyIntegerConstraint', {'value': '0'})
    if xml.links(name, 'ElementList') or xml.engine(name):
        raise ValueError(name+': component has elements or expressions')
    _single(xml, name, 'ColoredElements', 'LinkSub', 'App::PropertyLinkSubHidden', {'value': '', 'count': '0'})
    for prop, value in (('LinkClaimChild', 'false'), ('LinkCopyOnChangeTouched', 'false'), ('ShowElement', 'true')):
        _single(xml, name, prop, 'Bool', 'App::PropertyBool', {'value': value})
    _single(xml, name, 'LinkCopyOnChange', 'Integer', 'App::PropertyEnumeration', {'value': '0'})
    _single(xml, name, 'LinkCopyOnChangeGroup', 'Link', 'App::PropertyLink', {'value': ''})
    _single(xml, name, 'LinkCopyOnChangeSource', 'XLink', 'App::PropertyXLink', {'file': '', 'name': ''})
    _single(xml, name, 'LinkExecute', 'String', 'App::PropertyString', {'value': ''})
    _single(xml, name, 'Scale', 'Float', 'App::PropertyFloat', {'value': '1.0000000000000000'})
    _single(xml, name, 'ScaleVector', 'PropertyVector', 'App::PropertyVector',
            {'valueX': '1.0000000000000000', 'valueY': '1.0000000000000000', 'valueZ': '1.0000000000000000'})
    _single(xml, name, 'VisibilityList', 'BoolList', 'App::PropertyBoolList', {'value': ''})


def _mount_state(saved, name):
    xml = saved.xml
    if set(xml.properties[name]) != MOUNT_PROPERTIES or xml.engine(name) is None:
        raise ValueError(name+': mount property membership differs')
    _single(xml, name, 'AttacherType', 'String', 'App::PropertyString', {'value': 'Attacher::AttachEngine3D'})
    _single(xml, name, 'MapReversed', 'Bool', 'App::PropertyBool', {'value': 'false'})
    _single(xml, name, 'MapPathParameter', 'Float', 'App::PropertyFloat', {'value': '0.0000000000000000'})
    engine = xml.properties[name]['AttacherEngine']
    if engine.get('type') != 'App::PropertyEnumeration' or [i.get('value') for i in engine.findall('Integer')] != ['0']:
        raise ValueError(name+': mount attacher engine differs')


def _require(condition, message, **detail):
    if not condition:
        raise ValueError(message+' '+str(detail))


def _python(saved, name):
    found = [p for p in saved.xml.properties[name].values() if p.get('type') == 'App::PropertyPythonObject']
    if not found:
        return None
    if len(found) != 1 or found[0].get('name') != 'Proxy' or len(found[0]) != 1 or found[0][0].tag != 'Python':
        raise ValueError('unexpected Python object property on '+name)
    attributes = dict(found[0][0].attrib)
    cls = attributes.pop('class', None)
    if attributes != JOINT_STATE or len(found[0][0]):
        raise ValueError('Python proxy state is not the installed joint null state on '+name)
    return cls


def verify_saved(prepared, path, renames, retained):
    from .assembly_sources import (check_archive, close, flat, frame, rot_z, labels, visibility, proxies,
                                   check_mount_expressions)
    from . import gui_state
    try:
        check_archive(path, 'model.FCStd', code='VERIFICATION_FAILED')
        from zipfile import ZipFile
        from .source_envelope import prolog
        with ZipFile(path) as archive:
            prolog(archive.read('Document.xml'), 'model.FCStd', 'VERIFICATION_FAILED')
            prolog(archive.read('GuiDocument.xml'), 'model.FCStd', 'VERIFICATION_FAILED', gui=True)
        saved = Saved(path)
        xml = saved.xml
        if any(x.get('file') for x in saved.root.iter('XLink')):
            raise ValueError('saved assembly links an external file')
        native = prepared['native']
        part_of = {c['id']: c['part'] for c in prepared['components']}
        components = native['components']
        joints = native['joints']
        expected = {}
        for part in prepared['parts']:
            for old, new in renames[part['id']].items():
                expected[new] = part['source']['objects'][old]
        expected.update({n: 'PartDesign::CoordinateSystem' for n in native['mounts'].values()})
        expected.update({'Assembly': 'Assembly::AssemblyObject', 'Joints': 'Assembly::JointGroup',
                         'Ground': 'App::FeaturePython', **{n: 'App::Link' for n in components.values()},
                         **{n: 'App::FeaturePython' for n in joints.values()}})
        origin = xml.link('Assembly', 'Origin')
        helpers = {origin: 'App::Origin', **{n: xml.types.get(n) for n in xml.links(origin, 'OriginFeatures')}}
        if sorted(helpers.values()) != sorted(['App::Origin', 'App::Line', 'App::Line', 'App::Line',
                                               'App::Plane', 'App::Plane', 'App::Plane', 'App::Point']) or set(helpers) & set(expected):
            raise ValueError('assembly origin helpers differ')
        expected.update(helpers)
        if xml.types != expected:
            raise ValueError('saved assembly object membership or type differs')
        found = {name: _python(saved, name) for name in xml.types}
        if {k: v for k, v in found.items() if v} != {'Ground': 'GroundedJoint', **{n: 'Joint' for n in joints.values()}}:
            raise ValueError('saved Python proxies differ from the controlled joint set')
        everything = set(xml.types)
        for part in prepared['parts']:
            producer = Saved(retained[part['id']])
            mapping = renames[part['id']]
            mounts = [native['mounts'][part['id']+'.'+m['id']] for m in part['mounts']]
            isomorphic(producer, saved, mapping, everything-set(mapping.values()), mounts, part['id'])
            for old, new in mapping.items():
                if part['source']['objects'][old] in ('App::Line', 'App::Plane', 'App::Point', 'App::Origin'):
                    label, producer_label = xml.string(new, 'Label'), producer.xml.string(old, 'Label')
                    # FreeCAD keeps the label base and renumbers its trailing digits on copy.
                    if not re.fullmatch(re.escape(producer_label.rstrip('0123456789'))+r'\d*', label):
                        raise ValueError('origin helper label changed unexpectedly: '+new)
            for mount in part['mounts']:
                key = part['id']+'.'+mount['id']
                name = native['mounts'][key]
                _mount_state(saved, name)
                support = xml.child(name, 'AttachmentSupport', 'LinkSubList', 'App::PropertyLinkSubList')
                if (support.get('count') != '1' or len(support) != 1 or support[0].attrib
                        != {'obj': mapping[part['source']['xyPlane']], 'sub': ''}):
                    raise ValueError(key+': mount support differs')
                if xml.child(name, 'MapMode', 'Integer', 'App::PropertyEnumeration').get('value') != '2':
                    raise ValueError(key+': mount map mode is not ObjectXY')
                wanted = prepared['expected']['mounts'][part['id']][mount['id']]
                for prop in ('AttachmentOffset', 'Placement'):
                    if not close(saved.placement(name, prop), wanted):
                        raise ValueError(key+': saved mount '+prop+' differs')
                check_mount_expressions(part, mount, renames, xml.engine(name), _require, key)
        for identity, name in components.items():
            part = next(p for p in prepared['parts'] if p['id'] == part_of[identity])
            link = xml.child(name, 'LinkedObject', 'XLink', 'App::PropertyXLink')
            if link.attrib != {'file': '', 'stamp': '', 'name': renames[part['id']][part['source']['body']]}:
                raise ValueError(identity+': component does not link its embedded source Body')
            if xml.boolean(name, 'LinkTransform') is not False:
                raise ValueError(identity+': component link transform changed')
            _link_state(saved, name)
            for prop in ('Placement', 'LinkPlacement'):
                if not close(saved.placement(name, prop), prepared['expected']['components'][identity]['matrix']):
                    raise ValueError(identity+': saved component '+prop+' differs from the analytic pose')
        if xml.string('Assembly', 'Type') != 'Assembly' or not close(saved.placement('Assembly', 'Placement'), flat(frame())):
            raise ValueError('assembly root differs')
        members = [*joints.values()]
        if xml.links('Joints', 'Group') != ['Ground', *members]:
            raise ValueError('joint group membership differs')
        if set(xml.links('Assembly', 'Group')) != {'Joints', 'Ground', *components.values(), *members}:
            raise ValueError('assembly membership differs')
        if xml.child('Ground', 'ObjectToGround', 'Link', 'App::PropertyLinkGlobal').get('value') != components[prepared['grounded']]:
            raise ValueError('ground does not hold the declared root')
        for joint in prepared['joints']:
            name = joints[joint['id']]
            kind = xml.properties[name]['JointType']
            index = kind.findall('Integer')
            names = [e.get('value') for e in kind.findall('./CustomEnumList/Enum')]
            if (kind.get('type') != 'App::PropertyEnumeration' or len(kind) != 2 or len(index) != 1
                    or not names or index[0].get('value') != '0' or names[0] != 'Fixed'):
                raise ValueError(joint['id']+': joint is not Fixed')
            for index, end in ((1, 'parent'), (2, 'child')):
                reference = xml.child(name, 'Reference%d' % index, 'XLink', 'App::PropertyXLinkSub')
                datum = native['mounts'][part_of[joint[end]['component']]+'.'+joint[end]['mount']]
                if (reference.get('file') != '' or reference.get('name') != components[joint[end]['component']]
                        or reference.get('count') != '2' or [s.get('value') for s in reference] != [datum+'.', datum+'.']
                        or any(s.tag != 'Sub' or set(s.attrib) != {'value'} for s in reference)):
                    raise ValueError(joint['id']+': saved mount reference differs')
            offset = flat(frame(joint['offset'], rot_z(joint['clocking'])))
            for prop, value in (('Offset1', offset), ('Placement1', offset), ('Offset2', flat(frame())), ('Placement2', flat(frame()))):
                if not close(saved.placement(name, prop), value):
                    raise ValueError(joint['id']+': saved '+prop+' differs')
            if any(xml.boolean(name, prop) for prop in ('Detach1', 'Detach2', 'Suppressed')):
                raise ValueError(joint['id']+': joint is detached or suppressed')
            if xml.engine(name):
                raise ValueError(joint['id']+': joint carries expressions')
        for name, label in labels(prepared, renames).items():
            if xml.string(name, 'Label') != label:
                raise ValueError('native label differs: '+name)
        gui_state.verify(path, visibility(prepared, list(xml.types), renames), proxies(prepared))
        from .assembly_payloads import bind
        bind(prepared, path, saved.root, renames, retained, lambda name: saved.placement(name, 'Placement'))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, *ARCHIVE_ERRORS) as error:
        fail('VERIFICATION_FAILED', 'Saved sourced assembly is malformed or differs from its contract', str(path), detail=str(error))
