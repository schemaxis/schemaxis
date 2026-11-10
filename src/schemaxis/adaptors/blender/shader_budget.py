"""Bound distinct shader allocation and recursively instanced compilation work."""
from schemaxis.errors import fail

MAX_NODES = 8192
MAX_EXPANDED = 8192
MAX_GROUP_DEPTH = 32


def admit(roots, groups, where='production.materialGraphs', base_nodes=0, *, domain='shader'):
    """Each graph is a list: None for a node, or its referenced group identity.

    Count every declared node, including disconnected nodes and instances, and
    add a child's expansion for EACH instance. Memoizing definitions alone must
    not collapse repeated compilation work into unique-datablock counts.
    """
    if domain not in ('shader', 'compositor'):
        fail('INVALID_ARGUMENT', 'node budget domain must be reviewed', where)
    unique = base_nodes + sum(map(len, roots.values())) + sum(map(len, groups.values()))
    def refused(message, location, **observed):
        fail('RESOURCE_BUDGET_EXCEEDED', message, location, **observed)
    if unique > MAX_NODES:
        refused(domain+' allocation exceeds 8192 distinct nodes',where,estimatedNodes=unique)
    cache = {}; active = set()
    def group_cost(identity):
        if identity in cache:return cache[identity]
        if identity not in groups:fail('UNKNOWN_REFERENCE',domain+' group is absent',str(identity))
        if identity in active:fail('DEPENDENCY_CYCLE',domain+' groups contain a cycle',str(identity))
        if len(active)>=MAX_GROUP_DEPTH:
            refused(domain+' nesting exceeds 32 groups',str(identity))
        active.add(identity)
        try:result=cost(groups[identity],str(identity))
        finally:active.remove(identity)
        if result[1]>=MAX_GROUP_DEPTH:
            refused(domain+' nesting exceeds 32 groups',str(identity),estimatedDepth=result[1]+1)
        cache[identity]=result
        return result
    def cost(nodes, location):
        total=len(nodes);depth=0
        for ref in nodes:
            if ref is None:continue
            child,child_depth=group_cost(ref)
            total+=child;depth=max(depth,child_depth+1)
            if total>MAX_EXPANDED:
                refused(domain+' expansion exceeds 8192 node occurrences',location,estimatedOccurrences=total)
            if depth>MAX_GROUP_DEPTH:
                refused(domain+' nesting exceeds 32 groups',location,estimatedDepth=depth)
        return total,depth
    # Unused definitions remain bounded reusable declarations, not a way to
    # retain an enormous graph for a later material or captured consumer.
    for identity in groups:group_cost(identity)
    expanded=base_nodes;depth=max((d+1 for _,d in cache.values()),default=0)
    for identity,nodes in roots.items():
        count,current_depth=cost(nodes,str(identity));expanded+=count;depth=max(depth,current_depth)
        if expanded>MAX_EXPANDED:
            refused('aggregate '+domain+' expansion exceeds 8192 node occurrences',where,estimatedOccurrences=expanded)
    return {'distinctNodes':unique,'expandedOccurrences':expanded,'groupDepth':depth}


def validate(spec, graph_nodes, where):
    def refs(graph):
        return [n['group'] if n['kind']=='group' else None for n in graph['nodes']]
    groups={g['id']:refs(g) for g in spec['nodeGroups'] if g['family']=='material'}
    from .surface_compile import all_material_graphs
    roots={g['id']:refs(g)+[None] for g in all_material_graphs(spec)}
    return admit(roots,groups,where,2*sum(n['filter']=='material' for n in graph_nodes.values()))
