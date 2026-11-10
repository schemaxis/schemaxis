"""Host-side policy and verification for editable ParaView state bundles.

A scene may request ``"stateBundle": true``. Before any publication consumes the
visit, the native run captures each reader file with the shared bounded
``workflow_resources.capture`` foundation into ``data/<node>/`` of the bundle and
rebinds the reader to that pinned copy, so images and the saved state consume the
same bytes. The state (.pvsm) and a manifest pinning each captured
``resource.json`` are saved after the image. A separate, freshly started pvbatch
process then loads a relocated copy of the bundle with the original bundle
withheld (see ``reload``). Host verification rechecks bundle membership with a
bounded no-follow inventory before reading anything, revalidates each pinned
capture, and compares the retained reload evidence with the planned pipeline,
declared property readback, observations, appearance, colour legend, view size,
view time and camera. Nothing here imports ParaView.

This first slice is deliberately narrow: one scene, one visit, one appearance
and one image camera; generator sources, ordinary filters without file options
and the self-contained readers below. Authored input cannot load a state file:
the only LoadState call is the internal reload of this run's own bundle.
Concurrent-change detection matches ``workflow_resources``: ordinary changes are
detected; this is not a sandbox against an adversary replacing ancestors.
"""
import hashlib
import json
import math
import os
import re
import shutil
import stat
from pathlib import Path, PurePosixPath

from schemaxis import workflow_resources as resources
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail
from schemaxis.pipeline import markers

VERSION = 'schemaxis.paraview.state-bundle/2'
RELOAD_VERSION = 'schemaxis.paraview.state-bundle.reload/2'
STATE = 'state.pvsm'
MANIFEST = 'bundle.json'
DATA = 'data'
RESOURCE = 'resource.json'
# Self-contained readers open only the selected file; see integration._SELF_CONTAINED.
READERS = {'readSurface': 'FileName', 'readUnstructuredGrid': 'FileName', 'readImageData': 'FileName',
           'readStructuredGrid': 'FileName', 'readRectilinearGrid': 'FileName',
           'readSTL': 'FileNames', 'readPLY': 'FileNames'}
XML_READERS = {'readSurface': '.vtp', 'readUnstructuredGrid': '.vtu', 'readImageData': '.vti',
               'readStructuredGrid': '.vts', 'readRectilinearGrid': '.vtr'}
LIMITS = {'files': 16, 'fileBytes': 64 << 20, 'totalBytes': 256 << 20, 'stateBytes': 16 << 20,
          'manifestBytes': 4 << 20, 'proofBytes': 4 << 20, 'entries': 128, 'depth': 4, 'propertyValues': 4096}
TOLERANCE = 1e-9
SCOPE = ('one scene, one visit (one time, no axes), one appearance and one image camera; serial pvbatch only; '
         'generator sources, filters without file options and self-contained readers ' + ', '.join(sorted(READERS)))
PROOF_SCOPE = ('fresh-process readback of reader file-list-domain properties, pipeline objects and connections, '
               'the native properties bound to authored options, dataset observations, display colouring, '
               'representation and opacity, scalar lookup-table points/log scale, legend visibility/title, '
               'view size, view time and camera; other ParaView properties are saved but not independently compared')
LOSSES = ['units and coordinate frames are unknown; they are not inferred from the data',
          'only the declared visit is retained; animation, other times and other scenes are not',
          'the state is ParaView-version specific; it is verified only with the observed runtime',
          'copied datasets are the consumed files; the originating application project is not included']
GUI_STEPS = ['Copy or move the whole bundle directory; keep state.pvsm, bundle.json and data/ together.',
             'In ParaView choose File > Load State... and select state.pvsm.',
             'In the Load State Options dialog set Load State Data File Options to "Search files under specified '
             'directory", set Data Directory to the bundle\'s data/ folder and tick "Only Use Files In Data '
             'Directory".',
             'ParaView then lists each relocated reader under its file name (for example plate.vtp) in the '
             'Pipeline Browser; filters keep their node ids, and every object remains editable.',
             'The default "Use File Names From State" reads the absolute paths recorded at save time, which no '
             'longer name the bundle after it moves; other ways of opening state.pvsm are not verified.',
             'Verification loads the bundle with the same LoadStateOptions settings through pvbatch '
             '(paraview.simple.LoadState); the GUI dialog itself is not exercised.']
_HEX = re.compile('[0-9a-f]{64}')
_NODE = re.compile('[A-Za-z][A-Za-z0-9_-]{0,127}')
_PROPERTY = re.compile('[A-Za-z][A-Za-z0-9_]{0,127}')


def _bad(message, location, **details):
    fail('VERIFICATION_FAILED', message, str(location), **details)


def _hash(path):
    """Digest of a file this process just wrote; never used on bundle input under verification."""
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _resource_fault(error, location):
    _bad('bounded resource check failed: ' + error.fault.message, location, cause=error.fault.code,
         at=error.fault.location)


def validate(master, scenes):
    """Refuse requests outside the supported bounded slice during host planning."""
    requested = [index for index, scene in enumerate(scenes) if scene.get('stateBundle')]
    if not requested:
        return
    location = f'$.scenes[{requested[0]}].stateBundle'
    def refuse(message, **details):
        fail('UNSUPPORTED_STATE_BUNDLE', message, location, scope=SCOPE, **details)
    if len(scenes) != 1:
        refuse('an editable state bundle requires exactly one scene', scenes=len(scenes))
    scene = scenes[0]
    if len(master.times) != 1 or scene['selection']['states'] != 1:
        refuse('an editable state bundle retains exactly one visit; remove axes and select one time',
               visits=scene['selection']['states'], times=len(master.times))
    if len(scene['appearances']) != 1:
        refuse('an editable state bundle retains exactly one appearance', appearances=len(scene['appearances']))
    if len(scene['images']) != 1 or len(scene['images'][0]['cameras']) != 1:
        refuse('an editable state bundle needs exactly one image writer with one camera; '
               'that camera and image verify the saved view')
    if scene.get('text'):
        refuse('text annotations are not retained in editable state bundles yet', nodes=scene['text'])
    if scene['gltf'] or scene.get('exports'):
        refuse('combine an editable state bundle only with images, geometry and measurements')
    order = scene['selection']['order']
    readers = 0
    for node in order:
        declaration = master.declarations[master.nodes[node]['filter']]
        filter_id = declaration['id']
        if declaration.get('nativeDependencies'):
            refuse('plugins and generated native dependencies are not bundled', node=node)
        if declaration.get('role') == 'resource' or 'data' not in declaration.get('kinds', ['data']):
            refuse('native resources are not supported in editable state bundles', node=node)
        if master.nodes[node].get('onVisit'):
            refuse('native visit commands are not supported in editable state bundles', node=node)
        options = master.nodes[node]['options']
        if list(markers(options)):
            refuse('dynamic option values are not supported in editable state bundles', node=node)
        named = [key for key in declaration['options']
                 if any(token in key.lower() for token in ('file', 'path', 'directory'))]
        if filter_id in READERS:
            readers += 1
            if named != ['files'] or not isinstance(options.get('files'), list) or len(options['files']) != 1:
                refuse('a bundled reader needs exactly one file', node=node)
        elif not declaration['inputs'] and named:
            refuse('this reader is not a supported self-contained reader', node=node, filter=filter_id,
                   supported=sorted(READERS))
        elif named:
            refuse('filters with file options are not supported in editable state bundles', node=node,
                   options=named)
    if readers > LIMITS['files']:
        refuse('an editable state bundle copies at most %d reader files' % LIMITS['files'], readers=readers)
    late = list(markers({k: v for k, v in scene.items() if k in ('visible', 'appearances', 'images')}))
    if late:
        refuse('dynamic presentation values are not supported in editable state bundles')


def member_layout(node, name):
    """Bundle-relative capture directory and dataset path for one reader."""
    resource = f'{DATA}/{node}'
    return resource, f'{resource}/{DATA}/{name}'


def expected_tree(manifest):
    files = {STATE, MANIFEST}
    directories = {DATA}
    for member in manifest['members']:
        files |= {member['resource'] + '/' + RESOURCE, member['path']}
        directories |= {member['resource'], member['resource'] + '/' + DATA}
    return files, directories


def _scan(bundle, companions=frozenset()):
    """Bounded no-follow inventory of regular files and directories; nothing is opened.

    Only validated publication companions directly inside the bundle are skipped;
    a companion inside a captured tree is an unexpected member.
    """
    try:
        resources._no_links(bundle)
        info = bundle.lstat()
    except SchemaxisError as error:
        _resource_fault(error, bundle)
    except OSError as error:
        _bad('state bundle directory is missing: ' + str(error), bundle)
    if not stat.S_ISDIR(info.st_mode):
        _bad('state bundle directory is missing', bundle)
    files, directories, pending, entries = {}, {}, [(bundle, '', 0)], 0
    try:
        while pending:
            directory, prefix, depth = pending.pop()
            with os.scandir(directory) as found:
                for entry in found:
                    entries += 1
                    if entries > LIMITS['entries']:
                        _bad('state bundle has too many entries', bundle, limit=LIMITS['entries'])
                    relative = prefix + entry.name
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode):
                        _bad('state bundle contains a symbolic link', entry.path)
                    if stat.S_ISDIR(info.st_mode):
                        if depth + 1 >= LIMITS['depth']:
                            _bad('state bundle is nested too deeply', entry.path, limit=LIMITS['depth'])
                        directories[relative] = resources._signature(info)
                        pending.append((Path(entry.path), relative + '/', depth + 1))
                    elif stat.S_ISREG(info.st_mode):
                        if depth == 0 and Path(entry.path).resolve() in companions:
                            continue
                        files[relative] = resources._signature(info)
                    else:
                        _bad('state bundle contains a special file', entry.path)
    except OSError as error:
        _bad('cannot inventory state bundle: ' + str(error), bundle)
    return files, directories


def _read(path, signature, limit):
    """Read a regular file of at most ``limit`` bytes, bound to its inventoried signature."""
    if signature[3] > limit:
        _bad('file exceeds its verification size limit', path, bytes=signature[3], limit=limit)
    try:
        with resources._open_read(path) as stream:
            if resources._signature(os.fstat(stream.fileno())) != signature:
                _bad('file changed after inventory', path)
            payload = stream.read(limit + 1)
            if len(payload) != signature[3] or resources._signature(os.fstat(stream.fileno())) != signature:
                _bad('file changed while it was read', path)
    except SchemaxisError as error:
        if error.fault.code == 'VERIFICATION_FAILED':
            raise
        _resource_fault(error, path)
    except OSError as error:
        _bad('cannot read file: ' + str(error), path)
    return payload


def _json(payload, location):
    try:
        return json.loads(payload.decode('utf-8'),
                          parse_constant=lambda value: _bad('JSON contains a nonfinite number', location))
    except (UnicodeError, ValueError, RecursionError) as error:
        _bad('file is not valid UTF-8 JSON: ' + type(error).__name__, location)


def read_json(path, limit):
    """Bounded, no-follow read of one regular JSON file outside the bundle tree."""
    path = Path(path)
    try:
        resources._no_links(path)
        info = path.lstat()
    except SchemaxisError as error:
        _resource_fault(error, path)
    except OSError as error:
        _bad('file is missing: ' + str(error), path)
    if not stat.S_ISREG(info.st_mode):
        _bad('expected a regular file', path)
    payload = _read(path, resources._signature(info), limit)
    return _json(payload, path), hashlib.sha256(payload).hexdigest()


def _string(value, location, pattern=None):
    if not isinstance(value, str) or not value or len(value) > 4096 or '\x00' in value \
            or (pattern is not None and not pattern.fullmatch(value)):
        _bad('expected a valid string', location, observed=repr(value)[:80])
    return value


def _integer(value, location, minimum=0):
    if type(value) is not int or value < minimum:
        _bad('expected an integer of at least %d' % minimum, location, observed=repr(value)[:80])
    return value


def _number(value, location):
    try:
        finite = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        _bad('expected a finite number', location, observed=repr(value)[:80])
    return value


def _mapping(value, location, keys=None):
    if not isinstance(value, dict) or (keys is not None and set(value) != set(keys)):
        _bad('expected an object' + (' with keys ' + ', '.join(sorted(keys)) if keys else ''), location,
             observed=sorted(value)[:20] if isinstance(value, dict) else type(value).__name__)
    return value


def _array(value, location, limit=LIMITS['propertyValues']):
    if not isinstance(value, list) or len(value) > limit:
        _bad('expected a bounded array', location)
    return value


def _absolute(value, location):
    if not os.path.isabs(_string(value, location)) or '..' in PurePosixPath(value).parts:
        _bad('expected a normalised absolute path', location)
    return value


def _process(value, location):
    return _integer(value, location, 1)


MEMBER_KEYS = {'node', 'path', 'resource', 'resourceSha256', 'resourceDigest', 'sha256', 'bytes', 'origin',
               'property', 'proxyId'}
PIPELINE_KEYS = {'proxyId', 'xmlName', 'inputs', 'filter', 'properties'}
MANIFEST_KEYS = {'version', 'state', 'stateSha256', 'savedBundle', 'scene', 'time', 'viewTime', 'members',
                 'pipeline', 'observations', 'appearance', 'presentation', 'camera', 'viewSize', 'runtimeIdentity',
                 'processId', 'pathStrategy', 'openInParaView', 'units', 'frame', 'losses', 'scope', 'proofScope'}


def _properties(value, location):
    for index, entry in enumerate(_array(value, location, 256)):
        _mapping(entry, f'{location}[{index}]', {'option', 'path', 'raw', 'value'})
        if type(entry['raw']) is not bool:
            _bad('property readback mode must be boolean', f'{location}[{index}].raw')
        _string(entry['option'], f'{location}[{index}].option')
        path = _array(entry['path'], f'{location}[{index}].path', 8)
        if not path:
            _bad('property path is empty', f'{location}[{index}].path')
        for part in path:
            _string(part, f'{location}[{index}].path', _PROPERTY)
    return value


def validate_manifest(manifest, location):
    """Typed structure of a bundle manifest; raises VERIFICATION_FAILED, never raw exceptions."""
    _mapping(manifest, location, MANIFEST_KEYS)
    if manifest['version'] != VERSION or manifest['state'] != STATE:
        _bad('state bundle manifest version is unsupported', location)
    _string(manifest['stateSha256'], location + '.stateSha256', _HEX)
    _absolute(manifest['savedBundle'], location + '.savedBundle')
    _number(manifest['time'], location + '.time')
    _number(manifest['viewTime'], location + '.viewTime')
    _process(manifest['processId'], location + '.processId')
    size = _array(manifest['viewSize'], location + '.viewSize', 2)
    if len(size) != 2:
        _bad('viewSize must have two entries', location + '.viewSize')
    for value in size:
        _integer(value, location + '.viewSize', 1)
    _string(_mapping(manifest['runtimeIdentity'], location + '.runtimeIdentity').get('version'),
            location + '.runtimeIdentity.version')
    for key in ('observations', 'appearance', 'presentation', 'camera'):
        _mapping(manifest[key], location + '.' + key)
    pipeline = _mapping(manifest['pipeline'], location + '.pipeline')
    if len(pipeline) > 256:
        _bad('state bundle pipeline is too large', location + '.pipeline')
    for node, entry in pipeline.items():
        here = f'{location}.pipeline.{_string(node, location + ".pipeline", _NODE)}'
        _mapping(entry, here, PIPELINE_KEYS)
        for key in ('proxyId', 'xmlName', 'filter'):
            _string(entry[key], here + '.' + key)
        for item in _array(entry['inputs'], here + '.inputs', 64):
            _string(item, here + '.inputs')
        _properties(entry['properties'], here + '.properties')
    members = _array(manifest['members'], location + '.members', LIMITS['files'])
    total, nodes, paths = 0, set(), set()
    for index, member in enumerate(members):
        here = f'{location}.members[{index}]'
        _mapping(member, here, MEMBER_KEYS)
        node = _string(member['node'], here + '.node', _NODE)
        path = _string(member['path'], here + '.path')
        name = PurePosixPath(path).name
        if member_layout(node, name) != (member['resource'], path) or name in ('', '.', '..', RESOURCE):
            _bad('state bundle member escapes its capture directory', here, member=path)
        try:
            resources._relative(path, here + '.path')
        except SchemaxisError as error:
            _resource_fault(error, here + '.path')
        for key in ('sha256', 'resourceSha256', 'resourceDigest'):
            _string(member[key], here + '.' + key, _HEX)
        size = _integer(member['bytes'], here + '.bytes')
        total += size
        if size > LIMITS['fileBytes'] or total > LIMITS['totalBytes']:
            _bad('state bundle members exceed size limits', here, limits=LIMITS)
        _absolute(member['origin'], here + '.origin')
        if member['property'] not in ('FileName', 'FileNames'):
            _bad('state bundle member property is unsupported', here + '.property')
        _string(member['proxyId'], here + '.proxyId')
        if node in nodes or path in paths or node not in pipeline:
            _bad('state bundle members must be unique pipeline readers', here, node=node)
        nodes.add(node)
        paths.add(path)
    return manifest


def check_bundle(bundle, manifest_digest=None, companions=frozenset()):
    """Verify exact bundle membership, captures, digests, limits and containment; return the manifest.

    A bounded no-follow inventory precedes every read. ``companions`` are
    publication metadata files already validated against the run's committed
    metadata manifest; nothing is exempted by name.
    """
    bundle = Path(os.path.abspath(bundle))
    files, directories = _scan(bundle, companions)
    for required in (MANIFEST, STATE):
        if required not in files:
            _bad('state bundle %s is missing' % required, bundle / required)
    payload = _read(bundle / MANIFEST, files[MANIFEST], LIMITS['manifestBytes'])
    if manifest_digest is not None and hashlib.sha256(payload).hexdigest() != manifest_digest:
        _bad('state bundle manifest digest differs', bundle / MANIFEST)
    manifest = validate_manifest(_json(payload, bundle / MANIFEST), str(bundle / MANIFEST))
    expected, folders = expected_tree(manifest)
    if set(files) != expected or set(directories) != folders:
        _bad('state bundle membership differs from its manifest', bundle,
             missing=sorted((expected - set(files)) | (folders - set(directories))),
             extra=sorted((set(files) - expected) | (set(directories) - folders)))
    for member in manifest['members']:
        record = bundle / member['resource'] / RESOURCE
        if hashlib.sha256(_read(record, files[member['resource'] + '/' + RESOURCE],
                                LIMITS['manifestBytes'])).hexdigest() != member['resourceSha256']:
            _bad('captured resource manifest differs from its pinned digest', record)
        try:
            captured = resources.verify(bundle / member['resource'], max_files=1, max_bytes=LIMITS['fileBytes'])
        except SchemaxisError as error:
            _resource_fault(error, bundle / member['resource'])
        if (captured['kind'] != 'file' or captured['digest'] != member['resourceDigest']
                or captured['files'] != [{'path': PurePosixPath(member['path']).name, 'size': member['bytes'],
                                          'sha256': member['sha256']}]):
            _bad('captured resource differs from the bundle manifest', bundle / member['resource'])
    state = _read(bundle / STATE, files[STATE], LIMITS['stateBytes'])
    if hashlib.sha256(state).hexdigest() != manifest['stateSha256']:
        _bad('state bundle .pvsm digest differs', bundle / STATE)
    _check_state_paths(bundle, manifest, state)
    if _scan(bundle, companions) != (files, directories):
        _bad('state bundle changed during verification', bundle)
    return manifest


def _check_state_paths(bundle, manifest, payload):
    """Every reader file property in the .pvsm names its bundle copy; origins never appear."""
    import xml.etree.ElementTree as ET
    if b'<!DOCTYPE' in payload or b'<!ENTITY' in payload:
        _bad('saved ParaView state must not declare a document type or entities', bundle / STATE)
    try:
        root = ET.fromstring(payload.decode('utf-8'))
        # Decoded attribute values and text, so XML escaping cannot hide an origin.
        values = [value for element in root.iter()
                  for value in (*element.attrib.values(), element.text, element.tail) if value]
    except (UnicodeError, ET.ParseError, ValueError, RecursionError) as error:
        _bad('saved ParaView state is not well-formed UTF-8 XML: ' + type(error).__name__, bundle / STATE)
    for member in manifest['members']:
        if any(_names_path(value, member['origin']) for value in values):
            _bad('saved state still references an original input path', bundle, origin=member['origin'])
    state = root if root.tag == 'ServerManagerState' else root.find('ServerManagerState')
    if state is None:
        _bad('saved ParaView state has no server-manager state', bundle)
    proxies = {}
    for proxy in state.findall('Proxy'):
        if proxy.get('id') in proxies:
            _bad('saved ParaView state repeats a proxy id', bundle, proxyId=proxy.get('id'))
        proxies[proxy.get('id')] = proxy
    saved_root = Path(manifest['savedBundle'])
    for member in manifest['members']:
        proxy = proxies.get(member['proxyId'])
        if proxy is None:
            _bad('saved state lacks a bundled reader', bundle, node=member['node'])
        values = [element.get('value') for prop in proxy.findall('Property') if prop.get('name') == member['property']
                  for element in prop.findall('Element')]
        if values != [str(saved_root / member['path'])]:
            _bad('saved reader path does not name its bundle copy', bundle, node=member['node'], observed=values)


# Characters that can delimit a whole path inside a saved value. A normalised
# path never precedes an absolute origin with a name character, so a copy path
# that merely ends with the origin (``.../data/plate/data/plate.vtp`` against
# ``/data/plate.vtp``) is not a reference.
_PATH_DELIMITERS = frozenset(' \t\r\n"\';,|=()[]{}<>:/')


def _names_path(value, origin):
    """True when ``value`` names ``origin`` or a path beneath it at path boundaries."""
    start = value.find(origin)
    while start >= 0:
        end = start + len(origin)
        if (start == 0 or value[start - 1] in _PATH_DELIMITERS) and \
                (end == len(value) or value[end] in _PATH_DELIMITERS):
            return True
        start = value.find(origin, start + 1)
    return False


def _close(a, b, location, message='reloaded state differs from the saved scene'):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) \
            and not isinstance(b, bool):
        if not (math.isfinite(a) and math.isfinite(b)) or abs(a - b) > TOLERANCE * max(1, abs(a), abs(b)):
            _bad(message, location, saved=b, reloaded=a)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for index, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f'{location}[{index}]', message)
    elif isinstance(a, dict) and isinstance(b, dict) and set(a) == set(b):
        for key in a:
            _close(a[key], b[key], location + '.' + key, message)
    elif a != b or type(a) is not type(b):
        _bad(message, location, saved=repr(b)[:200], reloaded=repr(a)[:200])


def normal(appearance):
    """Image receipts record multi-word representations with Python quotes; compare the native value."""
    return {node: {**value, 'representation': value['representation'].strip("'")}
            for node, value in appearance.items()}


def summary(observation):
    """Canonical dataset observation compared across processes."""
    return {'dataType': observation['dataType'], 'points': observation['points'], 'cells': observation['cells'],
            'bounds': observation['bounds'], 'fields': observation['fields']}


def property_specs(master, node):
    """Native property paths bound to the node's authored options; reader files are checked separately.

    ``raw`` selects stored integer elements where ParaView reads an integer
    enumeration back as entry text (see native.retained_value).
    """
    from schemaxis.bindings import native_value
    declaration = master.declarations[master.nodes[node]['filter']]
    specs = []
    for key, value in master.nodes[node]['options'].items():
        binding = declaration['options'][key]
        if master.nodes[node]['filter'] in READERS and key == 'files':
            continue
        if 'proxyChoices' in binding:
            choice = binding['proxyChoices'][value['type']]
            specs.append({'option': key, 'path': list(binding['path']), 'raw': False, 'expected': choice['identity']})
            for nested, item in value.get('options', {}).items():
                inner = choice['options'][nested]
                specs.append({'option': key + '.' + nested, 'path': list(binding['path']) + list(inner['path']),
                              'raw': _integer_binding(inner), 'expected': native_value(inner, item, node)})
        else:
            specs.append({'option': key, 'path': list(binding['path']), 'raw': _integer_binding(binding),
                          'expected': native_value(binding, value, node)})
    return specs


def _integer_binding(binding):
    spec = binding.get('value', {})
    return spec.get('type') == 'integer' or (spec.get('type') == 'array'
                                             and spec.get('items', {}).get('type') == 'integer')


def _matches(saved, expected):
    if isinstance(expected, (list, tuple)):
        return isinstance(saved, list) and len(saved) == len(expected) and all(map(_matches, saved, expected))
    if isinstance(expected, (bool, int, float)) and isinstance(saved, (bool, int, float)):
        return math.isfinite(saved) and abs(saved - expected) <= TOLERANCE * max(1, abs(saved), abs(expected))
    return saved == expected


def presentation_expected(effective):
    """What the effective appearance asks of the lookup table and legend for one coloured node."""
    field = effective['field'][1]
    expected = {'logScale': bool(effective.get('logScale', False)), 'legendVisible': bool(effective.get('legend'))}
    if effective.get('legend') or 'legendTitle' in effective:
        expected['legendTitle'] = effective.get('legendTitle', field)
    if 'range' in effective:
        expected['range'] = list(effective['range'])
    return expected


def _check_presentation(saved, image, location):
    effective = image.get('effectiveAppearance', {}) if isinstance(image, dict) else {}
    nodes = {node for node, value in effective.items() if isinstance(value, dict) and value.get('field')}
    if set(saved) != nodes:
        _bad('saved colour lookup tables differ from the coloured nodes', location, saved=sorted(saved))
    for node in nodes:
        entry = _mapping(saved[node], f'{location}.{node}')
        want = presentation_expected(effective[node])
        if entry.get('logScale') != want['logScale'] or entry.get('legendVisible') != want['legendVisible'] \
                or entry.get('legendTitle') != want.get('legendTitle'):
            _bad('saved colour legend differs from the authored appearance', f'{location}.{node}')
        points = _array(entry.get('points'), f'{location}.{node}.points')
        if len(points) < 8 or len(points) % 4:
            _bad('saved colour lookup table is malformed', f'{location}.{node}.points')
        for value in points:
            _number(value, f'{location}.{node}.points')
        if 'range' in want:
            _close([points[0], points[-4]], want['range'], f'{location}.{node}.range')


def verify_artifact(directory, artifact, master, scene, state, image):
    """Recheck a retained state bundle and its independent reload evidence."""
    try:
        return _verify_artifact(directory, artifact, master, scene, state, image)
    except (KeyError, TypeError, AttributeError, ValueError, IndexError, OverflowError, RecursionError) as error:
        _bad('state bundle evidence is malformed: ' + type(error).__name__, directory)


def _verify_artifact(directory, artifact, master, scene, state, image):
    directory = Path(directory).resolve()
    state_path = Path(artifact['file']).resolve()
    bundle = state_path.parent
    if state_path.name != STATE or not bundle.is_relative_to(directory) or bundle == directory:
        _bad('state bundle path is invalid', state_path)
    from schemaxis.publication_metadata import committed_companions
    digest = _string(artifact.get('manifestSha256'), 'manifestSha256', _HEX)
    manifest = check_bundle(bundle, digest, committed_companions(directory, None))
    if [member['path'] for member in artifact.get('files', [])] != [MANIFEST]:
        _bad('state bundle receipt membership differs from its manifest', bundle)
    captured = [{key: member[key] for key in ('node', 'resource', 'resourceSha256', 'resourceDigest', 'path',
                                              'sha256', 'bytes')} for member in manifest['members']]
    if artifact.get('capturedInputs') != captured:
        _bad('state bundle receipt captures differ from its manifest', bundle)
    order = scene['selection']['order']
    if list(manifest['pipeline']) != order:
        _bad('state bundle pipeline differs from the planned dependency closure', bundle)
    for node in order:
        saved = manifest['pipeline'][node]
        if saved['proxyId'] != state['proxyIds'][node] or saved['filter'] != master.nodes[node]['filter']:
            _bad('state bundle pipeline identity differs from the run', node)
        specs = property_specs(master, node)
        if [(entry['option'], entry['path'], entry['raw']) for entry in saved['properties']] != \
                [(spec['option'], spec['path'], spec['raw']) for spec in specs]:
            _bad('saved native property readback differs from the authored options', node)
        for entry, spec in zip(saved['properties'], specs):
            if not _matches(entry['value'], spec['expected']):
                _bad('saved native property differs from its authored value', f'{node}.{spec["option"]}',
                     saved=repr(entry['value'])[:200], authored=repr(spec['expected'])[:200])
        _close(manifest['observations'][node], summary(state['observations'][node]), 'manifest.' + node)
    if image is None or manifest['appearance'] != normal(image['appearance']) or manifest['camera'] != image['camera'] \
            or manifest['viewSize'] != image['dimensions'][:2]:
        _bad('state bundle appearance or camera differs from the published image', bundle)
    # Bind the saved scene and time to the plan and the image, not only to each other.
    if manifest['scene'] != scene['id']:
        _bad('state bundle scene differs from the planned scene', bundle, saved=repr(manifest['scene'])[:200],
             planned=scene['id'])
    message = 'state bundle time differs from the planned visit and image'
    _close(manifest['time'], _number(state['visit']['time'], 'state.visit.time'), 'manifest.time', message)
    _close(manifest['viewTime'], _number(image['viewTime'], 'image.viewTime'), 'manifest.viewTime', message)
    _close(manifest['viewTime'], manifest['time'], 'manifest.viewTime', message)
    _check_presentation(manifest['presentation'], image, 'manifest.presentation')
    readers = {node for node in order if master.nodes[node]['filter'] in READERS}
    if {member['node'] for member in manifest['members']} != readers:
        _bad('bundled datasets differ from the planned readers', bundle)
    rebound = {member['node']: {'property': member['property'], 'origin': member['origin'],
                                'captured': str(Path(manifest['savedBundle']) / member['path']),
                                'sha256': member['sha256'], 'resourceDigest': member['resourceDigest'],
                                'bytes': member['bytes'], 'resourceSha256': member['resourceSha256']}
               for member in manifest['members']}
    if state.get('inputRebinding', {}) != rebound:
        _bad('reader rebinding provenance differs from the bundle captures', bundle)
    for node, entry in rebound.items():
        if state['effective'][node]['files'] != [entry['origin']]:
            _bad('a rebound reader did not originate from its effective file', node)
    proof, _ = read_json(bundle.with_name(bundle.name + '.reload.json'), LIMITS['proofBytes'])
    verify_reload(proof, manifest, digest)
    return {'manifest': manifest, 'reload': proof}


PROOF_KEYS = {'version', 'status', 'verified', 'relocatedBundle', 'processId', 'withheld', 'manifestSha256',
              'stateSha256', 'runtimeIdentity', 'pipeline', 'observations', 'appearance', 'presentation', 'camera',
              'viewSize', 'viewTime', 'loadOptions'}


def verify_reload(proof, manifest, manifest_digest):
    """Compare reload evidence with the manifest; paths are those recorded at save time."""
    try:
        _verify_reload(proof, manifest, manifest_digest)
    except (KeyError, TypeError, AttributeError, ValueError, IndexError, OverflowError, RecursionError) as error:
        _bad('independent reload evidence is malformed: ' + type(error).__name__, 'reload')


def _verify_reload(proof, manifest, manifest_digest):
    bundle = Path(manifest['savedBundle'])
    location = str(bundle) + '.reload'
    if not isinstance(proof, dict) or proof.get('version') != RELOAD_VERSION or proof.get('status') != 'succeeded' \
            or proof.get('verified') is not True:
        _bad('independent reload did not succeed', location,
             fault=proof.get('fault') if isinstance(proof, dict) else None)
    _mapping(proof, location, PROOF_KEYS)
    if proof['manifestSha256'] != manifest_digest or proof['stateSha256'] != manifest['stateSha256']:
        _bad('reload evidence is for a different bundle', location)
    relocated = Path(_absolute(proof['relocatedBundle'], location + '.relocatedBundle'))
    withheld = _mapping(proof['withheld'], location + '.withheld', {'path', 'absentDuringReload'})
    if (relocated == bundle or relocated.is_relative_to(bundle) or bundle.is_relative_to(relocated)
            or withheld['path'] != str(bundle) or withheld['absentDuringReload'] is not True):
        _bad('reload was not performed on a relocated copy with the original withheld', location)
    saved_process = _process(manifest['processId'], location + '.saved.processId')
    if _process(proof['processId'], location + '.processId') == saved_process:
        _bad('reload did not run in a fresh process', location)
    data = relocated / DATA
    if proof['loadOptions'] != {'dataDirectory': str(data), 'restrictToDataDirectory': True}:
        _bad('reload did not search only the relocated data directory', location, observed=proof['loadOptions'])
    runtime = _mapping(proof['runtimeIdentity'], location + '.runtimeIdentity')
    if runtime.get('application') != 'paraview' or runtime.get('version') != manifest['runtimeIdentity'].get('version') \
            or 'fault' in runtime:
        _bad('reload runtime differs from the saving runtime', location,
             saved=manifest['runtimeIdentity'].get('version'), reloaded=runtime.get('version'))
    if proof['viewSize'] != manifest['viewSize']:
        _bad('reloaded view size differs from the saved view', location, saved=manifest['viewSize'],
             reloaded=proof['viewSize'])
    _close(_number(proof['viewTime'], location + '.viewTime'), manifest['time'], location + '.viewTime')
    pipeline = _mapping(proof['pipeline'], location + '.pipeline')
    if set(pipeline) != set(manifest['pipeline']):
        _bad('reloaded pipeline membership differs', location,
             saved=sorted(manifest['pipeline']), reloaded=sorted(pipeline)[:50])
    members = {member['node']: member for member in manifest['members']}
    for node, saved in manifest['pipeline'].items():
        loaded = _mapping(pipeline[node], f'{location}.pipeline.{node}')
        if loaded.get('xmlName') != saved['xmlName'] or loaded.get('inputs') != saved['inputs']:
            _bad('reloaded pipeline object or connection differs', node)
        _close(loaded.get('properties'), saved['properties'], f'reload.{node}.properties')
        _close(proof['observations'][node], manifest['observations'][node], 'reload.' + node)
        found = _mapping(loaded.get('fileProperties'), f'{location}.pipeline.{node}.fileProperties')
        bound = {name: values for name, values in found.items() if _array(values, f'{node}.{name}', 64)}
        member = members.get(node)
        expected = {member['property']: [str(data / Path(member['path']).relative_to(DATA))]} if member else {}
        if bound != expected:
            _bad('reloaded file-bearing properties do not name exactly the relocated bundle copy', node,
                 observed=bound, expected=expected)
    _close(proof['appearance'], manifest['appearance'], 'reload.appearance')
    _close(proof['presentation'], manifest['presentation'], 'reload.presentation')
    _close(proof['camera'], manifest['camera'], 'reload.camera')


def reload(directory, receipt, runner):
    """Load each saved bundle from a relocated copy in a fresh native process.

    ``runner`` executes Python source in a new pvbatch process. The original
    bundle is renamed aside while the copy loads, so its absolute paths cannot
    be read; it is restored afterwards whatever the outcome. The receipt's
    manifest digest is required before anything is created and pins the
    original, the copy, the fresh process and the copy after consumption.
    """
    directory = Path(directory)
    results = []
    for artifact in receipt.get('artifacts', []):
        if artifact.get('identity', {}).get('kind') != 'state-bundle':
            continue
        bundle = Path(artifact['file']).parent
        digest = _string(artifact.get('manifestSha256'), str(bundle) + '.manifestSha256', _HEX)
        check_bundle(bundle, digest)
        area = directory / (bundle.name + '.relocated')
        if area.exists():
            fail('OUTPUT_EXISTS', 'reload area already exists', str(area))
        area.mkdir()
        relocated = area / 'moved' / 'bundle'
        shutil.copytree(bundle, relocated, symlinks=True)
        check_bundle(relocated, digest)
        proof = bundle.with_name(bundle.name + '.reload.json')
        withheld = bundle.with_name(bundle.name + '.withheld')
        bundle.rename(withheld)
        try:
            submission = runner('from schemaxis.adaptors.paraview.handback_native import reload_bundle\n'
                                f'reload_bundle({str(relocated)!r}, {str(bundle)!r}, {str(proof)!r}, {digest!r})\n')
            # The temporary copy is the fresh process's actual input. Recheck it
            # after consumption, before accepting evidence or deleting the copy.
            check_bundle(relocated, digest)
        finally:
            withheld.rename(bundle)
        from schemaxis.artifacts import atomic_json
        atomic_json(bundle.with_name(bundle.name + '.reload-submission.json'), submission.to_dict())
        # The relocated copy is disposable; the retained proof records its path.
        shutil.rmtree(area)
        results.append(str(proof))
    return results
