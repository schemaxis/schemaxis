"""Compatibility import; implementation lives in adaptors.blender.operations."""
import importlib as _importlib
import sys as _sys
_sys.modules[__name__] = _importlib.import_module("schemaxis.adaptors.blender.operations")
