"""Saved sweep admission and copy controls over an original native fixture."""
import copy
from pathlib import Path
import tempfile
import struct
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from schemaxis.adaptors.freecad import source_envelope
from schemaxis.adaptors.freecad.assembly_sources_saved import Saved, isomorphic, _copied_placement
from schemaxis.core.faults import SchemaxisError

FIXTURE = Path(__file__).resolve().parents[1]/'fixtures/freecad-history-sources/flanged-elbow.FCStd'


class SweepSources(unittest.TestCase):
    def facts(self):
        saved = Saved(FIXTURE)
        parameters = [name[4:] for name in saved.xml.properties['SchemaxisParameters'] if name.startswith('dim_')]
        return {'generation': 2, 'objects': saved.xml.types, 'parameters': parameters}

    def test_native_pipe_source_is_admitted_but_foreign_properties_are_refused(self):
        facts = self.facts()
        self.assertTrue(source_envelope.inspect(FIXTURE, facts, 'fixture')['payloads'])
        with ZipFile(FIXTURE) as archive:
            members = {n: archive.read(n) for n in archive.namelist()}
        with tempfile.TemporaryDirectory() as directory:
            for mutation in ('foreign', 'missing'):
                root = ET.fromstring(members['Document.xml'])
                props = root.find('./ObjectData/Object[@name="N3"]/Properties')
                if mutation == 'foreign':
                    ET.SubElement(props, 'Property', name='Payload', type='App::PropertyPythonObject')
                else:
                    props.remove(props.find('Property[@name="Spine"]'))
                props.set('Count', str(len(props.findall('Property'))))
                path = Path(directory)/(mutation+'.FCStd')
                # Retain the real fixed prolog; the intended closed vocabulary
                # or property-membership gate must be what refuses the mutation.
                data = members['Document.xml'].split(b'<Document ', 1)[0]+ET.tostring(root)
                with ZipFile(path, 'w') as archive:
                    for name, content in members.items():
                        archive.writestr(name, data if name == 'Document.xml' else content)
                with self.assertRaises(SchemaxisError) as caught:
                    source_envelope.inspect(path, facts, 'fixture')
                self.assertIn(caught.exception.fault.message, (
                    'Source object properties differ from the qualified set for its type',
                    'Saved element or attribute is outside the qualified source vocabulary'))

    def copied(self):
        original, embedded = Saved(FIXTURE), Saved(FIXTURE)
        for name, kind in embedded.xml.types.items():
            if kind == 'Sketcher::SketchObject':
                props = embedded.xml.properties[name]
                point = props['AttacherType'][0].get('value') == 'Attacher::AttachEnginePoint'
                props['AttacherEngine'].find('Integer').set('value', '3' if point else '1')
        return original, embedded

    def test_centroid_attachment_keeps_its_point_engine(self):
        original, embedded = self.copied()
        mapping = {name: name for name in original.objects}
        self.assertTrue(isomorphic(original, embedded, mapping, set(), [], 'fixture', regenerated_shadows=True))
        embedded.xml.properties['N6']['AttacherEngine'].find('Integer').set('value', '1')
        with self.assertRaisesRegex(ValueError, 'attacher engine changed unexpectedly'):
            isomorphic(original, embedded, mapping, set(), [], 'fixture', regenerated_shadows=True)

    def test_copy_roundoff_cannot_hide_a_changed_placement_or_property(self):
        original, embedded = self.copied()
        value = embedded.xml.properties['N2']['Placement'][0]
        value.set('Q3', '0.0000000000000001')
        self.assertTrue(_copied_placement(original, embedded, 'N2', 'N2', 'Placement'))
        for field in ('Px', 'Q0', 'A', 'Oz'):
            altered = copy.deepcopy(embedded)
            element = altered.xml.properties['N2']['Placement'][0]
            element.set(field, str(float(element.get(field))+1e-7))
            with self.subTest(field=field):
                self.assertFalse(_copied_placement(original, altered, 'N2', 'N2', 'Placement'))
        embedded.xml.properties['N2']['Placement'].set('type', 'App::PropertyString')
        self.assertFalse(_copied_placement(original, embedded, 'N2', 'N2', 'Placement'))

    def test_derived_direction_roundoff_preserves_real_axis_changes(self):
        original, embedded = self.copied()
        mapping = {name: name for name in original.objects}
        vector = embedded.xml.properties['N7']['Direction'][0]
        vector.set('valueY', '0.0000000000000002')
        self.assertTrue(isomorphic(original, embedded, mapping, set(), [], 'fixture', regenerated_shadows=True))
        vector.set('valueY', '0.0000001')
        with self.assertRaisesRegex(ValueError, 'sketch-normal direction differs'):
            isomorphic(original, embedded, mapping, set(), [], 'fixture', regenerated_shadows=True)

    def test_archive_feature_refusals_are_structured_before_native_open(self):
        original = FIXTURE.read_bytes()
        # Inert ZIP-header changes only: no encrypted or executable content.
        with tempfile.TemporaryDirectory() as directory:
            for label, offset, value in (('encrypted-local', 6, 1), ('unsupported-method', 8, 99)):
                data = bytearray(original)
                struct.pack_into('<H', data, offset, value)
                path = Path(directory)/(label+'.FCStd')
                path.write_bytes(data)
                with self.subTest(label=label), self.assertRaises(SchemaxisError) as caught:
                    source_envelope.inspect(path, self.facts(), 'fixture')
                self.assertEqual(caught.exception.fault.code, 'UNSUPPORTED_SOURCE')
                self.assertEqual(caught.exception.fault.message, 'Saved source archive cannot be decoded safely')
