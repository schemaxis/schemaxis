"""Host boundary checks for Shotcut result membership and source ranges.

A deterministic fake melt/ffmpeg/ffprobe trio drives the real runner, launchers
and verifier without a native Shotcut. It qualifies no native behaviour.
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.shotcut import adaptor
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[2]
WIDTH, HEIGHT, FRAMES = 32, 24, 6
COLOURS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)]
FFPROBE = '''
import json, sys
head, _, raw = open(sys.argv[-1], 'rb').read().partition(b'\\n')
w, h = map(int, head.split()[1:])
n = len(raw) // (w * h * 3)
print(json.dumps({'streams': [{'codec_type': 'video', 'codec_name': 'ffv1' if head.startswith(b'FAKEMKV') else 'h264',
    'width': w, 'height': h, 'nb_read_frames': str(n), 'avg_frame_rate': '25/1', 'r_frame_rate': '25/1',
    'sample_aspect_ratio': '1:1', 'field_order': 'progressive'}], 'format': {'duration': str(n / 25)},
    'frames': [{'media_type': 'video', 'interlaced_frame': 0, 'best_effort_timestamp_time': str(i / 25)} for i in range(n)]}))
'''
FFMPEG = '''
import sys
if sys.argv[1:2] == ['-version']: sys.exit(print('ffmpeg fake'))
open(sys.argv[-1], 'wb').write(open(sys.argv[sys.argv.index('-i') + 1], 'rb').read().partition(b'\\n')[2])
'''
MELT = '''
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
if sys.argv[1:2] == ['-version']: sys.exit(print('melt 7.41.0 fake'))
project, consumer = Path(sys.argv[1]), sys.argv[3]
if consumer.startswith('xml:'): sys.exit(Path(consumer[4:]).write_bytes(project.read_bytes()) and 0)
root = ET.parse(project).getroot()
width, height = (int(root.find('profile').get(k)) for k in ('width', 'height'))
chunk, out = width * height * 3, bytearray()
for entry in root.find("playlist[@id='timeline']").findall('entry'):
    producer = root.find("producer[@id='%s']" % entry.get('producer'))
    resource = [p.text for p in producer.findall('property') if p.get('name') == 'resource'][0]
    raw = (project.parent / resource).read_bytes().partition(b'\\n')[2]
    out += raw[int(entry.get('in')) * chunk:(int(entry.get('out')) + 1) * chunk]
Path(consumer[len('avformat:'):]).write_bytes(b'FAKEMKV %d %d\\n' % (width, height) + bytes(out))
'''


class ShotcutAllocationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        tools = self.root / 'tools'
        tools.mkdir()
        for name, body in (('melt', MELT), ('ffmpeg', FFMPEG), ('ffprobe', FFPROBE)):
            (tools / name).write_text('#!' + sys.executable + '\n' + body)
            (tools / name).chmod(0o755)
        self.melt = tools / 'melt'
        self.media = self.root / 'colours.media'
        self.media.write_bytes(b'FAKEMEDIA %d %d\n' % (WIDTH, HEIGHT) + b''.join(bytes(c) * WIDTH * HEIGHT for c in COLOURS))

    def document(self, **options):
        document = json.loads((ROOT / 'examples/schemaxis/shotcut-timeline.json').read_text())
        document['nodes'][0]['options']['assets'][0]['file'] = str(self.media)
        document['nodes'][0]['options'].update(options)
        return document

    def run_timeline(self, document=None, name='run'):
        return adaptor.run(document or self.document(), self.root / name, executable=str(self.melt), timeout=60)

    def rejected(self, directory, code='VERIFICATION_FAILED'):
        with self.assertRaises(SchemaxisError) as raised: adaptor._native_verify(directory)
        self.assertEqual(raised.exception.fault.code, code)
        return raised.exception.fault

    def test_fake_runtime_baseline_verifies(self):
        self.run_timeline()
        checked = adaptor._native_verify(self.root / 'run')
        self.assertEqual((checked['frames'], checked['duration']), (5, 0.2))

    def test_result_membership_must_match_the_verified_publications(self):
        self.run_timeline()
        directory = self.root / 'run'
        genuine = json.loads((directory / 'result.json').read_text())
        self.assertEqual(sorted(genuine), ['artifacts', 'project', 'projectBundle', 'status', 'verified', 'video'])
        for label, edit in {
                'video path elsewhere': lambda r: r.update(video='/nonexistent/video.mkv'),
                'bundle path elsewhere': lambda r: r.update(projectBundle=str(self.root / 'other.zip')),
                'project path swapped with video': lambda r: r.update(project=r['video'], video=r['project']),
                'artifact count': lambda r: r.update(artifacts=7),
                'artifact count boolean': lambda r: r.update(artifacts=True),
                'missing project': lambda r: r.pop('project'),
                'path not a string': lambda r: r.update(video=['video.mkv']),
        }.items():
            with self.subTest(label):
                result = dict(genuine)
                edit(result)
                (directory / 'result.json').write_text(json.dumps(result))
                self.assertIn('result', str(self.rejected(directory).message))
        (directory / 'result.json').write_text(json.dumps(genuine))
        self.assertEqual(adaptor._native_verify(directory)['frames'], 5)

    def test_unfinished_result_remains_an_incomplete_execution(self):
        self.run_timeline()
        directory = self.root / 'run'
        (directory / 'result.json').write_text(json.dumps({'status': 'incomplete', 'verified': False}))
        self.rejected(directory, 'INCOMPLETE_EXECUTION')

    def test_clip_beyond_actual_source_frames_fails_at_probe_with_details(self):
        document = self.document(clips=[{'asset': 'colours', 'startFrame': 4, 'frameCount': 3}])
        stages = []
        original = adaptor.execute
        def record(command, directory, stage, *args, **kwargs):
            stages.append(stage)
            return original(command, directory, stage, *args, **kwargs)
        with patch.object(adaptor, 'execute', side_effect=record):
            with self.assertRaises(SchemaxisError) as raised: self.run_timeline(document)
        fault = raised.exception.fault
        self.assertEqual(fault.code, 'INVALID_RANGE')
        self.assertEqual(fault.location, '$.nodes[0].options.clips[0]')
        self.assertEqual((fault.observed['asset'], fault.observed['sourceFrames'], fault.observed['requestedEnd']), ('colours', FRAMES, 7))
        self.assertEqual(stages, ['asset-00-probe'])
        self.assertEqual(json.loads((self.root / 'run/result.json').read_text())['fault']['code'], 'INVALID_RANGE')

    def test_final_clip_end_equal_to_source_frames_is_accepted(self):
        self.run_timeline(self.document(clips=[{'asset': 'colours', 'startFrame': 3, 'frameCount': 3}]))
        self.assertEqual(adaptor._native_verify(self.root / 'run')['frames'], 3)


if __name__ == '__main__': unittest.main()
