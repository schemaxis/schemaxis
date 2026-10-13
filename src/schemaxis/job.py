"""Compatibility import for ParaView execution orchestration."""
import importlib as _importlib
import sys as _sys
_sys.modules[__name__] = _importlib.import_module("schemaxis.adaptors.paraview.job")
