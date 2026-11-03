# Copyright (C) 2026 David L F Gaden
"""Schemaxis authoring with typed, pure spatial calculations and reference provenance."""
from schemaxis.core.documents import resolve_document as _resolve
from .functions import FUNCTIONS


def resolve_document(document, **limits):
    return _resolve(document, value_resolver=FUNCTIONS.invoke, **limits)
