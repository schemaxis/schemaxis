#!/usr/bin/env python3
"""Generate strict admission pins from adaptor-owned records and canonical schemas.

Run from a source checkout; this never starts a native application. --check
compares the generated snapshot without writing it. Records are reviewed trust
declarations, not automatic qualification inferred from registration/readiness.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from schemaxis.adaptors import registry
from schemaxis.mcp_admission import FileAdmission


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def source_files(provider=None):
    base = ROOT/'src/schemaxis'
    paths = []
    for path in sorted(base.rglob('*')):
        relative = path.relative_to(base)
        if (path.suffix not in ('.py', '.json') or '__pycache__' in relative.parts
                or relative.parts[0] == 'studio_ui' or relative.as_posix() == 'mcp_admission.json'):
            continue
        if relative.parts[0] == 'adaptors' and len(relative.parts) > 2 and relative.parts[1] != provider:
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError('Source pin must be a regular confined file: '+str(relative))
        paths.append((relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return dict(paths)


def read_reference(reference):
    path = ROOT/reference
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
        raise ValueError('Qualification reference must remain in the source checkout')
    return json.loads(path.read_text())


def qualified_operations(record, declarations):
    selection = record['operations']
    if selection == 'catalogue':
        return sorted(declarations), []
    names = set()
    for source in selection['evidence']:
        document = read_reference(source['reference'])
        rows = FileAdmission._matches(document, source['rows'])
        for _, row in rows:
            if row.get(source.get('statusKey', 'status')) != source.get('success', 'passed'):
                continue
            for pointer in source.get('operationPointers', ()):
                names.update(v for _, v in FileAdmission._matches(row, pointer))
            if source.get('examplePattern'):
                example = read_reference(source['examplePattern'].replace('{name}', row['name']))
                for pointer in record['operationSelectors']:
                    names.update(v for _, v in FileAdmission._matches(example, pointer))
            example_ref = source.get('examplesByName', {}).get(row.get('name'))
            if example_ref:
                example = read_reference(example_ref)
                for pointer in record['operationSelectors']:
                    names.update(v for _, v in FileAdmission._matches(example, pointer))
    for source in selection.get('qualifiedExamples', ()):
        # A specific reviewed success record and matching fixture are required;
        # a bare example is never qualification evidence.
        evidence = read_reference(source['reference'])
        rows = FileAdmission._matches(evidence, source['receipt'])
        if len(rows) != 1 or rows[0][1] is not True:
            raise ValueError('Qualified example does not name a verified receipt')
        example = read_reference(source['example'])
        for pointer in record['operationSelectors']:
            names.update(v for _, v in FileAdmission._matches(example, pointer))
    for source in selection.get('reviewedClaims', ()):
        # Some retained historical receipts describe their operation in prose.
        # The adaptor owns that explicit interpretation and cites a passing
        # machine-readable result; it is never guessed from a name or runtime.
        evidence = read_reference(source['reference'])
        rows = FileAdmission._matches(evidence, source['receipt'])
        if len(rows) != 1 or rows[0][1] is not True or not source.get('scope'):
            raise ValueError('Reviewed operation claim lacks its passing scoped receipt')
        names.add(source['operation'])
    unknown = names-set(declarations)
    if unknown:
        raise ValueError('Qualification refers to absent operations: '+str(sorted(unknown)))
    return sorted(names), sorted(set(declarations)-names)


def qualification_references(record):
    references = set(record['qualification'])
    selection = record['operations']
    if type(selection) is dict:
        for source in selection.get('evidence', ()):
            references.add(source['reference'])
            references.update(source.get('examplesByName', {}).values())
        for source in selection.get('qualifiedExamples', ()):
            references.update((source['reference'], source['example']))
        for source in selection.get('reviewedClaims', ()):
            references.add(source['reference'])
    return sorted(references)


def generate():
    policies = {}
    for provider in sorted(registry.ADAPTORS):
        # This snapshot's source namespace is the core distribution. Installing
        # a trusted plugin does not silently grant it the core's source pins.
        # Plugin support needs its own package-resource implementation closure.
        if registry.metadata(provider).get('source') != 'builtin':
            continue
        folder = registry.adaptor_files(provider)
        path = folder.joinpath('admission.json')
        if not path.is_file():
            continue
        owned = json.loads(path.read_text())
        if owned.get('protocol') != 'schemaxis.file-admission/1':
            raise ValueError('Unsupported admission record for '+provider)
        manifest = registry.metadata(provider)
        declarations = registry.declarations(provider)
        for version, record in owned['routes'].items():
            route = manifest['routes'][version]
            if not record.get('qualification') or not record.get('scope'):
                raise ValueError('Admission requires explicit qualification references and scope')
            references = qualification_references(record)
            for reference in references:
                path = ROOT/reference
                if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                    raise ValueError('Missing confined qualification reference: '+reference)
            operations, missing = qualified_operations(record, declarations)
            if not operations:
                raise ValueError('Admission record selects no qualified operations')
            for slot in record['fileSlots']:
                if slot.get('contentPolicy') == 'native':
                    if 'contentHook' in slot or 'contentOptions' in slot:
                        raise ValueError('Native content policy may not hide a hook')
                elif slot.get('contentPolicy') == 'hook':
                    hook = slot.get('contentHook')
                    package = registry.adaptor_package(provider)
                    if (type(hook) is not str or re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*', hook) is None
                            or not hook.split(':', 1)[0].startswith(package+'.')
                            or type(slot.get('contentOptions')) is not dict):
                        raise ValueError('Content hooks must be confined to their owning adaptor package')
                    module = hook.split(':', 1)[0].removeprefix('schemaxis.').replace('.', '/')
                    pins = source_files(provider)
                    if module+'.py' not in pins and module+'/__init__.py' not in pins:
                        raise ValueError('Content hook module is absent from the implementation pins')
                else:
                    raise ValueError('Every captured slot needs an explicit byte-validation policy')
            policy = {'catalogueGenerated': True,
                'classification': 'captured-inputs' if record['fileSlots'] else 'file-free',
                'provider': provider, 'route': route,
                'schema': registry.binding(route['schema'])(),
                'operations': operations, 'unqualifiedOperations': missing,
                **{key: record.get(key, []) for key in ('fileSlots', 'forbiddenPointers', 'operationSelectors', 'limitations')},
                'operationContexts': record.get('operationContexts', {}),
                'scope': record['scope'],
                'qualification': {ref: hashlib.sha256((ROOT/ref).read_bytes()).hexdigest()
                                  for ref in references},
                'files': source_files(provider)}
            policy['contractDigest'] = 'sha256:'+hashlib.sha256(canonical(policy)).hexdigest()
            policies[version] = policy
    workflow = {'classification': 'workflow', 'files': source_files()}
    workflow['contractDigest'] = 'sha256:'+hashlib.sha256(canonical(workflow)).hexdigest()
    policies['schemaxis.workflow/1'] = workflow
    return policies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = ROOT/'src/schemaxis/mcp_admission.json'
    result = json.dumps(generate(), indent=2, ensure_ascii=False, allow_nan=False)+'\n'
    if args.check:
        if target.read_text() != result:
            raise SystemExit('Strict admission snapshot is stale; run tools/mcp_admission.py')
    else:
        target.write_text(result)
    print('Strict admission snapshot '+('checked' if args.check else 'generated'))


if __name__ == '__main__':
    main()
