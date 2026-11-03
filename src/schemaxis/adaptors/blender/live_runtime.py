# Copyright (C) 2026 David L F Gaden
"""Compatibility alias for shared live_runtime."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module('schemaxis.live_runtime')
