# Copyright (C) 2026 David L F Gaden
"""Shared serial job ownership around the existing native dispatch context."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from .dispatch import allocation
from .errors import fail


class Cancellation:
    def __init__(self, parent=None, deadline=None):
        self.event = threading.Event()
        self.parent = parent
        self.deadline = deadline

    def set(self):
        self.event.set()

    def expired(self):
        return self.deadline is not None and time.monotonic() >= self.deadline

    def is_set(self):
        return self.event.is_set() or self.expired() or bool(self.parent and self.parent.is_set())


class SerialJobs:
    """Own futures and cancellation; operation scheduling stays in workflow/parallel."""
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='schemaxis-job')
        self.cancellations = {}
        self.futures = {}
        self.lock = threading.Lock()
        self.closed = False

    def submit(self, identity, function, cancel=None):
        with self.lock:
            if self.closed:
                fail('SESSION_CLOSED', 'job owner is closed')
            token = cancel if cancel is not None else Cancellation()
            self.cancellations[identity] = token
            def execute():
                with allocation({}, token):
                    return function()
            future = self.executor.submit(execute)
            self.futures[identity] = future
            return future

    def close(self):
        with self.lock:
            self.closed = True
            for token in self.cancellations.values():
                token.set()
        self.executor.shutdown(wait=True, cancel_futures=False)
