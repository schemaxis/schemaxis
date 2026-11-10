"""Exercise actual HTTP boundaries and media seeking, without a native app."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from schemaxis_viewer.__main__ import inventory, make_server


class ArtifactViewerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root/'data'
        self.data.mkdir()
        (self.data/'sample.txt').write_bytes(b'0123456789')
        (self.root/'private.txt').write_text('outside selection')
        (self.data/'outside.txt').symlink_to(self.root/'private.txt')
        self.server = make_server([self.data])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = self.server.viewer_url

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temporary.cleanup()

    def test_only_explicit_selection_is_addressable(self):
        records = json.load(urlopen(self.url+'inventory.json'))
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]['name'].endswith('/sample.txt'))
        self.assertNotIn('_path', records[0])
        base = self.url.split('/', 3)[:3]
        address = '/'.join(base)+records[0]['url']
        self.assertEqual(urlopen(address).read(), b'0123456789')
        for route in ('file/1', 'file/../private.txt', '../private.txt', 'subdir/../../private.txt'):
            with self.subTest(route=route), self.assertRaises(HTTPError) as caught:
                urlopen(self.url+route)
            self.assertEqual(caught.exception.code, 404)
        with self.assertRaises(HTTPError):
            urlopen('/'.join(base)+'/inventory.json')

    def test_ranges_and_head(self):
        for value, expected, start, end in [('bytes=2-5', b'2345', 2, 5),
                                             ('bytes=8-', b'89', 8, 9),
                                             ('bytes=-3', b'789', 7, 9)]:
            with urlopen(Request(self.url+'file/0', headers={'Range': value})) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), expected)
                self.assertEqual(response.headers['Content-Range'], f'bytes {start}-{end}/10')
        for value in ('bytes=20-', 'bytes=4-2', 'bytes=1-3,5-7', 'bytes=-0'):
            with self.subTest(value=value), self.assertRaises(HTTPError) as caught:
                urlopen(Request(self.url+'file/0', headers={'Range': value}))
            self.assertEqual(caught.exception.code, 416)
        with urlopen(Request(self.url+'file/0', method='HEAD')) as response:
            self.assertEqual(response.headers['Content-Length'], '10')
            self.assertEqual(response.read(), b'')

    def test_changed_artifacts_require_rescan(self):
        (self.data/'sample.txt').write_text('new content')
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url+'file/0')
        self.assertEqual(caught.exception.code, 409)

    def test_assets_and_csp(self):
        for name in ('', 'app.mjs', 'scene.mjs', 'style.css'):
            with urlopen(self.url+name) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("object-src 'none'", response.headers['Content-Security-Policy'])
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                self.assertGreater(len(response.read()), 0)

    def test_local_folder_library_paths_ranges_history_and_origin(self):
        body = json.dumps({'paths': [str(self.data)]}).encode()
        request = Request(self.url+'api/open', data=body, headers={'Content-Type': 'application/json'})
        with urlopen(request) as response:
            selected = json.load(response)
        record = selected['records'][0]
        self.assertEqual(record['relativePath'], 'sample.txt')
        self.assertNotIn('_fingerprint', record)
        self.assertNotIn('_path', record)
        origin = self.url.split('/', 3)[:3]
        url = '/'.join(origin)+record['url']
        with urlopen(Request(url, headers={'Range': 'bytes=2-5'})) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b'2345')
        with urlopen(self.url+'api/library') as response:
            self.assertEqual(json.load(response)['recent'][0]['paths'], [str(self.data)])
        denied = Request(self.url+'api/open', data=body, headers={'Origin': 'https://foreign.invalid'})
        with self.assertRaises(HTTPError) as caught:
            urlopen(denied)
        self.assertEqual(caught.exception.code, 403)
        (self.data/'sample.txt').write_text('changed')
        with self.assertRaises(HTTPError) as caught:
            urlopen(url)
        self.assertEqual(caught.exception.code, 409)

    def test_persistent_recent_references_do_not_copy_media(self):
        from schemaxis_viewer.library import LocalLibrary
        history = self.root/'history.json'
        library = LocalLibrary(history)
        identity = library.register([self.data], kind='run', expected={
            str(self.data/'sample.txt'): __import__('hashlib').sha256(b'0123456789').hexdigest()})
        library.set_preferences({'theme': 'dark', 'sidebarCollapsed': True})
        restored = LocalLibrary(history)
        self.assertEqual(restored.preferences, {'theme': 'dark', 'sidebarCollapsed': True})
        records = restored.records(identity, '/viewer/')
        self.assertEqual(len(records), 1)
        self.assertNotIn('0123456789', history.read_text())
        (self.data/'sample.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'changed after verification'):
            LocalLibrary(history).records(identity, '/viewer/')

    def test_folder_run_recognition_requires_the_metadata_contract(self):
        from schemaxis_viewer.library import LocalLibrary
        manifest = self.data/'publication-metadata.json'
        manifest.write_text(json.dumps({'version': 'foreign/1', 'publications': []}))
        library = LocalLibrary()
        identity = library.register([self.data])
        self.assertEqual(library.collections[identity]['info']['kind'], 'collection')
        manifest.write_text(json.dumps({'version': 'schemaxis.artifact-metadata/1', 'publications': []}))
        identity = library.register([self.data])
        self.assertEqual(library.collections[identity]['info']['kind'], 'run')

    def test_overlapping_selections_are_deduplicated(self):
        self.assertEqual(len(inventory([self.data, self.data/'sample.txt'])), 1)


if __name__ == '__main__':
    unittest.main()
