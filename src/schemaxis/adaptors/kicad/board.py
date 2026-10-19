"""Dependency-free bounded KiCad board reader and independent geometric checks.

The reader covers the s-expression subset needed to count and locate copper,
holes and the board outline. It is not a KiCad loader: unsupported structures are
rejected or reported as unchecked, never silently treated as absent.
"""
import math
import re
from pathlib import Path
from schemaxis.errors import fail

MAX_BOARD_BYTES = 4*1024*1024
MAX_DEPTH = 64
MAX_NODES = 400000
MAX_COPPER_ITEMS = 2000
MAX_HOLES = 2000
# KiCad 8.0 (20240108) through the KiCad 10.0 board format (20260206).
FORMATS = (20240108, 20260206)
INT_MAX_NM = 2**31-1
EDGE = 'Edge.Cuts'
PAD_TYPES = {'thru_hole': 'throughHole', 'smd': 'smd', 'connect': 'connector', 'np_thru_hole': 'npth'}


class Quoted(str):
    """A quoted s-expression string, distinct from a bare symbol."""


def check(condition, message):
    if not condition:
        fail('VERIFICATION_FAILED', message)


def unsupported(message, location='$.board', **observed):
    fail('UNSUPPORTED_BOARD', message, location, **observed)


def parse(text):
    """Parse bounded s-expression text into nested lists of symbols/strings."""
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BOARD_BYTES:
        fail('RESOURCE_LIMIT', 'KiCad board exceeds 4 MiB', '$.board')
    stack, root, nodes, i, size = [], None, 0, 0, len(text)
    while i < size:
        c = text[i]
        if c in ' \t\r\n':
            i += 1
        elif c == '(':
            if len(stack) >= MAX_DEPTH:
                fail('RESOURCE_LIMIT', 'board nesting exceeds 64 levels', '$.board')
            node = []
            if stack:
                stack[-1].append(node)
            elif root is None:
                root = node
            else:
                unsupported('board contains more than one top-level expression')
            stack.append(node); nodes += 1; i += 1
            if nodes > MAX_NODES:
                fail('RESOURCE_LIMIT', 'board exceeds 400000 expressions', '$.board')
        elif c == ')':
            if not stack:
                unsupported('unbalanced closing parenthesis', offset=i)
            stack.pop(); i += 1
        elif c == '"':
            j, parts = i+1, []
            while True:
                if j >= size:
                    unsupported('unterminated quoted string', offset=i)
                if text[j] == '\\' and j+1 < size:
                    parts.append({'n': '\n', 't': '\t', 'r': '\r'}.get(text[j+1], text[j+1])); j += 2
                elif text[j] == '"':
                    break
                else:
                    parts.append(text[j]); j += 1
            if not stack:
                unsupported('text outside the board expression')
            stack[-1].append(Quoted(''.join(parts))); i = j+1
        else:
            j = i
            while j < size and text[j] not in ' \t\r\n()"':
                j += 1
            if not stack:
                unsupported('text outside the board expression')
            stack[-1].append(text[i:j]); i = j
    if stack or root is None:
        unsupported('board expression is incomplete')
    return root


def children(node, head):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def child(node, head):
    found = children(node, head)
    return found[0] if found else None


def atoms(node):
    return [] if node is None else [c for c in node[1:] if not isinstance(c, list)]


def nm(value, what):
    """Convert a decimal millimetre atom exactly as KiCad's KiRound(mm*1e6)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        unsupported('invalid numeric value for '+what, value=str(value))
    if not math.isfinite(number) or abs(number) > 2000:
        unsupported('coordinate or size outside +/-2000 mm for '+what, value=str(value))
    scaled = number*1e6
    return int(math.floor(scaled+0.5)) if scaled >= 0 else -int(math.floor(-scaled+0.5))


def point(node, what):
    values = atoms(node)
    if node is None or len(values) < 2:
        unsupported('missing coordinate pair for '+what)
    return nm(values[0], what), nm(values[1], what)


def rotate(x, y, degrees):
    """KiCad RotatePoint in its y-down frame: positive angles appear anticlockwise."""
    turn = degrees % 360
    exact = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}
    if turn in exact:
        c, s = exact[turn]
    else:
        r = math.radians(turn); c, s = math.cos(r), math.sin(r)
    return x*c+y*s, -x*s+y*c


def millimetres(value):
    return None if value is None else round(value/1e6, 6)


def net_name(node, codes):
    """Resolve KiCad 10 named nets and the older numbered net references."""
    values = atoms(child(node, 'net'))
    if not values:
        return ''
    if len(values) >= 2 and isinstance(values[1], Quoted):
        return str(values[1])
    if isinstance(values[0], Quoted):
        return str(values[0])
    if values[0] not in codes:
        unsupported('track or pad references an undeclared net code', code=str(values[0]))
    return codes[values[0]]


def angle(node):
    values = atoms(node)
    if node is None or len(values) < 3:
        return 0.0
    try:
        value = float(values[2])
    except ValueError:
        unsupported('invalid rotation angle', value=str(values[2]))
    if not math.isfinite(value):
        unsupported('rotation angle must be finite', value=str(values[2]))
    return value


def read(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        fail('RESOURCE_NOT_FOUND', 'KiCad board must be an existing regular file', '$.board', file=str(path))
    if path.stat().st_size > MAX_BOARD_BYTES:
        fail('RESOURCE_LIMIT', 'KiCad board exceeds 4 MiB', '$.board', bytes=path.stat().st_size)
    try:
        return model(parse(path.read_text(encoding='utf-8')))
    except UnicodeDecodeError:
        unsupported('KiCad board must be UTF-8 text')


def model(root):
    """Extract counted board facts in integer nanometres from a parsed board."""
    if not root or root[0] != 'kicad_pcb':
        unsupported('file is not a kicad_pcb board')
    version = atoms(child(root, 'version'))
    if not version or not str(version[0]).isdigit():
        unsupported('board has no numeric format version')
    version = int(version[0])
    if not FORMATS[0] <= version <= FORMATS[1]:
        unsupported('board format version is outside the supported KiCad 8.0-10.0 range', version=version,
                    supported=list(FORMATS))
    thickness = atoms(child(child(root, 'general') or [], 'thickness'))
    layers = []
    for layer in (child(root, 'layers') or [])[1:]:
        if isinstance(layer, list) and len(layer) >= 3:
            layers.append({'name': str(layer[1]), 'type': str(layer[2])})
    copper = [l['name'] for l in layers if l['name'].endswith('.Cu')]
    if sorted(copper) != ['B.Cu', 'F.Cu']:
        unsupported('this first slice reads two-copper-layer boards (F.Cu and B.Cu only)', copper=copper)
    copper = ['F.Cu', 'B.Cu']
    codes = {str(n[1]): str(n[2]) for n in children(root, 'net') if len(n) >= 3}
    nets = set(codes.values())
    footprints, pads, holes, flags = [], [], [], set()
    for index, fp in enumerate(children(root, 'footprint')):
        where = f'$.board.footprint[{index}]'
        values = atoms(fp)
        library = str(values[0]) if values else ''
        side = (atoms(child(fp, 'layer')) or [''])[0]
        if side not in ('F.Cu', 'B.Cu'):
            unsupported('footprint must be on F.Cu or B.Cu', where, layer=str(side))
        x, y = point(child(fp, 'at'), 'footprint position'); rotation = angle(child(fp, 'at'))
        reference = ''
        for prop in children(fp, 'property'):
            if len(prop) >= 3 and prop[1] == 'Reference':
                reference = str(prop[2])
        for legacy in children(fp, 'fp_text'):
            if len(legacy) >= 3 and legacy[1] == 'reference':
                reference = str(legacy[2])
        attributes = [str(a) for a in atoms(child(fp, 'attr'))]
        for kind in ('fp_line', 'fp_rect', 'fp_arc', 'fp_circle', 'fp_poly', 'fp_curve'):
            if any((atoms(child(g, 'layer')) or [''])[0] == EDGE for g in children(fp, kind)):
                unsupported('footprint-owned Edge.Cuts outlines are outside this first slice', where)
        count = 0
        for pad in children(fp, 'pad'):
            pv = atoms(pad)
            if len(pv) < 3 or pv[1] not in PAD_TYPES:
                unsupported('pad needs a number, a supported type and a shape', where, pad=[str(v) for v in pv[:3]])
            px, py = point(child(pad, 'at'), 'pad position')
            dx, dy = rotate(px, py, rotation)
            ax, ay = x+int(round(dx)), y+int(round(dy))
            properties = {str(v) for v in atoms(child(pad, 'property'))}
            spans = {str(v) for v in atoms(child(pad, 'layers'))}
            size = atoms(child(pad, 'size'))
            entry = {'type': PAD_TYPES[pv[1]], 'net': net_name(pad, codes), 'castellated': 'pad_prop_castellated' in properties,
                     'pressFit': 'pad_prop_pressfit' in properties, 'at': (ax, ay), 'shape': str(pv[2]),
                     'size': (nm(size[0], 'pad size'), nm(size[1], 'pad size')) if len(size) >= 2 else None,
                     'angle': angle(child(pad, 'at')), 'item': (reference or library)+'.'+str(pv[0]),
                     'rratio': float((atoms(child(pad, 'roundrect_rratio')) or [0])[0]),
                     'chamfer': child(pad, 'chamfer_ratio') is not None and child(pad, 'chamfer') is not None,
                     'layers': copper if '*.Cu' in spans else [l for l in copper if l in spans or
                                                               ('F&B.Cu' in spans and l in ('F.Cu', 'B.Cu'))],
                     'padstack': child(pad, 'padstack') is not None}
            nets.add(entry['net']); pads.append(entry); count += 1
            drill = child(pad, 'drill')
            if pv[1] in ('thru_hole', 'np_thru_hole'):
                dv = atoms(drill)
                if drill is None or not dv:
                    unsupported('drilled pad has no drill size', where, pad=str(pv[0]))
                if dv[0] == 'oval' or child(drill, 'offset') is not None:
                    unsupported('oval and offset drills are outside this first slice', where, pad=str(pv[0]))
                if child(pad, 'backdrill') is not None or child(pad, 'tertiary_drill') is not None:
                    unsupported('backdrilled pads are outside this first slice', where, pad=str(pv[0]))
                if not ({'*.Cu', 'F&B.Cu'} & spans or {'F.Cu', 'B.Cu'} <= spans):
                    unsupported('drilled pads must span F.Cu to B.Cu', where, pad=str(pv[0]))
                if nm(dv[0], 'pad drill') <= 0:
                    unsupported('pad drill must be positive', where, pad=str(pv[0]))
                if side == 'B.Cu':
                    flags.add('backDrilledPads')
                holes.append({'x': ax, 'y': ay, 'diameter': nm(dv[0], 'pad drill'), 'plated': pv[1] == 'thru_hole',
                              'source': 'pad', 'item': (reference or library)+'.'+str(pv[0])})
        footprints.append({'reference': reference, 'library': library, 'side': side, 'x': x, 'y': y,
                           'rotation': rotation, 'attributes': attributes, 'pads': count})
    tracks = []
    for kind in ('segment', 'arc'):
        for item in children(root, kind):
            layer = (atoms(child(item, 'layer')) or [''])[0]
            if layer not in copper:
                unsupported(kind+' is not on a declared copper layer', layer=str(layer))
            width = nm((atoms(child(item, 'width')) or [None])[0], kind+' width')
            if width <= 0:
                unsupported(kind+' width must be positive')
            entry = {'kind': kind, 'layer': layer, 'net': net_name(item, codes), 'width': width,
                     'start': point(child(item, 'start'), kind), 'end': point(child(item, 'end'), kind)}
            nets.add(entry['net']); tracks.append(entry)
    vias = []
    for item in children(root, 'via'):
        tokens = {str(a) for a in atoms(item)}
        kind = 'blind' if 'blind' in tokens else 'buried' if 'buried' in tokens else 'micro' if 'micro' in tokens else 'through'
        pair = [str(a) for a in atoms(child(item, 'layers'))]
        if kind != 'through' or pair != ['F.Cu', 'B.Cu']:
            unsupported('only through vias from F.Cu to B.Cu are in this first slice', via=kind, layers=pair)
        if child(item, 'padstack') is not None:
            flags.add('viaPadstack')
        if child(item, 'backdrill') is not None or child(item, 'tertiary_drill') is not None:
            unsupported('backdrilled vias are outside this first slice')
        entry = {'kind': kind, 'at': point(child(item, 'at'), 'via'), 'layers': pair, 'net': net_name(item, codes),
                 'size': nm((atoms(child(item, 'size')) or [None])[0], 'via size'),
                 'drill': nm((atoms(child(item, 'drill')) or [None])[0], 'via drill')}
        if not 0 < entry['drill'] < entry['size']:
            unsupported('via drill must be positive and smaller than its diameter')
        nets.add(entry['net']); vias.append(entry)
        holes.append({'x': entry['at'][0], 'y': entry['at'][1], 'diameter': entry['drill'], 'plated': True,
                      'source': 'via', 'item': 'via'})
    if len(tracks)+len(vias) > MAX_COPPER_ITEMS:
        fail('RESOURCE_LIMIT', 'this first slice checks at most 2000 tracks, arcs and vias', '$.board',
             items=len(tracks)+len(vias))
    if len(holes) > MAX_HOLES:
        fail('RESOURCE_LIMIT', 'this first slice checks at most 2000 drilled holes', '$.board', holes=len(holes))
    return {'formatVersion': version, 'generator': str((atoms(child(root, 'generator')) or [''])[0]),
            'thickness': nm(thickness[0], 'board thickness') if thickness else None,
            'copperLayers': copper, 'nets': sorted(n for n in nets if n), 'footprints': footprints, 'pads': pads,
            'tracks': tracks, 'vias': vias, 'holes': holes, 'zones': len(children(root, 'zone')),
            'outline': outline(root), 'flags': sorted(flags)}


def outline(root):
    """Axis-aligned bounds of board-level Edge.Cuts graphics, in nanometres."""
    xs, ys, curved, unsupported_shapes = [], [], False, 0
    for item in root[1:]:
        if not isinstance(item, list) or not item or (atoms(child(item, 'layer')) or [''])[0] != EDGE:
            continue
        head = item[0]
        if head in ('gr_line', 'gr_rect'):
            for key in ('start', 'end'):
                x, y = point(child(item, key), head); xs.append(x); ys.append(y)
        elif head == 'gr_poly':
            for xy in children(child(item, 'pts') or [], 'xy'):
                x, y = point(xy, head); xs.append(x); ys.append(y)
            if children(child(item, 'pts') or [], 'arc'):
                unsupported_shapes += 1
        elif head == 'gr_circle':
            cx, cy = point(child(item, 'center'), head); ex, ey = point(child(item, 'end'), head)
            r = math.hypot(ex-cx, ey-cy); xs += [cx-r, cx+r]; ys += [cy-r, cy+r]; curved = True
        elif head == 'gr_arc':
            pts = [point(child(item, k), head) for k in ('start', 'mid', 'end')]
            box = arc_bounds(*pts); xs += box[0]; ys += box[1]; curved = True
        else:
            unsupported_shapes += 1
    if unsupported_shapes:
        unsupported('board outline uses Edge.Cuts shapes outside lines, rectangles, polygons, circles and arcs',
                    shapes=unsupported_shapes)
    if not xs:
        return {'present': False}
    return {'present': True, 'bounds': [min(xs), min(ys), max(xs), max(ys)], 'curved': curved}


def arc_bounds(start, mid, end):
    """Bounds of a three-point circular arc, including crossed quadrant extremes."""
    (x1, y1), (x2, y2), (x3, y3) = start, mid, end
    d = 2*(x1*(y2-y3)+x2*(y3-y1)+x3*(y1-y2))
    if d == 0:
        return [x1, x2, x3], [y1, y2, y3]
    ux = ((x1*x1+y1*y1)*(y2-y3)+(x2*x2+y2*y2)*(y3-y1)+(x3*x3+y3*y3)*(y1-y2))/d
    uy = ((x1*x1+y1*y1)*(x3-x2)+(x2*x2+y2*y2)*(x1-x3)+(x3*x3+y3*y3)*(x2-x1))/d
    r = math.hypot(x1-ux, y1-uy)
    a1, a2, a3 = (math.atan2(y-uy, x-ux) for x, y in (start, mid, end))
    def between(a):
        span = (a3-a1) % (2*math.pi); return ((a-a1) % (2*math.pi) <= span) == ((a2-a1) % (2*math.pi) <= span)
    xs, ys = [x1, x3], [y1, y3]
    for a, px, py in ((0, ux+r, uy), (math.pi/2, ux, uy+r), (math.pi, ux-r, uy), (-math.pi/2, ux, uy-r)):
        if between(a):
            xs.append(px); ys.append(py)
    return xs, ys


def segment_distance(a, b, c, d):
    """Minimum distance between closed segments ab and cd."""
    def to_segment(p, q, r):
        qx, qy, rx, ry = q[0], q[1], r[0], r[1]
        vx, vy = rx-qx, ry-qy; length = vx*vx+vy*vy
        t = 0 if length == 0 else max(0, min(1, ((p[0]-qx)*vx+(p[1]-qy)*vy)/length))
        return math.hypot(p[0]-qx-t*vx, p[1]-qy-t*vy)
    def orient(p, q, r):
        value = (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
        return (value > 0)-(value < 0)
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1*o2 < 0 and o3*o4 < 0:
        return 0.0
    return min(to_segment(a, c, d), to_segment(b, c, d), to_segment(c, a, b), to_segment(d, a, b))


MAX_COMPARISONS = 2000000
MAX_BREACHES = 1000


def copper_items(board, all_via_layers):
    """Straight tracks and via discs per copper layer, with half-width radii and x extents."""
    items = []
    for track in board['tracks']:
        (ax, ay), (bx, by), r = track['start'], track['end'], track['width']/2
        items.append((min(ax, bx)-r, max(ax, bx)+r, track['layer'], track['net'], track['start'], track['end'], r, 'track'))
    for via in board['vias']:
        (x, y), r = via['at'], via['size']/2
        for layer in (via['layers'] if all_via_layers else via['layers'][:1]):
            items.append((x-r, x+r, layer, via['net'], via['at'], via['at'], r, 'via'))
    return sorted(items, key=lambda item: item[0])


def sweep(items, window, visit):
    """Visit item pairs whose x extents are closer than window(); False if over budget.

    Pairs are pruned per layer by sorted x extent, so a pair separated by at least
    the current window in x can never have a smaller edge-to-edge gap.
    """
    compared = 0
    by_layer = {}
    for item in items:
        by_layer.setdefault(item[2], []).append(item)
    for layer_items in by_layer.values():
        for i, a in enumerate(layer_items):
            for b in layer_items[i+1:]:
                if b[0]-a[1] >= window():
                    break
                compared += 1
                if compared > MAX_COMPARISONS:
                    return False
                visit(a, b)
    return True


def gap(a, b):
    return max(0.0, segment_distance(a[4], a[5], b[4], b[5])-a[6]-b[6])


def modelled(board):
    return not any(t['kind'] == 'arc' for t in board['tracks']) and 'viaPadstack' not in board['flags']


def gaps(board, threshold):
    """Different-net track/via gaps below threshold on each layer spanned (for DRC).

    Returns (gaps, reason): gaps is None with a reason when outside the model or
    budget. Arcs and via padstacks are not modelled.
    """
    if not modelled(board):
        return None, 'arcs or via padstacks are not modelled'
    found = []
    def visit(a, b):
        if a[3] != b[3]:
            value = gap(a, b)
            if value < threshold:
                found.append(value)
    if not sweep(copper_items(board, True), lambda: threshold, visit):
        return None, 'track/via comparison budget exceeded'
    if len(found) > MAX_BREACHES:
        return None, 'more than 1000 clearance breaches'
    return sorted(found), None


def minimum_gap(board):
    """KiCad's board-statistics clearance: each track/via on its primary layer only."""
    if not modelled(board):
        return None, 'unchecked: arcs or via padstacks are not modelled'
    best = [float(INT_MAX_NM)]
    def visit(a, b):
        if a[3] != b[3]:
            best[0] = min(best[0], gap(a, b))
    if not sweep(copper_items(board, False), lambda: best[0], visit):
        return None, 'unchecked: track/via comparison budget exceeded'
    if best[0] >= INT_MAX_NM:
        return None, 'none: no different-net track/via pairs share a layer'
    return best[0], 'checked'


def drill_table(board):
    """Group holes by size, plating and source, as KiCad's statistics report does."""
    groups = {}
    for hole in board['holes']:
        key = (hole['diameter'], hole['plated'], hole['source'])
        groups[key] = groups.get(key, 0)+1
    return sorted(({'count': n, 'diameter_mm': millimetres(d), 'plated': p, 'source': s}
                   for (d, p, s), n in groups.items()), key=lambda e: (e['source'], e['plated'], e['diameter_mm']))


def components(board):
    result = {k: {'front': 0, 'back': 0} for k in ('tht', 'smd', 'unspecified')}
    for fp in board['footprints']:
        attributes = set(fp['attributes'])
        kind = 'tht' if 'through_hole' in attributes else 'smd' if 'smd' in attributes else 'unspecified'
        result[kind]['front' if fp['side'] == 'F.Cu' else 'back'] += 1
    return result


def summary(board):
    """JSON facts derived only from the host reader."""
    pads = {k: 0 for k in ('throughHole', 'smd', 'connector', 'npth', 'castellated', 'pressFit')}
    for pad in board['pads']:
        pads[pad['type']] += 1
        pads['castellated'] += pad['castellated']; pads['pressFit'] += pad['pressFit']
    vias = {k: sum(v['kind'] == k for v in board['vias']) for k in ('through', 'blind', 'buried', 'micro')}
    shape = board['outline']
    widths = [t['width'] for t in board['tracks'] if t['kind'] == 'segment']
    drills = [h['diameter'] for h in board['holes']]
    clearance, status = minimum_gap(board)
    return {'formatVersion': board['formatVersion'], 'generator': board['generator'],
            'thickness_mm': millimetres(board['thickness']), 'copperLayers': board['copperLayers'], 'nets': board['nets'],
            'counts': {'footprints': len(board['footprints']), 'pads': pads, 'vias': vias,
                       'segments': sum(t['kind'] == 'segment' for t in board['tracks']),
                       'arcs': sum(t['kind'] == 'arc' for t in board['tracks']), 'zones': board['zones'],
                       'holes': len(board['holes'])},
            'components': components(board),
            'outline': ({'present': True, 'bounds_mm': [millimetres(v) for v in shape['bounds']],
                         'width_mm': millimetres(shape['bounds'][2]-shape['bounds'][0]),
                         'height_mm': millimetres(shape['bounds'][3]-shape['bounds'][1]), 'curved': shape['curved']}
                        if shape['present'] else {'present': False}),
            'minimumTrackWidth_mm': millimetres(min(widths)) if widths else None,
            'minimumDrill_mm': millimetres(min(drills)) if drills else None,
            'minimumTrackClearance_mm': millimetres(clearance), 'trackClearanceStatus': status,
            'drillTable': drill_table(board),
            'footprints': [{'reference': fp['reference'], 'library': fp['library'], 'side': fp['side'],
                            'position_mm': [millimetres(fp['x']), millimetres(fp['y'])], 'rotation_deg': fp['rotation'],
                            'attributes': fp['attributes'], 'pads': fp['pads']} for fp in board['footprints']],
            'unsupportedForDrill': [f for f in board['flags'] if f == 'backDrilledPads'],
            'flags': board['flags']}


VALUE = re.compile(r'^(-?\d+(?:\.\d+)?) mm$')


def native_length(value, field):
    found = VALUE.match(value) if isinstance(value, str) else None
    check(found is not None, 'native statistic is not a millimetre value: '+field)
    return float(found[1])


def compare_statistics(facts, stats):
    """Cross-check KiCad's board statistics report against host reader facts."""
    check(isinstance(stats, dict) and isinstance(stats.get('board'), dict), 'native statistics JSON is malformed')
    report = stats['board']
    present = facts['outline']['present']
    check(report.get('has_outline') is present, 'native outline presence differs from Edge.Cuts graphics')
    tolerance = 0.01 if present and facts['outline']['curved'] else 0.00006
    if present:
        for key, field in (('width_mm', 'width'), ('height_mm', 'height')):
            check(abs(native_length(report.get(field), field)-facts['outline'][key]) <= tolerance,
                  'native board '+field+' differs from host outline bounds')
    sentinel = INT_MAX_NM/1e6
    for field, mine in (('min_track_width', facts['minimumTrackWidth_mm']), ('min_drill_diameter', facts['minimumDrill_mm']),
                        ('min_track_clearance', facts['minimumTrackClearance_mm'])):
        if field == 'min_track_clearance' and not facts['trackClearanceStatus'].startswith(('checked', 'none')):
            continue
        observed = native_length(report.get(field), field)
        expected = sentinel if mine is None else mine
        check(abs(observed-expected) <= 0.00006, 'native '+field+' differs from the host reader')
    if facts['thickness_mm'] is not None:
        check(abs(native_length(report.get('board_thickness'), 'board_thickness')-facts['thickness_mm']) <= 0.00006,
              'native board thickness differs')
    pads = stats.get('pads', {})
    for key, field in (('throughHole', 'through_hole'), ('smd', 'smd'), ('connector', 'connector'), ('npth', 'npth'),
                       ('castellated', 'castellated'), ('pressFit', 'press_fit')):
        check(pads.get(field) == facts['counts']['pads'][key], 'native pad count differs: '+field)
    vias = stats.get('vias', {})
    for key in ('through', 'blind', 'buried', 'micro'):
        check(vias.get(key) == facts['counts']['vias'][key], 'native via count differs: '+key)
    groups = stats.get('components', {})
    for key in ('tht', 'smd', 'unspecified'):
        entry = groups.get(key, {})
        check(entry.get('front') == facts['components'][key]['front'] and entry.get('back') == facts['components'][key]['back'],
              'native component count differs: '+key)
    holes = stats.get('drill_holes')
    check(isinstance(holes, list), 'native drill table is missing')
    observed = []
    for hole in holes:
        check(isinstance(hole, dict) and hole.get('shape') == 'Round' and hole.get('start_layer') == 'F.Cu'
              and hole.get('stop_layer') == 'B.Cu', 'native drill table contains an unsupported hole span or shape')
        x, y = native_length(hole.get('x_size'), 'x_size'), native_length(hole.get('y_size'), 'y_size')
        check(abs(x-y) <= 0.00006 and type(hole.get('count')) is int and type(hole.get('plated')) is bool
              and hole.get('source') in ('Pad', 'Via'), 'native drill table entry is malformed')
        observed.append((hole['source'].lower(), hole['plated'], round(x, 4), hole['count']))
    expected = [(e['source'], e['plated'], round(e['diameter_mm'], 4), e['count']) for e in facts['drillTable']]
    check(sorted(observed) == sorted(expected), 'native drill table differs from host-located holes')
    return {'outline': present, 'pads': True, 'vias': True, 'components': True, 'drillTable': True,
            'minimumTrackClearance': facts['trackClearanceStatus']}
