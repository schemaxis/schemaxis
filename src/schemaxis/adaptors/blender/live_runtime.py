"""Compatibility alias for shared live_runtime."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('schemaxis.live_runtime')
