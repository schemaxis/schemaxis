"""Design authoring schemas cover blank canvases and the exported starter."""
import copy
import json
from pathlib import Path
import unittest

from schemaxis.studio_schemas import design_schema
from schemaxis.workflow_design import create, VERSION, VERSION_2

try:
    from jsonschema import Draft202012Validator as Validator
except ImportError:
    Validator = None


@unittest.skipIf(Validator is None, 'optional jsonschema developer dependency unavailable')
class StudioSchemaTests(unittest.TestCase):
    def test_versions_are_standalone_and_accept_blank_designs(self):
        for version in (VERSION, VERSION_2):
            schema = design_schema(version)
            Validator.check_schema(schema)
            document = create()
            if version == VERSION:
                document = {key: document[key] for key in ('workflow', 'connections', 'controllers')}
                document['version'] = version
            Validator(schema).validate(document)

    def test_real_design_and_invalid_ports_and_viewports(self):
        root = Path(__file__).resolve().parents[2]
        document = json.loads((root / 'examples/studio/sequence-study/design.json').read_text())
        validator = Validator(design_schema(VERSION_2))
        validator.validate(document)
        broken = copy.deepcopy(document)
        broken['layout']['viewport'] = {'x': 0, 'y': 0, 'zoom': 0}
        self.assertFalse(validator.is_valid(broken))
        broken = copy.deepcopy(document)
        operation = next(iter(broken['ports']))
        broken['ports'][operation]['outputs']['invalid'] = {'artifact': 0, 'kind': 'value'}
        self.assertFalse(validator.is_valid(broken))
        broken = copy.deepcopy(document)
        broken['connections'][0]['from']['typo'] = 'operation'
        self.assertFalse(validator.is_valid(broken))
