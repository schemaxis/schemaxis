"""Host timeline semantics, independent expectations and evidence failure coverage."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from schemaxis.adaptors.shotcut import adaptor
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]


class ShotcutTests(unittest.TestCase):
    def document(self):
        return json.loads((ROOT / 'examples/schemaxis/shotcut-timeline.json').read_text())

    def fault(self, document, code):
        with self.assertRaises(SchemaxisError) as raised: adaptor.plan(document)
        self.assertEqual(raised.exception.fault.code, code)

    def test_timeline_ranges_coverage_and_source_preservation(self):
        document = self.document()
        before = copy.deepcopy(document)
        prepared = adaptor.plan(document)
        self.assertEqual(document, before)
        self.assertEqual(prepared['frames'], 5)
        self.assertEqual(prepared['duration'], 0.2)
        self.assertEqual([s['timelineStart'] for s in prepared['segments']], [0, 3])
        root = ET.fromstring(adaptor.project(prepared, Path('/tmp/shotcut-test')))
        self.assertEqual([e.attrib for e in root.find("playlist[@id='timeline']").findall('entry')],
                         [{'producer': 'asset-colours', 'in': '3', 'out': '5'}, {'producer': 'asset-colours', 'in': '0', 'out': '1'}])
        self.assertEqual(root.find("producer[@id='asset-colours']/property[@name='resource']").text, 'asset-00.media')

    def test_names_ranges_and_budget_rejections(self):
        for edit, code in [
            (lambda o: o['clips'][0].update(asset='missing'), 'INVALID_SELECTION'),
            (lambda o: o['assets'].append(copy.deepcopy(o['assets'][0])), 'INVALID_ASSET'),
            (lambda o: o['assets'][0].update(file='relative.mkv'), 'INVALID_RESOURCE'),
            (lambda o: o['clips'][0].update(startFrame=599, frameCount=2), 'INVALID_RANGE'),
            (lambda o: o['clips'][0].update(frameCount=600, startFrame=0), 'RESOURCE_LIMIT'),
            (lambda o: o.update(width=4096, height=4096), 'RESOURCE_LIMIT'),
        ]:
            document = self.document()
            edit(document['nodes'][0]['options'])
            self.fault(document, code)

    def probe(self):
        return {'streams': [{'codec_type': 'video', 'codec_name': 'ffv1', 'width': 32, 'height': 24, 'nb_read_frames': '6',
                             'avg_frame_rate': '25/1', 'r_frame_rate': '25/1', 'sample_aspect_ratio': '1:1', 'field_order': 'progressive'}],
                'format': {'duration': '0.24'}, 'frames': [{'media_type': 'video', 'interlaced_frame': 0, 'best_effort_timestamp_time': str(i / 25)} for i in range(6)]}

    def test_probe_rejects_mismatch_vfr_rotation_audio_and_malformed_evidence(self):
        options = adaptor.plan(self.document())['nodes'][0]['options']
        self.assertEqual(adaptor._probe(self.probe(), options), 6)
        for edit in [lambda p: p['frames'][2].update(best_effort_timestamp_time='0.09'),
                     lambda p: p['frames'][1].update(interlaced_frame=1),
                     lambda p: p['frames'][1].pop('interlaced_frame'),
                     lambda p: p['streams'][0].update(width=30),
                     lambda p: p['streams'][0].update(side_data_list=[{'rotation': 90}]),
                     lambda p: p['streams'].append({'codec_type': 'audio'}),
                     lambda p: p.update(frames=[None]),
                     lambda p: p['streams'][0].update(side_data_list=[None])]:
            probe = self.probe();edit(probe)
            with self.assertRaises(SchemaxisError) as raised: adaptor._probe(probe, options)
            self.assertEqual(raised.exception.fault.code, 'INVALID_MEDIA')

    def test_pixel_order_and_error_bounds(self):
        expected = bytes((255, 0, 0, 0, 255, 0))
        self.assertEqual(adaptor._compare(expected, expected, 3), [{'mean': 0, 'maximum': 0}, {'mean': 0, 'maximum': 0}])
        for actual in (expected[3:] + expected[:3], expected[:-1], bytes((240, 0, 0, 0, 255, 0))):
            with self.assertRaises(SchemaxisError) as raised: adaptor._compare(expected, actual, 3)
            self.assertEqual(raised.exception.fault.code, 'VERIFICATION_FAILED')

    def test_provisional_threads_do_not_resolve_media(self):
        document = self.document()
        document['nodes'][0]['options']['assets'][0]['file'] = {'$artifact': 'pending'}
        self.assertEqual(adaptor.provisionalResources(document, {}, 'edit'), {'threads': 1})
        with self.assertRaises(SchemaxisError): adaptor.provisionalResources(document, {'threads': 2}, 'edit')

    def test_cumulative_decode_budget_prevents_second_native_decode(self):
        document = self.document()
        options = document['nodes'][0]['options']
        media = str(ROOT / 'examples/schemaxis/shotcut-colours.mkv')
        options['assets'] = [{'name': 'first', 'file': media}, {'name': 'second', 'file': media}]
        options['clips'] = [{'asset': name, 'frameCount': 1} for name in ('first', 'second')]
        stages = []
        def execute(command, directory, stage, timeout, environment=None):
            stages.append(stage)
            if stage.endswith('-probe'):
                (Path(directory) / (stage + '.stdout')).write_text(json.dumps(self.probe()))
        with tempfile.TemporaryDirectory() as directory, patch.object(adaptor, 'MAX_BYTES', 20000), \
                patch.object(adaptor, '_tools', return_value=('/tmp/melt', '/tmp/ffmpeg', '/tmp/ffprobe')), \
                patch.object(adaptor, 'execute', side_effect=execute):
            with self.assertRaises(SchemaxisError) as raised:
                adaptor.run(document, Path(directory) / 'attempt')
            self.assertEqual(raised.exception.fault.code, 'RESOURCE_LIMIT')
            self.assertEqual(stages, ['asset-00-probe', 'asset-00-decode', 'asset-01-probe'])

    def test_missing_evidence_and_unavailable_native_are_structured(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SchemaxisError) as raised: adaptor.verify(directory)
            self.assertEqual(raised.exception.fault.code, 'VERIFICATION_FAILED')
            with self.assertRaises(SchemaxisError) as raised: adaptor.run(self.document(), Path(directory) / 'new', executable='/missing/Shotcut.app/melt')
            self.assertEqual(raised.exception.fault.code, 'INTERPRETER_NOT_FOUND')

    def test_fifo_source_is_rejected_before_native_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / 'source.fifo'
            os.mkfifo(fifo)
            document = self.document()
            document['nodes'][0]['options']['assets'][0]['file'] = str(fifo)
            with self.assertRaises(SchemaxisError) as raised: adaptor.reusableInputs(document)
            self.assertEqual(raised.exception.fault.code, 'INVALID_RESOURCE')
            with patch.object(adaptor, '_tools', return_value=('/tmp/melt', '/tmp/ffmpeg', '/tmp/ffprobe')), \
                    patch.object(adaptor, 'execute', side_effect=AssertionError('must not launch native')):
                with self.assertRaises(SchemaxisError) as raised: adaptor.run(document, Path(directory) / 'attempt')
            self.assertEqual(raised.exception.fault.code, 'INVALID_RESOURCE')

    def test_fingerprinting_bounds_and_malformed_paths(self):
        document = self.document()
        document['nodes'][0]['options']['assets'][0]['file'] = '/tmp/source\x00.mkv'
        self.fault(document, 'INVALID_RESOURCE')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.mkv'
            source.write_bytes(b'123456789')
            document['nodes'][0]['options']['assets'][0]['file'] = str(source)
            with patch.object(adaptor, 'MAX_BYTES', 8):
                with self.assertRaises(SchemaxisError) as raised: adaptor._source_bytes(str(source))
                self.assertEqual(raised.exception.fault.code, 'RESOURCE_LIMIT')

    def test_bundle_rejects_changed_members_and_is_deterministic(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            prepared = adaptor.plan(self.document())
            (target / 'project.mlt').write_bytes(adaptor.project(prepared, target))
            (target / 'asset-00.media').write_bytes(b'fixture media')
            adaptor._write_bundle(target, prepared)
            original = (target / 'project-bundle.zip').read_bytes()
            adaptor._check_bundle(target, prepared)
            adaptor._write_bundle(target, prepared)
            self.assertEqual((target / 'project-bundle.zip').read_bytes(), original)
            with zipfile.ZipFile(target / 'project-bundle.zip', 'a') as archive: archive.writestr('../outside', b'bad')
            with self.assertRaises(SchemaxisError) as raised: adaptor._check_bundle(target, prepared)
            self.assertEqual(raised.exception.fault.code, 'VERIFICATION_FAILED')


if __name__ == '__main__': unittest.main()
