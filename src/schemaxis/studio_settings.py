"""Studio settings with role-scoped ownership, stored beside the console session.

Roles are local interface modes, not a security boundary: the loopback server has
one owner. Scopes still record which role is expected to change each value, so a
later hosted deployment can enforce them on the server.
"""
import copy
import json
from pathlib import Path

from .errors import fail
from .storage import atomic, encoded

VERSION = 'schemaxis.studio-settings/1'
ROLES = ('admin', 'dev', 'user')

# Each setting: scope (lowest role allowed to write), type, default and bounds.
SPECIFICATION = {
    'role': {'scope': 'user', 'type': 'enum', 'values': list(ROLES), 'default': 'dev',
             'label': 'Interface role'},
    'theme': {'scope': 'user', 'type': 'enum', 'values': ['system', 'light', 'dark'], 'default': 'system',
              'label': 'Theme'},
    'editor.suggestions': {'scope': 'user', 'type': 'boolean', 'default': True,
                           'label': 'Suggest keys and values while typing'},
    'editor.hover': {'scope': 'user', 'type': 'boolean', 'default': True,
                     'label': 'Show schema documentation on hover'},
    'editor.tabSize': {'scope': 'user', 'type': 'integer', 'minimum': 2, 'maximum': 8, 'default': 2,
                       'label': 'Indentation width'},
    'output.indexWidth': {'scope': 'dev', 'type': 'integer', 'minimum': 1, 'maximum': 12, 'default': 6,
                          'label': 'Output index digits'},
    'output.namingPattern': {'scope': 'dev', 'type': 'string', 'maxLength': 256,
                             'default': '{index}-{operation}-{output}{ext}',
                             'label': 'Default output naming pattern'},
    'execution.workers': {'scope': 'admin', 'type': 'integer', 'minimum': 1, 'maximum': 64, 'default': 1,
                          'label': 'Default parallel workers'},
}
_RANK = {'user': 0, 'dev': 1, 'admin': 2}


def _check(key, value):
    spec = SPECIFICATION.get(key)
    if spec is None:
        fail('UNKNOWN_SETTING', 'choose a declared Studio setting', key, settings=sorted(SPECIFICATION))
    kind = spec['type']
    if kind == 'boolean' and type(value) is not bool:
        fail('INVALID_SETTING', 'expected true or false', key)
    if kind == 'integer':
        if type(value) is not int or not spec['minimum'] <= value <= spec['maximum']:
            fail('INVALID_SETTING', f"expected an integer from {spec['minimum']} to {spec['maximum']}", key)
    if kind == 'enum' and value not in spec['values']:
        fail('INVALID_SETTING', 'choose one of ' + ', '.join(spec['values']), key)
    if kind == 'string' and (not isinstance(value, str) or len(value) > spec['maxLength']):
        fail('INVALID_SETTING', f"expected text of at most {spec['maxLength']} characters", key)
    return value


class SettingsStore:
    def __init__(self, workspace):
        self.path = Path(workspace) / 'studio-settings.json'
        self.values = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
            except (OSError, ValueError):
                fail('INVALID_SETTING', 'studio-settings.json is not readable JSON; remove or repair it', str(self.path))
            if not isinstance(data, dict) or data.get('version') != VERSION or not isinstance(data.get('values'), dict):
                fail('INVALID_SETTING', 'studio-settings.json has an unsupported structure', str(self.path))
            for key, value in data['values'].items():
                self.values[key] = _check(key, value)

    def read(self):
        values = {key: copy.deepcopy(self.values.get(key, spec['default'])) for key, spec in SPECIFICATION.items()}
        return {'version': VERSION, 'values': values, 'specification': copy.deepcopy(SPECIFICATION),
                'roles': list(ROLES)}

    def write(self, values, role):
        if role not in ROLES:
            fail('INVALID_SETTING', 'choose admin, dev or user', 'role')
        if not isinstance(values, dict) or not values:
            fail('INVALID_SETTING', 'provide an object of setting values', 'values')
        updated = dict(self.values)
        for key, value in values.items():
            _check(key, value)
            if _RANK[role] < _RANK[SPECIFICATION[key]['scope']]:
                fail('SETTING_SCOPE', f"{SPECIFICATION[key]['label']} is managed by the "
                     f"{SPECIFICATION[key]['scope']} role", key)
            updated[key] = value
        atomic(self.path, encoded({'version': VERSION, 'values': updated}))
        self.values = updated
        return self.read()
