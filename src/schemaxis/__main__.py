"""Shared module and installed-command entry points for Schemaxis."""
import argparse
import json
import sys
from pathlib import Path
from schemaxis.core.documents import load_document
from schemaxis.core.faults import SchemaxisError, Fault
from .adaptors import registry


def project_version():
    """Read installed distribution metadata, or the uninstalled checkout's source."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version('schemaxis')
    except PackageNotFoundError:
        # Python 3.10 has no tomllib. Only read the project's literal version;
        # never execute build configuration or maintain a second version string.
        import re
        source = Path(__file__).resolve().parents[2] / 'pyproject.toml'
        if source.is_file():
            project = re.search(r'(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)', source.read_text(encoding='utf-8'))
            found = re.search(r'''(?m)^version\s*=\s*["']([^"']+)["']\s*$''', project[1]) if project else None
            if found:
                return found[1]
        raise ValueError('Schemaxis version metadata is missing; reinstall the package')


class _VersionAction(argparse.Action):
    """Resolve packaging metadata only when the version flag is requested."""
    def __call__(self, parser, namespace, values, option_string=None):
        try:
            value = project_version()
        except ValueError as error:
            parser.error(str(error))
        print(parser.prog + ' ' + value)
        parser.exit()


def command_topics(parser, prefix=()):
    """Project the actual parser's commands and summaries, including nested paths."""
    topics = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                summary = next((item.help for item in action._choices_actions
                                if action.choices.get(item.dest) is child), '')
                path = (*prefix, name)
                topics.append({'command': ' '.join(path), 'summary': summary,
                               'help': 'schemaxis ' + ' '.join(path) + ' --help'})
                topics.extend(command_topics(child, path))
    return topics


def help_topic(parser, args):
    """Exact command paths show argparse help; keywords share capability discovery."""
    query = ' '.join(args.topic)
    current = parser
    for name in args.topic:
        children = next((a.choices for a in current._actions
                         if isinstance(a, argparse._SubParsersAction)), {})
        if name not in children:
            current = None
            break
        current = children[name]
    if current is not None and not args.search:
        current.print_help()
        return None
    if not query.strip():
        parser.error('help --search needs a nonempty keyword or topic')
    from .capabilities import CapabilityCatalogue
    tokens = query.casefold().split()
    commands = [topic for topic in command_topics(parser)
                if all(token in (topic['command'] + ' ' + topic['summary']).casefold()
                       for token in tokens)]
    return {'query': query, 'commands': commands,
            'capabilities': CapabilityCatalogue().search(query, scope=args.scope,
                input_kind=args.input_kind, output_kind=args.output_kind,
                limit=args.limit, cursor=args.cursor, max_bytes=args.max_bytes,
                revision=args.revision)}


def authored_input(filename, format=None):
    """Load human-authored syntax; retained worker records stay strict JSON."""
    from .core.documents import load_document_file
    if str(filename) == '-':
        return load_document(sys.stdin.read(), format=format or 'json')
    return load_document_file(filename, format=format)


def build_parser():
    """The complete command-line parser, including admitted adaptors' ``cliOptions``."""
    from .adaptors.registry import ADAPTORS
    parser = argparse.ArgumentParser(prog='schemaxis', description='Schemaxis declared application pipelines',
        epilog="Use 'schemaxis COMMAND --help' for command options, 'schemaxis help KEYWORDS' "
               "to search commands and operations, or 'schemaxis capabilities browse' to explore applications.")
    parser.add_argument('--version', action=_VersionAction, nargs=0,
                        help="show the installed project's version and exit")
    commands = parser.add_subparsers(dest='command', required=True)
    help_command = commands.add_parser('help', help='show command help or search commands and capability topics')
    help_command.add_argument('topic', nargs='*', help='command path or operation keywords')
    help_command.add_argument('--search', action='store_true', help='search even when the topic is an exact command path')
    help_command.add_argument('--scope', default='root', help='capability scope, e.g. app/freecad or domain/geometry')
    help_command.add_argument('--input-kind')
    help_command.add_argument('--output-kind')
    help_command.add_argument('--limit', type=int, default=12)
    help_command.add_argument('--cursor')
    help_command.add_argument('--max-bytes', type=int, default=8192)
    help_command.add_argument('--revision')
    storage = commands.add_parser('storage', help='inspect storage and plan portable backups, archives and restoration')
    storage_actions = storage.add_subparsers(dest='storage_action', required=True)
    storage_inspect = storage_actions.add_parser('inspect', help='inspect selected case storage, schema references and configured installations')
    storage_inspect.add_argument('--root', type=Path, required=True)
    storage_inspect.add_argument('--no-installations', action='store_true', help='omit private configured application locations')
    storage_plan = storage_actions.add_parser('plan', help='dry-run explicit case preservation or restoration; sources are retained')
    storage_plan.add_argument('--action', choices=('backup', 'archive', 'compress', 'restore'), required=True)
    storage_plan.add_argument('--root', type=Path)
    storage_plan.add_argument('--run', action='append', default=[], help='explicit case path relative to root; may be repeated')
    storage_plan.add_argument('--destination', type=Path, required=True)
    storage_plan.add_argument('--archive', type=Path, help='archive file or backup directory to restore')
    storage_plan.add_argument('--older-than-days', type=float, default=0)
    storage_plan.add_argument('--max-bytes', type=int, default=8*1024**3, help='maximum restored content bytes (default: 8 GiB)')
    storage_plan.add_argument('--save', type=Path, help='exclusively save the reviewed plan as JSON')
    storage_apply = storage_actions.add_parser('apply', help='apply an unchanged saved plan with its explicit confirmation digest')
    storage_apply.add_argument('plan', type=Path)
    storage_apply.add_argument('--confirm', required=True, help='confirmation digest from the reviewed plan')
    policy = storage_actions.add_parser('policy', help='create opt-in interval policies and generate due plans; no worker is installed')
    policies = policy.add_subparsers(dest='policy_action', required=True)
    policy_create = policies.add_parser('create', help='save a plan-only named policy without starting or scheduling cleanup')
    policy_create.add_argument('file', type=Path)
    policy_create.add_argument('--name', required=True)
    policy_create.add_argument('--root', type=Path, required=True)
    policy_create.add_argument('--run', action='append', required=True)
    policy_create.add_argument('--destination', type=Path, required=True)
    policy_create.add_argument('--action', choices=('backup', 'archive', 'compress'), default='compress')
    policy_create.add_argument('--every-days', type=float, required=True)
    policy_create.add_argument('--first-due', required=True, help='ISO 8601 time with UTC offset')
    policy_create.add_argument('--older-than-days', type=float, default=0)
    policy_due = policies.add_parser('due', help='generate the current interval plan without applying it or updating a timer')
    policy_due.add_argument('file', type=Path)
    policy_due.add_argument('--now', help='explicit ISO 8601 instant for deterministic preview')
    schedule = commands.add_parser('schedule', help='durable future Schemaxis execution')
    schedule.add_argument('--workspace', type=Path, required=True, help='shared schedule store, also used by the independent worker')
    schedule_actions = schedule.add_subparsers(dest='schedule_action', required=True)
    for action in ('create', 'preview'):
        sub = schedule_actions.add_parser(action)
        sub.add_argument('spec', help='JSON/YAML schedule declaration, or - for stdin')
        sub.add_argument('--input-format', choices=('json', 'yaml'))
        if action == 'preview': sub.add_argument('--count', type=int, default=5)
    schedule_actions.add_parser('list')
    show = schedule_actions.add_parser('show')
    show.add_argument('id')
    for action in ('pause', 'resume', 'cancel', 'delete', 'update'):
        sub = schedule_actions.add_parser(action)
        sub.add_argument('id')
        sub.add_argument('--revision', type=int, required=True)
        if action == 'update':
            sub.add_argument('changes', help='JSON/YAML changes file, or - for stdin')
            sub.add_argument('--input-format', choices=('json', 'yaml'))
    worker = schedule_actions.add_parser('serve', help='run the independent foreground schedule worker')
    worker.add_argument('--poll-seconds', type=float, default=1)
    convert = commands.add_parser('convert', help='convert authored JSON/YAML values; JSON export omits YAML comments')
    convert.add_argument('input')
    convert.add_argument('--input-format', choices=('json', 'yaml'))
    convert.add_argument('--to', choices=('json', 'yaml'), required=True)
    convert.add_argument('--output', type=Path, help='write to a new file; default prints source')
    readiness = commands.add_parser('readiness', help='audit host-only adaptor admission and delivery gaps')
    readiness.add_argument('--app', action='append', choices=tuple(ADAPTORS))
    readiness.add_argument('--repository-root', type=Path, help='matching source checkout for delivery links')
    readiness.add_argument('--check', action='store_true', help='fail if required structural checks are incomplete')
    readiness.add_argument('--admission', action='store_true', help='require the complete development-kit delivery contract')
    adaptor = commands.add_parser('adaptor', help='adaptor context, scaffolding and reusable conformance')
    kit = adaptor.add_subparsers(dest='adaptor_action', required=True)
    context = kit.add_parser('context', help='bounded route-specific delivery context')
    context.add_argument('version')
    context.add_argument('--pointer', default='')
    context.add_argument('--offset', type=int, default=0)
    context.add_argument('--limit', type=int, default=12)
    context.add_argument('--max-bytes', type=int, default=8192)
    context.add_argument('--revision')
    conform = kit.add_parser('conform', help='reusable host or opt-in native admission checks')
    conform.add_argument('version')
    conform.add_argument('--output-directory', type=Path, required=True)
    conform.add_argument('--repository-root', type=Path)
    conform.add_argument('--native', action='store_true')
    conform.add_argument('--timeout', type=float, default=120)
    conform.add_argument('--wall-timeout', type=float, default=300, help='independent per-case wall-clock ceiling')
    conform.add_argument('--executable', help='explicit runtime for the selected adaptor')
    record = kit.add_parser('record', help='register a successful current-source native qualification receipt')
    record.add_argument('receipt', type=Path)
    scaffold = kit.add_parser('scaffold', help='generate an unqualified source overlay without installing it')
    scaffold.add_argument('provider')
    scaffold.add_argument('--output-directory', type=Path, required=True)
    scaffold.add_argument('--model', choices=('nodes', 'document'), default='nodes')
    updates = commands.add_parser('updates', help='check unabsorbed upstream stable releases and estimate migration work')
    updates.add_argument('--app', action='append', choices=tuple(ADAPTORS))
    updates.add_argument('--prepare', type=Path, help='write a report and AI repair briefs')
    configure = commands.add_parser('configure', help='save an application location in private local configuration')
    configure.add_argument('provider', choices=tuple(ADAPTORS))
    configure.add_argument('location', help='executable or installation root')
    describe = commands.add_parser('describe', help='describe executable filter bindings without starting applications')
    describe.add_argument('filter', nargs='?')
    describe.add_argument('--provider', choices=tuple(ADAPTORS), default=registry.default_provider())
    schema = commands.add_parser('schema', help='export standalone authored/expanded JSON Schema or literal options')
    schema.add_argument('--provider', choices=tuple(ADAPTORS), default=registry.default_provider())
    schema.add_argument('--input-format', choices=('json', 'yaml'))
    mode = schema.add_mutually_exclusive_group()
    mode.add_argument('--authored', action='store_true', help='include parser-supported authored composition, inline objects and analytics')
    mode.add_argument('--expanded', action='store_true', help='export expanded input (default except --all)')
    from .schema_authoring import VERSIONS
    target = schema.add_mutually_exclusive_group()
    target.add_argument('--version', choices=tuple(VERSIONS), help='select an exact routed input document version')
    target.add_argument('--operation', help='export one operation options schema')
    target.add_argument('--section', choices=('camera', 'series', 'workflow', 'execution', 'operation-execution', 'composition', 'analytic', *[k for item in ADAPTORS.values() for k in item.get('sections', {})]))
    target.add_argument('--all', dest='schema_all', action='store_true', help='standalone umbrella for all registered versions; authored unless --expanded')
    target.add_argument('--expand', metavar='INPUT', help='emit composition/inline/analytic-expanded pipeline JSON for schema checking')
    commands.add_parser('discover', help='list provider contracts without starting applications')
    template = commands.add_parser('template', help='inspect, bind and plan reusable workflow templates without native execution')
    template_actions = template.add_subparsers(dest='template_action', required=True)
    template_inspect = template_actions.add_parser('inspect', help='read a validated template bundle and its semantic digest')
    template_inspect.add_argument('filename', type=Path)
    for action in ('bind', 'plan'):
        template_action = template_actions.add_parser(action, help=action + ' an exact template revision and case')
        template_action.add_argument('filename', type=Path)
        template_action.add_argument('--values', required=True, help='case JSON file, or - for standard input')
        template_action.add_argument('--input-format', choices=('json', 'yaml'), help='case values syntax')
        if action == 'bind':
            template_action.add_argument('--document-only', action='store_true', help='emit the ordinary workflow document instead of the binding record')
    agent = commands.add_parser('agent', help='local JSON-lines agent tools over the shared execution service')
    agent.add_argument('--workspace', type=Path, required=True)
    capabilities = commands.add_parser('capabilities', help='bounded capability navigation and selected contracts')
    actions = capabilities.add_subparsers(dest='capability_action', required=True)
    browse = actions.add_parser('browse', help='browse root, application or group summaries')
    browse.add_argument('scope', nargs='?', default='root')
    search = actions.add_parser('search', help='search declared operations by deterministic keywords and kinds')
    search.add_argument('query')
    search.add_argument('--scope', default='root')
    search.add_argument('--input-kind')
    search.add_argument('--output-kind')
    schema_parts = actions.add_parser('schema', help='read bounded fragments of an authoritative document schema')
    schema_parts.add_argument('identity')
    schema_parts.add_argument('--pointer', default='', help='JSON Pointer; empty selects the schema root')
    for listing in (browse, search, schema_parts):
        listing.add_argument('--limit', type=int, default=12)
        listing.add_argument('--cursor')
        listing.add_argument('--max-bytes', type=int, default=8192)
        listing.add_argument('--revision')
    detail = actions.add_parser('describe', help='retrieve complete selected operation contract sections')
    detail.add_argument('identity')
    detail.add_argument('--section', action='append', dest='sections')
    detail.add_argument('--known-digest')
    detail.add_argument('--revision')
    coverage = commands.add_parser('coverage', help='report adaptor native inventory and binding gaps')
    coverage.add_argument('--provider', choices=tuple(ADAPTORS), default=registry.default_provider())
    query = commands.add_parser('query', help='identify adaptor requirements without starting applications')
    query.add_argument('input', nargs='?')
    query.add_argument('--input-format', choices=('json', 'yaml'))
    query.add_argument('--operations', nargs='+')
    reference = commands.add_parser('reference', help='generate schemas, reference pages and module index')
    reference.add_argument('--check', action='store_true')
    reference.add_argument('--output-directory', type=Path, default=None)
    commands.add_parser('functions', help='describe typed runtime functions')
    commands.add_parser('colours', help='list retained Matplotlib colour names without importing Matplotlib')
    console = commands.add_parser('console', aliases=['schemaxis'], help='persistent bounded multi-adaptor console')
    from .console_session import CONSOLE_TYPES
    console.add_argument('--provider', choices=tuple(CONSOLE_TYPES), default=registry.default_provider(console=True))
    for item in ADAPTORS.values():
        for option in item.get('cliOptions', []):
            if option['dest'] == item['id']:
                console.add_argument(option['flag'], dest=option['dest'], help=option['help'])
    console.add_argument('--executable', help='provider executable or installation root')
    console.add_argument('--workspace', type=Path, default=Path('.schemaxis'))
    console.add_argument('--web', action='store_true', help='serve Schemaxis Studio, the local graphical interface')
    console.add_argument('--port', type=int, default=0, help='loopback viewer port (default: automatically selected)')
    console.add_argument('--command', dest='console_commands', action='append', help='execute a command and exit; may be repeated')
    for command in ('plan', 'run', 'inspect'):
        sub = commands.add_parser(command, help={
            'plan': 'validate and plan a declared input without starting applications',
            'run': 'execute a declared input and retain verified evidence',
            'inspect': 'inspect typed native data from a declared input',
        }[command])
        sub.add_argument('input', help='JSON/YAML file or - for stdin')
        sub.add_argument('--input-format', choices=('json', 'yaml'))
        if command in ('run', 'inspect'):
            sub.add_argument('--output-directory', required=True)
            sub.add_argument('--executable', help='executable/location for the selected adaptor')
            for item in ADAPTORS.values():
                for option in item.get('cliOptions', []):
                    sub.add_argument(option['flag'], **{k: v for k, v in option.items() if k != 'flag'})
            sub.add_argument('--timeout', type=float, default=300)
        if command == 'run':
            sub.add_argument('--resume', action='store_true', help='reuse verified workflow attempts and retry unfinished jobs')
        if command == 'inspect':
            sub.add_argument('--node', required=True)
            sub.add_argument('--visit', type=int, default=0)
    verify = commands.add_parser('verify', help='check retained receipt membership and artifact digests')
    verify.add_argument('directory')
    return parser


def main():
    from .adaptors.registry import ADAPTORS
    parser = build_parser()
    args = parser.parse_args()
    if args.command == 'help':
        return help_topic(parser, args)
    if args.command == 'storage':
        from . import storage_management as management
        from .storage import atomic, encoded, load
        if args.storage_action == 'inspect':
            return management.inspect(args.root, installations=not args.no_installations)
        if args.storage_action == 'apply':
            return management.apply_plan(load(args.plan.read_text()), args.confirm)
        if args.storage_action == 'policy':
            if args.policy_action == 'due':
                return management.due_policy(args.file, now=args.now)
            return management.create_policy(args.file, name=args.name, root=args.root,
                runs=args.run, destination=args.destination, every_days=args.every_days,
                first_due=args.first_due, older_than_days=args.older_than_days, action=args.action)
        if args.action == 'restore' and args.archive is None:
            parser.error('storage plan --action restore requires --archive')
        if args.action != 'restore' and (args.root is None or not args.run):
            parser.error('storage plan requires --root and explicit --run selections')
        result = management.plan(args.root, args.run, action=args.action,
            destination=args.destination, archive=args.archive,
            older_than_days=args.older_than_days, max_bytes=args.max_bytes)
        if args.save:
            atomic(args.save, encoded(result), exclusive=True)
        return result
    if args.command == 'schedule':
        from .scheduler import SchedulerStore, SchedulerRunner
        store = SchedulerStore(args.workspace)
        action = args.schedule_action
        if action in ('create', 'preview'):
            spec = authored_input(args.spec, args.input_format)
            return store.create(spec) if action == 'create' else store.preview(spec, count=args.count)
        if action == 'list': return store.list()
        if action == 'show': return store.get(args.id)
        if action == 'update':
            return store.update(args.id, args.revision, authored_input(args.changes, args.input_format))
        if action != 'serve': return getattr(store, action)(args.id, args.revision)
        import signal
        import threading
        import math
        if not math.isfinite(args.poll_seconds) or not 0.05 <= args.poll_seconds <= 60:
            parser.error('--poll-seconds must be finite and between 0.05 and 60')
        stop = threading.Event()
        previous = {signum: signal.signal(signum, lambda *_: stop.set())
                    for signum in (signal.SIGINT, signal.SIGTERM)}
        runner = None
        try:
            runner = SchedulerRunner(args.workspace)
            runner.serve(stop, poll_seconds=args.poll_seconds)
            return {'status': 'stopped', 'workspace': str(args.workspace)}
        finally:
            if runner is not None: runner.close()
            for signum, handler in previous.items(): signal.signal(signum, handler)
    if args.command == 'convert':
        from .source_formats import dump_document
        source = dump_document(authored_input(args.input, args.input_format), format=args.to)
        if args.output:
            from .storage import atomic
            atomic(args.output, source.encode('utf-8'), exclusive=True)
            return {'file': str(args.output), 'format': args.to,
                    'presentation': 'conversion preserves values; YAML comments are omitted'}
        sys.stdout.write(source)
        return None
    if args.command == 'readiness':
        from .readiness import report, enforce
        result = report(args.app, root=args.repository_root, admission=args.admission)
        return enforce(result) if args.check else result
    if args.command == 'adaptor':
        if args.adaptor_action == 'scaffold':
            from .adaptor_scaffold import scaffold
            return scaffold(args.provider, args.output_directory, model=args.model)
        if args.adaptor_action == 'conform':
            from .adaptor_conformance import qualify
            provider, _ = registry.resolve({'version': args.version})
            locations = {provider: args.executable} if args.executable else None
            return qualify(args.version, args.output_directory, native=args.native,
                           root=args.repository_root, locations=locations, timeout=args.timeout, wall_timeout=args.wall_timeout)
        if args.adaptor_action == 'record':
            from .adaptor_conformance import register
            return register(args.receipt)
        from .adaptor_delivery import context
        return context(args.version, pointer=args.pointer, offset=args.offset, limit=args.limit,
                       max_bytes=args.max_bytes, revision=args.revision)
    if args.command == 'agent':
        from .agent_transport import serve
        serve(args.workspace)
        return None
    if args.command == 'updates':
        from .updates import report, prepare
        result = report(args.app)
        if args.prepare: result['preparedDirectory'] = prepare(result, args.prepare)
        return result
    if args.command == 'configure':
        from .configuration import configure
        return configure(args.provider, args.location)
    if args.command == 'coverage':
        path = ADAPTORS[args.provider].get('coverage')
        if not path:
            from .errors import fail
            fail('UNSUPPORTED_CAPABILITY', 'adaptor does not publish native coverage')
        return registry.binding(path)()
    if args.command == 'schema':
        from .schema import export_schema, expand_input
        if args.expand:
            return expand_input(authored_input(args.expand, args.input_format))
        return export_schema(args.provider, args.operation, args.section,
            authored=args.authored or (args.schema_all and not args.expanded), version=args.version, all_versions=args.schema_all)
    if args.command == 'reference':
        from .reference import generate
        return generate(args.output_directory, check=args.check)
    if args.command == 'query':
        from .adaptors.registry import query
        if bool(args.input) == bool(args.operations):
            parser.error('query needs either INPUT or --operations')
        document = authored_input(args.input, args.input_format) if args.input else None
        return query(document, args.operations)
    if args.command == 'capabilities':
        from .capabilities import CapabilityCatalogue
        catalogue = CapabilityCatalogue()
        if args.capability_action == 'describe':
            return catalogue.describe(args.identity, sections=args.sections,
                                      known_digest=args.known_digest, revision=args.revision)
        options = dict(limit=args.limit, cursor=args.cursor, revision=args.revision, max_bytes=args.max_bytes)
        if args.capability_action == 'schema':
            return catalogue.schema(args.identity, pointer=args.pointer, **options)
        if args.capability_action == 'search':
            return catalogue.search(args.query, scope=args.scope, input_kind=args.input_kind,
                                    output_kind=args.output_kind, **options)
        return catalogue.browse(args.scope, **options)
    if args.command == 'discover':
        from .adaptors.registry import discover
        return {**discover(), 'commands': [topic['command'] for topic in command_topics(parser)
                                          if ' ' not in topic['command']]}
    if args.command == 'template':
        from .workflow_templates import load_template, prepare_template
        from .storage import load
        if args.template_action == 'inspect':
            return load_template(args.filename)
        try:
            from .core.documents import document_format
            # Keep the established case/template JSON fault contract while YAML
            # enters through the optional authored-source boundary.
            if document_format(args.values, args.input_format) == 'json':
                values = load(sys.stdin.read() if args.values == '-' else Path(args.values).read_text(encoding='utf-8'))
            else:
                values = authored_input(args.values, args.input_format)
        except RecursionError:
            from .errors import fail
            fail('INVALID_DOCUMENT', 'case JSON exceeds supported nesting depth', '$.case')
        result = prepare_template(args.filename, values, planning=args.template_action == 'plan')
        return result['document'] if getattr(args, 'document_only', False) else result
    if args.command == 'functions':
        from .functions import FUNCTIONS
        return FUNCTIONS.describe()
    if args.command == 'colours':
        from .colours import palette
        return palette()
    if args.command in ('console', 'schemaxis'):
        from .console import AdaptorConsoleSession, ConsoleSession, run_console
        executable = args.executable or getattr(args, args.provider, None)
        session = AdaptorConsoleSession(args.workspace, provider=args.provider, executable=executable)
        try:
            if args.console_commands:
                for command in args.console_commands:
                    result = session.execute(command)
                    print(json.dumps({'ok': True, 'result': result}, indent=2))
            if args.web:
                from .studio_server import serve
                return serve(session, args.port)
            if not args.console_commands:
                run_console(session)
            return session.status()
        finally:
            session.close()
    if args.command == 'describe':
        from .adaptors.registry import declarations
        values = declarations(args.provider)
        if args.filter and args.filter not in values:
            from .errors import fail
            fail('UNKNOWN_FILTER', 'filter is not declared', args.filter, available=sorted(values))
        return values[args.filter] if args.filter else values
    if args.command == 'verify':
        directory = Path(args.directory)
        authored = load_document((directory/'authored.json').read_text()) if (directory/'authored.json').exists() else {}
        if authored.get('version') == 'schemaxis.workflow/1':
            from .workflow import verify
            return verify(directory)
        return registry.verify(directory, authored)
    document = authored_input(args.input, args.input_format)
    workflow = document.get('version') == 'schemaxis.workflow/1'
    if args.command == 'plan':
        if workflow:
            from .workflow import inspect_plan
            return inspect_plan(document)
        return registry.plan(document, legacy=True)
    locations = {option['dest']: getattr(args, option['dest'], None)
                 for item in ADAPTORS.values() for option in item.get('cliOptions', [])}
    if args.executable and not workflow:
        provider, _ = registry.resolve(document, legacy=True)
        locations[provider] = [args.executable] if ADAPTORS[provider].get('locationKind') == 'roots' else args.executable
    if args.command == 'inspect':
        from .inspection import inspect
        return inspect(document, args.node, args.output_directory, locations=locations, visit=args.visit, timeout=args.timeout)
    if args.resume and not workflow:
        from .errors import fail
        fail('UNSUPPORTED_RESUME', 'resume requires a workflow document')
    if workflow:
        from .workflow import execute
        return execute(document, args.output_directory, locations=locations, timeout=args.timeout, resume=args.resume)
    return registry.run(document, args.output_directory, locations=locations, timeout=args.timeout)


def console_main():
    try:
        result = main()
        if result is not None:
            print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except SchemaxisError as error:
        print(json.dumps(error.to_dict(), indent=2))
        return 1
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({'fault': Fault('INVALID_INPUT', str(error), '$', 'input').to_dict()}, indent=2))
        return 1


if __name__ == '__main__':
    sys.exit(console_main())
