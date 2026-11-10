"""Serve an explicitly selected set of files, without exposing the filesystem."""
import argparse
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import webbrowser

from .library import inventory, LocalLibrary, browse, history_file
from .transport import ViewerTransport

from . import WEB_ROOT as WEB


def make_server(inputs=(), port=0, *, history=None):
    library = LocalLibrary(history)
    initial = library.register(inputs) if inputs else None
    records = library.collections[initial]['records'] if initial else []
    allowed = {item['id']: item['_path'] for item in records}
    fingerprints = {item['id']: (item['_path'].stat().st_size, item['_path'].stat().st_mtime_ns) for item in records}
    token = secrets.token_urlsafe(24)
    prefix = '/' + token + '/'

    class Handler(ViewerTransport, BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            route = urlsplit(self.path).path
            if not route.startswith(prefix):
                self.send_error(404)
                return
            route = route[len(prefix):]
            if route.startswith('api/'):
                try:
                    self.authorised()
                    query = {key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()}
                    if route == 'api/library':
                        return self.respond(json.dumps(library.listing()).encode(), 'application/json', head)
                    if route == 'api/browse':
                        return self.respond(json.dumps(browse(query.get('directory'))).encode(), 'application/json', head)
                    if route == 'api/inventory':
                        return self.respond(json.dumps(library.records(query['id'], prefix+'api/')).encode(), 'application/json', head)
                    if route.startswith('api/file/'):
                        identity, index = route[len('api/file/'):].split('/')
                        return self.serve_file(library.file(identity, index), head, artifact=True)
                except PermissionError:
                    return self.send_error(403)
                except ValueError as error:
                    return self.failure(409, str(error), 'STALE_COLLECTION')
                except (KeyError, IndexError, OSError):
                    return self.send_error(404)
                return self.send_error(404)
            if route == 'inventory.json':
                payload = [{key: value for key, value in item.items() if not key.startswith('_')} |
                           {'url': prefix + 'file/' + item['id']} for item in records]
                self.respond(json.dumps(payload).encode(), 'application/json', head)
                return
            if route.startswith('file/'):
                path = allowed.get(route[5:])
                if path is None:
                    self.send_error(404)
                    return
                try:
                    observed = path.stat()
                    if (observed.st_size, observed.st_mtime_ns) != fingerprints[route[5:]]:
                        self.send_error(409, 'Selected file changed; restart the viewer to rescan')
                        return
                except OSError:
                    self.send_error(404, 'Selected file is no longer available')
                    return
                self.serve_file(path, head, artifact=True)
                return
            path = WEB / (route or 'index.html')
            if path.parent != WEB or not path.is_file():
                self.send_error(404)
                return
            self.serve_file(path, head)

        def authorised(self):
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                raise PermissionError('Invalid local host')
            origin = self.headers.get('Origin')
            if origin and origin != f'http://127.0.0.1:{self.server.server_port}':
                raise PermissionError('Cross-origin request denied')

        def do_POST(self):
            try:
                self.authorised()
                route = urlsplit(self.path).path
                if route not in (prefix+'api/open', prefix+'api/preferences'):
                    return self.send_error(404)
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 65536:
                    return self.send_error(400)
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    raise ValueError('Provide a local folder request')
                if route == prefix+'api/preferences':
                    return self.respond(json.dumps(library.set_preferences(request)).encode(), 'application/json', False)
                paths = request.get('paths')
                if not isinstance(paths, list) or not paths or len(paths) > 100 or not all(isinstance(p, str) for p in paths):
                    raise ValueError('Choose a local folder')
                identity = library.register(paths)
                self.respond(json.dumps({'id': identity, 'records': library.records(identity, prefix+'api/'), 'sources': library.sources(identity)}).encode(), 'application/json', False)
            except PermissionError:
                self.send_error(403)
            except (OSError, ValueError, TypeError) as error:
                self.failure(400, str(error), 'INVALID_COLLECTION')


    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.library = library
    server.viewer_url = f'http://127.0.0.1:{server.server_port}{prefix}'
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description='Explore local artifacts, sequences and spatial image planes')
    parser.add_argument('paths', nargs='*', help='Files and/or folders; folders are scanned recursively')
    parser.add_argument('--port', type=int, default=0, help='Local port (default: choose an available port)')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    try:
        server = make_server(args.paths, args.port, history=history_file())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f'Artifact viewer: {server.viewer_url}', flush=True)
    print('Local, read-only session. Ctrl+C stops the viewer.', flush=True)
    if not args.no_browser:
        webbrowser.open(server.viewer_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
