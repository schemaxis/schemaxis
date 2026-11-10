# Copyright (C) 2026 David L F Gaden
"""Native application locations for a local Studio workspace, without launching apps."""
import os
from pathlib import Path

from .configuration import executable
from .console_session import CONSOLE_TYPES
from .errors import fail, keys


class StudioSetup:
    def __init__(self, app):
        self.app = app
        self.defaults = {name: executable(name) for name, item in CONSOLE_TYPES.items()
                         if not item.get('hostOnly')}

    def location(self, provider):
        configured = self.app.session._state['configurations'].get(provider, {})
        return configured.get('executable') or self.defaults.get(provider)

    @staticmethod
    def available(provider, location):
        if not location:
            return False
        path = Path(location)
        return path.exists() if CONSOLE_TYPES[provider].get('locationKind') == 'roots' else (
            path.is_file() and os.access(path, os.X_OK))

    def configure_default(self, provider):
        if provider in self.app.session._state['configurations']:
            return
        location = self.defaults.get(provider)
        if self.available(provider, location):
            self.app.session.configure(provider, location)

    def read(self):
        return {'applications': [{'provider': name, 'location': self.location(name),
                                  'available': self.available(name, self.location(name)),
                                  'locationKind': item.get('locationKind', 'executable'),
                                  'live': bool(item.get('consoleCapabilities', {}).get('liveGeometry'))}
                                 for name, item in sorted(CONSOLE_TYPES.items()) if not item.get('hostOnly')]}

    def request(self, request):
        keys(request, ('action', 'provider', 'location', 'role', 'module', 'manifest',
                       'backend', 'allowDownloads', 'keepDownload', 'downloads', 'plan', 'confirmation'), 'setup')
        action = request.get('action')
        if action in ('modules', 'registerModule', 'fetchModule', 'moduleSettings', 'cachePlan', 'cacheClear'):
            from .app_modules import ModuleManager, read_json
            manager = ModuleManager()
            if action == 'modules':
                return manager.inventory()
            if request.get('role') != 'admin':
                fail('SETTING_SCOPE', 'application modules are managed in administrator mode')
            with self.app.job_lock:
                if self.app.busy:
                    fail('SESSION_BUSY', 'wait for the current native operation to finish')
                if action == 'registerModule':
                    # Only local administrator-selected files, never manifests from a workflow.
                    return manager.register(read_json(request.get('manifest', '')))
                if action == 'fetchModule':
                    if type(request.get('keepDownload', False)) is not bool:
                        fail('INVALID_REQUEST', 'keepDownload must be a boolean')
                    return manager.fetch([request.get('module')], keep_download=request.get('keepDownload', False),
                                         allow_download=manager.settings()['allowDownloads'])
                if action == 'moduleSettings':
                    return manager.configure(backend=request.get('backend'), allow_downloads=request.get('allowDownloads'))
                if action == 'cachePlan':
                    if type(request.get('downloads', False)) is not bool:
                        fail('INVALID_REQUEST', 'downloads must be a boolean')
                    return manager.cleanup_plan([request.get('module')], downloads=request.get('downloads', False))
                return manager.clear(request.get('plan'), request.get('confirmation'))
        with self.app.job_lock:
            if self.app.busy:
                fail('SESSION_BUSY', 'wait for the current native operation to finish')
            with self.app.lock:
                if request.get('action') == 'read':
                    return self.read()
                if request.get('action') != 'configure':
                    fail('INVALID_REQUEST', 'choose read or configure', 'action')
                if request.get('role') != 'admin':
                    fail('SETTING_SCOPE', 'application locations are managed in administrator mode', 'role')
                provider, location = request.get('provider'), request.get('location')
                if provider not in self.defaults or not isinstance(location, str):
                    fail('INVALID_CONFIGURATION', 'choose an adaptor and its executable or installation root')
                self.app.session.configure(provider, str(Path(location).expanduser()))
                self.app.refresh_snapshot()
                return self.read()
