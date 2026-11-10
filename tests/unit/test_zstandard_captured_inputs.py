"""Pinned bytes and closed task-specific snapshot consumption agree with schemas."""
from pathlib import Path
import tempfile
import unittest
from schemaxis.captured_inputs import adopt, consume
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.zstandard.adaptor import OPTIONS, VERSION
from schemaxis.adaptors.zstandard.captured_inputs import accept_resource
from schemaxis.schema_authoring import version_schema


class ZstandardCapturedInputs(unittest.TestCase):
    def test_selected_task_positions_and_malformed_members_are_closed(self):
        resource = {'kind': 'file', 'member': 'data.bin'}
        for operation, options in OPTIONS.items():
            doc = {'version': VERSION, 'operation': operation}
            for key in ('source', 'dictionary', 'reference'):
                with self.subTest(operation=operation, key=key):
                    if key in options:
                        self.assertEqual(accept_resource(doc, '/' + key, resource)['reader'], key)
                    else:
                        with self.assertRaises(SchemaxisError):accept_resource(doc, '/' + key, resource)
        doc = {'version': VERSION, 'operation': 'concatenate', 'sources': ['a.zst', 'b.zst']}
        self.assertEqual(accept_resource(doc, '/sources/1', resource)['reader'], 'sources')
        for token in ('-1', '01', '²', '１', '9' * 5000, '2'):
            with self.subTest(token=token), self.assertRaises(SchemaxisError):
                accept_resource(doc, '/sources/' + token, resource)
        with self.assertRaises(SchemaxisError):
            accept_resource({**doc, 'sources': {'0': 'data'}}, '/sources/0', resource)
        for pointer in ('/profiles/0/id', '/level', '/sources/0/extra', '/fileSet/root'):
            with self.subTest(pointer=pointer), self.assertRaises(SchemaxisError):accept_resource(doc, pointer, resource)

    def test_true_snapshots_preserve_membership_and_pin_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);files = root/'original';files.mkdir()
            (files/'a.bin').write_bytes(b'\x00\xffalpha');(files/'b.bin').write_bytes(b'beta')
            file = adopt(files/'a.bin', root/'single')
            directory = adopt(files, root/'directory', kind='directory')
            doc = {'version': VERSION, 'operation': 'compress', 'source': file['reference']}
            resolved, evidence = consume(doc, 'document')
            self.assertEqual(Path(resolved['source']).read_bytes(), b'\x00\xffalpha')
            self.assertEqual(evidence[0]['policy']['scope'], 'selected pinned file')
            # Workflow composition resolves the task before the adaptor's
            # captured-input policy checks its selected field roles.
            from schemaxis.workflow import inspect_plan
            composed = {**doc, 'operation': {'$document': '/definitions/task'},
                        'definitions': {'task': 'compress'}}
            planned = inspect_plan({'version': 'schemaxis.workflow/1',
                                    'operations': [{'id': 'compress', 'document': composed}]})
            self.assertEqual(planned['operations'][0]['provisionalPlan']['operation'], 'compress')
            explicit = {**directory['reference'], 'member': 'b.bin'}
            self.assertEqual(Path(consume({**doc, 'source': explicit}, 'document')[0]['source']).read_bytes(), b'beta')
            selection = {'version': VERSION, 'operation': 'compressFiles', 'fileSet': {'root': directory['reference']}}
            result, records = consume(selection, 'document')
            self.assertEqual(sorted(p.name for p in Path(result['fileSet']['root']).iterdir()), ['a.bin', 'b.bin'])
            self.assertEqual(records[0]['policy']['scope'], 'pinned directory membership')
            for bad in ({**doc, 'source': directory['reference']},
                        {**selection, 'fileSet': {'root': file['reference']}}):
                with self.subTest(bad=bad), self.assertRaises(SchemaxisError):consume(bad, 'document')
            Path(resolved['source']).write_bytes(b'changed')
            with self.assertRaises(SchemaxisError) as caught:consume(doc, 'document')
            self.assertEqual(caught.exception.fault.code, 'RESOURCE_MISMATCH')
            self.assertIs(doc['source'], file['reference'])

    def test_authored_schema_admits_every_supported_position_and_no_other_controls(self):
        from jsonschema import Draft202012Validator
        reference = {'$resource': '/snapshots/input', 'digest': 'a' * 64, 'member': 'data.bin'}
        validator = Draft202012Validator(version_schema(VERSION, authored=True, artifact=True))
        for document in (
            {'version': VERSION, 'operation': 'compress', 'source': reference, 'dictionary': reference},
            {'version': VERSION, 'operation': 'encodeDelta', 'source': reference, 'reference': reference},
            {'version': VERSION, 'operation': 'concatenate', 'sources': [reference]},
            {'version': VERSION, 'operation': 'trainDictionary', 'samples': [reference] * 8},
            {'version': VERSION, 'operation': 'compressFiles', 'fileSet': {'root': {k:v for k,v in reference.items() if k != 'member'}}},
            {'version': VERSION, 'operation': 'restoreFiles', 'fileSet': {'files': [{'source': reference, 'name': 'a.zst'}]}}):
            with self.subTest(document=document):validator.validate(document)
        for document in (
            {'version': VERSION, 'operation': 'compress', 'source': reference, 'level': reference},
            {'version': VERSION, 'operation': 'restore', 'source': reference, 'samples': [reference] * 8},
            {'version': VERSION, 'operation': 'compareProfiles', 'source': reference, 'profiles': [{'id': reference}]},
            {'version': VERSION, 'operation': 'compressFiles', 'fileSet': {'files': [{'source': reference, 'name': reference}]}}):
            with self.subTest(document=document):self.assertFalse(validator.is_valid(document))
