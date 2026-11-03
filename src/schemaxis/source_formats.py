# Copyright (C) 2026 David L F Gaden
"""Explicit conversion between authored JSON and the optional YAML profile."""
import json
from .core.documents import document_format, load_document, load_document_file


def dump_document(value, format='json'):
    document_format(format=format)
    if format == 'yaml':
        from .core.yaml_documents import dump
        return dump(value)
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
