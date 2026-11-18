# Copyright (C) 2026 David L. F. Gaden.
"""Exact JSON file encoding and bounded, non-joining wire admission."""
import json
from .core.faults import Fault, SchemaxisError


def chunks(value):
    yield from json.JSONEncoder(indent=2, allow_nan=False).iterencode(value)
    yield '\n'


class Budget:
    def __init__(self, limit):
        self.limit, self.used = limit, 0

    def add(self, value):
        try:
            for chunk in chunks(value):
                self.used += len(chunk.encode('utf-8'))
                if self.used > self.limit:
                    raise SchemaxisError(Fault('LIVE_LIMIT',
                        'Checked resident reply exceeds the transfer limit; use a shorter name or Undo an unaligned change.',
                        '$', 'live'))
        except (TypeError, ValueError, RecursionError) as error:
            raise SchemaxisError(Fault('INVALID_ARGUMENT', 'Live input must be bounded finite JSON', '$', 'live')) from error
        return self.used


def size(value, limit):
    return Budget(limit).add(value)
