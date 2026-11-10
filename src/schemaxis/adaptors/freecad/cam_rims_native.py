"""Complete actual circular rims, compiled to one finite SDK target each."""
import math
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .cam_mixed_budget import LIMITS


def prospective(groups,budget,other_operations):
    """Reject aggregate overlap work BEFORE the first native intersection."""
    pairs=sum(len(group)*(len(group)-1)//2 for group in groups)
    if budget.operations+pairs+other_operations>LIMITS['booleans']:
        fail('RESOURCE_LIMIT','Complete circular rim overlap work exceeds the aggregate Boolean budget')
    # Each edge has two endpoints; comparing all of them needs at most4n²
    # comparisons. Actual comparisons still consume the shared counter.
    comparisons=sum(4*len(group)**2 for group in groups if len(group)>1)
    if budget.identity_checks+comparisons>LIMITS['facePairs']:
        fail('RESOURCE_LIMIT','Complete circular rim endpoint work exceeds its aggregate budget')
    remaining_timeout()


def representative(group,radius,budget,intersection,location):
    """Prove one whole circle using actual topology, never endpoint proximity.

    The fixed circular-hole SDK emits one target PER Base edge, even when two
    semicircles share a centre. After full coverage proof its centre/radius API
    therefore receives exactly one deterministically chosen actual edge.
    """
    def refused(message):
        fail('UNSUPPORTED_SOURCE',message,location)
    if not group:refused('Pointed target has no actual qualified circular rim')
    lengths=[edge.Length for _,edge in group]
    if any(not math.isfinite(value) or value<=0 for value in lengths):
        refused('Pointed circular rim has a nonfinite or degenerate edge')
    if abs(math.fsum(lengths)-2*math.pi*radius)>1e-7:
        refused('Pointed circular rim does not cover exactly one complete circle')
    if len(group)==1:
        if not group[0][1].isClosed():refused('Pointed circular rim is incomplete')
        return group[0][0]
    vertices=[];links=[]
    for _,edge in group:
        remaining_timeout()
        if edge.isClosed() or edge.countElement('Vertex')!=2:
            refused('Split circular rim needs two distinct actual endpoints per edge')
        ends=edge.Vertexes
        if len(ends)!=2:refused('Split rim endpoint inventory differs from native topology')
        indices=[]
        for endpoint in ends:
            matches=[]
            for index,known in enumerate(vertices):
                budget.check()
                if endpoint.isSame(known):matches.append(index)
            if len(matches)>1:refused('Split rim repeats a native endpoint identity')
            if matches:indices.append(matches[0])
            else:indices.append(len(vertices));vertices.append(endpoint)
        if indices[0]==indices[1]:refused('Split rim edge repeats one endpoint')
        links.append(indices)
    adjacency=[[] for _ in vertices]
    for first,last in links:
        adjacency[first].append(last);adjacency[last].append(first)
    if any(len(neighbours)!=2 for neighbours in adjacency):
        refused('Split circular rim has a gap or branching endpoint')
    seen=set();pending=[0]
    while pending:
        remaining_timeout();index=pending.pop()
        if index in seen:continue
        seen.add(index);pending.extend(adjacency[index])
    if len(seen)!=len(vertices):refused('Split circular rim has disconnected cycles')
    for index,(_,first) in enumerate(group):
        for _,last in group[index+1:]:
            budget.check()
            if first.isSame(last):refused('Split circular rim repeats an actual edge')
            overlap=intersection(first,last)
            if overlap.countElement('Edge'):
                refused('Split circular rim edges overlap')
    return min(index for index,_ in group)
