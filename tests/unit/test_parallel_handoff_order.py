"""Object member order must not change multi-source provenance or its integrity checks."""
import copy
import json
import unittest
from unittest.mock import patch

from schemaxis import parallel


class HandoffOrderTests(unittest.TestCase):
    def test_multiple_artifact_roles_survive_json_object_reordering(self):
        document = {'version': 'schemaxis.ffmpeg/1', 'nodes': [{'id': 'review', 'filter': 'muxReview',
            'options': {role: {'$artifact': role, 'index': 0} for role in ('video', 'audio', 'captions')}}]}
        completed = {role: [{'directory': '/verified/' + role, 'effective': {}}]
                     for role in ('video', 'audio', 'captions')}
        def receipt(directory, _document):
            return {'artifacts': [{'file': str(directory) + '/asset', 'kind': 'file', 'sha256': 'a' * 64}]}
        with patch('schemaxis.parallel.verify_native', side_effect=receipt):
            original, before = parallel.resolve(document, completed)
            reordered, after = parallel.resolve(json.loads(json.dumps(document, sort_keys=True)), completed)
        self.assertEqual(original, reordered)
        self.assertNotEqual(before, after, 'the regression must exercise a different traversal order')
        self.assertTrue(parallel.same_handoffs(before, after))
        changed = copy.deepcopy(after)
        changed[0]['sha256'] = 'b' * 64
        self.assertFalse(parallel.same_handoffs(before, changed))
        self.assertFalse(parallel.same_handoffs(before, after[:-1]))
        self.assertFalse(parallel.same_handoffs(before, after + after[:1]))

    def test_duplicate_counts_and_typed_values_are_preserved(self):
        one = {'from': 'source', 'index': 1, 'file': '/verified/asset', 'sha256': 'a' * 64}
        self.assertTrue(parallel.same_handoffs([one, one], [copy.deepcopy(one), copy.deepcopy(one)]))
        self.assertFalse(parallel.same_handoffs([one, one], [one]))
        for value in (True, 1.0):
            changed = {**one, 'index': value}
            self.assertFalse(parallel.same_handoffs([one], [changed]))
        for invalid in (None, {}, ['not a record'], [{'value': float('nan')}]):
            self.assertFalse(parallel.same_handoffs([one], invalid))

    def test_ordered_consumer_arrays_still_differ(self):
        # Provenance is unordered, but the condition in verify also compares the effective document.
        left = {'files': ['/verified/a', '/verified/b']}
        right = {'files': ['/verified/b', '/verified/a']}
        records = [{'from': 'a'}, {'from': 'b'}]
        self.assertTrue(parallel.same_handoffs(records, list(reversed(records))))
        self.assertNotEqual(left, right)
