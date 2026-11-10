"""Shared local declared tool packages; no network retrieval or authored code."""
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import unicodedata
import zipfile

from .errors import fail, keys
from .storage import atomic, encoded, load

MAX_ARCHIVE = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_MEMBER = 8 * 1024 * 1024
MAX_MEMBERS = 256
ALLOWED_SUFFIXES = {'.json', '.txt', '.csv', '.png', '.jpg', '.jpeg'}
MANIFEST_FIELDS = {'version', 'id', 'revision', 'title', 'summary', 'description',
    'tags', 'author', 'licence', 'template', 'display', 'execution', 'requirements', 'provenance'}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _relative(name):
    if (not isinstance(name, str) or len(name) > 512 or ':' in name or '\\' in name
            or '\x00' in name or any(p in {'', '.', '..'} for p in name.split('/'))
            or Path(name).suffix.lower() not in ALLOWED_SUFFIXES):
        fail('INVALID_TOOL_PACKAGE', 'members must be confined declared data files', member=name)
    return name


def _json(data):
    try:
        value = load(data.decode('utf-8'))
        from .workflow_templates import _json as validate_json
        validate_json(value)
        return value
    except (UnicodeError, RecursionError):
        fail('INVALID_TOOL_PACKAGE', 'JSON members must be bounded UTF-8 JSON')


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        fail('INVALID_TOOL_MANIFEST', 'provide bounded nonempty text', field=field)


def _manifest(manifest):
    keys(manifest, MANIFEST_FIELDS, '$.tool')
    if set(manifest) != MANIFEST_FIELDS or manifest['version'] != 'schemaxis.tool/1':
        fail('INVALID_TOOL_MANIFEST', 'provide the complete schemaxis.tool/1 manifest')
    if not isinstance(manifest['id'], str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_.-]{0,127}', manifest['id']):
        fail('INVALID_TOOL_MANIFEST', 'invalid tool identity')
    if type(manifest['revision']) is not int or manifest['revision'] < 1:
        fail('INVALID_TOOL_MANIFEST', 'revision must be a positive integer')
    for field, limit in [('title', 256), ('summary', 500), ('description', 32768), ('author', 128), ('licence', 128)]:
        _text(manifest[field], field, limit)
    if not re.fullmatch('[A-Za-z0-9.-]+', manifest['licence']):
        fail('INVALID_TOOL_MANIFEST', 'licence must be a single SPDX identifier')
    if not isinstance(manifest['tags'], list) or len(manifest['tags']) > 32:
        fail('INVALID_TOOL_MANIFEST', 'tags must be a bounded list')
    for tag in manifest['tags']:
        _text(tag, 'tags', 80)
    _relative(manifest['template'])
    display = manifest['display']
    keys(display, ('parameterGroups', 'parameterOrder', 'units', 'widgets', 'examples', 'outputs', 'thumbnail'), '$.tool.display')
    # Presentation is data only. Rendering or widget execution is not part of this runner.
    from .workflow_templates import _json as validate_json
    validate_json(display)
    execution = manifest['execution']
    keys(execution, ('tier', 'durationClass', 'uploadedInputs'), '$.tool.execution')
    if (execution.get('tier') != 'local' or execution.get('uploadedInputs') is not False
            or execution.get('durationClass') not in {'short', 'medium', 'long', 'unknown'}):
        fail('UNSUPPORTED_TOOL_EXECUTION', 'the local minimum supports local tier and no uploaded inputs')
    if not isinstance(manifest['requirements'], list):
        fail('INVALID_TOOL_MANIFEST', 'requirements must be a derived list')
    keys(manifest['provenance'], ('files',), '$.tool.provenance')
    if not isinstance(manifest['provenance'].get('files'), dict):
        fail('INVALID_TOOL_MANIFEST', 'provenance.files must map payload paths to SHA-256')


def _archive(data):
    if not isinstance(data, bytes) or len(data) > MAX_ARCHIVE:
        fail('TOOL_PACKAGE_LIMIT', 'archive exceeds sixteen MiB')
    members, total, spellings = {}, 0, set()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            records = archive.infolist()
            if not 1 <= len(records) <= MAX_MEMBERS:
                fail('TOOL_PACKAGE_LIMIT', 'archive member count is outside 1..256')
            for record in records:
                name = _relative(record.filename)
                mode = record.external_attr >> 16
                if (record.flag_bits & 1 or record.is_dir() or stat.S_ISLNK(mode)
                        or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or mode & 0o111
                        or unicodedata.normalize('NFC', name).casefold() in spellings):
                    fail('INVALID_TOOL_PACKAGE', 'encrypted, special, executable or duplicate members are forbidden', member=name)
                spellings.add(unicodedata.normalize('NFC', name).casefold())
                if record.file_size > MAX_MEMBER:
                    fail('TOOL_PACKAGE_LIMIT', 'member exceeds eight MiB')
                with archive.open(record) as stream:
                    content = stream.read(MAX_MEMBER+1)
                total += len(content)
                if len(content) > MAX_MEMBER or total > MAX_TOTAL:
                    fail('TOOL_PACKAGE_LIMIT', 'actual decompressed byte bound exceeded')
                members[name] = content
    except (zipfile.BadZipFile, RuntimeError, OSError, ValueError, NotImplementedError) as error:
        fail('INVALID_TOOL_PACKAGE', 'archive cannot be read: '+str(error))
    if 'package.json' not in members or 'tool.json' not in members:
        fail('INVALID_TOOL_PACKAGE', 'archive needs package.json and tool.json')
    index = _json(members['package.json'])
    keys(index, ('version', 'files'), '$.package')
    if index.get('version') != 'schemaxis.tool-package/1' or not isinstance(index.get('files'), list):
        fail('INVALID_TOOL_PACKAGE', 'invalid digest inventory')
    expected = [{'path': name, 'bytes': len(content), 'sha256': _sha(content)}
                for name, content in sorted(members.items()) if name != 'package.json']
    if index['files'] != expected:
        fail('TOOL_PACKAGE_CHANGED', 'digest inventory differs from actual package members')
    manifest = _json(members['tool.json'])
    _manifest(manifest)
    provenance = {name: _sha(content) for name, content in sorted(members.items())
                  if name not in {'tool.json', 'package.json'}}
    if manifest['provenance']['files'] != provenance:
        fail('TOOL_PACKAGE_CHANGED', 'tool provenance differs from package members')
    template_name = manifest['template']
    if template_name not in members:
        fail('INVALID_TOOL_PACKAGE', 'referenced template is absent')
    template = _json(members[template_name])
    workflow_name = str(Path(template_name).parent / _relative(template.get('workflow')))
    if workflow_name not in members:
        fail('INVALID_TOOL_PACKAGE', 'referenced workflow is absent')
    workflow = _json(members[workflow_name])
    from .storage import digest
    bundle = {'template': template, 'workflow': workflow,
              'digest': digest({'template': template, 'workflow': workflow})}
    return {'digest': 'sha256:'+_sha(data), 'manifest': manifest, 'bundle': bundle,
            'inventory': expected}


def _prepared(bundle, values, admission):
    """Preflight before the existing binder's planning hooks; do not run hooks first."""
    from . import workflow_templates as templates
    from .mcp_admission import materialise_workflow
    templates._json(values)
    if not isinstance(values, dict):
        fail('INVALID_PARAMETER', 'tool values must map parameter identities to declared values')
    template, document = bundle['template'], copy.deepcopy(bundle['workflow'])
    parameters = template.get('parameters')
    if not isinstance(parameters, dict) or set(values) - set(parameters):
        fail('INVALID_PARAMETER', 'unknown tool parameter')
    for identity, spec in parameters.items():
        if not isinstance(spec, dict) or 'target' not in spec:
            fail('INVALID_TEMPLATE', 'invalid parameter contract')
        target = spec['target']
        if not isinstance(target, dict) or target.get('scope') != 'workflow':
            fail('UNSUPPORTED_BINDING', 'tool parameters bind workflow values only')
        if identity not in values and 'default' not in spec:
            fail('MISSING_PARAMETER', 'supply the required tool parameter', parameter=identity)
        value = values.get(identity, spec.get('default'))
        if spec.get('kind') not in templates._KINDS:
            fail('UNSUPPORTED_PARAMETER_KIND', 'unsupported declared parameter kind')
        templates._constraints(spec, '$.parameters.'+identity)
        templates._value(value, spec, '$.parameters.'+identity)
        parts = templates._pointer(target.get('pointer'), '$.parameters.'+identity, binding=True)
        parent, key = templates._target(document, parts, '$.parameters.'+identity)
        parent[key] = copy.deepcopy(value)
    effective = materialise_workflow(document)
    admission.check(effective)
    # Existing validation and planning are now safe to enter. No caller run/path
    # preferences enter the binder; ordinary task budgets still own execution.
    case = {'version': templates.VALUES_VERSION,
        'template': {'id': template.get('id'), 'revision': template.get('revision'), 'digest': bundle['digest']},
        'values': values}
    result = templates.bind_values(bundle, case)
    if materialise_workflow(result['document']) != effective:
        fail('TOOL_PACKAGE_CHANGED', 'binding result differs from admitted input')
    return result


def check_package(data, *, values=None, admission=None):
    from .mcp_admission import FileAdmission
    from .adaptors import registry
    admission = admission or FileAdmission()
    package = _archive(data)
    # The minimum requires defaults so tool check/pack can produce a host plan
    # without inventing values. Execution may override any declared parameter.
    prepared = _prepared(package['bundle'], {} if values is None else values, admission)
    from .mcp_admission import materialise_workflow
    effective = materialise_workflow(prepared['document'])
    providers = sorted({registry.resolve(op['document'])[0] for op in effective['operations']})
    requirements = [{'adaptor': provider, 'application': provider, 'versionRange': 'unknown'} for provider in providers]
    if package['manifest']['requirements'] != requirements:
        fail('INVALID_TOOL_REQUIREMENTS', 'tool requirements differ from independently derived workflow', derived=requirements)
    package['prepared'] = prepared
    package['providers'] = providers
    return package


class PackageStore:
    def __init__(self, workspace):
        self.root = Path(workspace)/'tool-packages'
        if self.root.is_symlink():
            fail('INVALID_TOOL_PACKAGE', 'package store must be owned storage')
        self.root.mkdir(parents=True, exist_ok=True)

    def import_package(self, filename):
        path = Path(filename)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
            fail('INVALID_TOOL_PACKAGE', 'import a bounded regular local archive')
        data = path.read_bytes()
        checked = check_package(data)
        target = self.root/(checked['digest'][7:]+'.schemaxis-tool')
        if target.exists():
            if target.is_symlink() or target.read_bytes() != data:
                fail('TOOL_PACKAGE_CHANGED', 'immutable stored archive differs')
        else:
            atomic(target, data, exclusive=True)
        return {'digest': checked['digest'], 'id': checked['manifest']['id'],
                'revision': checked['manifest']['revision'], 'providers': checked['providers']}

    def resolve(self, package_digest, *, values=None, admission=None):
        if not isinstance(package_digest, str) or not re.fullmatch('sha256:[a-f0-9]{64}', package_digest):
            fail('INVALID_TOOL_DIGEST', 'select an exact lowercase SHA-256 archive digest')
        path = self.root/(package_digest[7:]+'.schemaxis-tool')
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
            fail('UNKNOWN_TOOL_PACKAGE', 'import this local package before calling run_tool')
        data = path.read_bytes()
        if 'sha256:'+_sha(data) != package_digest:
            fail('TOOL_PACKAGE_CHANGED', 'stored package bytes differ from requested digest')
        return check_package(data, values=values, admission=admission)


def pack_directory(directory, output):
    """Pack exactly authored data plus a generated digest inventory; no symlinks."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        fail('INVALID_TOOL_PACKAGE', 'select a regular package directory')
    members = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            fail('INVALID_TOOL_PACKAGE', 'package members cannot be symlinks')
        if path.is_dir():
            continue
        name = _relative(path.relative_to(root).as_posix())
        if name == 'package.json':
            continue
        if not path.is_file() or path.stat().st_size > MAX_MEMBER:
            fail('TOOL_PACKAGE_LIMIT', 'package member exceeds a bound')
        members[name] = path.read_bytes()
        if len(members) >= MAX_MEMBERS or sum(map(len, members.values())) > MAX_TOTAL:
            fail('TOOL_PACKAGE_LIMIT', 'package exceeds member/byte bounds')
    if 'tool.json' not in members:
        fail('INVALID_TOOL_PACKAGE', 'package needs tool.json')
    manifest = _json(members['tool.json'])
    template_name = _relative(manifest.get('template'))
    if template_name not in members:
        fail('INVALID_TOOL_PACKAGE', 'referenced template is absent')
    template = _json(members[template_name])
    workflow_name = str(Path(template_name).parent / _relative(template.get('workflow')))
    if workflow_name not in members:
        fail('INVALID_TOOL_PACKAGE', 'referenced workflow is absent')
    workflow = _json(members[workflow_name])
    from .storage import digest
    from .mcp_admission import FileAdmission, materialise_workflow
    from .adaptors import registry
    bundle = {'template': template, 'workflow': workflow,
        'digest': digest({'template': template, 'workflow': workflow})}
    prepared = _prepared(bundle, {}, FileAdmission())
    providers = sorted({registry.resolve(op['document'])[0]
        for op in materialise_workflow(prepared['document'])['operations']})
    manifest['requirements'] = [{'adaptor': provider, 'application': provider, 'versionRange': 'unknown'} for provider in providers]
    manifest['provenance'] = {'files': {name: _sha(data) for name, data in sorted(members.items()) if name != 'tool.json'}}
    members['tool.json'] = encoded(manifest)
    members['package.json'] = encoded({'version': 'schemaxis.tool-package/1', 'files': [
        {'path': name, 'bytes': len(data), 'sha256': _sha(data)} for name, data in sorted(members.items())]})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    data = stream.getvalue()
    checked = check_package(data)
    atomic(Path(output), data, exclusive=True)
    return {'digest': checked['digest'], 'bytes': len(data), 'providers': checked['providers']}


def run_tool(service, task_id, package_digest, values, expected_revision, execute=False):
    if type(execute) is not bool:
        fail('INVALID_ARGUMENT', 'execute must be a boolean')
    package = PackageStore(service.workspace).resolve(package_digest, values=values)
    with service.lock:
        planned = service.plan(task_id, package['prepared']['document'], expected_revision)
        provenance = {'digest': package_digest, 'id': package['manifest']['id'],
            'revision': package['manifest']['revision'], 'templateDigest': package['bundle']['digest'],
            'values': copy.deepcopy(package['prepared']['values']), 'bindings': package['prepared']['bindings']}
        state = copy.deepcopy(service.state)
        state['plans'][planned['id']]['package'] = provenance
        service._commit(state)
        result = {'package': provenance, 'plan': planned}
        if execute:
            try:
                PackageStore(service.workspace).resolve(package_digest, values=values)
                result['job'] = service.execute(planned['id'], planned['revision'])
            except Exception as error:
                from .execution_service import error_fault
                fault = error_fault(error)
                fail(fault['code'], fault['message'], plan=planned['id'], revision=planned['revision'], cause=fault)
        return result
