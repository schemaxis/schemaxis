"""The Schemaxis expression language as a standalone, dependency-free package.

Nothing here imports the rest of Schemaxis. A caller supplies an Environment
(how names resolve, which extra functions exist) and gets parsing, checking
and evaluation with the semantics of docs/design/expression-language.md.
"""
from .checker import Checked, Checker, check
from .environment import (CONSTANT, OBSERVED, PHASES, VISIT, Binding, Environment, HostFunction, Info,
                          MappingEnvironment, Namespace, Shape)
from .evaluator import Evaluator, evaluate
from .faults import ExprFault
from .syntax import parse
from .values import INVALID, MISSING, Box, classify, coerce, make_box, to_json

__all__ = ['Binding', 'Box', 'CONSTANT', 'Checked', 'Checker', 'Environment', 'Evaluator', 'ExprFault',
           'HostFunction', 'INVALID', 'Info', 'MISSING', 'MappingEnvironment', 'Namespace', 'OBSERVED', 'PHASES',
           'Shape', 'VISIT', 'check', 'classify', 'coerce', 'evaluate', 'make_box', 'parse', 'to_json']
