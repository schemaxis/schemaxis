"""Reusable modern Streamable HTTP binding; trusted hosts supply authentication."""
import base64
from dataclasses import dataclass
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading

from .execution_service import ExecutionService
from .mcp import MAX_REQUEST, MODERN, McpDispatcher, ProtocolError, RequestContext, parse_message
from .storage import encoded


@dataclass(frozen=True)
class HttpRequest:
    method: str
    headers: object
    body: bytes = b''
    path: str = '/mcp'


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict
    body: bytes


class McpHttpBinding:
    def __init__(self, dispatcher, *, allowed_origins=()):
        self.dispatcher = dispatcher
        self.allowed_origins = frozenset(allowed_origins)

    @staticmethod
    def _response(status, value=None):
        data = b'' if value is None else encoded(value)
        return HttpResponse(status, {'Content-Type': 'application/json',
            'Content-Length': str(len(data)), 'Cache-Control': 'no-store'}, data)

    @staticmethod
    def _header_value(value):
        if value.startswith('=?base64?') and value.endswith('?='):
            return base64.b64decode(value[9:-2], validate=True).decode('utf-8')
        if any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError('invalid header characters')
        return value

    def handle(self, request, context):
        if request.path != '/mcp':
            return self._response(404)
        if request.method != 'POST':
            response = self._response(405)
            return HttpResponse(response.status, {**response.headers, 'Allow': 'POST'}, response.body)
        try:
            pairs = list(request.headers.items()) if hasattr(request.headers, 'items') else list(request.headers)
            headers = {}
            for name, value in pairs:
                lower = name.lower()
                if lower in headers or not isinstance(value, str):
                    raise ValueError('duplicate or invalid HTTP header')
                headers[lower] = value
        except Exception:
            return self._response(400)
        if 'origin' in headers and headers['origin'] not in self.allowed_origins:
            return self._response(403)
        try:
            self.dispatcher._check_context(context)
        except ProtocolError:
            return self._response(401)
        if len(request.body) > MAX_REQUEST:
            return self._response(413)
        if headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            return self._response(415)
        accept = {part.split(';')[0].strip().lower() for part in headers.get('accept', '').split(',')}
        if not {'application/json', 'text/event-stream'} <= accept:
            return self._response(406)
        identity = None
        try:
            message = parse_message(request.body)
            identity = message.get('id')
            if type(identity) not in (str, int) or len(str(identity)) > 128:
                identity = None
            params = message.get('params', {})
            if not isinstance(params, dict):
                raise ProtocolError(-32602, 'params must be an object')
            metadata = params.get('_meta', {})
            if not isinstance(metadata, dict):
                raise ProtocolError(-32602, '_meta must be an object')
            version = metadata.get('io.modelcontextprotocol/protocolVersion')
            if version is None:
                raise ProtocolError(-32602, 'modern protocolVersion metadata is required')
            if headers.get('mcp-protocol-version') != version or headers.get('mcp-method') != message.get('method'):
                raise ProtocolError(-32020, 'Header mismatch')
            if message.get('method') in {'tools/call', 'resources/read', 'prompts/get'}:
                field = 'uri' if message['method'] == 'resources/read' else 'name'
                try:
                    mirrored = self._header_value(headers['mcp-name'])
                except Exception:
                    raise ProtocolError(-32020, 'Missing or invalid Mcp-Name') from None
                if mirrored != params.get(field):
                    raise ProtocolError(-32020, 'Header mismatch')
            if version != MODERN:
                raise ProtocolError(-32022, 'Unsupported protocol version', {'supported': [MODERN], 'requested': version})
            response = self.dispatcher.handle(message, binding='http', context=context)
        except ProtocolError as error:
            return self._response(400, self.dispatcher._error(identity, error))
        if response is None:
            return self._response(202)
        code = response.get('error', {}).get('code')
        status = 404 if code == -32601 else 400 if code is not None else 200
        return self._response(status, response)


def serve_http(workspace, *, profile='declared-documents', port=8766, allowed_origins=()):
    """Loopback development host, not a production server or OAuth provider."""
    credential = os.environ.get('SCHEMAXIS_MCP_TOKEN', '')
    if len(credential) < 32 or any(ord(c) < 33 or ord(c) > 126 for c in credential):
        raise ValueError('set SCHEMAXIS_MCP_TOKEN to a private ASCII token of at least 32 characters')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('port must be 1..65535')
    with ExecutionService(workspace) as service:
        dispatcher = McpDispatcher(service, profile=profile)
        binding = McpHttpBinding(dispatcher, allowed_origins=allowed_origins)
        slots = threading.BoundedSemaphore(8)

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass  # Never log caller content, credentials or resource paths.

            def _handle(self):
                self.close_connection = True
                if not slots.acquire(blocking=False):
                    self.send_error(503)
                    return
                try:
                    self.connection.settimeout(10)
                    context = None
                    supplied = self.headers.get('Authorization', '')
                    if hmac.compare_digest(supplied, 'Bearer '+credential):
                        context = RequestContext('local-http', dispatcher.store.namespace, service)
                    if self.headers.get('Transfer-Encoding') is not None:
                        self.send_error(400)
                        return
                    try:
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 <= length <= MAX_REQUEST:
                            self.send_error(413)
                            return
                    except ValueError:
                        self.send_error(400)
                        return
                    body = self.rfile.read(length) if self.command == 'POST' else b''
                    if len(body) != length and self.command == 'POST':
                        self.send_error(400)
                        return
                    response = binding.handle(HttpRequest(self.command, list(self.headers.items()), body, self.path), context)
                    self.send_response(response.status)
                    for name, value in response.headers.items():
                        self.send_header(name, value)
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.wfile.write(response.body)
                finally:
                    slots.release()

            do_POST = do_GET = do_DELETE = do_OPTIONS = _handle

        with ThreadingHTTPServer(('127.0.0.1', port), Handler) as server:
            server.daemon_threads = True
            try:
                server.serve_forever(poll_interval=.25)
            except KeyboardInterrupt:
                pass
