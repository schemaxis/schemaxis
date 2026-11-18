# Copyright (C) 2026 David L F Gaden
"""Schemaxis authoring with typed, pure spatial calculations and reference provenance."""
from schemaxis.core.documents import resolve_document as _resolve
from .expressions import fold_constants, has_expressions, has_markers
from .functions import FUNCTIONS


class Deferral:
    """Leaves a function unresolved while its arguments still hold markers."""

    def __init__(self, given):
        self.given = given

    def __call__(self, arguments):
        return has_markers(arguments) or (self.given is not None and self.given(arguments))


def resolve_document(document, **limits):
    """Resolve references and functions; constant string expressions become values.

    axes gives, for each document of a study, the value of every axis at the
    current visit; expressions that depend only on those are then values too.
    """
    axes = limits.pop('axes', None)
    if has_expressions(document):
        limits['defer'] = Deferral(limits.get('defer'))
    result, evidence = _resolve(document, value_resolver=FUNCTIONS.invoke, **limits)
    if has_expressions(result):
        result = fold_constants(result, evidence, axes)
    return result, evidence
