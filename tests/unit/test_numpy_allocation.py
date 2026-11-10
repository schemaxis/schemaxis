"""Keyless publication handoff: the key column a keyless run publishes can be consumed by NumPy."""
import copy
import unittest

from schemaxis.adaptors.numpy import adaptor as a, oracle as o
from tests.unit.test_numpy import SENSORS, baseline, code, publication


def keyless():
    doc = baseline()
    del doc['rowKey']
    return doc


def consumer(**changes):
    doc = copy.deepcopy(keyless())
    doc['rowKey'] = {'name': 'row', 'unit': 'count'}
    doc.update(changes)
    return doc


class KeylessHandoffTests(unittest.TestCase):
    def setUp(self):
        data = SENSORS.read_bytes().decode().splitlines()
        # A keyless source has no time column.
        self.data = ''.join(','.join(line.split(',')[1:]) + '\n' for line in data).encode()

    def test_keyless_reconstruction_header_is_row(self):
        _, _, tables = publication(keyless(), self.data)
        self.assertEqual(tables['reconstruction.csv'].decode().splitlines()[0], 'row,ch1,ch2,ch3,ch4')

    def test_keyless_reconstruction_is_consumable_with_row_key(self):
        _, _, tables = publication(keyless(), self.data)
        reconstruction = tables['reconstruction.csv']
        self.assertEqual(code(lambda: a.plan(consumer())), ('accepted', None))
        config = a.native_config(a.plan(consumer()))
        keys, rows = o.parse(reconstruction, config)
        self.assertEqual(keys[:3], [1.0, 2.0, 3.0])
        self.assertEqual(len(rows), len(keys))

    def test_reanalysis_of_a_keyless_reconstruction_is_verified_with_row_columns(self):
        _, _, first = publication(keyless(), self.data)
        doc = consumer(retention={'components': 2}, requirements={'minimumExplainedVariance': 0.999})
        config, summary, tables = publication(doc, first['reconstruction.csv'])
        self.assertEqual(config['header'][0], 'row')
        for name in ('scores.csv', 'reconstruction.csv'):
            self.assertEqual(tables[name].decode().splitlines()[0].split(',')[0], 'row')
        result = o.assess(config, first['reconstruction.csv'], summary, tables)
        self.assertEqual(result['outcome'], 'accepted')
        self.assertEqual(result['retained'], 2)

    def test_without_row_key_the_published_header_is_still_refused(self):
        _, _, tables = publication(keyless(), self.data)
        config = a.native_config(a.plan(keyless()))
        self.assertEqual(code(lambda: o.parse(tables['reconstruction.csv'], config))[0], 'PCA_HEADER_MISMATCH')

    def test_reserved_names_stay_reserved_except_row_key_row(self):
        for name in ('component', 'channelIndex', 'PC1', 'PC12'):
            self.assertEqual(code(lambda: a.plan(consumer(rowKey={'name': name, 'unit': 'count'}))),
                             ('PCA_INVALID_CONTRACT', '$.rowKey.name'), name)
        for name in ('row', 'component', 'channelIndex', 'PC1'):
            doc = baseline()
            doc['channels'][0]['name'] = name
            self.assertEqual(code(lambda: a.plan(doc)), ('PCA_INVALID_CONTRACT', '$.channels[0].name'), name)

    def test_row_key_row_cannot_collide_with_a_channel_or_repeat(self):
        doc = consumer()
        doc['channels'][1]['name'] = 'row'
        self.assertEqual(code(lambda: a.plan(doc)), ('PCA_INVALID_CONTRACT', '$.channels[1].name'))
        doc = consumer(rowKey={'name': 'ch1', 'unit': 'count'})
        self.assertEqual(code(lambda: a.plan(doc)), ('PCA_INVALID_CONTRACT', '$.channels[0].name'))


if __name__ == '__main__':
    unittest.main()
