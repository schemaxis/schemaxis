# Copyright (C) 2026 David L F Gaden
"""Discover installed adaptor manifests without importing application runtimes.

Built-in adaptors are folders below ``schemaxis.adaptors``. External adaptor
packages are installed distributions that declare an entry point in the
``schemaxis.adaptors`` group: the entry-point name is the adaptor ID and its
value is an importable package containing ``adaptor.json`` with the built-in
layout. Discovery reads only package resources: locating them imports the
package ``__init__`` and nothing else, so plugin ``__init__`` modules must stay
light and free of native imports. Every binding must stay inside the package
that declares it.

Only trusted, operator-installed distributions can contribute adaptors.
Authored input selects registered IDs/versions, never module paths, packages or
external folders. A built-in manifest fault stops loading; a faulty plugin is
excluded with a structured ``INVALID_ADAPTOR`` fault (see ``PLUGIN_FAULTS``)
so the built-ins remain usable and the fault stays visible in ``discover``.
Set ``SCHEMAXIS_ADAPTOR_PLUGINS=off`` to load built-ins only.

Plugins may not claim framework identities (``FRAMEWORK_IDS``,
``FRAMEWORK_DOCUMENTS``, ``FRAMEWORK_SECTIONS``), document versions in another
adaptor's ``schemaxis.`` namespace, or command-line flags and destinations that
the framework or another adaptor already owns. A plugin binding that fails when
first used is excluded the same way (see ``exclude_plugin``).

Inside a native runtime archive the registry reads the host's admitted plugin
list (``RUNTIME_PLUGINS``) instead of the interpreter's installed metadata, so
an application's embedded Python sees exactly the plugins the host bundled.
"""
import copy
import json
import os
import re
import warnings
from importlib import import_module
from importlib.resources import files
from types import SimpleNamespace
from schemaxis.core.faults import Fault, SchemaxisError
from schemaxis.errors import fail

GROUP = 'schemaxis.adaptors'
BUILTIN = 'schemaxis.adaptors'
_PACKAGE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*')
_COLOUR = re.compile(r'#[0-9a-fA-F]{6}')
_BINDING_KEYS = ('registerFunctions', 'runtimeSchema', 'coverage', 'liveGraph', 'optionSchema',
                 'capabilities', 'studioCatalogue', 'studioInspect', 'liveModule', 'documentValidation')
_FLAG = re.compile(r'--[a-z0-9][a-z0-9-]*')
RUNTIME_PLUGINS = 'runtime-plugins.json'

# Identities the console, schema and workflow code handle specially. Plugins
# may not claim them; FRAMEWORK_DOCUMENTS reserves every version of each stem.
FRAMEWORK_IDS = frozenset({'workflow', 'workflow-design'})
FRAMEWORK_SECTIONS = frozenset({'camera', 'series', 'workflow', 'execution', 'operation-execution',
                                'composition', 'analytic'})
FRAMEWORK_DOCUMENTS = frozenset('schemaxis.' + stem for stem in (
    'workflow', 'workflow-design', 'workflow-template', 'workflow-values', 'study', 'plan', 'reference',
    'resource', 'views', 'agent', 'feedback', 'observation', 'output-naming', 'capabilities', 'readiness',
    'artifact-metadata', 'adaptor-delivery', 'adaptor-execution', 'adaptor-qualification',
    'studio-adaptor', 'studio-guidance', 'studio-settings', 'schema-snapshot', 'schema-bundle',
    'schema-index', 'storage-policy', 'storage-plan', 'storage-bundle'))
# Options that the run, inspect and console parsers define themselves.
FRAMEWORK_FLAGS = frozenset({'-h', '--help', '--input-format', '--output-directory', '--executable',
                             '--timeout', '--resume', '--node', '--visit', '--provider', '--workspace',
                             '--web', '--port', '--command'})
FRAMEWORK_DESTS = frozenset({'help', 'command', 'input', 'input_format', 'output_directory', 'executable',
                             'timeout', 'resume', 'node', 'visit', 'provider', 'workspace', 'web', 'port',
                             'console_commands'})


class AdaptorPluginWarning(UserWarning):
    """An installed external adaptor package was excluded from the registry."""


def plugins_enabled():
    return os.environ.get('SCHEMAXIS_ADAPTOR_PLUGINS', '').strip().lower() not in ('0', 'off', 'false', 'no')


def _runtime_archive():
    """True when this module was imported from a host-built runtime archive."""
    from zipimport import zipimporter
    return isinstance(getattr(__spec__, 'loader', None), zipimporter)


def bundled_entry_points():
    """Entry points the host recorded in a runtime archive, or ``None`` outside one.

    Only the host writes this list, beside the archived core it trusts; authored
    input never reaches it. It is read only when the core runs from the archive.
    """
    if not _runtime_archive():
        return None
    resource = files(BUILTIN).joinpath(RUNTIME_PLUGINS)
    if not resource.is_file():
        return []
    return [SimpleNamespace(name=p['id'], value=p['package'], group=GROUP,
                            dist=SimpleNamespace(name=p['distribution']))
            for p in json.loads(resource.read_text())['plugins']]


def plugin_entry_points():
    """Installed ``schemaxis.adaptors`` entry points (Python 3.10+ selection)."""
    bundled = bundled_entry_points()
    if bundled is not None:
        return bundled
    from importlib.metadata import entry_points
    return list(entry_points(group=GROUP))


def _distribution(entry):
    dist = getattr(entry, 'dist', None)
    name = getattr(dist, 'name', None) if dist is not None else None
    if not name and dist is not None:
        name = getattr(dist, 'metadata', {}).get('Name')
    return name or 'unknown'


def _claimant(owner):
    return 'the framework' if owner is None else 'adaptor ' + repr(owner)


def _cli(item, identity, cli):
    """Validate ``cliOptions``; return the flags and names this adaptor would claim.

    Flags and argparse destinations share one parser per command and one
    location namespace with adaptor IDs, so neither may be claimed twice.
    """
    options = item.get('cliOptions', [])
    if not isinstance(options, list): raise ValueError('cliOptions must be an array')
    flags, names, dests = {}, {identity: identity}, set()
    for option in options:
        if (not isinstance(option, dict) or set(option) - {'flag', 'dest', 'help', 'action'}
                or not isinstance(option.get('flag'), str) or not _FLAG.fullmatch(option['flag'])
                or not isinstance(option.get('dest'), str) or not option['dest'].isidentifier()
                or not isinstance(option.get('help'), str)
                or option.get('action', 'store') not in ('store', 'append')):
            raise ValueError('cliOptions require flag (--name), identifier dest, help and optional '
                             'action store or append')
        if option['flag'] in flags or option['dest'] in dests:
            raise ValueError('cliOptions repeat ' + option['flag'] + ' or its dest')
        flags[option['flag']] = identity
        dests.add(option['dest'])
        names[option['dest']] = identity
    for flag in flags:
        if flag in cli['flags']:
            raise ValueError('cliOptions flag ' + flag + ' collides with ' + _claimant(cli['flags'][flag]))
    for name in names:
        if name in cli['names'] and cli['names'][name] != identity:
            raise ValueError('adaptor ID or cliOptions dest ' + repr(name) + ' collides with ' +
                             _claimant(cli['names'][name]))
    return flags, names


def _reserved(item, identity, folders):
    """Plugins may not claim framework identities or another adaptor's namespace."""
    if identity in FRAMEWORK_IDS or identity in folders:
        raise ValueError('adaptor ID ' + repr(identity) + ' is reserved by the framework')
    own = re.compile(r'schemaxis\.' + re.escape(identity) + r'(\.[A-Za-z0-9_-]+)*/.+')
    for version, route in item['routes'].items():
        stem = version.partition('/')[0]
        if stem in FRAMEWORK_DOCUMENTS or version.startswith('schemaxis.workflow'):
            raise ValueError('document version ' + repr(version) + ' is reserved by the framework')
        if re.match(r'schemaxis[./]', version) and not own.fullmatch(version):
            raise ValueError('document version ' + repr(version) + ' is outside schemaxis.' + identity)
        name = route.get('schemaName', identity)
        if name in FRAMEWORK_SECTIONS | FRAMEWORK_IDS:
            raise ValueError('schemaName ' + repr(name) + ' is reserved by the framework')
    for section in item.get('sections', {}):
        if section in FRAMEWORK_SECTIONS | FRAMEWORK_IDS:
            raise ValueError('schema section ' + repr(section) + ' is reserved by the framework')
    packages = item.get('runtimePackages', [])
    if not isinstance(packages, list) or any(not isinstance(p, str) or not _PACKAGE.fullmatch(p) for p in packages):
        raise ValueError('runtimePackages must be an array of package names')


def _admit(item, identity, prefix, claims, folders=None):
    """Validate one manifest; return what it would claim (``folders`` marks a plugin)."""
    versions, sections = claims['versions'], claims['sections']
    if not isinstance(item, dict): raise TypeError('adaptor.json must contain an object')
    if item['id'] != identity or not isinstance(identity, str) or not identity.isidentifier():
        raise ValueError('adaptor ID must be unique and match its folder or entry point')
    item.setdefault('adaptor', prefix + 'adaptor')
    item.setdefault('declarations', item['adaptor'] + ':DECLARATIONS')
    item.setdefault('runtimeFamily', 'unspecified')
    item.setdefault('executables', [])
    item.setdefault('keywords', [])
    item.setdefault('execution', 'adaptor-defined execution')
    if not isinstance(item['version'], str): raise ValueError('version must be a string')
    for key in ('executables', 'keywords'):
        if not isinstance(item[key], list) or any(not isinstance(v, str) for v in item[key]):
            raise ValueError(key + ' must be an array of strings')
    if 'display' in item:
        display = item['display']
        if (not isinstance(display, dict) or set(display) - {'name', 'mark', 'colour'}
                or not isinstance(display.get('name'), str) or not 0 < len(display['name'].strip()) <= 64
                or not isinstance(display.get('mark', 'xx'), str) or not 0 < len(display.get('mark', 'xx').strip()) <= 3
                or not isinstance(display.get('colour', '#000000'), str)
                or not _COLOUR.fullmatch(display.get('colour', '#000000'))):
            raise ValueError('display requires name (1-64 characters), optional mark (1-3) and colour #rrggbb')
    bindings = [item['adaptor'], item['declarations']]
    bindings.extend(item[k] for k in _BINDING_KEYS if k in item)
    for key in ('sections', 'consoleHooks', 'referenceSettings'):
        if not isinstance(item.get(key, {}), dict): raise ValueError(key + ' must be an object')
        bindings.extend(item.get(key, {}).values())
    if not isinstance(item['routes'], dict) or item['version'] not in item['routes']:
        raise ValueError('primary version must have a route')
    claimed = set()
    for version, route in item['routes'].items():
        if not isinstance(version, str) or version in versions or version in claimed:
            raise ValueError('document versions must be unique strings')
        if not isinstance(route, dict) or not isinstance(route.get('module'), str) or not isinstance(route.get('schema'), str):
            raise ValueError('routes require module and schema bindings')
        if not isinstance(route.get('hooks', {}), dict): raise ValueError('route hooks must be an object')
        if not isinstance(route.get('schemaName', identity), str): raise ValueError('schemaName must be a string')
        route.setdefault('compose', True)
        route.setdefault('workflow', True)
        route.setdefault('scheduled', True)
        bindings.extend([route['module'], route['schema'], *route.get('hooks', {}).values()])
        for flag in ('workflow', 'scheduled', 'compose', 'graph', 'timeBatches', 'graphEditing'):
            if flag in route and type(route[flag]) is not bool: raise ValueError(flag + ' must be boolean')
        claimed.add(version)
    # Sections and route schema names share the schema export namespace.
    owned = set(item.get('sections', {})) | {r.get('schemaName', identity) for r in item['routes'].values()}
    if owned & sections: raise ValueError('schema sections must be unique')
    if any(not isinstance(path, str) or not path.startswith(prefix) for path in bindings):
        raise ValueError('bindings must belong to the adaptor package ' + prefix[:-1])
    if folders is not None:
        _reserved(item, identity, folders)
    flags, names = _cli(item, identity, claims)
    return {'versions': claimed, 'sections': owned, 'flags': flags, 'names': names}


def _claim(claims, claimed):
    for key, value in claimed.items():
        claims[key].update(value)


def _plugin_fault(message, location, recovery, **observed):
    return Fault('INVALID_ADAPTOR', message, location, 'discovery', observed=observed, recovery=recovery)


def _plugins(entries, result, claims, folders=frozenset()):
    """Admit external adaptor packages; return faults for the excluded ones."""
    faults, candidates = [], {}
    seen = set()
    for entry in entries:
        key = (entry.name, entry.value, _distribution(entry))
        if key not in seen:
            seen.add(key)
            candidates.setdefault(entry.name, []).append(entry)
    for identity in sorted(candidates):
        entries = candidates[identity]
        sources = sorted('plugin:' + _distribution(e) for e in entries)
        location = 'entry point ' + GROUP + ':' + identity
        if identity in result:
            faults.append(_plugin_fault('adaptor ID collides with the ' + result[identity]['source'] + ' adaptor',
                location, 'Rename the plugin adaptor or uninstall one distribution.',
                id=identity, sources=[result[identity]['source'], *sources]))
            continue
        if len(entries) > 1:
            faults.append(_plugin_fault('adaptor ID is claimed by more than one installed plugin', location,
                'Uninstall all but one distribution that provides this adaptor ID.', id=identity, sources=sources))
            continue
        entry, source = entries[0], sources[0]
        package = entry.value.strip()
        try:
            if not identity.isidentifier():
                raise ValueError('entry-point name must be a valid adaptor ID')
            if not _PACKAGE.fullmatch(package) or package == 'schemaxis' or package.startswith('schemaxis.'):
                raise ValueError('entry-point value must name an importable package outside schemaxis')
            try:
                manifest = files(package).joinpath('adaptor.json')
                item = json.loads(manifest.read_text())
            except (ImportError, OSError, TypeError) as error:
                raise ValueError('package resources unavailable: ' + str(error)) from error
            if not isinstance(item, dict) or item.get('id') != identity:
                raise ValueError('entry-point name ' + repr(identity) + ' does not match manifest id ' +
                                 repr(item.get('id') if isinstance(item, dict) else None))
            if item.get('default') or item.get('defaultConsole'):
                raise ValueError('plugins may not claim the default or defaultConsole provider')
            claimed = _admit(item, identity, package + '.', claims, folders)
        except (KeyError, TypeError, ValueError) as error:
            faults.append(_plugin_fault(str(error), location,
                'Repair or uninstall the distribution; built-in adaptors remain available.',
                id=identity, package=package, sources=[source]))
            continue
        except Exception as error:  # an import-time failure in the plugin's __init__
            faults.append(_plugin_fault('plugin package failed to load: ' + type(error).__name__ + ': ' + str(error),
                location, 'Keep the plugin __init__ light; repair or uninstall the distribution.',
                id=identity, package=package, sources=[source]))
            continue
        item['package'], item['source'] = package, source
        _claim(claims, claimed)
        result[identity] = item
    return faults


def load_registry(root=None, *, plugins=None, strict=False, faults=None):
    """Built-ins from ``root`` (default ``schemaxis.adaptors``) plus plugin entry points.

    ``plugins`` overrides the installed entry points (tests pass a list). With
    ``strict`` the first plugin fault is raised; otherwise faulty plugins are
    excluded and their faults appended to ``faults``.
    """
    root = files(BUILTIN) if root is None else root
    result = {}
    claims = {'versions': set(), 'sections': set(),
              'flags': dict.fromkeys(FRAMEWORK_FLAGS), 'names': dict.fromkeys(FRAMEWORK_DESTS)}
    folders = set()
    for folder in sorted(root.iterdir(), key=lambda p: p.name):
        manifest = folder.joinpath('adaptor.json')
        # A folder reserves its name only if it holds package content; a stale
        # __pycache__ left behind by a removed built-in reserves nothing.
        if folder.is_dir() and any(child.name != '__pycache__' for child in folder.iterdir()):
            folders.add(folder.name)
        if not folder.is_dir() or not manifest.is_file():
            continue
        try:
            item = json.loads(manifest.read_text())
            identity = item['id']
            if identity != folder.name or identity in result:
                raise ValueError('adaptor ID must be unique and match its folder')
            _claim(claims, _admit(item, identity, BUILTIN + '.' + identity + '.', claims))
            item['package'], item['source'] = BUILTIN + '.' + identity, 'builtin'
            result[identity] = item
        except (KeyError, TypeError, ValueError) as error:
            fail('INVALID_ADAPTOR', str(error), str(manifest))
    for flag in ('default', 'defaultConsole'):
        if sum(bool(m.get(flag)) for m in result.values()) > 1:
            fail('INVALID_ADAPTOR', 'multiple adaptors claim ' + flag)
    if plugins is None:
        plugins = plugin_entry_points() if plugins_enabled() else []
    found = _plugins(plugins, result, claims, frozenset(folders))
    if found and strict:
        raise SchemaxisError(found[0])
    if faults is not None:
        faults.extend(found)
    return result


def _load():
    found = []
    registry = load_registry(faults=found)
    for fault in found:
        warnings.warn(fault.location + ': ' + fault.message + ' (excluded)', AdaptorPluginWarning, stacklevel=2)
    return registry, found


ADAPTORS, PLUGIN_FAULTS = _load()
_EXCLUDED = {}


def exclude_plugin(provider, error):
    """Exclude a plugin whose binding failed after admission; return its fault.

    Admission reads manifests only, so a missing module or attribute surfaces
    when a binding is first resolved. The plugin is then removed from
    ``ADAPTORS`` and its fault joins ``PLUGIN_FAULTS``. Returns ``None`` for a
    built-in or unknown provider, whose errors must propagate.
    """
    if provider in _EXCLUDED:
        return _EXCLUDED[provider]
    item = ADAPTORS.get(provider)
    if item is None or item.get('source', 'builtin') == 'builtin':
        return None
    detail = error.fault.message if isinstance(error, SchemaxisError) else str(error)
    fault = _plugin_fault('plugin binding failed: ' + type(error).__name__ + ': ' + detail,
        'entry point ' + GROUP + ':' + provider,
        'Repair or uninstall the distribution; built-in adaptors remain available.',
        id=provider, package=item['package'], sources=[item['source']])
    _EXCLUDED[provider] = fault
    ADAPTORS.pop(provider, None)
    PLUGIN_FAULTS.append(fault)
    warnings.warn(fault.location + ': ' + fault.message + ' (excluded)', AdaptorPluginWarning, stacklevel=3)
    return fault


def isolated(provider, call, *args, **kwargs):
    """``(result, None)``, or ``(None, fault)`` after excluding a failing plugin."""
    try:
        return call(*args, **kwargs), None
    except Exception as error:
        fault = exclude_plugin(provider, error)
        if fault is None:
            raise
        return None, fault


def binding(path):
    module, separator, name = path.partition(':')
    if not separator: fail('INVALID_ADAPTOR', 'binding requires module:attribute', path)
    return getattr(import_module(module), name)


def default_provider(console=False):
    key = 'defaultConsole' if console else 'default'
    return next((name for name, item in ADAPTORS.items() if item.get(key)), next(iter(ADAPTORS), None))


def metadata(provider=None):
    provider = provider or default_provider()
    if not isinstance(provider, str) or provider not in ADAPTORS:
        fail('UNKNOWN_PROVIDER', 'choose a registered provider', providers=sorted(ADAPTORS))
    return ADAPTORS[provider]


def adaptor_package(provider):
    """Importable package that owns a registered adaptor's modules and resources."""
    return metadata(provider).get('package', BUILTIN + '.' + provider)


def adaptor_files(provider):
    """Resource folder for an adaptor without importing its runtime modules.

    Built-in folders (including the unregistered ``workflow`` guidance folders)
    stay below ``schemaxis.adaptors``; plugins resolve to their own package.
    """
    item = ADAPTORS.get(provider) if isinstance(provider, str) else None
    if item is not None and item.get('source', 'builtin') != 'builtin':
        return files(item['package'])
    if not isinstance(provider, str) or not re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_-]*', provider):
        fail('UNKNOWN_PROVIDER', 'choose a registered provider', providers=sorted(ADAPTORS))
    return files(BUILTIN).joinpath(provider)


def adaptor_source(provider, name=''):
    """Human-readable source label for audits: a repository path or package path."""
    item = ADAPTORS.get(provider)
    if item is not None and item.get('source', 'builtin') != 'builtin':
        return item['package'].replace('.', '/') + '/' + name
    return 'src/schemaxis/adaptors/' + provider + '/' + name


def routes():
    """Built-in routes first so their schema positions do not move when plugins are installed."""
    entries = [(version, (name, route)) for name, item in ADAPTORS.items()
               for version, route in item.get('routes', {item['version']: {'module': item['adaptor']}}).items()]
    def order(entry):
        plugin = ADAPTORS.get(entry[1][0], {}).get('source', 'builtin') != 'builtin'
        return (plugin, entry[1][1].get('schemaOrder', 100), entry[0])
    return dict(sorted(entries, key=order))


def resolve(document, *, legacy=False):
    if not isinstance(document, dict): fail('INVALID_DOCUMENT', 'document must be an object')
    version = document.get('version')
    if legacy and 'version' not in document:
        version = metadata()['version']
    found = routes().get(version) if isinstance(version, str) else None
    if found is None: fail('UNSUPPORTED_VERSION', 'document version has no registered adaptor', version=str(version))
    return found


def route_hook(document, name, *, required=False, legacy=False):
    provider, route = resolve(document, legacy=legacy)
    path = route.get('hooks', {}).get(name)
    if path: return binding(path)
    if required: fail('UNSUPPORTED_CAPABILITY', 'adaptor does not implement ' + name, provider)
    return None


def declarations(adaptor):
    item = metadata(adaptor)
    try:
        value = binding(item['declarations'])
        value = value() if callable(value) else value
    except Exception as error:
        fault = exclude_plugin(adaptor, error)
        if fault is None:
            raise
        raise SchemaxisError(fault) from error
    return copy.deepcopy(value)


def plan(document, *, raw=False, legacy=False):
    from schemaxis.unfilled import reject_unfilled
    reject_unfilled(document)
    _, route = resolve(document, legacy=legacy)
    def native(value):
        module = import_module(route['module'])
        result = vars(module).get('_native_plan', module.plan)(value)
        return result if raw or 'planIndex' not in route else result[route['planIndex']]
    from schemaxis.adaptor_runtime import plan as prepare
    return prepare(document, route, native)


def run(document, directory, *, locations=None, timeout=300, **legacy_locations):
    from schemaxis.unfilled import reject_unfilled
    reject_unfilled(document)
    provider, route = resolve(document, legacy=True)
    from schemaxis.configuration import locations as configured_locations
    locations = configured_locations({**legacy_locations, **(locations or {})})
    item = metadata(provider)
    location = locations.get(provider, locations.get('roots') if item.get('locationKind') == 'roots' else None)
    options = {'roots': location} if item.get('locationKind') == 'roots' else {'executable': location}
    options.update({key: locations.get(value) for key, value in route.get('runOptions', {}).items()})
    from schemaxis.adaptor_runtime import execute
    module = import_module(route['module'])
    return execute(document, directory, route, vars(module).get('_native_run', module.run), _verify_native,
                   vars(module).get('_native_plan', module.plan), timeout=timeout, **options)


def verify(directory, document=None):
    from pathlib import Path
    directory = Path(directory)
    from schemaxis.schema_snapshots import verify_run
    verify_run(directory)
    document = json.loads((directory/'authored.json').read_text()) if document is None else document
    _, route = resolve(document, legacy=True)
    from schemaxis.adaptor_runtime import is_common, verify as verify_common
    if is_common(directory):
        return verify_common(directory, document, route, _verify_native)
    path = route.get('hooks', {}).get('verify')
    module = import_module(route['module'])
    function = binding(path) if path else vars(module).get('_native_verify', module.verify)
    result = function(directory)
    from schemaxis.publication_metadata import verify as verify_metadata
    verify_metadata(directory)
    return result


def _verify_native(directory, document):
    from pathlib import Path
    directory = Path(directory)
    from schemaxis.schema_snapshots import verify_run
    verify_run(directory)
    if json.loads((directory/'authored.json').read_text()) != document:
        fail('VERIFICATION_FAILED', 'native input differs from the resolved visit', str(directory))
    hook = route_hook(document, 'verifyAttempt', legacy=True)
    if hook:
        return hook(directory, document)
    _, route = resolve(document, legacy=True)
    path = route.get('hooks', {}).get('verify')
    module = import_module(route['module'])
    return (binding(path) if path else vars(module).get('_native_verify', module.verify))(directory)


def discover():
    providers = []
    for name, item in list(ADAPTORS.items()):
        operations, fault = isolated(name, declarations, name)
        if fault is not None:
            continue
        providers.append({'id': name, 'documentVersion': item['version'],
            'authoring': {'documentReferences': True, 'valueFunctions': True, 'expressions': True,
                          'analytics': True, 'operationValues': True},
            'runtimeFamily': item['runtimeFamily'], 'scope': item['execution'],
            'operations': sorted(operations), 'keywords': item['keywords'],
            'executables': item['executables'], 'availability': 'not checked',
            'source': item.get('source', 'builtin'),
            'additionalDocumentVersions': [v for v in item['routes'] if v != item['version']],
            'consoleCapabilities': copy.deepcopy(item.get('consoleCapabilities', {})),
            'executionCapabilities': copy.deepcopy(item.get('executionCapabilities', {})),
            'schema': 'docs/generated/'+name+'.schema.json',
            'reference': 'docs/generated/'+name+'-operations.md'})
    result = {'providers': providers}
    if PLUGIN_FAULTS:
        result['pluginFaults'] = [fault.to_dict() for fault in PLUGIN_FAULTS]
    return result


def query(document=None, operations=None):
    from schemaxis.schema import expand_input
    from schemaxis.parallel import provisional
    required, flags, selected = {}, {}, {}
    if document is not None:
        if not isinstance(document, dict): fail('INVALID_DOCUMENT', 'query requires an object')
        if document.get('version') == 'schemaxis.workflow/1':
            from schemaxis.workflow import validate
            pipelines = [entry['document'] for entry in validate(document)]
        else: pipelines = [document]
        for pipeline in pipelines:
            provider, route = resolve(pipeline)
            selected[provider] = route
            hook = route_hook(pipeline, 'query')
            if hook:
                names, extra = hook(pipeline)
            elif route.get('graphEditing', True) is False:
                plan(provisional(pipeline))
                names, extra = [], route.get('queryFlags', {})
            else:
                expanded = expand_input(pipeline) if route.get('graph') else plan(provisional(pipeline))
                nodes = expanded.get('nodes', [])
                if not isinstance(nodes, list) or any(not isinstance(n, dict) or not isinstance(n.get('filter'), str) for n in nodes):
                    fail('INVALID_DOCUMENT', 'nodes require declared filter names')
                names, extra = [n['filter'] for n in nodes], {}
            required.setdefault(provider, set()).update(names)
            flags.setdefault(provider, {}).update(extra)
    else:
        if not operations: fail('MISSING_ARGUMENT', 'provide an input file or --operations')
        catalogues = {p: isolated(p, declarations, p)[0] for p in list(ADAPTORS)}
        required = {p: set(operations) for p, found in catalogues.items()
                    if found is not None and set(operations) <= set(found)}
    reports = []
    for provider, names in required.items():
        item, route = ADAPTORS[provider], selected.get(provider, {})
        reports.append({'adaptor': provider, 'operations': sorted(names),
            'unsupportedOperations': sorted(names-set(declarations(provider))),
            'savedSceneRendering': False, 'fixedAssemblies': False, **flags.get(provider, {}),
            'executables': item['executables'], 'availability': 'not checked', 'execution': item['execution'],
            'schema': route.get('querySchema', 'docs/generated/'+provider+'.schema.json'),
            'reference': route.get('queryReference', 'docs/generated/'+provider+'-operations.md')})
    return {'supported': bool(reports) and not any(r['unsupportedOperations'] for r in reports),
        'adaptors': reports, 'scope': 'declared requirements only; installation, graph validity and native results are not certified',
        'nextSteps': ['schemaxis schema --expand INPUT', 'schemaxis run INPUT --output-directory NEW_DIRECTORY']}
