"""Deterministic bounded dependency-to-layout policy; no native imports."""
import re
from schemaxis.core.faults import SchemaxisError


def arrange(options, block_plan, fault):
    """Longest-path ranks, lexical lanes, centred uniform cards, accountable budgets."""
    boxes = {}; seen = set()
    for i, box in enumerate(options['boxes']):
        identity = box['id']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', identity) or identity in seen:
            fault('INVALID_LAYOUT', 'flow box and link IDs must be unique simple names', f'$.boxes[{i}].id')
        boxes[identity] = box; seen.add(identity)
    predecessors = {name: set() for name in boxes}; successors = {name: set() for name in boxes}; pairs = set()
    for i, link in enumerate(options['links']):
        identity = link['id']; source, target = link['source'], link['target']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}', identity) or identity in seen:
            fault('INVALID_LAYOUT', 'flow box and link IDs must be unique simple names', f'$.links[{i}].id')
        seen.add(identity)
        if source not in boxes or target not in boxes:
            fault('INVALID_LAYOUT', 'dependencies must name declared boxes', f'$.links[{i}]')
        if (source, target) in pairs:
            fault('INVALID_LAYOUT', 'duplicate directed dependencies are ambiguous', f'$.links[{i}]')
        pairs.add((source, target)); predecessors[target].add(source); successors[source].add(target)
    remaining = {name: len(dependencies) for name, dependencies in predecessors.items()}
    ready = sorted(name for name, count in remaining.items() if count == 0)
    ranks = {}; order = []
    while ready:
        identity = ready.pop(0); order.append(identity)
        ranks[identity] = max((ranks[parent] + 1 for parent in predecessors[identity]), default=0)
        for target in sorted(successors[identity]):
            remaining[target] -= 1
            if remaining[target] == 0:
                ready.append(target); ready.sort()
    if len(order) != len(boxes):
        fault('FLOW_CYCLE', 'flow dependencies must form an acyclic graph', '$.links',
              unresolved=sorted(set(boxes) - set(order)))
    rank_count = max(ranks.values()) + 1
    lanes = {rank: sorted(name for name in boxes if ranks[name] == rank) for rank in range(rank_count)}
    width, height = options['boxWidth'], options['boxHeight']
    rank_gap, lane_gap = options['rankGap'], options['laneGap']
    if rank_gap < max(3, options['clearance']) or lane_gap < options['clearance']:
        fault('INVALID_LAYOUT', 'rankGap and laneGap must preserve clearance; rankGap also needs 3 mm for arrows', '$')
    if min(width, height) <= 2 * options['padding']:
        fault('INVALID_LAYOUT', 'uniform cards need room for padding on both sides', '$')
    stroked_width, stroked_height = width + .4, height + .4
    required_width = rank_count * stroked_width + (rank_count - 1) * rank_gap
    required_height = max(len(names) * stroked_height + (len(names) - 1) * lane_gap for names in lanes.values())
    if required_width + 2 * options['margin'] > options['width'] + 1e-10 or required_height + 2 * options['margin'] > options['height'] + 1e-10:
        fault('FLOW_PAGE_OVERFLOW', 'dependency ranks and lanes do not fit the declared page budget', '$',
              requiredPage=[required_width + 2 * options['margin'], required_height + 2 * options['margin']],
              actualPage=[options['width'], options['height']], rankCount=rank_count,
              maximumLanes=max(map(len, lanes.values())))
    derived = []
    for rank, names in lanes.items():
        column_height = len(names) * stroked_height + (len(names) - 1) * lane_gap
        for lane, name in enumerate(names):
            derived.append({**boxes[name], 'x': (options['width'] - required_width) / 2 + .2 + rank * (stroked_width + rank_gap),
                            'y': (options['height'] - column_height) / 2 + .2 + lane * (stroked_height + lane_gap),
                            'width': width, 'height': height})
    derived_links = sorted(options['links'], key=lambda link: link['id'])
    document = {'version': 'schemaxis.inkscape/1', 'operation': 'blockDiagram',
        **{k: v for k, v in options.items() if k not in ('boxWidth', 'boxHeight', 'rankGap', 'laneGap', 'boxes', 'links')},
        'boxes': derived, 'links': derived_links}
    try: prepared = block_plan(document)
    except SchemaxisError as error:
        if error.fault.code == 'INVALID_LAYOUT' and ('crosses' in error.fault.message):
            index = int(error.fault.location.split('[')[-1].split(']')[0]); identity = derived_links[index]['id']
            authored_index = next(i for i, link in enumerate(options['links']) if link['id'] == identity)
            fault('FLOW_ROUTING_COLLISION', 'deterministic connector crosses an unrelated card; this graph needs another page/layout choice',
                  f'$.links[{authored_index}]', link=identity, **dict(error.fault.observed))
        raise
    layout = {'algorithm': 'dag-longest-path/1', 'ranks': {name: ranks[name] for name in sorted(ranks)},
              'rankCount': rank_count, 'laneCounts': [len(lanes[rank]) for rank in range(rank_count)],
              'requiredSize': [required_width, required_height], 'cardSize': [width, height],
              'rankGap': rank_gap, 'laneGap': lane_gap}
    return {**prepared, 'operation': 'flowDiagram', 'layout': layout}
