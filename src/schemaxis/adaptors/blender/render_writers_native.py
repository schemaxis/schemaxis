"""Legacy image renders never execute a saved compositor's file destinations.

Only an explicit render-bundle job may stage and enable its declared writers.
Muting changes process-local state and is always reversed before project save.
"""
from contextlib import contextmanager

from .compositor_budget import NativeBudget


@contextmanager
def suppress(scene):
    tree = scene.compositing_node_group
    saved = []
    if tree is not None:
        budget = NativeBudget()
        budget.observe(tree)
        for current in budget.trees:
            for node in current.nodes:
                if node.bl_idname == 'CompositorNodeOutputFile':
                    saved.append((node, node.mute))
    try:
        for node, _ in saved:
            node.mute = True
        yield
    finally:
        for node, muted in reversed(saved):
            node.mute = muted
