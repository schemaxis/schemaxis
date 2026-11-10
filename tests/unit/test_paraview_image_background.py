import json
from pathlib import Path
import tempfile
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.job import plan, verify_receipt
from test_paraview_publication_framing import CUBE, receipt_fixture


def document(**writer):
    return {'version': 'schemaxis/1', 'nodes': [{'id': 's', 'filter': 'sphere'}],
            'scenes': [{'id': 's', 'visible': {'s': {}},
                        'images': [{'id': 'view', 'cameras': [{}], **writer}]}]}


def writer_of(value):
    return plan(value)[1][0]['images'][0]


class BackgroundValidationTests(unittest.TestCase):
    def fault(self, code, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, code)

    def test_omitted_background_is_opaque_white(self):
        writer = writer_of(document())
        self.assertEqual((writer['background'], writer['transparentBackground']), ([1, 1, 1], False))

    def test_named_hex_and_rgb_backgrounds_resolve_to_rgb(self):
        for value, expected in (('black', [0.0, 0.0, 0.0]), ('#336699', [0.2, 0.4, 0.6]), ([0.1, 0.2, 0.3], [0.1, 0.2, 0.3])):
            with self.subTest(value=value):
                self.assertEqual(writer_of(document(background=value))['background'], expected)

    def test_transparency_is_a_separate_switch(self):
        writer = writer_of(document(background='black', transparentBackground=True))
        self.assertEqual((writer['background'], writer['transparentBackground']), ([0.0, 0.0, 0.0], True))

    def test_translucent_backgrounds_are_refused_with_the_alternative_named(self):
        for value in ('none', '#33669980'):
            with self.subTest(value=value):
                self.fault('INVALID_BACKGROUND', lambda: plan(document(background=value)))

    def test_malformed_backgrounds_are_refused(self):
        for value in ([1, 0, 0, 1], [2, 0, 0], 'not-a-colour', 7):
            with self.subTest(value=value):
                with self.assertRaises(SchemaxisError):
                    plan(document(background=value))
        with self.assertRaises(SchemaxisError):
            plan(document(transparentBackground='yes'))

    def test_background_is_part_of_the_authored_plan_digest(self):
        self.assertNotEqual(plan(document())[2]['pipeline']['digest'],
                            plan(document(background='black'))[2]['pipeline']['digest'])


class BackgroundReceiptTests(unittest.TestCase):
    CAMERA = {'direction': [1, 0, 0], 'up': [0, 0, 1]}

    def fault(self, action):
        with self.assertRaises(SchemaxisError) as caught:
            action()
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')

    def fixture(self, directory, background):
        master, scenes, receipt, artifact = receipt_fixture(directory, self.CAMERA, CUBE, None, 0)
        artifact.pop('camera')
        writer = scenes[0]['images'][0]
        writer.update(background)
        return master, scenes, receipt, artifact

    def write(self, directory, receipt):
        (directory / 'verification.json').write_text(json.dumps(receipt))

    def test_receipts_before_backgrounds_verify_only_the_old_white_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            master, scenes, receipt, _ = self.fixture(directory, {})
            self.assertTrue(verify_receipt(directory, master, scenes)['verified'])
            scenes[0]['images'][0]['background'] = [0.0, 0.0, 0.0]
            self.fault(lambda: verify_receipt(directory, master, scenes))

    def test_versioned_receipts_bind_requested_and_native_background(self):
        requested = {'background': [0.2, 0.4, 0.6], 'transparentBackground': True}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            master, scenes, receipt, artifact = self.fixture(directory, requested)
            receipt['backgroundVersion'] = 1
            artifact['effectiveBackground'] = dict(requested)
            artifact['background'] = {'colour': [0.2, 0.4, 0.6], 'transparent': True,
                                      'channels': 4, 'backgroundPixels': 10}
            self.write(directory, receipt)
            self.assertTrue(verify_receipt(directory, master, scenes)['verified'])
            for key, wrong in (('colour', [0.2, 0.4, 0.7]), ('transparent', False)):
                with self.subTest(observed=key):
                    original = artifact['background'][key]
                    artifact['background'][key] = wrong
                    self.write(directory, receipt)
                    self.fault(lambda: verify_receipt(directory, master, scenes))
                    artifact['background'][key] = original
            artifact['effectiveBackground']['transparentBackground'] = False
            self.write(directory, receipt)
            self.fault(lambda: verify_receipt(directory, master, scenes))
            del artifact['effectiveBackground']
            self.write(directory, receipt)
            self.fault(lambda: verify_receipt(directory, master, scenes))


if __name__ == '__main__':
    unittest.main()
