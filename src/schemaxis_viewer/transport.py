"""Read-only local media transport shared by standalone and embedded hosts."""
import mimetypes
import json


class ViewerTransport:
    def headers_for(self, mime, length):
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(length))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self' blob:; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors " + ("'self'" if getattr(self, 'viewer_embedded', False) else "'none'"))

    def respond(self, data, mime, head):
        self.send_response(200)
        self.headers_for(mime, len(data))
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def failure(self, status, message, code='VIEWER_ERROR'):
        payload = json.dumps({'fault': {'code': code, 'message': message}}).encode()
        self.send_response(status)
        self.headers_for('application/json', len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def serve_file(self, path, head, artifact=False):
        try:
            stream = path.open('rb')
        except OSError:
            self.send_error(404, 'Selected file is no longer available')
            return
        with stream:
            size = path.stat().st_size
            start, end = 0, size - 1
            partial = self.headers.get('Range')
            if partial:
                try:
                    unit, values = partial.split('=')
                    a, b = values.split('-')
                    if unit != 'bytes' or ',' in values:
                        raise ValueError()
                    if a:
                        start = int(a)
                        end = min(int(b), end) if b else end
                    else:
                        count = int(b)
                        if count <= 0:
                            raise ValueError()
                        start = max(0, size - count)
                    if not 0 <= start <= end < size:
                        raise ValueError()
                except ValueError:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            if path.suffix == '.mjs':
                mime = 'text/javascript'
            # Authored HTML is an artifact to inspect/download, never an app.
            if artifact and mime in ('text/html', 'application/xhtml+xml', 'text/javascript'):
                mime = 'text/plain'
            self.send_response(206 if partial else 200)
            self.headers_for(mime, max(0, end - start + 1))
            self.send_header('Accept-Ranges', 'bytes')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if head:
                return
            stream.seek(start)
            remaining = end - start + 1
            try:
                while remaining > 0:
                    block = stream.read(min(remaining, 256 * 1024))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError):
                pass
