"""A loopback-only canary listener for EPUBCheck network probes: one owned thread, bounded lifetime, never reachable from another host.

It records the request line of every connection and answers each with an empty 200, so a checker that fetches a DTD from it continues normally.
"""
import socket
import threading
import time


class Loopback:
    def __init__(self, lifetime=300):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(8)
        self.listener.settimeout(0.2)
        self.port, self.requests, self.stop = self.listener.getsockname()[1], [], threading.Event()
        self.deadline = time.monotonic() + lifetime
        self.thread = threading.Thread(target=self.serve)
        self.thread.start()

    def serve(self):
        while not self.stop.is_set() and time.monotonic() < self.deadline:
            try:
                connection, _ = self.listener.accept()
            except OSError:
                continue
            try:
                connection.settimeout(1.0)
                self.requests.append(connection.recv(4096).split(b'\r\n')[0].decode('latin-1'))
                connection.sendall(b'HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n')
            except OSError:
                pass
            finally:
                connection.close()

    def close(self):
        self.stop.set()
        self.thread.join(5)
        self.listener.close()
