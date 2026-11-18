#!/usr/bin/env python3
# Copyright (C) 2026 David L. F. Gaden.
"""Generate or check the reproducible adaptor authoring coverage inventory.

Discovery is host-only. It reads registered manifests, declarations, route
schemas, the projected Studio Add catalogue, adaptor guidance and the source of
framework contracts that have no literal schema; it never imports a native
application. Every schema field address is accounted to one inventory item,
with a fingerprint of its own validation keywords. Nested collection members,
map entries, discriminated variants, declared native commands and framework
contract units are rows of their own, each with four independent dimensions.
Derived statuses record declaration or structural facts with their basis;
judgements, reviews and native qualifications come only from the
hand-maintained ledger. Anything else remains unassessed, unknown, not reviewed
and not qualified.

The tracked inventory covers built-in adaptors with plugins disabled, so it is
identical on every checkout. ``--external PATH`` inventories installed external
plugins separately as owner handoffs. ``--check`` regenerates in memory and
fails when the tracked inventory or summary is stale. When run as a script, a
native-import blocker is installed and the command line is parsed once, before
any framework module is imported. The builtin modes disable plugins for this
process only; ``--external`` requires plugins and refuses if the operator's
``SCHEMAXIS_ADAPTOR_PLUGINS`` setting disables them.
"""
import argparse
import importlib.abc
import os
import sys

NATIVE_ROOTS = frozenset({'bpy', 'paraview', 'vtk', 'vtkmodules', 'FreeCAD', 'FreeCADGui', 'Part', 'gmsh',
                          'cantera', 'qgis', 'PySide', 'PySide2', 'PySide6', 'PyQt5', 'PyQt6', 'tkinter',
                          'matplotlib', 'numpy', 'pyarrow', 'pandas', 'scipy', 'ifcopenshell', 'pyproj',
                          'xarray', 'sympy', 'meshio', 'h5py', 'netCDF4', 'osgeo', 'openseespy', 'oracledb',
                          'zstandard', 'fitz', 'pymupdf'})


class NativeImportBlocker(importlib.abc.MetaPathFinder):
    """Refuse native application imports during discovery and record every attempt."""

    def __init__(self):
        self.attempts = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in NATIVE_ROOTS:
            self.attempts.append(fullname)
            raise ModuleNotFoundError('native import refused during inventory discovery: ' + fullname, name=fullname)
        return None


def arguments(argv):
    """The single authoritative command-line parse; abbreviations are refused."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='fail if the tracked inventory or summary is stale')
    mode.add_argument('--external', metavar='PATH', help='inventory installed external plugins into PATH')
    return parser.parse_args(argv)


BLOCKER = NativeImportBlocker()
PRESENT = sorted(name for name in sys.modules if name.split('.')[0] in NATIVE_ROOTS)
ARGS = None
PLUGIN_SETTING = os.environ.get('SCHEMAXIS_ADAPTOR_PLUGINS')
if __name__ == '__main__':
    sys.meta_path.insert(0, BLOCKER)
    ARGS = arguments(sys.argv[1:])
    if ARGS.external is None:
        os.environ['SCHEMAXIS_ADAPTOR_PLUGINS'] = 'off'

import ast  # noqa: E402
import hashlib  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from collections import Counter  # noqa: E402
from operator import itemgetter  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))

from schemaxis import workflow_templates  # noqa: E402
from schemaxis.adaptors import registry  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from schemaxis.expressions import SECTIONS  # noqa: E402
from schemaxis.studio_guidance import SHARED, enumerated_subset, escape, fields, load, shared_fields, shared_schema  # noqa: E402

VERSION = 'schemaxis.adaptor-authoring-inventory/2'
LEDGER_VERSION = 'schemaxis.adaptor-authoring-ledger/1'
TOOL = 'tools/inventory_adaptor_authoring.py'
COMMAND = 'PYTHONPATH=src python3 ' + TOOL
LEDGER = 'verification/adaptor-authoring/ledger.json'
OUTPUT = 'verification/adaptor-authoring/inventory.json'
SUMMARY = 'verification/adaptor-authoring/summary.md'
DIMENSIONS = ('naming', 'renaming', 'multiMode', 'subset')
STATUSES = {
    'assessment': ('unassessed', 'derived', 'assessed', 'insufficient-evidence', 'blocked'),
    'implementation': ('unknown', 'not-implemented', 'generic-fallback', 'generic-rule', 'partial',
                       'implemented', 'defect', 'not-applicable'),
    'review': ('not-reviewed', 'challenged', 'accepted', 'rejected'),
    'qualification': ('not-qualified', 'recorded-prior', 'qualified', 'unavailable', 'not-required'),
}
CREDIT = ('generic-fallback', 'generic-rule', 'partial', 'implemented', 'defect')
QUALIFIED = ('recorded-prior', 'qualified')
CLASSIFICATIONS = ('unclassified', 'independent-siblings', 'conditional', 'collection', 'sequential',
                   'singleton', 'side-effect', 'insufficient-evidence', 'not-an-element')
RECORD_KEYS = {'assessment', 'implementation', 'review', 'qualification', 'basis', 'rationale', 'current',
               'classification', 'candidates', 'referenceScope', 'tests', 'evidence', 'findings',
               'disposition', 'gates', 'varying', 'shared', 'outputs', 'choices', 'routes', 'entryPoint'}
LIST_KEYS = ('candidates', 'tests', 'evidence', 'findings', 'gates', 'varying', 'shared', 'outputs', 'routes')
FIELD_KINDS = ('identity', 'name-candidate', 'reference', 'subset-candidate', 'path', 'map', 'choice',
               'constant', 'ref', 'structure', 'alternatives', 'array', 'scalar', 'contract-key', 'other')
SURFACE_KINDS = ('identity', 'name-candidate', 'reference', 'subset-candidate', 'path', 'map')
SURFACE_DIMENSION = {'identity': 'renaming', 'name-candidate': 'renaming', 'reference': 'renaming',
                     'map': 'renaming', 'subset-candidate': 'subset', 'path': 'multiMode'}
NOT_ELEMENTS = ('definition', 'discriminator', 'graph-container', 'route-root')
NESTED = ('nested-member', 'nested-entry', 'nested-variant')
UNASSESSED_KINDS = NESTED + ('native-command', 'framework-entity', 'contract-unit')
SINGLE_VALUED = ('document-singleton', 'operation-selector')
SUBSET_CONTROLS = ('blocks', 'reader-selection', 'dataset-arrays', 'document-nodes', 'assembly-paths', 'reader-array-domain', 'file-subset', 'document-entries', 'inspected-entries')
PATH_WORDS = ('file', 'path', 'directory', 'folder', 'destination', 'output', 'filename')
SHARED_PROVIDERS = tuple(sorted(set(SHARED.values())))
STUDIO = 'src/schemaxis/studio_ui/windows/workbench/'
AUTHORING_SURFACES = ('studioAdd', 'studioEdit', 'studioProperties', 'quickRows', 'batch',
                      'core', 'cli', 'console', 'ai')
SURFACE_STATES = ('projected', 'not-projected', 'missing', 'unassessed')
SCHEMA_PROSE = frozenset({'description', 'title', '$comment', 'x-studio-guide', 'x-studio-technical'})
SCHEMA_MAPS = frozenset({'properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'})
SCHEMA_SINGLES = frozenset({'items', 'additionalProperties', 'not', 'if', 'then', 'else', 'contains',
                            'propertyNames', 'unevaluatedProperties', 'unevaluatedItems', 'additionalItems'})
SCHEMA_LISTS = frozenset({'anyOf', 'oneOf', 'allOf', 'prefixItems'})
ENTRY_PROSE = frozenset({'title', 'description', 'nativeDescription', 'guidance', 'searchText'})
GUIDE_SEMANTICS = ('control', 'authoring', 'fileExtensions')
CHILDREN = frozenset({'properties', '$defs', 'definitions', 'patternProperties', 'not', 'if', 'then', 'else',
                      'oneOf', 'anyOf', 'allOf', 'prefixItems', 'dependentSchemas', 'contains'})
CONSTRAINTS = ('type', 'pattern', 'minLength', 'maxLength', 'format', 'const', 'enum', '$ref')
PORT_KEYS = ('kind', 'kinds', 'required', 'multiple', 'native')
DESIGN_ENTITY = 'entity:workflow-operations'
TEMPLATE_PROVIDER = 'workflow-template'
TEMPLATE_SOURCE = 'src/schemaxis/workflow_templates.py'
TEMPLATE_FUNCTIONS = ('_validate', '_constraints', '_run_options', 'bind_values', 'load_template')
# Validator call sites (function, validated subject) -> route, unit, address and,
# for keys that are user-chosen names, the placeholder and its field kind.
CONTRACT_SITES = {
    ('_validate', 'manifest'): (workflow_templates.TEMPLATE_VERSION, 'document:template', '', None),
    ('load_template', 'manifest'): (workflow_templates.TEMPLATE_VERSION, 'document:template', '', None),
    ('_validate', 'parameters'): (workflow_templates.TEMPLATE_VERSION, 'entity:parameters', '/parameters',
                                  ('{parameter}', 'identity')),
    ('_validate', 'spec'): (workflow_templates.TEMPLATE_VERSION, 'entity:parameters', '/parameters/{parameter}', None),
    ('_validate', 'target'): (workflow_templates.TEMPLATE_VERSION, 'entity:parameters',
                              '/parameters/{parameter}/target', None),
    ('_constraints', 'constraints'): (workflow_templates.TEMPLATE_VERSION, 'entity:parameters',
                                      '/parameters/{parameter}/constraints', None),
    ('_validate', 'outputs'): (workflow_templates.TEMPLATE_VERSION, 'entity:outputs', '/outputs',
                               ('{output}', 'identity')),
    ('_validate', 'output'): (workflow_templates.TEMPLATE_VERSION, 'entity:outputs', '/outputs/{output}', None),
    ('_validate', 'requirements'): (workflow_templates.TEMPLATE_VERSION, 'document:requirements',
                                    '/requirements', None),
    ('bind_values', 'bundle'): (workflow_templates.VALUES_VERSION, 'capture:bundle', '/@bundle', None),
    ('bind_values', 'values'): (workflow_templates.VALUES_VERSION, 'document:case', '', None),
    ('bind_values', 'supplied_identity'): (workflow_templates.VALUES_VERSION, 'entity:template-identity',
                                           '/template', None),
    ('bind_values', 'supplied'): (workflow_templates.VALUES_VERSION, 'entity:values', '/values',
                                  ('{parameter}', 'reference')),
    ('_run_options', 'run'): (workflow_templates.VALUES_VERSION, 'document:run', '/run', None),
    ('_run_options', 'naming'): (workflow_templates.VALUES_VERSION, 'document:run', '/run/naming', None),
}
CONTRACT_KINDS = {'id': 'identity', 'title': 'name-candidate', 'label': 'name-candidate', 'operation': 'reference',
                  'pointer': 'reference', 'outputDirectory': 'path', ('document:template', 'workflow'): 'path'}
TEMPLATE_ROUTES = {'cli': 'schemaxis.__main__:prepare_template', 'ai': 'schemaxis.service_contracts:prepare_template',
                   'core': 'schemaxis.execution_service:prepare_template',
                   'studioRunner': 'schemaxis.studio_cases:prepare_template',
                   'designExport': 'schemaxis.workflow_design:export_template',
                   'toolPackages': 'schemaxis.tool_packages:bind_values'}


def item_key(adaptor, route, item):
    """Stable item key: escaped adaptor, route and item joined by slashes."""
    return '/'.join(escape(part) for part in (adaptor, route, item))


def surface_key(adaptor, route, item, address):
    """Item key followed by the RFC 6901 address of the field."""
    return item_key(adaptor, route, item) + address


def split_key(key):
    """Return (adaptor, route, item, address) for an item or surface key."""
    parts = key.split('/', 3)
    if len(parts) < 3:
        raise ValueError('inventory key requires adaptor, route and item: ' + key)
    unescaped = [part.replace('~1', '/').replace('~0', '~') for part in parts[:3]]
    return (*unescaped, '/' + parts[3] if len(parts) == 4 else '')


def dimension(assessment='unassessed', implementation='unknown', basis='none', **extra):
    """A dimension record; review and native qualification default to absent."""
    record = {'assessment': assessment, 'implementation': implementation, 'review': 'not-reviewed',
              'qualification': 'not-required' if implementation == 'not-applicable' else 'not-qualified',
              'basis': basis}
    record.update({key: value for key, value in extra.items() if value not in (None, [], '')})
    return record


def schema_semantic(node):
    """A schema without explanatory annotations; literal values and property names stay verbatim.

    Annotations are removed only where a schema keyword can appear. ``default``,
    ``const``, ``enum`` and any other non-schema keyword keep their full value,
    whatever member names it contains.
    """
    if isinstance(node, list):
        return [schema_semantic(item) for item in node]
    if not isinstance(node, dict):
        return node
    result = {}
    for key, value in node.items():
        if key in SCHEMA_PROSE:
            continue
        if key in SCHEMA_MAPS and isinstance(value, dict):
            result[key] = {name: schema_semantic(child) for name, child in value.items()}
        elif key in SCHEMA_SINGLES and isinstance(value, (dict, list)):
            result[key] = schema_semantic(value)
        elif key in SCHEMA_LISTS and isinstance(value, list):
            result[key] = [schema_semantic(child) for child in value]
        else:
            result[key] = value
    return result


def entry_semantic(entry):
    """An Add catalogue entry without its display prose; its schema keeps literal values."""
    return {key: schema_semantic(value) if key == 'schema' else value
            for key, value in entry.items() if key not in ENTRY_PROSE}


def guide_semantics(record):
    """The behaviour-bearing part of a field guidance record, kept verbatim."""
    return {key: record[key] for key in GUIDE_SEMANTICS if key in (record or {})}


def field_contract(node, guide):
    """A field's own schema keywords plus its guidance control, authoring and file records."""
    return fingerprint({'schema': own(node), 'guide': guide}) if guide else fingerprint(own(node))


def fingerprint(value):
    """Short canonical digest of the exact value given; callers decide what is prose."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=repr)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def own(node):
    """A schema node's own keywords; child schemas are fingerprinted at their own address."""
    if not isinstance(node, dict):
        return node
    result = {key: value for key, value in node.items() if key not in CHILDREN and key not in SCHEMA_PROSE}
    for key in ('items', 'additionalProperties'):
        if isinstance(result.get(key), dict):
            result.pop(key)
    return result


def _resolve(schema, node):
    target = node.get('$ref') if isinstance(node, dict) else None
    if isinstance(target, str) and target.startswith('#/$defs/'):
        return schema.get('$defs', {}).get(target[len('#/$defs/'):], {})
    return node if isinstance(node, dict) else {}


def _strings(schema, node, depth=0):
    node = _resolve(schema, node)
    if depth > 4 or not node:
        return False
    if node.get('type') == 'string' or (node.get('enum') and all(isinstance(v, str) for v in node['enum'])):
        return True
    branches = node.get('anyOf', []) + node.get('oneOf', [])
    return bool(branches) and all(_strings(schema, branch, depth + 1) for branch in branches)


def classify(schema, address, node, control=None):
    """Structural field class; a candidate surface, never an assessment."""
    if control in SUBSET_CONTROLS:
        return 'subset-candidate'
    parts = address.split('/')
    name = parts[-1] if len(parts) > 2 and parts[-2] == 'properties' else None
    if name == 'id' and parts[-3:-2] != ['inputs']:
        return 'identity'
    if len(parts) > 3 and parts[-2] == 'properties' and parts[-3] == 'inputs':
        return 'reference'
    if name == 'node' and _strings(schema, node):
        return 'reference'
    if name == 'name' and _strings(schema, node):
        return 'name-candidate'
    if set(node) == {'$ref'}:
        return 'ref'
    if node.get('type') == 'array' or 'items' in node:
        items = node.get('items')
        return 'subset-candidate' if isinstance(items, dict) and _strings(schema, items) else 'array'
    if isinstance(node.get('additionalProperties'), dict) or node.get('patternProperties'):
        return 'map'
    if 'const' in node:
        return 'constant'
    if isinstance(node.get('enum'), list):
        return 'choice' if len(node['enum']) > 1 else 'constant'
    if name and node.get('type') == 'string' and any(word in name.lower() for word in PATH_WORDS):
        return 'path'
    if node.get('type') == 'object' or 'properties' in node:
        return 'structure'
    if any(key in node for key in ('anyOf', 'oneOf', 'allOf')):
        return 'alternatives'
    if node.get('type') in ('string', 'number', 'integer', 'boolean', 'null'):
        return 'scalar'
    return 'other'


def schema_address(schema, at):
    """Map a catalogue insertion pointer to the literal schema address it inserts."""
    node, address = schema, ''
    for segment in at.split('/')[1:]:
        node, address = _descend(schema, node, address, segment)
        if node is None:
            return None
    return address


def _descend(schema, node, address, segment):
    target = node.get('$ref') if isinstance(node, dict) else None
    if isinstance(target, str) and target.startswith('#/$defs/'):
        address = '/$defs/' + escape(target[len('#/$defs/'):])
        node = _resolve(schema, node)
    placeholder = segment == '-' or (segment.startswith('{') and segment.endswith('}'))
    name = segment.replace('~1', '/').replace('~0', '~')
    if not placeholder and name in node.get('properties', {}):
        return node['properties'][name], address + '/properties/' + escape(name)
    if placeholder and isinstance(node.get('items'), dict):
        return node['items'], address + '/items'
    if placeholder and isinstance(node.get('additionalProperties'), dict):
        return node['additionalProperties'], address + '/additionalProperties'
    for keyword in ('anyOf', 'oneOf'):
        for index, branch in enumerate(node.get(keyword, [])):
            found, where = _descend(schema, branch, address + '/' + keyword + '/' + str(index), segment)
            if found is not None:
                return found, where
    return None, None


def _anchors(schema, addresses, declarations):
    """Schema address prefixes that start each top-level item's owned subtree."""
    anchors = {'': 'route-root'}
    for address, node in addresses:
        parts = address.split('/')
        if len(parts) == 3 and parts[1] == '$defs':
            name = parts[2].replace('~1', '/').replace('~0', '~')
            operation = name[len('options-'):] if name.startswith('options-') else None
            anchors[address] = 'operation:' + operation if operation in declarations else 'definition:' + name
        elif len(parts) == 3 and parts[1] == 'properties':
            anchors[address] = 'document:' + parts[2].replace('~1', '/').replace('~0', '~')
        elif address:
            for discriminator in ('filter', 'writer', 'operation'):
                value = node.get('properties', {}).get(discriminator, {})
                if isinstance(value, dict) and value.get('const') in declarations:
                    anchors[address] = 'operation:' + value['const']
                    break
    return anchors


def _discriminators(node):
    found = {}
    for name, value in node.get('properties', {}).items():
        if isinstance(value, dict) and 'const' in value:
            found[name] = value['const']
        elif isinstance(value, dict) and isinstance(value.get('enum'), list) and len(value['enum']) == 1:
            found[name] = value['enum'][0]
    return found


def _object_like(schema, node, depth=0):
    node = _resolve(schema, node)
    if depth > 4 or not node:
        return False
    if node.get('properties') or node.get('type') == 'object':
        return True
    return any(_object_like(schema, branch, depth + 1) for branch in node.get('anyOf', []) + node.get('oneOf', []))


def scalar_collection_member(schema, member):
    from schemaxis.studio_catalogue import literal_schema
    literal = literal_schema(_resolve(schema, member))
    return literal.get('type') in ('string', 'number', 'integer', 'boolean', 'null')


def _ordered_blender_unit(anchor):
    steps = r'/properties/meshEdits/items/properties/steps/items'
    if re.search(steps + r'(?:/oneOf/[0-9]+)?$', anchor):
        return dimension('derived', 'not-applicable', 'ordered Blender mesh edit stages',
                         classification='sequential', qualification='not-required',
                         rationale='Each stage consumes the mesh produced by the previous stage.',
                         evidence=['src/schemaxis/adaptors/blender/mesh_edits.py'])
    if re.search(r'/properties/tracks/items/oneOf/[0-9]+/properties/keys/items$', anchor):
        motion = 'production_motion.py' if '/properties/clips/items' in anchor else 'production.py'
        return dimension('derived', 'not-applicable', 'ordered Blender channel keyframes',
                         classification='collection', qualification='not-required',
                         rationale='Unique, increasing frame values form the single declared channel track.',
                         evidence=['src/schemaxis/adaptors/blender/' + motion])
    if re.search(r'/properties/(?:tracks|constraints)/items/oneOf/\d+$', anchor):
        return dimension('derived', 'not-implemented', 'Blender animation or constraint ownership',
                         classification='conditional',
                         rationale='Tracks have exclusive target and channel bindings. Constraints participate in the owner’s ordered stack.',
                         evidence=['src/schemaxis/adaptors/blender/production.py',
                                   'src/schemaxis/adaptors/blender/production_motion.py',
                                   'src/schemaxis/adaptors/blender/production_native.py'])
    patterns = (
        (r'/properties/attributes/items/oneOf/\d+/properties/entries/items$', 'Sparse indices and values populate one named attribute.', 'mesh_data.py'),
        (r'/properties/splines/items(?:/oneOf/\d+)?(?:/properties/points/items)?$', 'Ordered points define segments of one owned curve.', 'spline.py'),
        (r'/properties/(?:geometryGraphs/items|materialGraphs/items|compositor|nodeGroups/items)/properties/links/items$',
         'A link connects two existing sockets inside the same graph.', 'node_catalogue.py'),
    )
    for pattern, rationale, filename in patterns:
        if re.search(pattern, anchor):
            return dimension('derived', 'not-applicable', 'Blender member of a compound value',
                             classification='collection', qualification='not-required', rationale=rationale,
                             evidence=['src/schemaxis/adaptors/blender/' + filename])
    return None


_ADAPTOR_NESTED_RULES = {
    'apachearrow': (
        (r'/properties/where/items$', 'collection', 'The predicates filter one input table together.'),
        (r'/properties/columns/items$', 'conditional', 'The column declarations must match the captured input table header.'),
    ),
    'blender': (
        (r'/properties/(?:hierarchy|collections|regions|slots)/items$', 'collection',
         'These entries express the association or ordering inside an existing owner.'),
        (r'/properties/values/additionalProperties$', 'collection', 'The key identifies a socket of the existing group node.'),
        (r'/properties/(?:meshEdits|intents)/items$', 'conditional',
         'Each intent requires a distinct or compatible target and ordered geometry or motion edits.'),
        (r'/\$defs/options-(?:lathe|polylineTube)/properties/(?:points|profile)/anyOf/0/items$', 'collection',
         'The entries are coordinates of one ordered profile.'),
        (r'/properties/(?:geometryBindings|materialBindings|meshData|shapeKeys|cloth|skin|rigidBodies)/items$', 'conditional',
         'An instance must select a separate compatible owner. The existing association is used for that owner.'),
        (r'/properties/(?:layers|clips)/items(?:/properties/bindings/items)?$', 'conditional',
         'These items describe an animation stack or its target bindings; layer order and overlap must be checked.'),
        (r'/properties/(?:materialGraphs|geometryGraphs|nodeGroups|rigs)/items$', 'collection',
         'The member owns a complete graph or hierarchy. Its separately authorable children carry their own policies.'),
        (r'/properties/nodeGroups/items/properties/(?:inputs|outputs|nodes)/items$', 'conditional',
         'New entries need typed socket identifiers and compatible graph links within the group.'),
        (r'/properties/(?:renderBundles|simulationCaches)/items(?:/properties/outputs/items(?:/anyOf/\d+)?(?:/properties/layers/items)?)?$',
         'conditional', 'Publishing another member requires a compatible frame range, target and independent output ownership.'),
        (r'/properties/(?:materialAovs|renderLightgroups|materialAssignments)/items(?:/oneOf/\d+)?$', 'conditional',
         'The selected assignment targets a named owner with a checked binding namespace.'),
        (r'/properties/(?:offsets|weights|mask)/items$', 'collection',
         'These entries contribute to the same mesh deformation or skin binding.'),
    ),
    'calc': (
        (r'/properties/terms/items$', 'collection', 'Terms form one linear requirement.'),
        (r'/properties/columns/items$', 'conditional', 'Adding a column requires matching values in the captured table rows.'),
    ),
    'cantera': (
        (r'/properties/composition/items$', 'collection', 'The entries make up one normalized mixture.'),
    ),
    'elmer': (
        (r'/properties/layers/items$', 'sequential', 'Layer order defines the assembled material stack.'),
    ),
    'exiftool': (
        (r'/properties/(?:assumedOffsets|references|simultaneous|shifts|positions|corrections|itemOverrides)/items$', 'collection',
         'These values supply the observations, assignments or corrections for one metadata operation.'),
        (r'/properties/set/properties/languages/items$', 'collection',
         'The localized strings are members of one authored field value.'),
        (r'/properties/(?:groups/properties/members|itemEdits)/items$', 'conditional',
         'Each entry must bind to an existing media ID or declared clock group without competing assignments.'),
    ),
    'freecad': (
        (r'^/properties/(?:supports|loads)/items(?:/anyOf/\d+)?$', 'conditional',
         'The named analysis record must resolve to an admissible face or load target without incompatible constraints.'),
        (r'/properties/(?:mounts|parameters|formulas|inputs)/additionalProperties(?:/properties/position/items)?$',
         'conditional', 'The map key owns an attachment or binding referenced by other document fields.'),
        (r'/properties/faces/items/anyOf/\d+$', 'collection', 'The selector contributes one face of the owning operation.'),
        (r'^/properties/(?:parts|components|joints)/items(?:/oneOf/\d+)?$', 'conditional',
         'Added parts must be used and each component must join the one connected assembly.'),
        (r'^/properties/operations/items(?:/oneOf/\d+)?$', 'sequential',
         'The machining sequence consumes the stock state produced by previous operations.'),
        (r'/properties/(?:spreadsheet|mounts)/.+/properties/terms/additionalProperties$', 'collection',
         'Each term contributes to one compiled affine value.'),
    ),
    'getdp': (
        (r'/properties/layers/items$', 'sequential', 'Layer order defines the assembled material stack.'),
    ),
    'gmsh': (
        (r'/properties/(?:faceGroups|cylinderGroups)/items$', 'conditional',
         'A new physical group must select its own admissible geometric entities and label.'),
    ),
    'gnuplot': (
        (r'/properties/columns/items$', 'conditional', 'The declarations must match columns in the captured CSV header.'),
    ),
    'graphviz': (
        (r'/properties/edges/items$', 'collection', 'An edge binds two existing nodes in the same graph.'),
    ),
    'hdf5': (
        (r'/properties/(?:steps|fields|inputs|batches|dependencies|objects|links|edits|expectations|extracts)(?:/anyOf/\d+)?/items$',
         'conditional', 'An instance requires distinct paths or bindings in the HDF5 file or source namespace.'),
        (r'/properties/(?:dimensions|slices|where|targets)/items$', 'collection',
         'Entries describe the axes, source selection or slice of one dataset operation.'),
        (r'/properties/(?:external|sources|members|cells)/items$', 'collection',
         'Entries together describe the storage, values or connectivity of one typed array.'),
    ),
    'imagej': (
        (r'/properties/frames/items$', 'sequential', 'Frame order and sample times define one image series.'),
    ),
    'ngspice': (
        (r'^/oneOf/[01]/properties/circuit/properties/(?:capacitors|resistors)/items$', 'collection',
         'This operation alternative uses the shared circuit collection for authoring.'),
        (r'^/oneOf/2/properties/circuit/properties/(?:capacitors|resistors)/items$', 'singleton',
         'The RC step requires exactly one resistor and one capacitor.'),
        (r'^/oneOf/[012]/properties/requirements/items$', 'collection',
         'This operation alternative uses the shared requirements property for authoring.'),
        (r'/properties/inductors/items$', 'conditional', 'Additional inductors must not form ideal loops or shorts.'),
    ),
    'numpy': (
        (r'/properties/channels/items$', 'conditional', 'Channel declarations must match the captured signal dimensions.'),
        (r'/properties/reconstructionRMS/items$', 'collection', 'The entries bound reconstructions of declared channels.'),
    ),
    'opensees': (
        (r'/properties/loads/items$', 'collection', 'The entries assign forces to nodes of the same structural analysis.'),
    ),
    'oracle': (
        (r'/properties/(?:terms|conditions|checks|on|groupBy|orderBy|values|arguments)/items$', 'collection',
         'The entries make up one expression, condition, grouping or ordering contract.'),
        (r'/properties/(?:foreignKeys|unique|joins|steps|set|computed)/items$', 'conditional',
         'The entries must preserve existing key, target, expression and transaction dependencies.'),
    ),
    'paraview': (
        (r'/\$defs/options-.+/properties/(?:selectors|cellArrays|regions|Functions)(?:/anyOf/\d+)+/items$', 'collection',
         'The value is one entry in an existing selection, not a pipeline node.'),
        (r'/properties/(?:QueryString|any|all)(?:/anyOf/\d+)*/items$', 'collection',
         'Terms belong to one query expression.'),
        (r'/properties/(?:appearances|measurements)/items(?:/additionalProperties)?$', 'collection',
         'These entries configure appearance or measurement selections within the scene.'),
    ),
    'premiere': (
        (r'/properties/clips/items$', 'conditional', 'An edited clip must preserve the source and timeline ranges.'),
        (r'/properties/tracks/items$', 'conditional', 'The named track owns ordered clips and may be referenced by editorial checks.'),
    ),
    'qgis': (
        (r'^/properties/(?:definitions|settings|dimensions)/', 'collection',
         'These keys or members are shared configuration and expression values.'),
        (r'/properties/aggregates/items$', 'collection', 'The aggregate selects one result column of its summary operation.'),
    ),
    'qpdf': (
        (r'/properties/pages/items$', 'sequential', 'The entries are ordered pages of one document publication.'),
    ),
    'r': (
        (r'/properties/predictors/items$', 'conditional', 'Predictor declarations must match columns of the captured data.'),
        (r'/properties/requirements/items$', 'collection', 'Each fixed requirement form has its own authoring policy.'),
    ),
    'shotcut': (
        (r'/properties/options/properties/assets/items$', 'conditional',
         'The asset identity lives in the existing timeline and is referenced by clips.'),
    ),
    'sqlite': (
        (r'/properties/foreignKeys/items$', 'conditional', 'A foreign key needs an earlier table and a matching primary key.'),
    ),
    'sox': (
        (r'/properties/clips/items$', 'sequential', 'The clips are assembled in order into one audio output.'),
    ),
    'whispercpp': (
        (r'/properties/(?:timings|corrections)/items$', 'collection',
         'Time ranges and corrections apply to the same retained transcript.'),
    ),
    'workflow-design': (
        (r'^/properties/(?:layout/properties/nodes/additionalProperties|connections/items)', 'collection',
         'These entries describe layout or edges between already declared workflow operations.'),
        (r'^/properties/(?:controllers|ports|parameters|outputs)/', 'conditional',
         'The workflow designer must preserve all bindings, port contracts and controller dependencies.'),
    ),
}


def _nested_adaptor_semantics(adaptor, anchor):
    """Classify list members with an explicit adaptor-owned composition contract."""
    for pattern, classification, rationale in _ADAPTOR_NESTED_RULES.get(adaptor, ()):
        if re.search(pattern, anchor):
            conditional = classification == 'conditional'
            evidence = ('src/schemaxis/workflow_design.py' if adaptor == 'workflow-design'
                        else registry.adaptor_source(adaptor, 'guidance.json'))
            return dimension('derived', 'not-implemented' if conditional else 'not-applicable',
                             'adaptor collection semantics', classification=classification,
                             qualification='not-qualified' if conditional else 'not-required',
                             rationale=rationale, evidence=[evidence])
    return None


def _blender_graph_variant(anchor, specification):
    graph = r'/properties/(?:materialGraphs/items|geometryGraphs/items|compositor)/properties/nodes/items/oneOf/\d+$'
    if not re.search(graph, anchor):
        return None
    props = specification.get('properties', {})
    if props.get('kind', {}).get('const') == 'output':
        return _singleton_multi_mode('Blender graph requires exactly one output')
    if (set(props) <= {'id', 'kind', 'values', 'properties'}
            and all(props.get(name, {}).get('properties') == {} for name in ('values', 'properties'))):
        return dimension('derived', 'not-applicable', 'Blender graph node has no configurable settings',
                         classification='independent-siblings', qualification='not-required',
                         rationale='Name and edits to graph links distinguish these nodes.',
                         evidence=['src/schemaxis/adaptors/blender/node_catalogue.py'])
    return None


def _closed_anonymous_member(schema, node):
    spec = _resolve(schema, node)
    props = spec.get('properties', {})
    identity_or_target = {'id', 'name', 'label', 'alias', 'title', 'path', 'key', 'tag', 'identity', 'object',
                          'item', 'node', 'source', 'target', 'slot', 'channel', 'index', 'header', 'frame',
                          'table', 'parameter', 'column', 'address', 'mount', 'port', 'axis', 'selector'}
    return (spec.get('type') == 'object' and spec.get('additionalProperties') is False
            and bool(props) and not (identity_or_target & {key.casefold() for key in props})
            and not any(key.lower().endswith(('id', 'name', 'path')) for key in props))


def nested_units(schema, addresses, anchors, records):
    """Nested collection members, map entries and discriminated variants not already anchored."""
    units = {}
    for address, node in addresses:
        if not isinstance(node, dict):
            continue
        branch = re.search(r'/(oneOf|anyOf)/\d+$', address)
        if branch and address not in anchors:
            found = _discriminators(node)
            if found or records.get(address, {}).get('authoring', {}).get('multiMode'):
                units[address] = ('nested-variant', found)
        items = node.get('items')
        target = address + '/items'
        if isinstance(items, dict) and target not in anchors and _object_like(schema, items):
            alternatives = [target + '/' + keyword + '/' + str(index) for keyword in ('oneOf', 'anyOf')
                            for index, _ in enumerate(items.get(keyword, []))]
            if not (alternatives and all(other in anchors for other in alternatives)):
                units[target] = ('nested-member', None)
        entry = node.get('additionalProperties')
        target = address + '/additionalProperties'
        if isinstance(entry, dict) and entry and target not in anchors:
            units[target] = ('nested-entry', None)
        for pattern in node.get('patternProperties', {}):
            target = address + '/patternProperties/' + escape(pattern)
            if target not in anchors:
                units[target] = ('nested-entry', None)
    return units


def owner(anchors, address):
    """Item owning an address: the anchor with the longest matching prefix."""
    parts = address.split('/')
    for end in range(len(parts), 0, -1):
        prefix = '/'.join(parts[:end])
        if prefix in anchors:
            return anchors[prefix]
    return anchors['']


def _parent(anchors, address):
    parts = address.split('/')
    for end in range(len(parts) - 1, 0, -1):
        prefix = '/'.join(parts[:end])
        if prefix in anchors:
            return anchors[prefix]
    return anchors['']


class Collector:
    """Accumulates rows for one inventory build."""

    def __init__(self, scope):
        self.scope = scope
        self.routes, self.items, self.fields, self.surfaces, self.gaps = [], [], [], [], []

    def gap(self, key, code, detail):
        self.gaps.append({'key': key, 'code': code, 'detail': detail})


def _singleton(schema, specification, depth=0):
    """True only when every alternative is explicitly a single non-collection value."""
    node = _resolve(schema, specification)
    branches = node.get('anyOf', []) + node.get('oneOf', [])
    if branches:
        return depth < 4 and all(_singleton(schema, branch, depth + 1) for branch in branches)
    if 'const' in node or isinstance(node.get('enum'), list):
        return True
    if node.get('type') in ('string', 'number', 'integer', 'boolean'):
        return True
    return (node.get('type') == 'object' and 'properties' in node and not node.get('patternProperties')
            and not isinstance(node.get('additionalProperties'), dict))


def _item_kind(schema, entry, specification):
    at = entry.get('at', '')
    if entry['id'].startswith('operation:'):
        if at == '/nodes/-':
            return 'operation-node'
        if at == '/operation':
            return 'operation-selector'
        if at.endswith('/exports/-'):
            return 'operation-writer'
        return 'operation-other'
    if entry['id'].startswith('document:'):
        specification = _resolve(schema, specification)
        if entry['id'][len('document:'):] in SECTIONS:
            return 'document-map'
        if specification.get('type') == 'array':
            return 'document-collection'
        if isinstance(specification.get('additionalProperties'), dict) or specification.get('patternProperties'):
            return 'document-map'
        return 'document-singleton' if _singleton(schema, specification) else 'document-setting'
    return 'hook-item'


def _anchor_kind(schema, identity, specification):
    if identity == 'route-root':
        return 'route-root'
    if identity.startswith('definition:'):
        return 'definition'
    if identity == 'document:version':
        return 'discriminator'
    if identity == 'document:nodes':
        return 'graph-container'
    if identity.startswith('operation:'):
        return 'operation-unprojected'
    return _item_kind(schema, {'id': identity}, specification)


def _catalogue_addresses(entries, definitions):
    """Collect actual form addresses, including referenced member definitions."""
    pending = [entry['schema'] for entry in entries if 'schema' in entry]
    visited, addresses = set(), set()
    while pending:
        for _, field in fields(pending.pop()):
            address = field.get('x-studio-guide', {}).get('address')
            if address is not None:
                addresses.add(address)
            ref = field.get('$ref', '')
            if ref.startswith('#/$defs/') and ref not in visited:
                visited.add(ref)
                key = ref.removeprefix('#/$defs/').replace('~1', '/').replace('~0', '~')
                if key in definitions:
                    pending.append(definitions[key])
    return addresses


def _route(collector, adaptor, version, role, schema, entries, declarations, guidance, evidence, definitions=None,
           shared=False, local_roles=None):
    """Inventory one route: items, nested units, commands, every owned field, surfaces and gaps."""
    route_key = item_key(adaptor, version, 'route-root')
    addresses = list(shared_fields(version, schema) if shared else fields(schema))
    records = guidance.get('routes', {}).get(version, {}).get('fields', {})
    projected_addresses = _catalogue_addresses(entries, definitions or {})
    anchors = _anchors(schema, addresses, declarations)
    items, order = {}, Counter()
    for entry in entries:
        order[entry['id']] += 1
        identity = entry['id'] if order[entry['id']] == 1 else entry['id'] + '@' + str(order[entry['id']])
        items[identity] = {'entry': entry, 'anchors': []}
    for identity, count in sorted(order.items()):
        if count > 1:
            collector.gap(item_key(adaptor, version, identity), 'duplicate-catalogue-id',
                          str(count) + ' Add catalogue entries share this id; later ones are keyed @2, @3, ...')
    for address, identity in sorted(anchors.items()):
        items.setdefault(identity, {'entry': None, 'anchors': []})['anchors'].append(address)
    if role == 'primary':
        for name in sorted(declarations):
            items.setdefault('operation:' + name, {'entry': None, 'anchors': []})
    for identity, record in sorted(items.items()):
        entry = record['entry']
        if not entry or not entry.get('at') or identity.startswith('operation:'):
            continue
        if identity.startswith('document:') and not entry['at'].endswith('/-'):
            continue
        where = schema_address(schema, entry['at'])
        if where is None:
            collector.gap(item_key(adaptor, version, identity), 'insertion-address-unresolved',
                          'Add catalogue insertion ' + entry['at'] + ' does not resolve to a schema address')
        elif where not in anchors:
            anchors[where] = identity
            record['anchors'].append(where)
    units = nested_units(schema, addresses, anchors, records)
    parents = {}
    for address in sorted(units):
        identity = 'entity:' + address
        anchors[address] = identity
        items[identity] = {'entry': None, 'anchors': [address], 'unit': units[address]}
    for address in sorted(units):
        parents['entity:' + address] = item_key(adaptor, version, _parent(anchors, address))
    nodes = dict(addresses)
    owned, edges = {}, {}
    for address, node in addresses:
        status = records.get(address, {'status': 'pending'})['status']
        projected_control = None
        if definitions and node.get('type') == 'array':
            definition = re.fullmatch(r'/\$defs/([^/]+)/properties/([^/]+)(?:/anyOf/0)?', address)
            if definition:
                key, field = (part.replace('~1', '/').replace('~0', '~') for part in definition.groups())
                projected = definitions.get(key, {}).get('properties', {}).get(field, {})
                kind = projected.get('x-studio-control', {}).get('kind')
                if kind in ('reader-array-domain', 'file-subset', 'enum-subset'):
                    projected_control = kind
        direct_control = records.get(address, {}).get('control', {}).get('kind')
        kind = classify(schema, address, node, direct_control or projected_control)
        if local_roles and address in local_roles:
            kind = local_roles[address]
        control = (_control(records, address) or projected_control) if kind == 'subset-candidate' else None
        identity = owner(anchors, address)
        parent, _, field = address.rpartition('/properties/')
        owning_item = items.get(identity, {})
        entry = owning_item.get('entry')
        if not control and kind == 'subset-candidate' and entry and parent in owning_item['anchors']:
            projected = entry['schema'].get('properties', {}).get(field, {})
            if projected.get('x-studio-control', {}).get('kind') == 'enum-subset':
                control = 'enum-subset'
        if not shared and kind == 'subset-candidate' and not control and enumerated_subset(node):
            editor_owner = identity
            while editor_owner in parents:
                _, _, editor_owner, _ = split_key(parents[editor_owner])
            owning_item = items.get(editor_owner, {}).get('entry')
            if owning_item and owning_item.get('at'):
                control = 'enum-subset'
        owned.setdefault(identity, []).append((address, kind, status, control, node,
                                               guide_semantics(records.get(address))))
        target = node.get('$ref')
        if isinstance(target, str) and target.startswith('#/$defs/'):
            destination = owner(anchors, '/$defs/' + escape(target[len('#/$defs/'):]))
            if destination != identity:
                edges.setdefault(identity, set()).add(destination)
    surfaces = {}
    for identity, rows in owned.items():
        operation = identity[len('operation:'):] if identity.startswith('operation:') else None
        for address, kind, status, control, node, guide in rows:
            collector.fields.append((item_key(adaptor, version, identity), address, kind, status,
                                     field_contract(node, guide)))
            if kind in SURFACE_KINDS:
                surfaces.setdefault(identity, []).append((address, kind, control))
                port = declarations.get(operation, {}).get('inputs', {}).get(address.split('/')[-1]) \
                    if kind == 'reference' and '/inputs/properties/' in address else None
                readback_domain = False
                tuple_size = None
                if kind == 'subset-candidate':
                    option_path = re.fullmatch(r'/\$defs/options-([^/]+)/properties/([^/]+)(?:/anyOf/0)?', address)
                    if option_path:
                        operation_key, option_key = option_path.groups()
                        binding = declarations.get(operation_key, {}).get('options', {}).get(option_key, {})
                        tuple_size = binding.get('tupleSize')
                    elif operation and address.startswith('/$defs/readback/'):
                        field = address.rsplit('/', 1)[-1].replace('~1', '/').replace('~0', '~')
                        binding = declarations.get(operation, {}).get('options', {}).get(field, {})
                        tuple_size = binding.get('tupleSize')
                        domains = set(binding.get('nativeDomains', ()))
                        readback_domain = bool(domains & {'vtkSMArraySelectionDomain', 'vtkSMDataAssemblyDomain'})
                collector.surfaces.append(_surface(adaptor, version, identity, address, kind, control, node, port,
                                                   readback_domain=readback_domain, tuple_size=tuple_size))
    stale = sorted(address for address in records if address not in nodes)
    for address in stale:
        collector.gap(surface_key(adaptor, version, 'route-root', address), 'guidance-stale-address',
                      'guidance record addresses a field absent from the route schema')
    operations = 0
    for identity, record in sorted(items.items()):
        entry = record['entry']
        specification = nodes.get(record['anchors'][0], {}) if record['anchors'] else {}
        if 'unit' in record:
            kind = record['unit'][0]
        else:
            kind = _item_kind(schema, entry, specification) if entry else _anchor_kind(schema, identity, specification)
        reachable = _reachable(identity, edges)
        row = _item(adaptor, version, identity, kind, entry, record['anchors'], owned.get(identity, []),
                    reachable, surfaces, declarations, guidance, definitions or {}, shared)
        if kind in ('operation-writer', 'hook-item'):
            projected = (entry or {}).get('schema', {}).get('x-studio-guide', {}).get('authoring', {})
            if 'multiMode' in projected:
                source = {**entry, 'authoringBasis': 'adaptor Studio catalogue'} if kind == 'operation-writer' else entry
                row['multiMode'] = _multi_mode(kind, projected, adaptor, source)
                row['naming'] = _naming(kind, source, projected, _properties(entry), has_identity=True,
                                        definitions=definitions or {}, adaptor=adaptor)
                row['authoring']['quickRows'] = 'projected'
                row['authoring']['studioEdit'] = 'projected'
        if 'unit' in record:
            row['parent'] = parents[identity]
            if record['unit'][1]:
                row['discriminator'] = record['unit'][1]
            anchor = record['anchors'][0]
            container = nodes.get(anchor.removesuffix('/items'), {})
            reference = specification.get('$ref', '').removeprefix('#')
            policy = records.get(anchor, {}).get('authoring', records.get(reference, {}).get('authoring', {}))
            member_settings = kind in ('nested-member', 'nested-variant') and re.search(
                r'/items(?:/(oneOf|anyOf)/[0-9]+)?$', anchor)
            if member_settings and anchor in projected_addresses and 'naming' in policy:
                row['naming'] = _naming(kind, {}, policy, _resolve(schema, specification).get('properties', {}),
                                        has_identity=True, definitions=definitions or {}, adaptor=adaptor)
            elif member_settings and 'naming' in policy:
                row['naming'] = dimension('derived', 'not-applicable', 'validator copy of projected member',
                                           rationale='Settings uses the shared member schema at a different address.')
            if member_settings and 'multiMode' in policy and anchor not in projected_addresses:
                row['multiMode'] = dimension('derived', 'not-applicable', 'validator copy of projected member',
                                             classification='collection', qualification='not-required',
                                             rationale='The Add catalogue edits the shared member through another schema address.')
            elif member_settings and 'multiMode' in policy:
                row['multiMode'] = _multi_mode(kind, policy, adaptor, None)
                if policy.get('identityField') is False:
                    row['naming'] = dimension('derived', 'not-applicable', 'declared unnamed member',
                                              rationale='The member is authored through its settings and has no separate Name.')
                row['authoring']['quickRows'] = 'projected'
                row['authoring']['studioEdit'] = 'projected'
                if policy['multiMode'].get('batchPath', policy['multiMode'].get('path')):
                    row['authoring']['batch'] = 'projected'
            elif kind == 'nested-member' and container.get('type') == 'array' and container.get('maxItems') == 1:
                row['multiMode'] = _singleton_multi_mode('declared nested collection maxItems')
            elif kind == 'nested-variant' and re.search(r'/properties/[^/]+(?:/(?:anyOf|oneOf)/[0-9]+)+$', anchor):
                row['multiMode'] = _singleton_multi_mode('declared alternative for one property')
            elif kind == 'nested-variant' and re.fullmatch(r'(?:/(?:anyOf|oneOf)/[0-9]+)+', anchor):
                row['multiMode'] = _singleton_multi_mode('declared document alternative')
            elif (kind == 'nested-member' and (alternatives := specification.get('oneOf', []) + specification.get('anyOf', []))
                  and all(_discriminators(branch) for branch in alternatives)):
                row['multiMode'] = dimension('derived', 'not-applicable', 'discriminated collection member',
                                             classification='collection', qualification='not-required',
                                             rationale='Each member has a fixed kind and its variant carries the authoring policy.')
            elif kind == 'nested-member' and scalar_collection_member(schema, specification):
                row['multiMode'] = dimension('derived', 'not-applicable', 'literal scalar collection member',
                                             classification='collection',
                                             rationale='The scalar is a value in its containing list, not an independent element.')
            elif (kind == 'nested-member'
                  and re.search(r'/properties/inputs/properties/[^/]+(?:/(?:oneOf|anyOf)/[0-9]+)*/items$', anchor)
                  and split_key(parents[identity])[2].startswith('operation:')):
                row['multiMode'] = dimension('derived', 'not-applicable', 'pipeline input reference',
                                             classification='collection', qualification='not-required',
                                             rationale='An entry selects an existing output port for the owning operation.')
            elif (re.match(r'^/\$defs/(?:json|runtime|runtimeValue)/', anchor)
                  or adaptor == 'workflow' and re.match(
                      r'^/\$defs/(?:analytic|composition|expression|authorArray|authorData|authorObject|numericTree)/', anchor)):
                row['multiMode'] = dimension('derived', 'not-applicable', 'literal or runtime value grammar',
                                             classification='not-an-element', qualification='not-required',
                                             rationale='This item describes a value consumed inside another element.')
            elif (match := re.match(r'^/oneOf/[0-9]+(/properties/.+)$', anchor)) and match[1] in nodes \
                    and schema_semantic(specification) == schema_semantic(nodes[match[1]]):
                row['multiMode'] = dimension('derived', 'not-applicable', 'duplicate operation schema member',
                                             classification='not-an-element', qualification='not-required',
                                             rationale='The matching root property is the shared authoring location.',
                                             current=match[1])
            elif adaptor == 'freecad' and '/properties/drive/properties/' in anchor:
                row['multiMode'] = dimension('derived', 'not-applicable', 'FreeCAD affine binding grammar',
                                             classification='collection', qualification='not-required',
                                             rationale='Each term contributes to the affine value of one driven option.',
                                             evidence=['src/schemaxis/adaptors/freecad/parameters.py'])
            elif (adaptor == 'freecad' and
                  re.search(r'/properties/(?:geometry|constraints|holder)/items(?:/(?:anyOf|oneOf)/[0-9]+)?$', anchor)):
                row['multiMode'] = dimension('derived', 'not-applicable', 'FreeCAD compound geometry settings',
                                             classification='collection', qualification='not-required',
                                             rationale='The entries describe one sketch or tool envelope in their declared order.')
            elif adaptor == 'blender' and kind == 'nested-variant' and (graph := _blender_graph_variant(anchor, specification)):
                row['multiMode'] = graph
            elif adaptor == 'blender' and (ordered := _ordered_blender_unit(anchor)):
                row['multiMode'] = ordered
            elif (semantics := _nested_adaptor_semantics(adaptor, anchor)):
                row['multiMode'] = semantics
            elif kind in ('nested-member', 'nested-variant') and _closed_anonymous_member(schema, specification):
                row['multiMode'] = dimension('derived', 'not-applicable', 'closed anonymous member',
                                             classification='collection', qualification='not-required',
                                             rationale='The record has no member identity field. It is part of its containing value.')
        if row['naming']['implementation'] == 'unknown':
            naming_scope = _naming_scope(schema, specification, kind, row['multiMode'])
            if naming_scope:
                row['naming'] = naming_scope
        operations += kind.startswith('operation-') and kind != 'operation-unprojected'
        if kind == 'operation-unprojected' and role == 'primary':
            row['gaps'].append('declaration-not-projected')
            collector.gap(row['key'], 'declaration-not-projected',
                          'declared operation is absent from the primary route Add catalogue')
        if kind == 'definition' and identity.startswith('definition:options-'):
            row['gaps'].append('options-definition-undeclared')
            collector.gap(row['key'], 'options-definition-undeclared',
                          'options definition has no matching declaration')
        if entry and identity.startswith('operation:') and identity.split('@')[0][len('operation:'):] not in declarations:
            row['gaps'].append('catalogue-operation-undeclared')
            collector.gap(row['key'], 'catalogue-operation-undeclared',
                          'Add catalogue operation has no declaration')
        if entry is None and shared and kind not in NOT_ELEMENTS:
            row['gaps'].append('no-add-catalogue-projection')
        collector.items.append(_compact(row))
    commands = _commands(collector, adaptor, version, declarations, owned)
    if shared:
        collector.gap(route_key, 'no-add-catalogue-projection',
                      'shared Studio route: designer/editor surfaces are not projected into an Add catalogue')
    collector.routes.append({
        'key': item_key(adaptor, version, '').rstrip('/'), 'adaptor': adaptor, 'route': version, 'role': role,
        'scope': collector.scope, 'evidence': evidence, 'catalogueItems': len(entries),
        'declarations': len(declarations), 'commands': commands, 'operationItems': operations,
        'nestedUnits': len(units), 'fields': len(addresses), 'items': len(items) + commands,
        'contract': fingerprint({'schema': schema_semantic(schema), 'declarations': declarations}),
        'guideContract': fingerprint({address: guide_semantics(record) for address, record in sorted(records.items())
                                      if guide_semantics(record)}),
        'guidance': dict(sorted(Counter(records.get(a, {'status': 'pending'})['status'] for a, _ in addresses).items())),
        'staleGuidance': len(stale)})


def _commands(collector, adaptor, version, declarations, owned):
    """One row per declared native command; schema enumeration is reconciled both ways."""
    total = 0
    for operation in sorted(declarations):
        declared = declarations[operation].get('commands') or {}
        enumerated = set()
        for address, _, _, _, node, _ in owned.get('operation:' + operation, []):
            if '/properties/onVisit' in address and isinstance(node.get('enum'), list):
                enumerated.update(value for value in node['enum'] if isinstance(value, str))
        parent = item_key(adaptor, version, 'operation:' + operation)
        for name in sorted(declared):
            total += 1
            key = item_key(adaptor, version, 'command:' + operation + ':' + name)
            projected = name in enumerated
            row = {'key': key, 'adaptor': adaptor, 'route': version, 'item': 'command:' + operation + ':' + name,
                   'kind': 'native-command', 'anchors': [], 'parent': parent,
                   'projection': 'schema-enumerated' if projected else 'missing', 'gaps': [],
                   'command': {'operation': operation, 'name': name, **declared[name]},
                   'contract': {'declaration': fingerprint(declared[name])},
                   'evidence': [registry.ADAPTORS[adaptor]['declarations'] if adaptor in registry.ADAPTORS
                                else 'declarations']}
            for dimension_name in DIMENSIONS:
                row[dimension_name] = dimension(basis='native command declaration; stateful semantics unassessed',
                                                classification='unclassified' if dimension_name == 'multiMode' else None)
            row['multiMode'] = dimension('derived', 'not-applicable', 'command executes on an existing proxy',
                                         classification='sequential', qualification='not-required',
                                         rationale='An invocation participates in the owning node visit and creates no sibling node.')
            row['authoring'] = _authoring('native-command', None, {})
            if not projected:
                row['gaps'].append('command-not-enumerated')
                collector.gap(key, 'command-not-enumerated', 'declared command is absent from the onVisit schema enum')
            collector.items.append(_compact(row))
        for name in sorted(enumerated - set(declared)):
            collector.gap(parent, 'command-undeclared', 'onVisit enumerates ' + name + ' without a declaration')
    return total


def _compact(row):
    if not row['gaps']:
        row.pop('gaps')
    if 'fields' in row:
        row['fields'] = {key: value for key, value in row['fields'].items() if value not in (0, [])}
    return row


def _control(records, address):
    """A field's declared control, inherited by its own literal alternative branches."""
    parts = address.split('/')
    while True:
        control = records.get('/'.join(parts), {}).get('control', {}).get('kind')
        if control or len(parts) < 3 or parts[-2] not in ('anyOf', 'oneOf') or not parts[-1].isdigit():
            return control
        parts = parts[:-2]


def _reachable(identity, edges):
    seen, pending = set(), list(edges.get(identity, ()))
    while pending:
        current = pending.pop()
        if current not in seen and current != identity:
            seen.add(current)
            pending.extend(edges.get(current, ()))
    return sorted(seen)


def _surface(adaptor, version, identity, address, kind, control, node, port=None, *, readback_domain=False, tuple_size=None):
    """A field-level authoring surface with independent records for all four dimensions."""
    if kind == 'subset-candidate' and control in SUBSET_CONTROLS:
        primary = dimension('derived', 'implemented', 'guidance control ' + control + ' renders the shared subset selector')
    elif kind == 'subset-candidate' and control == 'enum-subset':
        primary = dimension('derived', 'implemented', 'Studio catalogue supplies literal choices for the shared subset picker')
    elif kind == 'subset-candidate' and readback_domain:
        primary = dimension('derived', 'not-applicable', 'automatic reader runs on the written artifact',
                            rationale='Readback names are available after the export writes its managed file.')
    elif kind == 'subset-candidate' and tuple_size and tuple_size > 1:
        primary = dimension('derived', 'not-applicable', 'declared native tuples',
                            rationale='Entries encode complete ordered tuples rather than individually selected names.')
    elif kind == 'subset-candidate' and address.endswith('/properties/onVisit'):
        primary = dimension('derived', 'not-applicable', 'ordered invocation list',
                            rationale='The pipeline executes each command occurrence in order, including repeats.')
    elif (kind == 'subset-candidate' and adaptor == 'exiftool'
          and re.search(r'/properties/edits/properties/(creator/properties/set|keywords/properties/(set|add))$', address)):
        primary = dimension('derived', 'not-applicable', 'authored metadata text',
                            rationale='The author supplies new creator or keyword text directly.')
    elif (kind == 'subset-candidate' and adaptor == 'zstandard'
          and re.search(r'/properties/fileSet/properties/(include|exclude)$', address)):
        primary = dimension('derived', 'not-applicable', 'authored file selection patterns',
                            rationale='The authored patterns match names when the directory is captured.')
    elif kind == 'subset-candidate' and node.get('maxItems') == 1:
        primary = dimension('derived', 'not-applicable', 'declared selection limit',
                            rationale='The field accepts at most one value, so a multi-selection picker does not apply.')
    elif kind == 'subset-candidate':
        primary = dimension(basis='structural: array of string choices')
    elif kind == 'path':
        primary = dimension(basis='structural: string field named like a file, path or destination',
                            current='destination/collision semantics not assessed')
    else:
        primary = dimension(basis='structural: ' + kind + ' field')
    row = {'key': surface_key(adaptor, version, identity, address), 'kind': kind}
    for name in DIMENSIONS:
        row[name] = primary if name == SURFACE_DIMENSION[kind] else dimension(basis='structural: ' + kind + ' field')
    constraints = {key: node[key] for key in CONSTRAINTS if isinstance(node, dict) and key in node}
    if constraints and kind != 'subset-candidate':
        row['constraints'] = constraints
    if port:
        row['port'] = {key: port[key] for key in PORT_KEYS if key in port}
        if port.get('multiple'):
            row['subset'] = dimension('derived', 'implemented', 'declared multi-input port',
                                      rationale='Studio offers compatible named inputs and preserves selection order.')
            control = 'input-subset'
    if control:
        row['control'] = control
    return row


def _properties(entry):
    return entry.get('schema', {}).get('properties', {}) if entry else {}


def _options_file(entry, definitions):
    options = _properties(entry).get('options', {})
    target = options.get('$ref', '') if isinstance(options, dict) else ''
    if target.startswith('#/$defs/'):
        options = definitions.get(target[len('#/$defs/'):], {})
    return 'file' in options.get('properties', {})


def _item(adaptor, version, identity, kind, entry, anchors, rows, reachable, surfaces, declarations,
          guidance, definitions, shared):
    key = item_key(adaptor, version, identity)
    operation = identity.split('@')[0][len('operation:'):] if identity.startswith('operation:') else None
    record = guidance.get('operations', {}).get(operation, {}) if operation else {}
    authoring = entry.get('authoring', record.get('authoring', {})) if entry else {}
    found = list(surfaces.get(identity, []))
    for other in reachable:
        found.extend(surfaces.get(other, []))
    counts = Counter(kind_name for _, kind_name, _ in found)
    controls = sum(1 for _, kind_name, control in found if kind_name == 'subset-candidate' and control in SUBSET_CONTROLS)
    row = {'key': key, 'adaptor': adaptor, 'route': version, 'item': identity, 'kind': kind,
           'anchors': sorted(anchors), 'projection': _projection(entry, kind, shared), 'gaps': []}
    if entry:
        row['catalogue'] = {key_name: entry[key_name] for key_name in ('id', 'at', 'group') if key_name in entry}
    contract = {}
    if operation:
        declaration = declarations.get(operation)
        row['operation'] = operation
        row['declared'] = declaration is not None
        native = (declaration or {}).get('native')
        if native and native != operation:
            row['native'] = native
        row['operationGuidance'] = record.get('status', 'pending') if declaration is not None else 'undeclared'
        if declaration is not None:
            contract['declaration'] = fingerprint(declaration)
            ports = {name: {k: port[k] for k in PORT_KEYS if k in port}
                     for name, port in declaration.get('inputs', {}).items()}
            if ports:
                row['ports'] = ports
            if declaration.get('commands'):
                row['commands'] = sorted(declaration['commands'])
    if entry:
        contract['catalogue'] = fingerprint(entry_semantic(entry))
    if record:
        contract['guidance'] = fingerprint({'status': record.get('status'), 'authoring': record.get('authoring')})
    if contract:
        row['contract'] = contract
    guides = {owned[0]: {key: value for key, value in owned[5].items() if key != 'fileExtensions'}
              for owned in rows if set(owned[5]) - {'fileExtensions'}}
    if guides:
        row['guides'] = guides
    row['fields'] = {'owned': len(rows), 'pendingGuidance': sum(1 for owned in rows if owned[2] == 'pending'),
                     'identity': counts['identity'] + counts['name-candidate'], 'references': counts['reference'],
                     'subsetCandidates': counts['subset-candidate'], 'subsetControls': controls,
                     'paths': counts['path'], 'maps': counts['map']}
    via = sorted(other for other in reachable if other in surfaces)
    if via:
        row['fields']['via'] = via
    has_identity = bool(counts['identity'] + counts['name-candidate'] + counts['map'])
    top = _properties(entry)
    if kind in UNASSESSED_KINDS:
        basis = 'structural: ' + kind + '; semantics unassessed'
        for name in DIMENSIONS:
            row[name] = dimension(basis=basis, classification='unclassified' if name == 'multiMode' else None)
    else:
        row['naming'] = _naming(kind, entry, authoring, top, has_identity, definitions, adaptor)
        row['renaming'] = _renaming(kind, identity, top, has_identity, entry)
        row['multiMode'] = _multi_mode(kind, authoring, adaptor, entry)
        row['subset'] = _subset(kind, counts['subset-candidate'], controls)
    row['authoring'] = _authoring(kind, entry, authoring)
    return row


def _authoring(kind, entry, authoring):
    """Which authoring surfaces project this item; sharing a schema is not evidence of behaviour."""
    if entry:
        add = 'projected'
    elif kind == 'operation-unprojected':
        add = 'missing'
    else:
        add = 'not-projected'
    multi = 'projected' if 'multiMode' in authoring and entry and entry.get('at') in ('/nodes/-', '/scenes/-') else 'not-projected'
    policy = authoring.get('multiMode', {})
    batch = multi if policy.get('batchPath', policy.get('path')) else 'not-projected'
    return {'studioAdd': add, 'studioEdit': 'unassessed', 'studioProperties': 'unassessed', 'quickRows': multi,
            'batch': batch, 'core': 'unassessed', 'cli': 'unassessed', 'console': 'unassessed', 'ai': 'unassessed'}


def _projection(entry, kind, shared):
    if entry:
        return 'projected'
    if kind in ('discriminator', 'graph-container', 'definition', 'route-root'):
        return 'not-projected:' + kind
    if kind in NESTED:
        return 'not-projected:nested'
    if shared:
        return 'not-projected:shared-route'
    return 'missing'


def _naming(kind, entry, authoring, top, has_identity, definitions, adaptor):
    if kind in NOT_ELEMENTS:
        return dimension('derived', 'not-applicable', 'structural',
                         rationale='not an insertable element; nested units and identities have their own rows')
    if 'naming' in authoring:
        policy = authoring['naming']
        candidates = ([policy['path']] if 'path' in policy else
                      [field['path'] for field in authoring['instanceFields'] if field.get('style') != 'omit'])
        current = policy['style'] + ' of ' + policy['path'] if 'path' in policy else 'Ordered distinguishing settings'
        source = entry.get('authoringBasis', 'guidance authoring.naming')
        return dimension('derived', 'implemented', source, current=current,
                         candidates=candidates, evidence=[registry.adaptor_source(adaptor, 'guidance.json'), STUDIO + 'element-authoring.mjs'])
    if entry and 'id' in top and entry.get('at') == '/nodes/-' and _options_file(entry, definitions):
        return dimension(implementation='generic-rule', basis='Studio parent-folder and file-stem rule for options.file',
                         current='folder_stem from options.file, else operation name plus counter',
                         candidates=['/options/file'], evidence=[STUDIO + 'authoring-defaults.mjs', STUDIO + 'operation-form.mjs'])
    if entry and 'id' in top:
        return dimension(implementation='generic-fallback', basis='Studio operation name plus counter',
                         current='operation name plus counter', evidence=[STUDIO + 'authoring-defaults.mjs'])
    if entry and entry.get('at') == '/sweeps/-' and 'name' in top:
        return dimension(implementation='generic-fallback', basis='Studio sweep plus counter',
                         current='sweep plus counter', evidence=[STUDIO + 'authoring-defaults.mjs'])
    return _anonymous(kind, has_identity)


def _anonymous(kind, has_identity):
    if not has_identity and kind in SINGLE_VALUED:
        return dimension('derived', 'not-applicable', 'structural: single value without its own id, name or named-map field',
                         rationale='this single-valued item has no instance identity; nested units have their own rows')
    if not has_identity:
        return dimension(basis='structural: no id, name or named-map field; whether members need identities is unassessed')
    return dimension(basis='structural: identity fields are owned by this item')


def _naming_scope(schema, specification, kind, multi_mode):
    """A Name belongs to an authored instance or a map key, not its value fields."""
    basis = multi_mode['basis']
    if basis in ('declared alternative for one property', 'declared document alternative',
                 'discriminated collection member', 'duplicate operation schema member', 'validator copy of projected member'):
        return dimension('derived', 'not-applicable', 'shared naming location',
                         rationale='This schema branch does not create a separate Name. Its owning form or member has the editable field.')
    if kind in ('native-command', 'operation-selector', 'hook-item'):
        return dimension('derived', 'not-applicable', 'command or settings projection',
                         rationale='The action configures an existing owner or selects a declared operation. It declares no new Name.')
    if kind in ('document-collection', 'document-map', 'document-setting'):
        return dimension('derived', 'not-applicable', 'document setting or collection wrapper',
                         rationale='The property has no Name of its own. The editor uses its declared key and assesses its members separately.')
    if kind not in ('nested-member', 'nested-variant', 'document-singleton'):
        return None
    current = _resolve(schema, specification)
    alternatives = current.get('anyOf', []) + current.get('oneOf', []) or [current]
    own_fields = {'id', 'name', 'alias', 'label', 'title'}
    if any(own_fields & set(_resolve(schema, branch).get('properties', {})) for branch in alternatives):
        return None
    return dimension('derived', 'not-applicable', 'schema has no member Name field',
                     rationale='The member carries typed settings, values or references without declaring a separate Name.')


def _renaming(kind, identity, top, has_identity, entry):
    if kind in NOT_ELEMENTS:
        return dimension('derived', 'not-applicable', 'structural', rationale='not an insertable element')
    if kind == 'document-map' and identity[len('document:'):] in SECTIONS:
        return dimension(implementation='generic-rule', basis='core spatial_rename over checked expression bindings',
                         current='named entries renamed with their expression references; route suitability unassessed',
                         referenceScope='expression bindings in the selected document scope',
                         evidence=['src/schemaxis/spatial_rename.py'])
    if 'id' in top:
        if entry and entry.get('at') == '/nodes/-':
            return dimension('derived', 'not-implemented', 'Studio Settings preserves saved node identifiers',
                             current='Saved node Names are fixed in Settings and compact rows.',
                             evidence=[STUDIO + 'operation-form.mjs', STUDIO + 'multi-mode.mjs'])
        return dimension('derived', 'not-implemented', 'Studio forms; no reference-aware rename transaction',
                         current='Name editable; references are not updated', evidence=[STUDIO + 'operation-form.mjs'])
    return _anonymous(kind, has_identity)


def _singleton_multi_mode(basis):
    return dimension('derived', 'not-applicable', basis, classification='singleton',
                     rationale='The containing field permits at most one instance.')


def _multi_mode(kind, authoring, adaptor, entry):
    if kind in NOT_ELEMENTS:
        return dimension('derived', 'not-applicable', 'structural', classification='not-an-element',
                         rationale='not an insertable element')
    limit = (entry or {}).get('collectionLimit', {})
    if limit.get('maxItems') == 1 and 'multiMode' not in authoring:
        return _singleton_multi_mode('declared parent collection maxItems')
    if 'multiMode' in authoring:
        policy = authoring['multiMode']
        varying = [field['path'] for field in authoring['instanceFields']] if 'instanceFields' in authoring else [policy['path']]
        batch = policy.get('batchPath', policy.get('path'))
        current = 'Exact-list Batch at ' + batch if batch else 'Compact rows'
        source = (entry or {}).get('authoringBasis', 'guidance authoring.multiMode')
        classification = 'conditional' if authoring.get('when') or policy.get('validatePlan') else 'independent-siblings'
        return dimension('derived', 'implemented', source, classification=classification,
                         rationale=policy['rationale'], varying=varying, current=current,
                         evidence=[registry.adaptor_source(adaptor, 'guidance.json'), STUDIO + 'multi-mode.mjs'])
    if kind == 'operation-selector':
        return _singleton_multi_mode('declared document operation discriminator')
    if kind == 'operation-writer':
        return dimension('derived', 'not-implemented', 'writer publishes to an owned destination',
                         classification='side-effect',
                         rationale='Batch publication requires separate destinations and explicit ownership checks.')
    if (kind in ('document-collection', 'document-map', 'document-setting') and entry
            and not entry.get('at', '').endswith('/-')):
        return dimension('derived', 'not-applicable', 'one document property owns the collection or setting',
                         classification='collection' if kind != 'document-setting' else 'singleton',
                         rationale='The form edits the enclosing property. Individual members have their own inventory rows.')
    if kind == 'document-singleton':
        return dimension('derived', 'not-applicable', 'structural: document property holds a single value',
                         classification='singleton',
                         rationale='a non-collection document property cannot hold sibling elements; nested units have their own rows')
    return dimension(basis='none', classification='unclassified')


def _subset(kind, candidates, controls):
    if kind in NOT_ELEMENTS:
        return dimension('derived', 'not-applicable', 'structural',
                         rationale='field-level subset surfaces are assessed on the surface rows')
    if candidates and controls == candidates:
        return dimension('derived', 'implemented', 'every structural candidate has a declared subset control')
    if controls:
        return dimension('derived', 'partial', str(controls) + ' of ' + str(candidates) + ' structural candidates have a declared subset control')
    if candidates:
        return dimension(basis=str(candidates) + ' structural candidate(s); none has a declared subset control')
    return dimension(basis='no structural candidate detected; free-form selections are not excluded')


def _registered(collector, adaptor):
    from schemaxis.studio_catalogue import catalogue
    meta = registry.metadata(adaptor)
    declarations, fault = registry.isolated(adaptor, registry.declarations, adaptor)
    if fault is not None:
        collector.gap(item_key(adaptor, meta['version'], 'route-root'), 'declarations-failed', fault.message)
        declarations = {}
    try:
        guidance = load(adaptor)
    except SchemaxisError as error:
        collector.gap(item_key(adaptor, meta['version'], 'route-root'), 'guidance-invalid', error.fault.message)
        guidance = {'operations': {}, 'routes': {}}
    for version in sorted(meta['routes']):
        route = meta['routes'][version]
        role = 'primary' if version == meta['version'] else 'secondary'
        evidence = [meta['declarations'], route['schema'], 'schemaxis.studio_catalogue:catalogue',
                    registry.adaptor_source(adaptor, 'guidance.json')]
        if meta.get('studioCatalogue') and role == 'primary':
            evidence.append(meta['studioCatalogue'])
        try:
            schema = registry.binding(route['schema'])()
        except Exception as error:
            collector.gap(item_key(adaptor, version, 'route-root'), 'schema-failed', type(error).__name__ + ': ' + str(error))
            continue
        try:
            projected = catalogue(adaptor, version)
            entries = projected['items']
        except Exception as error:
            collector.gap(item_key(adaptor, version, 'route-root'), 'catalogue-failed', type(error).__name__ + ': ' + str(error))
            projected, entries = {'definitions': {}}, []
        owned = declarations if role == 'primary' else _declared_in(schema, declarations)
        first_item = len(collector.items)
        policy, local_roles = None, {}
        binding = route.get('authoringReferences')
        if binding:
            from schemaxis.identity_policy import for_route
            try:
                policy = for_route(adaptor, route)
            except SchemaxisError as error:
                collector.gap(item_key(adaptor, version, 'route-root'), 'identity-policy-invalid', error.fault.message)
            if policy:
                for projection in policy['projection'].values():
                    if projection.get('domain') == 'owner-local':
                        local_roles.update(dict.fromkeys(projection['identitySchemas'], 'identity'))
                        local_roles.update(dict.fromkeys(projection['referenceSchemas'], 'reference'))
        _route(collector, adaptor, version, role, schema, entries, owned, guidance, evidence, projected['definitions'],
               local_roles=local_roles)
        if policy:
            record_identity_policy(collector, first_item, policy, binding)
    for version in sorted(set(guidance.get('routes', {})) - set(meta['routes'])):
        collector.gap(item_key(adaptor, version, 'route-root'), 'guidance-route-unregistered',
                      'guidance.json holds a route the adaptor does not register')
    for name in sorted(set(guidance.get('operations', {})) - set(declarations)):
        collector.gap(item_key(adaptor, meta['version'], 'operation:' + name), 'guidance-operation-undeclared',
                      'guidance.json explains an operation the adaptor does not declare')


def record_identity_policy(collector, first_item, policy, binding):
    """Fingerprint admitted policy data; projection alone grants no implementation credit."""
    contract = fingerprint(policy)
    route = collector.routes[-1]
    route['identityReferences'] = {'binding': binding, 'contract': contract, 'data': policy}
    items = {row['key']: row for row in collector.items[first_item:]}
    local = {identity: projection for identity, projection in policy['projection'].items()
             if projection.get('domain') == 'owner-local'}
    if local:
        for surface in collector.surfaces:
            adaptor, version, owner, address = split_key(surface['key'])
            item = item_key(adaptor, version, owner)
            if item not in items:
                continue
            for identity, projection in local.items():
                role = ('target' if address in projection['identitySchemas'] else
                        'consumer' if address in projection['referenceSchemas'] else None)
                if role:
                    record = {'binding': binding, 'contract': contract, 'domain': 'owner-local', 'role': role,
                              'owner': item_key(route['adaptor'], route['route'], 'operation:' + projection['operation'])}
                    surface.setdefault('identityReferences', {})[identity] = record
                    items[item].setdefault('identityReferences', {})[identity] = record
    for row in collector.items[first_item:]:
        operation = row.get('operation')
        for identity, projection in policy['projection'].items():
            if identity in local:
                continue
            category = ('operations' if operation in projection['operations'] else
                        'writers' if operation in projection['writers'] else None)
            if category is not None:
                row.setdefault('identityReferences', {})[identity] = {
                    'binding': binding, 'target': category == 'operations',
                    'ports': projection[category][operation], 'contract': contract}


def _declared_in(schema, declarations):
    """Secondary routes own only the declared operations their schema names."""
    named = set()
    for address, node in fields(schema):
        for discriminator in ('filter', 'writer', 'operation'):
            value = node.get('properties', {}).get(discriminator, {})
            if isinstance(value, dict) and isinstance(value.get('const'), str):
                named.add(value['const'])
        parts = address.split('/')
        if len(parts) == 3 and parts[1] == '$defs' and parts[2].startswith('options-'):
            named.add(parts[2][len('options-'):].replace('~1', '/').replace('~0', '~'))
    return {name: value for name, value in declarations.items() if name in named}


def _shared(collector, provider):
    from schemaxis import workflow_authoring, workflow_design
    guidance = load(provider)
    actions = sorted(workflow_authoring._DESIGN_ACTIONS)
    for version in sorted(name for name, owner_name in SHARED.items() if owner_name == provider):
        schema = shared_schema(version)
        evidence = ['schemaxis.studio_guidance:shared_schema', registry.adaptor_source(provider, 'guidance.json')]
        _route(collector, provider, version, 'shared', schema, [], {}, guidance, evidence, shared=True)
        if version in (workflow_design.VERSION, workflow_design.VERSION_2):
            row = {'key': item_key(provider, version, DESIGN_ENTITY), 'adaptor': provider, 'route': version,
                   'item': DESIGN_ENTITY, 'kind': 'framework-entity', 'anchors': [],
                   'projection': 'not-projected:embedded-workflow',
                   'gaps': [], 'designActions': actions,
                   'contract': {'actions': fingerprint(workflow_authoring._DESIGN_ACTIONS),
                                'source': fingerprint(inspect.getsource(workflow_design.rename_operation))},
                   'evidence': ['schemaxis.workflow_authoring:_DESIGN_ACTIONS', 'schemaxis.workflow_design']}
            for name in DIMENSIONS:
                row[name] = dimension(basis='framework entity: workflow operation instances edited by design actions',
                                      classification='unclassified' if name == 'multiMode' else None)
            row['authoring'] = _authoring('framework-entity', None, {})
            collector.items.append(_compact(row))
            collector.routes[-1]['items'] += 1


def contract_sites(source):
    """Closed-key validator calls ``keys(subject, allowed, location)`` with their enclosing function."""
    tree = ast.parse(source)
    sites, constraints = [], {}
    for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
        for node in ast.walk(function):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'keys'
                    and len(node.args) == 3):
                subject = ast.unparse(node.args[0])
                allowed = node.args[1]
                static = (isinstance(allowed, (ast.Tuple, ast.List))
                          and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in allowed.elts))
                sites.append({'function': function.name, 'subject': subject,
                              'keys': [e.value for e in allowed.elts] if static else None,
                              'dynamic': None if static else ast.unparse(allowed),
                              'location': ast.unparse(node.args[2])})
            if (function.name == '_constraints' and isinstance(node, ast.Dict)
                    and all(isinstance(k, ast.Constant) for k in node.keys)
                    and all(isinstance(v, ast.Tuple) for v in node.values)):
                for kind, allowed in zip(node.keys, node.values):
                    constraints[kind.value] = [e.value for e in allowed.elts if isinstance(e, ast.Constant)]
    return sites, constraints


def _framework(collector, source=None):
    """Template and values contracts: validator-backed rows; no literal schema exists."""
    path = ROOT / TEMPLATE_SOURCE
    source = path.read_text() if source is None else source
    sites, constraints = contract_sites(source)
    tree = ast.parse(source)
    module_contract = fingerprint(ast.dump(tree, include_attributes=False))
    tree_functions = {node.name: ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    found = {}
    for site in sites:
        found.setdefault((site['function'], site['subject']), []).append(site)
    for site_key in sorted(set(found) - set(CONTRACT_SITES)):
        collector.gap(item_key(TEMPLATE_PROVIDER, workflow_templates.TEMPLATE_VERSION, 'route-root'),
                      'contract-site-unmapped', site_key[0] + ' validates ' + site_key[1] + ' with no inventory unit')
    for site_key in sorted(set(CONTRACT_SITES) - set(found)):
        collector.gap(item_key(TEMPLATE_PROVIDER, CONTRACT_SITES[site_key][0], 'route-root'),
                      'contract-site-missing', site_key[0] + ' no longer validates ' + site_key[1])
    routes = {}
    for dynamic_pass in (False, True):
        for site_key, (version, unit, base, dynamic) in sorted(CONTRACT_SITES.items()):
            route = routes.setdefault(version, {'units': {}, 'fields': {}, 'anchors': {}})
            route['anchors'][base] = unit
            for site in found.get(site_key, []):
                route['units'].setdefault(unit, set()).add(site_key[0])
                if dynamic_pass:
                    if dynamic:
                        route['fields'][base] = ('map', fingerprint([site_key, site['location'], site['dynamic']]))
                        route['fields'][base + '/' + dynamic[0]] = (dynamic[1], fingerprint([site_key, site['dynamic']]))
                    continue
                names = site['keys']
                if site_key == ('_constraints', 'constraints'):
                    names = sorted({name for allowed in constraints.values() for name in allowed})
                elif names is None and not dynamic:
                    collector.gap(item_key(TEMPLATE_PROVIDER, version, unit), 'contract-site-dynamic',
                                  site_key[0] + ' validates ' + site_key[1] + ' against ' + str(site['dynamic']))
                for name in names or ():
                    route['fields'][base + '/' + escape(name)] = (
                        CONTRACT_KINDS.get((unit, name), CONTRACT_KINDS.get(name, 'contract-key')),
                        fingerprint([unit, site['location'], name,
                                     constraints if site_key[0] == '_constraints' else None]))
                route['fields'].setdefault(base, ('structure', fingerprint([site_key, site['location']])))
    for version, route in sorted(routes.items()):
        anchors = dict(route['anchors'])
        anchors.setdefault('', 'route-root')
        owned = {}
        for address, (kind, contract) in sorted(route['fields'].items()):
            identity = owner(anchors, address)
            owned.setdefault(identity, []).append(address)
            collector.fields.append((item_key(TEMPLATE_PROVIDER, version, identity), address, kind, 'none', contract))
            if kind in SURFACE_KINDS:
                collector.surfaces.append(_surface(TEMPLATE_PROVIDER, version, identity, address, kind, None, {}))
        functions = sorted({function for units in route['units'].values() for function in units})
        for unit in sorted(set(anchors.values())):
            unit_anchors = sorted(address for address, name in anchors.items() if name == unit)
            row = {'key': item_key(TEMPLATE_PROVIDER, version, unit), 'adaptor': TEMPLATE_PROVIDER, 'route': version,
                   'item': unit, 'kind': 'contract-unit', 'anchors': unit_anchors,
                   'projection': 'not-projected:no-literal-schema', 'gaps': [],
                   'fields': {'owned': len(owned.get(unit, []))},
                   'contract': {'validators': sorted(route['units'].get(unit, set())),
                                'source': fingerprint([tree_functions.get(f, '') for f in sorted(route['units'].get(unit, set()))]),
                                'module': module_contract},
                   'evidence': [TEMPLATE_SOURCE]}
            for name in DIMENSIONS:
                row[name] = dimension(basis='validator-backed contract unit; semantics unassessed',
                                      classification='unclassified' if name == 'multiMode' else None)
            row['authoring'] = _authoring('contract-unit', None, {})
            collector.items.append(_compact(row))
        route_key = item_key(TEMPLATE_PROVIDER, version, 'route-root')
        collector.gap(route_key, 'no-literal-schema', 'contract is enforced by validators; no literal schema is published')
        collector.gap(route_key, 'no-add-catalogue-projection', 'no Studio Add catalogue projects this document')
        authoring = {}
        for surface, binding in sorted(TEMPLATE_ROUTES.items()):
            module, _, name = binding.partition(':')
            text = _module_source(module)
            authoring[surface] = binding if text is not None and name in text else 'missing'
            if authoring[surface] == 'missing':
                collector.gap(route_key, 'authoring-route-missing', binding + ' was not found')
        collector.routes.append({
            'key': item_key(TEMPLATE_PROVIDER, version, '').rstrip('/'), 'adaptor': TEMPLATE_PROVIDER, 'route': version,
            'role': 'framework-contract', 'scope': collector.scope, 'evidence': [TEMPLATE_SOURCE],
            'catalogueItems': 0, 'declarations': 0, 'commands': 0, 'operationItems': 0, 'nestedUnits': 0,
            'fields': len(route['fields']), 'items': len(set(anchors.values())),
            'contract': fingerprint({f: tree_functions.get(f, '') for f in functions}), 'moduleContract': module_contract,
            'validators': functions, 'authoringRoutes': authoring,
            'constraintKeys': constraints if version == workflow_templates.TEMPLATE_VERSION else {},
            'guidance': {}, 'staleGuidance': 0})


def _module_source(module):
    import importlib.util
    spec = importlib.util.find_spec(module)
    if spec is None or not spec.origin or not spec.origin.endswith('.py'):
        return None
    return Path(spec.origin).read_text()


def build(providers=None, *, scope='builtin', ledger=None, root=None, template_source=None):
    """Return the inventory for registered adaptors in ``scope`` (builtin or external)."""
    collector = Collector('builtin' if scope == 'builtin' else 'external-handoff')
    for adaptor in sorted(registry.ADAPTORS):
        source = registry.ADAPTORS[adaptor].get('source', 'builtin')
        if (providers is None or adaptor in providers) and (source == 'builtin') == (scope == 'builtin'):
            _registered(collector, adaptor)
    if scope == 'builtin':
        for provider in SHARED_PROVIDERS:
            if providers is None or provider in providers:
                _shared(collector, provider)
        if providers is None or TEMPLATE_PROVIDER in providers:
            _framework(collector, template_source)
    else:
        for fault in registry.PLUGIN_FAULTS:
            identity = dict(fault.observed or {}).get('id', 'unknown')
            collector.gap(item_key(identity, 'unregistered', 'route-root'), 'plugin-excluded', fault.message)
    applied = apply_ledger(collector, ledger or {'version': LEDGER_VERSION, 'entries': {}}, root)
    return assemble(collector, scope, applied)


def validate_record(record, location):
    """Refuse unknown keys or statuses; not-applicable needs a rationale."""
    if not isinstance(record, dict) or set(record) - RECORD_KEYS:
        raise ValueError(location + ': unknown dimension keys ' + str(sorted(set(record) - RECORD_KEYS)
                                                                        if isinstance(record, dict) else record))
    for name, allowed in STATUSES.items():
        if name in record and record[name] not in allowed:
            raise ValueError(location + ': ' + name + ' must be one of ' + ', '.join(allowed))
    if 'classification' in record and record['classification'] not in CLASSIFICATIONS:
        raise ValueError(location + ': classification must be one of ' + ', '.join(CLASSIFICATIONS))
    for name in LIST_KEYS:
        if name in record and (not isinstance(record[name], list)
                               or any(not isinstance(value, str) or not value.strip() for value in record[name])):
            raise ValueError(location + ': ' + name + ' requires a list of text')
    for name in ('basis', 'rationale', 'current', 'referenceScope', 'disposition', 'choices'):
        if name in record and (not isinstance(record[name], str) or not record[name].strip()):
            raise ValueError(location + ': ' + name + ' requires text')
    if 'entryPoint' in record and (not isinstance(record['entryPoint'], str)
                                   or not re.fullmatch(r'[A-Za-z_][\w.]*:[A-Za-z_]\w*', record['entryPoint'])):
        raise ValueError(location + ': entryPoint requires module:function')
    if record.get('implementation') == 'not-applicable' and not record.get('rationale'):
        raise ValueError(location + ': not-applicable requires a rationale')


def _route_scope(entry, route, location):
    """Ledger implementation or qualification credit must name the exact route it applies to."""
    claims = entry.get('implementation') in CREDIT or entry.get('qualification') in QUALIFIED
    if claims and route not in entry.get('routes', []):
        raise ValueError(location + ': implementation or qualification credit requires routes naming ' + route)
    if 'routes' in entry and route not in entry['routes']:
        raise ValueError(location + ': evidence routes ' + str(entry['routes']) + ' do not include ' + route)


def apply_ledger(collector, ledger, root=None):
    """Overlay reviewed statuses; every ledger key must still exist in discovery."""
    if not isinstance(ledger, dict) or ledger.get('version') != LEDGER_VERSION or set(ledger) != {'version', 'entries'}:
        raise ValueError('ledger requires version ' + LEDGER_VERSION + ' and entries')
    rows = {row['key']: row for row in collector.items}
    rows.update({row['key']: row for row in collector.surfaces})
    applied = 0
    for key, entry in sorted(ledger['entries'].items()):
        if not isinstance(entry, dict) or not entry or set(entry) - set(DIMENSIONS) - {'notes'}:
            raise ValueError(key + ': ledger entries hold dimension records and optional notes')
        if key not in rows:
            raise ValueError(key + ': ledger key is absent from discovery (stale or mistyped)')
        target = rows[key]
        route = split_key(key)[1]
        for name in sorted(set(entry) - {'notes'}):
            if not isinstance(entry[name], dict):
                raise ValueError(key + ' ' + name + ': dimension record must be an object')
            _route_scope(entry[name], route, key + ' ' + name)
            merged = {**target[name], **entry[name]}
            validate_record(merged, key + ' ' + name)
            _paths(merged, root, key + ' ' + name)
            target[name] = merged
        if 'notes' in entry:
            if not isinstance(entry['notes'], str) or not entry['notes'].strip():
                raise ValueError(key + ': notes require text')
            target['notes'] = entry['notes']
        applied += 1
    return applied


def _paths(record, root, location):
    if root is None:
        return
    for name in ('tests', 'evidence'):
        for value in record.get(name, []):
            path = value.split('#', 1)[0].split('::', 1)[0]
            if '/' in path and ':' not in path and not (Path(root) / path).exists():
                raise ValueError(location + ': ' + name + ' path does not exist: ' + path)


def assemble(collector, scope, applied):
    """Sort rows, normalise repeated records and anchor field addresses."""
    items = sorted(collector.items, key=itemgetter('key'))
    surfaces = sorted(collector.surfaces, key=itemgetter('key'))
    index = {row['key']: number for number, row in enumerate(items)}
    keys = [row['key'] for row in items] + [row['key'] for row in surfaces]
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicates:
        raise ValueError('duplicate inventory keys: ' + ', '.join(duplicates[:10]))
    rows = sorted(_anchored(items[index[key]], index[key], address, kind, status, contract)
                  for key, address, kind, status, contract in collector.fields)
    summary = counts(items, rows, surfaces, collector)
    texts = sorted({_text(row[name]) for row in items + surfaces for name in DIMENSIONS})
    records = {text: number for number, text in enumerate(texts)}
    sets = sorted({_text(row['authoring']) for row in items})
    authoring = {text: number for number, text in enumerate(sets)}
    for row in items + surfaces:
        for name in DIMENSIONS:
            row[name] = records[_text(row[name])]
    for row in items:
        row['authoring'] = authoring[_text(row['authoring'])]
    result = {
        'version': VERSION,
        'generator': {'command': COMMAND, 'check': COMMAND + ' --check', 'tool': TOOL,
                      'ledger': LEDGER, 'summary': SUMMARY},
        'scope': _scope(scope),
        'layout': {'keys': 'escaped adaptor/route/item; a surface key appends its RFC 6901 address',
                   'records': 'item and surface dimensions index the shared records table',
                   'authoring': 'item authoring indexes authoringSets: per-surface projection states',
                   'fields': 'address = items[item].anchors[anchor] + suffix; contract fingerprints own keywords',
                   'contract': 'twelve-hex sha256 of canonical content; only schema annotations in keyword '
                               'position and catalogue display prose are removed; literals, declarations, '
                               'operation and field guidance control/authoring/fileExtensions records are '
                               'verbatim; template contracts hash the complete normalized module syntax tree',
                   'guides': 'item guides list each owned field\'s verbatim control and authoring records',
                   'projection': 'projected, schema-enumerated, missing or not-projected:<reason> for the Studio Add '
                                 'catalogue (commands: the onVisit schema enum)'},
        'vocabulary': {'statuses': {name: list(values) for name, values in STATUSES.items()},
                       'classifications': list(CLASSIFICATIONS), 'fieldKinds': list(FIELD_KINDS),
                       'surfaceKinds': list(SURFACE_KINDS), 'dimensions': list(DIMENSIONS),
                       'authoringSurfaces': list(AUTHORING_SURFACES), 'surfaceStates': list(SURFACE_STATES)},
        'counts': summary,
        'ledgerEntries': applied,
        'records': [json.loads(text) for text in texts],
        'authoringSets': [json.loads(text) for text in sets],
        'routes': sorted(collector.routes, key=itemgetter('key')),
        'items': items,
        'fieldColumns': ['item', 'anchor', 'suffix', 'kind', 'guidance', 'contract'],
        'fields': rows,
        'surfaces': surfaces,
        'gaps': sorted(collector.gaps, key=itemgetter('code', 'key', 'detail')),
    }
    result['digest'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


def _text(record):
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def _anchored(item, number, address, kind, status, contract):
    best = None
    for position, anchor in enumerate(item['anchors']):
        if (address == anchor or address.startswith(anchor + '/')) and (
                best is None or len(anchor) > len(item['anchors'][best])):
            best = position
    if best is None:
        raise ValueError(item['key'] + ' owns ' + address + ' outside its anchors')
    return [number, best, address[len(item['anchors'][best]):], kind, status, contract]


def expand_fields(inventory):
    """Yield (item key, address, kind, guidance status, contract fingerprint) for every field row."""
    items = inventory['items']
    for number, anchor, suffix, kind, status, contract in inventory['fields']:
        yield items[number]['key'], items[number]['anchors'][anchor] + suffix, kind, status, contract


def record(inventory, row, name):
    """The full dimension record of an item or surface row."""
    return inventory['records'][row[name]]


def _scope(scope):
    if scope == 'builtin':
        return {'adaptors': 'every built-in registered adaptor, all routes, shared Studio workflow routes and '
                            'validator-backed workflow template and values contracts',
                'plugins': 'excluded: external plugins are owner handoffs inventoried with --external; '
                           'uninstalled plugins are not covered',
                'fields': 'every schema address from studio_guidance.fields (shared routes: owned addresses only); '
                          'contract routes list validator-enforced keys',
                'derived': 'derived statuses state declaration or structural facts; they are not reviews'}
    return {'adaptors': 'installed external plugin adaptors only', 'plugins': 'owner handoffs; not built-in coverage',
            'fields': 'every schema address from studio_guidance.fields',
            'derived': 'derived statuses state declaration or structural facts; they are not reviews'}


def counts(items, rows, surfaces, collector):
    result = {'routes': len(collector.routes), 'adaptors': len({row['adaptor'] for row in collector.routes}),
              'items': len(items), 'fields': len(rows), 'surfaces': len(surfaces), 'gaps': len(collector.gaps),
              'commands': sum(1 for row in items if row['kind'] == 'native-command'),
              'nestedUnits': sum(1 for row in items if row['kind'] in NESTED),
              'itemKinds': dict(sorted(Counter(row['kind'] for row in items).items())),
              'fieldKinds': dict(sorted(Counter(row[3] for row in rows).items())),
              'surfaceKinds': dict(sorted(Counter(row['kind'] for row in surfaces).items())),
              'gapCodes': dict(sorted(Counter(row['code'] for row in collector.gaps).items())),
              'dimensions': {}, 'surfaceRecords': {}}
    for name in DIMENSIONS:
        result['dimensions'][name] = {status: dict(sorted(Counter(row[name][status] for row in items).items()))
                                      for status in STATUSES}
        result['surfaceRecords'][name] = {status: dict(sorted(Counter(row[name][status] for row in surfaces).items()))
                                          for status in STATUSES}
    return result


def render(inventory):
    """Deterministic JSON with one row per line for reviewable diffs."""
    lines = ['{']
    keys = list(inventory)
    for position, key in enumerate(keys):
        value = inventory[key]
        suffix = ',' if position < len(keys) - 1 else ''
        if key in ('routes', 'items', 'fields', 'surfaces', 'gaps', 'records', 'authoringSets') and value:
            lines.append('  ' + json.dumps(key) + ': [')
            for number, row in enumerate(value):
                lines.append('    ' + json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
                             + (',' if number < len(value) - 1 else ''))
            lines.append('  ]' + suffix)
        else:
            lines.append('  ' + json.dumps(key) + ': ' + json.dumps(value, sort_keys=True, ensure_ascii=False) + suffix)
    lines.append('}')
    return '\n'.join(lines) + '\n'


def compare(stored, current, limit=20):
    """Human-readable drift between a stored and a regenerated inventory."""
    problems = []
    if stored.get('version') != current.get('version'):
        problems.append('inventory version differs')
    for name in ('routes', 'items', 'surfaces'):
        before = {row['key'] for row in stored.get(name, [])}
        after = {row['key'] for row in current.get(name, [])}
        for label, keys in (('dropped', before - after), ('new', after - before)):
            if keys:
                problems.append(f'{len(keys)} {label} {name}: ' + ', '.join(sorted(keys)[:limit]))
    before, after = _field_rows(stored), _field_rows(current)
    for label, keys in (('dropped', set(before) - set(after)), ('new', set(after) - set(before))):
        if keys:
            problems.append(f'{len(keys)} {label} fields: ' + ', '.join(sorted(keys)[:limit]))
    changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
    if changed:
        problems.append(f'{len(changed)} changed fields: ' + ', '.join(changed[:limit]))
    if stored.get('counts') != current.get('counts'):
        differing = sorted(key for key in set(stored.get('counts', {})) | set(current.get('counts', {}))
                           if stored.get('counts', {}).get(key) != current.get('counts', {}).get(key))
        problems.append('counts differ: ' + ', '.join(differing))
    for name in ('routes', 'items', 'surfaces', 'gaps'):
        rows = {_identity(row): _expanded(stored, row) for row in stored.get(name, [])}
        differing = sorted(_identity(row) for row in current.get(name, [])
                           if _identity(row) in rows and rows[_identity(row)] != _expanded(current, row))
        if differing:
            problems.append(f'{len(differing)} changed {name}: ' + ', '.join(differing[:limit]))
    if not problems and stored != current:
        problems.append('inventory content differs')
    return problems


def _identity(row):
    return row['key'] if 'code' not in row else row['code'] + ' ' + row['key']


def _expanded(inventory, row):
    result = dict(row)
    for name in DIMENSIONS:
        if isinstance(result.get(name), int) and result[name] < len(inventory.get('records', [])):
            result[name] = inventory['records'][result[name]]
    if isinstance(result.get('authoring'), int) and result['authoring'] < len(inventory.get('authoringSets', [])):
        result['authoring'] = inventory['authoringSets'][result['authoring']]
    return result


def _field_rows(inventory):
    return {key + address: (kind, status, contract) for key, address, kind, status, contract in expand_fields(inventory)}


def load_ledger(root):
    path = Path(root) / LEDGER
    return json.loads(path.read_text()) if path.is_file() else {'version': LEDGER_VERSION, 'entries': {}}


LIMITS = (
    'Derived statuses state declaration or structural facts with their basis. They are not reviews, '
    'and an implemented derived status is not native qualification.',
    'Surface kinds (identity, reference, subset-candidate, path, map) and nested units (members, map entries, '
    'discriminated variants) are structural candidates found from schema shape and field names. A row says '
    'that a unit exists, not that it needs a Name, multi-mode or a subset control; all four dimensions stay '
    'unassessed until audited.',
    'Authoring surfaces record projection facts only: Studio Add from the catalogue, quick rows and Batch '
    'actions from a declared multi-mode policy. Edit, Properties, core, CLI, console and AI behaviour is '
    'unassessed per item; sharing a schema is not evidence of shared behaviour.',
    'Contract fingerprints cover each field\'s own validation keywords together with its guidance control, '
    'authoring and fileExtensions records, declarations, catalogue entries and operation guidance authoring '
    'records. Only schema annotations in keyword position (description, title, $comment, Studio guide '
    'annotations) and catalogue display prose are excluded; literal defaults, constants, enumerations, '
    'declarations and guidance control/authoring/fileExtensions records are verbatim. Field guidance drifts '
    'only through its status, control, authoring and fileExtensions; its explanation, label, units, '
    'defaultMeaning, pitfalls, examples, sources and question are documentation and do not drift.',
    'Admitted identity/reference policy data, its exact route binding and generated port projection are '
    'fingerprinted on routes and applicable items. Policy presence alone grants no implementation, review '
    'or native qualification credit.',
    'Workflow template and values documents have no literal schema. Their rows come from the closed-key '
    'validator calls in workflow_templates.py. Their contract fingerprints the complete normalized module '
    'syntax tree, so any code change in that module, including helpers and constants, requires regeneration.',
    'Shared Studio routes (workflow, workflow-design) inventory only the addresses they own; embedded '
    'adaptor documents are counted on their own routes.',
    'External plugins are owner handoffs. The tracked inventory is built with plugins disabled; '
    'uninstalled plugins are not covered and never inherit built-in statuses.',
    'Generic fallbacks (operation name plus counter) and family rules (folder and file stem) are '
    'recorded as such; they do not count as local-context naming for any member until assessed.',
)


def _ordered(values):
    return [(status, values[status]) for status in STATUSES if status in values]


def _table(header, rows):
    lines = ['| ' + ' | '.join(header) + ' |', '| ' + ' | '.join('---' for _ in header) + ' |']
    lines.extend('| ' + ' | '.join(str(cell) for cell in row) + ' |' for row in rows)
    return lines


def _status_table(values):
    return _table(['Status', 'Values'], [[status, ', '.join(f'{k} {v}' for k, v in sorted(entries.items()))]
                                        for status, entries in _ordered(values)])


def summary(inventory):
    """Deterministic human-readable summary of an assembled inventory."""
    counts_ = inventory['counts']
    records = inventory['records']
    lines = ['# Adaptor authoring coverage inventory', '',
             'Generated by `' + inventory['generator']['command'] + '`; do not edit. Verify with `'
             + inventory['generator']['check'] + '`.', '',
             'Machine-readable rows: [inventory.json](inventory.json). Reviewed statuses: [ledger.json](ledger.json).',
             'Requirements and regression cases: [README.md](README.md).',
             'Inventory digest: `' + inventory['digest'] + '`.', '', '## Scope', '']
    lines.extend('- **' + key + '**: ' + value for key, value in sorted(inventory['scope'].items()))
    lines += ['', '## Totals', '']
    lines += _table(['Measure', 'Count'], [[name, counts_[name]] for name in
                                           ('adaptors', 'routes', 'items', 'nestedUnits', 'commands', 'fields',
                                            'surfaces', 'gaps')]
                    + [['ledger entries', inventory['ledgerEntries']]])
    lines += ['', 'Item kinds: ' + ', '.join(f'{k} {v}' for k, v in counts_['itemKinds'].items()) + '.', '',
              'Field kinds: ' + ', '.join(f'{k} {v}' for k, v in counts_['fieldKinds'].items()) + '.', '',
              '## Dimension statuses (items)', '']
    for name in DIMENSIONS:
        lines += ['### ' + name, ''] + _status_table(counts_['dimensions'][name]) + ['']
    lines += ['## Dimension statuses (field surfaces)', '']
    for name in DIMENSIONS:
        lines += ['### ' + name, ''] + _status_table(counts_['surfaceRecords'][name]) + ['']
    lines += ['## Adaptor progress', '',
              'Counts of items per adaptor whose dimension is not yet assessed or reviewed. '
              '`n/a` counts derived not-applicable rows, each with a recorded rationale.', '']
    rows = []
    for adaptor in sorted({row['adaptor'] for row in inventory['items']}):
        members = [row for row in inventory['items'] if row['adaptor'] == adaptor]
        cells = [adaptor, len(members)]
        for name in DIMENSIONS:
            values = [records[row[name]] for row in members]
            cells.append('{} unassessed, {} implemented, {} n/a, {} reviewed'.format(
                sum(v['assessment'] == 'unassessed' for v in values),
                sum(v['implementation'] == 'implemented' for v in values),
                sum(v['implementation'] == 'not-applicable' for v in values),
                sum(v['review'] == 'accepted' for v in values)))
        rows.append(cells)
    lines += _table(['Adaptor', 'Items', *DIMENSIONS], rows)
    lines += ['', '## Routes', '']
    lines += _table(['Adaptor', 'Route', 'Role', 'Add items', 'Operations', 'Commands', 'Nested units',
                     'Inventory items', 'Fields', 'Guidance', 'Stale guidance'],
                    [[row['adaptor'], row['route'], row['role'], row['catalogueItems'], row['operationItems'],
                      row['commands'], row['nestedUnits'], row['items'], row['fields'],
                      ', '.join(f'{k} {v}' for k, v in row['guidance'].items()), row['staleGuidance']]
                     for row in inventory['routes']])
    lines += ['', '## Native commands', '']
    lines += _table(['Command', 'Native', 'Projection'],
                    [['`' + row['key'] + '`', row['command'].get('native', ''), row['projection']]
                     for row in inventory['items'] if row['kind'] == 'native-command']) \
        if counts_['commands'] else ['None declared.']
    lines += ['', '## Gaps', '']
    if inventory['gaps']:
        lines += _table(['Code', 'Key', 'Detail'], [[row['code'], '`' + row['key'] + '`', row['detail']]
                                                   for row in inventory['gaps']])
    else:
        lines.append('None found.')
    reviewed = [row for row in inventory['items'] + inventory['surfaces']
                if any(records[row[n]]['assessment'] == 'assessed' for n in DIMENSIONS)]
    lines += ['', '## Ledger-assessed rows', '']
    lines += ['- `' + row['key'] + '`' for row in sorted(reviewed, key=itemgetter('key'))] or ['None.']
    lines += ['', '## Limits', '']
    lines += ['- ' + text for text in LIMITS]
    return '\n'.join(lines) + '\n'


def native_modules():
    return sorted(name for name in sys.modules if name.split('.')[0] in NATIVE_ROOTS)


def installed_plugins():
    return sorted({entry.name for entry in registry.plugin_entry_points()})


def native_problems():
    """Native modules present before discovery, refused attempts and anything loaded since."""
    problems = []
    if PRESENT:
        problems.append('native modules were loaded before discovery started: ' + ', '.join(PRESENT))
    if BLOCKER.attempts:
        problems.append('native imports attempted during discovery: ' + ', '.join(sorted(set(BLOCKER.attempts))))
    loaded = sorted(set(native_modules()) - set(PRESENT))
    if loaded:
        problems.append('native modules imported during discovery: ' + ', '.join(loaded))
    return problems


def main(argv=None):
    args = ARGS if argv is None else arguments(argv)
    if BLOCKER not in sys.meta_path or args is None or args != ARGS:
        print('run as a script so the native-import blocker and argument parse precede discovery', file=sys.stderr)
        return 2
    if args.external is None and registry.plugins_enabled():
        print('run as a script so plugins are disabled before discovery', file=sys.stderr)
        return 2
    if args.external is not None and not registry.plugins_enabled():
        print('--external needs plugins, but SCHEMAXIS_ADAPTOR_PLUGINS=' + str(PLUGIN_SETTING)
              + ' disables them; unset it to inventory installed plugins', file=sys.stderr)
        return 2
    problems = native_problems()
    result = None
    if not problems:
        ledger = load_ledger(ROOT) if args.external is None else None
        result = build(scope='builtin' if args.external is None else 'external', ledger=ledger, root=ROOT)
        problems = native_problems()
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 2
    text, summary_text = render(result), summary(result)
    plugins = installed_plugins()
    if args.external is not None:
        Path(args.external).write_text(text)
        print(f"external: {len(plugins)} installed plugin(s) {', '.join(plugins) or '(none)'}; "
              f"{result['counts']['items']} items, {result['counts']['fields']} fields, "
              f"{result['counts']['gaps']} gaps written to {args.external}")
        return 0
    output, summary_path = ROOT / OUTPUT, ROOT / SUMMARY
    if args.check:
        stale = []
        if not output.is_file():
            stale.append('missing ' + OUTPUT)
        else:
            stale.extend(compare(json.loads(output.read_text()), result))
            if not stale and output.read_text() != text:
                stale.append(OUTPUT + ' formatting differs from the generator')
        if not summary_path.is_file() or summary_path.read_text() != summary_text:
            stale.append(SUMMARY + ' is stale')
        for problem in stale:
            print('stale: ' + problem, file=sys.stderr)
        status = 'stale' if stale else 'current'
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
        summary_path.write_text(summary_text)
        stale, status = [], 'written'
    total = result['counts']
    print(f"{status}: {total['adaptors']} adaptors, {total['routes']} routes, {total['items']} items "
          f"({total['nestedUnits']} nested units, {total['commands']} commands), {total['fields']} fields, "
          f"{total['surfaces']} surfaces, {total['gaps']} gaps, {result['ledgerEntries']} ledger entries")
    if plugins:
        print(f"external: {len(plugins)} installed plugin(s) are not covered by the tracked inventory: "
              f"{', '.join(plugins)}; run --external PATH for their owner handoff")
    return 1 if stale else 0


if __name__ == '__main__':
    sys.exit(main())
