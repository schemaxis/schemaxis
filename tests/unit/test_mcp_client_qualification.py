"""Client qualification must check the current protocol tool surface."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

from schemaxis.service_contracts import METHODS


class ClientQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[2]/'tools/qualify_mcp_clients.py'
        spec = importlib.util.spec_from_file_location('mcp_client_qualification', path)
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)

    def test_configured_input_tools_are_required_without_a_fixed_tool_count(self):
        names = ['methods', *(name.replace('.', '_') for name in METHODS)]
        self.assertTrue(self.helper.complete_tools(names))
        self.assertFalse(self.helper.complete_tools(names, isolated=True))
        names.extend(('inputs_list', 'input_from_resource'))
        self.assertTrue(self.helper.complete_tools(names, isolated=True))
        self.assertFalse(self.helper.complete_tools(names+['plan'], isolated=True))
        self.assertFalse(self.helper.complete_tools(names+['shell'], isolated=True))

    def test_native_client_launch_forwards_only_operator_isolation_configuration(self):
        args = SimpleNamespace(config=None, server_python='python3',
                               isolation_config=Path('/operator/isolation.json'))
        params = self.helper.parameters(args, Path('/owned/session'))
        self.assertEqual(params['args'][-2:], ['--isolation-config', '/operator/isolation.json'])
        self.assertEqual(set(params['env']), {'PYTHONPATH', 'OPENAI_AGENTS_DISABLE_TRACING'})


if __name__ == '__main__':
    unittest.main()
