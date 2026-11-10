"""Local module provisioning and reviewed cache cleanup commands."""
from pathlib import Path


def arguments(commands):
    parser = commands.add_parser('modules', help='manage packaged applications, execution preferences and cache')
    actions = parser.add_subparsers(dest='module_action', required=True)
    actions.add_parser('list', help='inspect registered modules, images and retained downloads')
    register = actions.add_parser('register', help='register a trusted, qualified module manifest')
    register.add_argument('manifest', type=Path)
    fetch = actions.add_parser('fetch', help='fetch registered application images or restore saved downloads')
    fetch.add_argument('module', nargs='+')
    fetch.add_argument('--keep-download', action='store_true', help='also retain an offline image archive')
    fetch.add_argument('--offline', action='store_true', help='use installed images or saved archives only')
    settings = actions.add_parser('settings', help='read or change managed workflow execution preferences')
    settings.add_argument('--backend', choices=('container', 'native'))
    downloads = settings.add_mutually_exclusive_group()
    downloads.add_argument('--allow-downloads', dest='downloads', action='store_true')
    downloads.add_argument('--offline', dest='downloads', action='store_false')
    settings.set_defaults(downloads=None)
    cache = actions.add_parser('cache', help='review and explicitly clear selected managed runtime caches')
    operations = cache.add_subparsers(dest='cache_action', required=True)
    plan = operations.add_parser('plan', help='preview cache removal; preserve downloads unless selected')
    plan.add_argument('--module', action='append', required=True)
    plan.add_argument('--downloads', action='store_true', help='also remove verified saved image archives')
    plan.add_argument('--save', type=Path)
    clear = operations.add_parser('clear', help='apply an unchanged reviewed cleanup plan')
    clear.add_argument('plan', type=Path)
    clear.add_argument('--confirm', required=True, help='confirmation digest from the reviewed plan')


def execute(args):
    from .app_modules import ModuleManager, read_json
    from .storage import atomic, encoded
    manager = ModuleManager()
    if args.module_action == 'register':
        return manager.register(read_json(args.manifest))
    if args.module_action == 'list':
        return manager.inventory()
    if args.module_action == 'fetch':
        return manager.fetch(args.module, keep_download=args.keep_download, allow_download=not args.offline)
    if args.module_action == 'settings':
        current = manager.settings()
        if args.backend is None and args.downloads is None:
            return current
        return manager.configure(backend=args.backend or current['backend'],
            allow_downloads=current['allowDownloads'] if args.downloads is None else args.downloads)
    if args.cache_action == 'clear':
        return manager.clear(read_json(args.plan), args.confirm)
    plan = manager.cleanup_plan(args.module, downloads=args.downloads)
    if args.save:
        atomic(args.save, encoded(plan), exclusive=True)
    return plan


def execution_backend(args, locations):
    """An explicit native executable is itself a request for native execution."""
    from .errors import fail
    explicit_native = bool(args.executable or any(value is not None for value in locations.values()))
    if args.backend == 'container' and explicit_native:
        fail('INVALID_CONFIGURATION', 'choose native executable overrides or container execution, not both')
    return args.backend or ('native' if explicit_native else None)
