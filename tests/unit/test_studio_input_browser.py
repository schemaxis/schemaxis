"""Local input chooser lists paths without uploading case data."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from schemaxis.studio_files import browse_inputs, choose_input_file
from schemaxis.studio_catalogue import catalogue
from schemaxis.core.faults import SchemaxisError


class StudioInputBrowserTests(unittest.TestCase):
    def test_desktop_chooser_selects_existing_files_without_shell_and_handles_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / 'case with spaces.foam'; selected.touch()
            app = SimpleNamespace(session=SimpleNamespace(workspace=root))
            with patch('schemaxis.studio_files.shutil.which', return_value='/usr/bin/zenity'), \
                 patch.dict('os.environ', {'DISPLAY': ':0'}), \
                 patch('schemaxis.studio_files.subprocess.run') as run:
                run.return_value = SimpleNamespace(returncode=0, stdout=str(selected) + '\n')
                self.assertEqual(choose_input_file(app, '', ['.foam']), {'status': 'selected', 'path': str(selected)})
                args = run.call_args.args[0]
                self.assertIn('--filename=' + str(root) + '/', args)
                self.assertIn('--file-filter=Supported files | *.foam', args)
                self.assertNotIn('shell', run.call_args.kwargs)
                run.return_value = SimpleNamespace(returncode=1, stdout='')
                self.assertEqual(choose_input_file(app, '', []), {'status': 'cancelled'})
                run.return_value = SimpleNamespace(returncode=0, stdout=str(root))
                with self.assertRaises(SchemaxisError): choose_input_file(app, '', [])
            with patch('schemaxis.studio_files.shutil.which', return_value=None):
                self.assertEqual(choose_input_file(app, '', [])['status'], 'unavailable')

    def test_extension_spellings_and_compressed_suffixes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('case.FOAM', 'volume.nii.gz', 'archive.gz'):
                (root / name).touch()
            app = SimpleNamespace(session=SimpleNamespace(workspace=root))
            for extension in ('foam', '.foam', '*.foam'):
                self.assertEqual([entry['name'] for entry in browse_inputs(app, extensions=extension)['entries']], ['case.FOAM'])
            self.assertEqual([entry['name'] for entry in browse_inputs(app, extensions='.nii.gz')['entries']], ['volume.nii.gz'])
            with self.assertRaises(SchemaxisError):
                browse_inputs(app, extensions=['.foam'])

    def test_matching_files_and_folder_navigation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'case').mkdir()
            (root / 'case' / 'coupe.foam').touch()
            (root / 'notes.txt').touch()
            app = SimpleNamespace(session=SimpleNamespace(workspace=root))
            listing = browse_inputs(app, extensions='.foam')
            self.assertEqual([entry['name'] for entry in listing['entries']], ['case'])
            case = browse_inputs(app, str(root / 'case'), '.foam')
            self.assertEqual(case['parent'], str(root))
            self.assertEqual(case['entries'][0]['path'], str(root / 'case' / 'coupe.foam'))
            self.assertFalse(case['entries'][0]['directory'])
            with self.assertRaises(SchemaxisError):
                browse_inputs(app, str(root / 'missing'))

    def test_foam_guidance_and_chooser_remain_adaptor_owned(self):
        result = catalogue('paraview')
        foam = next(item for item in result['items'] if item['id'] == 'operation:foam')
        self.assertIn('unique name', foam['schema']['properties']['id']['description'])
        options = result['definitions']['options-foam']['properties']
        self.assertIn('not from the JSON', options['file']['description'])
        self.assertEqual(options['file']['x-studio-file']['extensions'], ['.foam'])
        for name in ('caseType', 'regions', 'cellArrays', 'skipZero'):
            self.assertGreater(len(options[name]['description']), 80)
