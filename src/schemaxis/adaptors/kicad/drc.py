"""KiCad DRC JSON validation and bounded host predictions for cross-checking.

Host predictions cover two failure classes on simple boards: different-net
track/via clearance breaches against one netclass clearance, and missing
connections between pads of a net. They are falsification checks of the native
report, not a replacement design-rule engine; anything outside their model is
recorded as unchecked rather than assumed clean.
"""
import json
import math
import re
from pathlib import Path
from . import board as boards
from .board import check

MAX_REPORT_BYTES = 8*1024*1024
SCHEMA = 'https://schemas.kicad.org/drc.v1.json'
SEVERITIES = ('error', 'warning', 'exclusion')
DEFAULT_CLEARANCE_NM = 200000
ACTUAL = re.compile(r'actual (\d+(?:\.\d+)?) mm\)')
COPPER_ITEM = re.compile(r'^(Track|Via) \[')
PAD_SHAPES = ('circle', 'rect', 'roundrect', 'oval')


def rules(project, custom_rules):
    """Return the single-netclass clearance the host model may assume, or why not."""
    clearance, severity, reason = DEFAULT_CLEARANCE_NM, 'error', None
    if custom_rules:
        reason = 'custom .kicad_dru rules are not modelled'
    if isinstance(project, dict):
        net = project.get('net_settings') or {}
        classes = net.get('classes') or []
        if len(classes) > 1 or net.get('netclass_patterns') or net.get('netclass_assignments'):
            reason = reason or 'multiple netclasses or netclass assignments are not modelled'
        if classes:
            value = classes[0].get('clearance')
            if not (isinstance(value, (int, float)) and math.isfinite(value) and 0 < value <= 100):
                reason = reason or 'Default netclass clearance is not a finite positive millimetre value'
            else:
                clearance = boards.nm(value, 'netclass clearance')
        severities = ((project.get('board') or {}).get('design_settings') or {}).get('rule_severities') or {}
        severity = severities.get('clearance', 'error')
        if severity != 'error':
            reason = reason or 'clearance severity is not error'
    return {'clearance_mm': boards.millimetres(clearance), 'clearance': clearance, 'applicable': reason is None,
            'reason': reason}


def inside(point, pad, slack):
    """Whether a point lies on a pad's copper outline, for supported shapes."""
    (x, y), (px, py), (w, h) = point, pad['at'], pad['size']
    dx, dy = boards.rotate(x-px, y-py, -pad['angle'])
    if pad['shape'] == 'circle':
        return math.hypot(dx, dy) <= w/2+slack
    if pad['shape'] == 'oval':
        r = min(w, h)/2; ax, ay = (max(w-h, 0)/2, 0) if w >= h else (0, max(h-w, 0)/2)
        return boards.segment_distance((dx, dy), (dx, dy), (-ax, -ay), (ax, ay)) <= r+slack
    # A roundrect is the rectangle shrunk by its corner radius, then grown by it.
    r = pad['rratio']*min(w, h) if pad['shape'] == 'roundrect' else 0
    ox, oy = max(abs(dx)-(w/2-r), 0), max(abs(dy)-(h/2-r), 0)
    return math.hypot(ox, oy) <= r+slack


def reach(kind, item):
    """Centre segment and bounding radius of a copper item."""
    if kind == 'pad':
        return item['at'], item['at'], math.hypot(*item['size'])/2
    if kind == 'track':
        return item['start'], item['end'], item['width']/2
    return item['at'], item['at'], item['size']/2


def contact(a, b):
    """'anchor' when KiCad's endpoint/centre anchor of one item lies on the other,
    'separate' when the copper cannot overlap, otherwise 'ambiguous'."""
    (ka, ia), (kb, ib) = a, b
    if kb == 'pad' and ka != 'pad':
        (ka, ia), (kb, ib) = b, a
    if ka == 'pad' and kb == 'pad':
        anchored = inside(ib['at'], ia, 1) or inside(ia['at'], ib, 1)
    elif ka == 'pad':
        anchors = (ib['start'], ib['end']) if kb == 'track' else (ib['at'],)
        anchored = any(inside(p, ia, 1) for p in anchors)
    else:
        (sa, ea, ra), (sb, eb, rb) = reach(ka, ia), reach(kb, ib)
        anchored = any(boards.segment_distance(p, p, sb, eb) <= rb+1 for p in {sa, ea}) or \
            any(boards.segment_distance(p, p, sa, ea) <= ra+1 for p in {sb, eb})
    if anchored:
        return 'anchor'
    (sa, ea, ra), (sb, eb, rb) = reach(ka, ia), reach(kb, ib)
    return 'separate' if boards.segment_distance(sa, ea, sb, eb) > ra+rb+1 else 'ambiguous'


def connectivity(board):
    """Count missing connections between pad clusters of each net, or explain why unchecked.

    Items join only through anchor contacts. Same-net copper that overlaps without
    such an anchor (crossing tracks, overlapping pads) is outside the model.
    """
    if board['zones']:
        return None, 'copper zones are not modelled'
    if not boards.modelled(board):
        return None, 'arcs or via padstacks are not modelled'
    pads = [p for p in board['pads'] if p['net'] and p['type'] != 'npth']
    if any(p['shape'] not in PAD_SHAPES or p['size'] is None or p['padstack'] or p['chamfer'] for p in pads):
        return None, 'custom, chamfered or padstack pad shapes are not modelled'
    nodes = [('pad', p) for p in pads]+[('track', t) for t in board['tracks'] if t['net']]+[
        ('via', v) for v in board['vias'] if v['net']]
    def layers(kind, item):
        return set(item['layers']) if kind != 'track' else {item['layer']}
    parent = list(range(len(nodes)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    extents = []
    for index, (kind, item) in enumerate(nodes):
        start, end, radius = reach(kind, item)
        extents.append((min(start[0], end[0])-radius, max(start[0], end[0])+radius, item['net'], index))
    extents.sort()
    by_net, compared = {}, 0
    for entry in extents:
        by_net.setdefault(entry[2], []).append(entry)
    for entries in by_net.values():
        for i, (_, right, _, a) in enumerate(entries):
            for left, _, _, b in entries[i+1:]:
                if left-right > 1:
                    break
                compared += 1
                if compared > boards.MAX_COMPARISONS:
                    return None, 'connectivity comparison budget exceeded'
                if not layers(*nodes[a]) & layers(*nodes[b]):
                    continue
                relation = contact(nodes[a], nodes[b])
                if relation == 'ambiguous':
                    return None, 'same-net copper overlaps without an endpoint or centre contact'
                if relation == 'anchor':
                    parent[root(a)] = root(b)
    clusters = {}
    for i, (kind, item) in enumerate(nodes):
        entry = clusters.setdefault((item['net'], root(i)), {'pads': 0})
        entry['pads'] += kind == 'pad'
    if any(c['pads'] == 0 for c in clusters.values()):
        return None, 'floating copper without pads is not modelled'
    nets = {}
    for net, _ in clusters:
        nets[net] = nets.get(net, 0)+1
    return sum(n-1 for n in nets.values()), None


def predict(board, rule):
    breaches, reason = boards.gaps(board, rule['clearance']) if rule['applicable'] else (None, rule['reason'])
    missing, why = connectivity(board)
    return {'clearance_mm': rule['clearance_mm'],
            'clearance': ({'status': 'checked', 'breaches': len(breaches),
                           'gaps_mm': [round(g/1e6, 4) for g in breaches]} if breaches is not None
                          else {'status': 'unchecked', 'reason': reason}),
            'unconnected': ({'status': 'checked', 'missing': missing} if why is None
                            else {'status': 'unchecked', 'reason': why})}


def read(path, version, source):
    """Validate the KiCad DRC v1 JSON subset and count findings by severity."""
    path = Path(path)
    check(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_REPORT_BYTES,
          'missing or excessive DRC report')
    report = json.loads(path.read_text(encoding='utf-8'))
    check(isinstance(report, dict) and report.get('$schema') == SCHEMA, 'DRC report schema differs')
    check(report.get('kicad_version') == version, 'DRC report version differs from the observed runtime')
    check(report.get('coordinate_units') == 'mm' and report.get('source') == source, 'DRC report units or source differ')
    check(report.get('included_severities') == list(SEVERITIES), 'DRC report omitted requested severities')
    check(report.get('schematic_parity') == [], 'schematic parity was not requested')
    findings = {}
    for key in ('violations', 'unconnected_items'):
        entries = report.get(key)
        check(isinstance(entries, list) and len(entries) <= 100000, 'DRC report list is malformed: '+key)
        for entry in entries:
            check(isinstance(entry, dict) and isinstance(entry.get('type'), str) and entry.get('severity') in SEVERITIES
                  and isinstance(entry.get('description'), str) and isinstance(entry.get('items'), list),
                  'DRC finding is malformed')
            for item in entry['items']:
                position = item.get('pos') if isinstance(item, dict) else None
                check(isinstance(position, dict) and all(type(position.get(a)) in (int, float) and math.isfinite(position[a])
                      for a in ('x', 'y')) and isinstance(item.get('description'), str), 'DRC finding item is malformed')
        findings[key] = entries
    check(all(v['type'] == 'unconnected_items' for v in findings['unconnected_items']), 'unconnected list has other types')
    counted = findings['violations']
    types = {}
    for entry in counted:
        name = entry['type']+':'+entry['severity']
        types[name] = types.get(name, 0)+1
    ignored = report.get('ignored_checks')
    check(isinstance(ignored, list) and all(isinstance(i, dict) and isinstance(i.get('key'), str) for i in ignored),
          'DRC ignored-check list is malformed')
    return {'errors': sum(v['severity'] == 'error' for v in counted),
            'warnings': sum(v['severity'] == 'warning' for v in counted),
            'exclusions': sum(v['severity'] == 'exclusion' for v in counted),
            'unconnected': sum(v['severity'] != 'exclusion' for v in findings['unconnected_items']),
            'byType': dict(sorted(types.items())), 'ignoredChecks': sorted(i['key'] for i in ignored),
            'findings': [{'type': v['type'], 'severity': v['severity'], 'description': v['description'],
                          'items': [i['description'] for i in v['items']]}
                         for v in counted+findings['unconnected_items']]}


def console(stdout, report):
    """KiCad prints the same totals it writes; disagreement indicates a mixed run."""
    found = re.search(r'Found (\d+) violations\s+Found (\d+) unconnected items', stdout)
    check(found is not None, 'native DRC console totals are missing')
    check(int(found[1]) == report['errors']+report['warnings']+report['exclusions'] and
          int(found[2]) == len([f for f in report['findings'] if f['type'] == 'unconnected_items']),
          'native DRC console totals differ from its JSON report')


def cross_check(report, prediction):
    """Compare host predictions with the native findings they model."""
    result = {}
    clearance = prediction['clearance']
    if clearance['status'] == 'checked':
        native = [f for f in report['findings'] if f['type'] in ('clearance', 'shorting_items')
                  and f['items'] and all(COPPER_ITEM.match(i) for i in f['items'])]
        check(len(native) == clearance['breaches'],
              f"native track/via clearance findings ({len(native)}) differ from host breaches ({clearance['breaches']})")
        actual = []
        for finding in native:
            if finding['type'] == 'clearance':
                found = ACTUAL.search(finding['description'])
                check(found is not None, 'native clearance finding lacks its actual gap')
                actual.append(round(float(found[1]), 4))
        expected = [g for g in clearance['gaps_mm'] if g > 0]
        # Native text rounds to 0.0001 mm; host gaps are rounded the same way.
        check(len(actual) == len(expected) and all(abs(a-b) <= 0.00006 for a, b in zip(sorted(actual), sorted(expected))),
              'native clearance gaps differ from host geometry')
        result['clearance'] = 'confirmed'
    else:
        result['clearance'] = 'unchecked: '+clearance['reason']
    unconnected = prediction['unconnected']
    if unconnected['status'] == 'checked':
        native = len([f for f in report['findings'] if f['type'] == 'unconnected_items'])
        check(native == unconnected['missing'],
              f"native unconnected items ({native}) differ from host pad clusters ({unconnected['missing']})")
        result['unconnected'] = 'confirmed'
    else:
        result['unconnected'] = 'unchecked: '+unconnected['reason']
    return result


def assess(report, options):
    """Apply authored maximum counts to native findings; never infer a pass."""
    limits = {'errors': options['maximumErrors'], 'warnings': options['maximumWarnings'],
              'unconnected': options['maximumUnconnected']}
    observed = {key: report[key] for key in limits}
    failed = sorted(key for key in limits if observed[key] > limits[key])
    return {'accepted': not failed, 'observed': observed, 'maximum': limits, 'exceeded': failed,
            'exclusions': report['exclusions']}
