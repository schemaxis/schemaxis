"""adaptors paraview package. Native imports are deferred until execution."""
# Register the host-safe selection-query compiler before any declaration is checked.
from . import selection_query  # noqa: F401
