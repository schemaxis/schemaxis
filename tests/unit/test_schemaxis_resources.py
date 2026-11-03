# Copyright (C) 2026 David L F Gaden
"""Native resources have typed graph dependencies and explicit publication limits."""
import copy
from pathlib import Path
import json
import unittest
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.paraview.job import plan

ROOT=Path(__file__).resolve().parents[2]


def document():
    return json.loads((ROOT/'examples/schemaxis/paraview-resources.json').read_text())


class ResourceTests(unittest.TestCase):
    def test_shared_resources_contribute_one_dependency_identity(self):
        master,scenes,_=plan(document())
        self.assertEqual(master.nodes['coloured']['dependencies'],['colours','wave'])
        self.assertEqual(master.nodes['colouredRgb']['dependencies'],['colours','wave'])
        self.assertEqual(master.nodes['colours']['dependencies'],['opacity','transfer2d'])
        self.assertEqual(scenes[0]['selection']['order'].count('colours'),1)
        self.assertEqual(scenes[0]['publications'],4)

    def test_resource_kind_must_match_the_port(self):
        value=document();value['nodes'][3]['inputs']['LookupTable']='opacity'
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'TYPE_MISMATCH')

    def test_resources_are_not_dataset_outputs(self):
        value=document();value['scenes'][0]['geometry']=['colours']
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'TYPE_MISMATCH')

    def test_resource_inputs_do_not_accept_numeric_output_ports(self):
        value=document();value['nodes'][3]['inputs']['LookupTable']={'node':'colours','port':0}
        with self.assertRaises(SchemaxisError) as caught:plan(value)
        self.assertEqual(caught.exception.fault.code,'INVALID_OUTPUT_PORT')
