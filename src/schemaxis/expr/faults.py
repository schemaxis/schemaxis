"""Structured faults of the expression language."""


class ExprFault(Exception):
    """A fault with a stable code, a code-point range and observed details."""

    def __init__(self, code, message, position=None, length=None, **observed):
        super().__init__(message)
        self.code = code
        self.message = message
        self.position = position
        self.length = length
        self.observed = observed

    def locate(self, node):
        if self.position is None:
            self.position = node.position
            self.length = node.length
        return self
