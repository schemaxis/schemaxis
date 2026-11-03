# Copyright (C) 2026 David L F Gaden
"""Small integration harness for static discovery, planning and execution."""
import argparse
import json
import sys
from pathlib import Path

from schemaxis.core.catalogue import Catalogue, CatalogueError
from schemaxis.core.executor import Executor
from schemaxis.core.documents import load_document, resolve_document
from schemaxis.core.planner import Planner, PlanningError
from schemaxis.core.extensions import ExtensionError
from schemaxis.core.faults import SchemaxisError, Fault


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('describe', help='read the static capability manifest without loading ParaView')
    commands.add_parser('export-manifest', help='regenerate static JSON from the in-source dictionary')
    inspect = commands.add_parser('inspect-native', help='start ParaView to capture native metadata for review')
    inspect.add_argument('--group', default='filters')
    inspect.add_argument('--proxy', default='Cut')
    inspect.add_argument('--output-directory', type=Path, required=True)
    for verb in ('list', 'help'):
        command = commands.add_parser(verb, help='browse retained native command/property hierarchy')
        command.add_argument('path', nargs='?', default='')
        command.add_argument('--json', action='store_true')
        command.add_argument('--recursive', action='store_true', help='include all descendants')
    capture = commands.add_parser('inspect-commands', help='capture installed native definitions and Python function namespace')
    capture.add_argument('--output-directory', type=Path, required=True)
    help_option = commands.add_parser('help-option', help='show retained upstream help without starting ParaView')
    help_option.add_argument('option')
    for verb in ('plan', 'run'):
        run = commands.add_parser(verb, help='validate and resolve input' if verb == 'plan' else 'plan and execute input')
        run.add_argument('input', help='JSON file, or - for standard input')
        run.add_argument('--case-file', help='override case.file for a single real-case step')
        run.add_argument('--output-directory', help='override outputDirectory for a single-step document')
    args = parser.parse_args()
    package = Path(__file__).parent
    if args.command in ('list', 'help'):
        from .hierarchy import help_at
        result = help_at(args.path, recursive=args.recursive)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if args.command == 'help':
                print(result['path'] or 'ParaView')
                print(result.get('version') or '')
                print(result.get('documentation', {}).get('description') or 'No upstream description captured at this level.')
                if 'adaptor' in result:
                    print('Schemaxis: ' + json.dumps(result['adaptor']))
            for child in result['children']:
                print('  ' * child.get('depth', 0) + child['path'] + ' [' + child['status'] + ']')
        return 0
    if args.command == 'inspect-commands':
        from .intake import inspect_commands
        print(json.dumps(inspect_commands(args.output_directory).to_dict(), indent=2))
        return 0
    if args.command == 'inspect-native':
        from .intake import inspect_native
        print(json.dumps(inspect_native(args.group, args.proxy, args.output_directory).to_dict(), indent=2))
        return 0
    if args.command == 'help-option':
        from .native_help import option_help
        print(json.dumps(option_help(args.option), indent=2))
        return 0
    if args.command == 'export-manifest':
        from .slice_export import SliceExport
        SliceExport.export_manifest(package / 'capabilities/slice_export.json')
        return 0
    catalogue = Catalogue.from_roots([package])
    if args.command == 'describe':
        print(json.dumps([record.document for record in catalogue], indent=2))
        return 0
    authored = load_document(sys.stdin.read() if args.input == '-' else Path(args.input).read_text(encoding='utf-8'))
    document, references = resolve_document(authored)
    if args.output_directory or args.case_file:
        if not isinstance(document.get('steps'), list) or len(document['steps']) != 1 or not isinstance(document['steps'][0], dict):
            raise SchemaxisError(Fault('INVALID_OVERRIDE', '--output-directory requires a single-step document',
                                 '$/steps', 'input'))
        arguments = document['steps'][0].setdefault('arguments', {})
        if not isinstance(arguments, dict):
            raise ValueError('step arguments must be an object')
        if args.output_directory:
            arguments['outputDirectory'] = args.output_directory
        if args.case_file:
            if not isinstance(arguments.get('case'), dict):
                raise ValueError('--case-file requires a real-case step')
            arguments['case']['file'] = args.case_file
    plan = Planner(catalogue).resolve(document)
    report = {'resolvedDocument': document, 'documentReferences': references,
              'overrides': {key: value for key, value in {'outputDirectory': args.output_directory, 'caseFile': args.case_file}.items() if value},
              'plan': plan.to_dict()}
    if args.command == 'plan':
        print(json.dumps(report, indent=2))
        return 0
    result = Executor(catalogue).execute(plan.to_dict())
    print(json.dumps({**report, 'execution': result.to_dict()}, indent=2))
    return 0 if result.state.value == 'succeeded' else 1


if __name__ == '__main__':
    try:
        status = main()
    except (SchemaxisError, ExtensionError) as error:
        print(json.dumps({'fault': error.fault.to_dict()}, indent=2))
        status = 1
    except (PlanningError, CatalogueError, OSError, ValueError) as error:
        fault = Fault(getattr(error, 'code', 'INVALID_INPUT'), str(error),
                      str(getattr(error, 'location', None) or '$'), 'validation')
        print(json.dumps({'fault': fault.to_dict()}, indent=2))
        status = 1
    raise SystemExit(status)
