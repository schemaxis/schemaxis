"""Bound generated/captured compositor allocation and repeated group expansion."""
from .shader_budget import admit
from schemaxis.errors import fail


def validate(spec, where='production.compositor'):
    def references(graph):
        return [node['group'] if node['kind'] == 'group' else None for node in graph['nodes']]
    groups = {g['id']: references(g) for g in spec.get('nodeGroups', []) if g['family'] == 'compositor'}
    graph = spec.get('compositor')
    roots = {'scene': references(graph)} if graph is not None else {}
    outputs = [output for bundle in spec.get('renderBundles', []) for output in bundle['outputs']]
    from .render_bundles import source_slots
    ports = sum(source_slots(spec, item.get('source', {})) for output in outputs
                for item in (output['layers'] if output['kind'] == 'multilayer' else [output]))
    # The builder may share actual RLayers node identity per view layer. Charge
    # every declared layer, including one not needed by the current bundle.
    generated = len(outputs) + (len(spec.get('viewLayers', [])) + (0 if graph else 1) if outputs else 0)
    nodes = sum(map(len, roots.values())) + generated
    links = len(graph.get('links', [])) if graph else 0
    if nodes > 2048 or links + ports > 8192:
        fail('RESOURCE_BUDGET_EXCEEDED', 'compositor root exceeds 2048 nodes or 8192 links', where,
             estimatedNodes=nodes, estimatedLinks=links + ports)
    if generated:
        roots.setdefault('scene', []).extend([None] * generated)
    return admit(roots, groups, where, domain='compositor')


class NativeBudget:
    """Native identities are shared only when the actual datablock is shared."""
    def __init__(self):
        self.trees = {}

    def observe(self, tree):
        self.trees = {}
        node_count = 0
        pending, active = [tree], set()
        while pending:
            current = pending.pop()
            if current in active:
                continue
            active.add(current)
            if current.bl_idname != 'CompositorNodeTree':
                fail('UNSUPPORTED_ASSET_DEPENDENCY', 'compositor budget needs reviewed native trees', current.name)
            if len(current.nodes) > 2048 or len(current.links) > 8192:
                fail('RESOURCE_BUDGET_EXCEEDED', 'native compositor tree exceeds node/link bounds', current.name)
            node_count += len(current.nodes)
            if node_count > 8192 or len(active) > 8192:
                fail('RESOURCE_BUDGET_EXCEEDED', 'native compositor allocation exceeds 8192 nodes/trees', current.name)
            refs = []
            for node in current.nodes:
                child = node.node_tree if node.bl_idname == 'CompositorNodeGroup' else None
                refs.append(child)
                if child is not None:
                    pending.append(child)
            self.trees[current] = refs
        # Keep datablocks as keys; display-name collisions cannot merge costs.
        groups = {key: refs for key, refs in self.trees.items() if key != tree}
        return admit({tree: self.trees[tree]}, groups, 'native.compositor', domain='compositor')
