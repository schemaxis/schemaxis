"""Independent reader for KiCad's decimal absolute Excellon drill subset."""
import math
import re
from pathlib import Path
from .board import check

MAX_DRILL_BYTES = 4*1024*1024
TOOL = re.compile(r'^T(\d{1,3})C(\d+(?:\.\d+)?)$')
HIT = re.compile(r'^X(-?\d+(?:\.\d+)?)Y(-?\d+(?:\.\d+)?)$')
SELECT = re.compile(r'^T(\d{1,3})$')
FUNCTION = re.compile(r'^; #@! TF\.FileFunction,(Plated|NonPlated|MixedPlating),1,2(?:,(PTH|NPTH))?$')
APERTURE = re.compile(r'^; #@! TA\.AperFunction,(Plated|NonPlated),(PTH|NPTH),[A-Za-z]+$')
# KiCad writes decimal metric coordinates with three and inch coordinates with
# four fractional digits; half of one written digit bounds the rounding.
RESOLUTION = {'mm': 0.0005, 'in': 0.00005}
SCALE = {'mm': 1.0, 'in': 25.4}


def files(stem, separate):
    return [stem+'-PTH.drl', stem+'-NPTH.drl'] if separate else [stem+'.drl']


def read(path, units):
    """Return the declared plating role, tools and hits of one drill file."""
    path = Path(path)
    check(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_DRILL_BYTES,
          'missing or excessive drill file: '+path.name)
    lines = [line.strip() for line in path.read_text(encoding='ascii').splitlines()]
    check(lines and lines[0] == 'M48' and lines[-1] == 'M30' and lines.count('%') == 1,
          'drill file lacks an Excellon header/body/end structure: '+path.name)
    split = lines.index('%'); header, body = lines[1:split], lines[split+1:-1]
    role, tools, pending = None, {}, None
    for line in header:
        found = FUNCTION.match(line)
        if found:
            check(role is None, 'repeated drill file function'); role = found[1]; continue
        found = APERTURE.match(line)
        if found:
            pending = found[1] == 'Plated'; continue
        if line.startswith(';'):
            continue
        found = TOOL.match(line)
        if found:
            number = int(found[1])
            check(number not in tools and pending is not None, 'drill tool lacks a unique plating attribute')
            tools[number] = {'diameter': float(found[2])*SCALE[units], 'plated': pending}; pending = None; continue
        check(line in ('FMAT,2', 'METRIC' if units == 'mm' else 'INCH'), 'unexpected drill header line: '+line)
    check(role is not None and ('METRIC' if units == 'mm' else 'INCH') in header, 'drill units or file function differ')
    check(body[:2] == ['G90', 'G05'], 'drill body must select absolute drilling mode')
    hits, selected = [], None
    for line in body[2:]:
        found = SELECT.match(line)
        if found:
            check(int(found[1]) in tools, 'drill body selects an undefined tool'); selected = int(found[1]); continue
        found = HIT.match(line)
        check(found is not None and selected is not None, 'unsupported drill body line: '+line)
        x, y = float(found[1])*SCALE[units], float(found[2])*SCALE[units]
        check(math.isfinite(x) and math.isfinite(y), 'nonfinite drill coordinate')
        hits.append({'tool': selected, 'x': x, 'y': y, **tools[selected]})
    return {'file': path.name, 'role': role, 'tools': len(tools), 'hits': hits}


def compare(holes, readings, units, separate):
    """Match every board hole to exactly one drill hit of the same plating and size."""
    tolerance = RESOLUTION[units]*SCALE[units]+1e-9
    roles = [r['role'] for r in readings]
    check(roles == (['Plated', 'NonPlated'] if separate else ['MixedPlating']), 'drill file plating roles differ')
    if separate:
        for reading, plated in zip(readings, (True, False)):
            check(all(h['plated'] is plated for h in reading['hits']), 'hit plating differs from its drill file role')
    hits = [h for r in readings for h in r['hits']]
    check(len(hits) == len(holes), 'drill hit count differs from host-located holes')
    # Excellon uses a y-up frame; KiCad board coordinates are y-down.
    remaining = sorted(hits, key=lambda h: (h['plated'], h['x'], -h['y']))
    worst = 0.0
    for hole in sorted(holes, key=lambda h: (h['plated'], h['x'], h['y'])):
        x, y, d = hole['x']/1e6, hole['y']/1e6, hole['diameter']/1e6
        for index, hit in enumerate(remaining):
            error = max(abs(hit['x']-x), abs(-hit['y']-y))
            if hit['plated'] is hole['plated'] and abs(hit['diameter']-d) <= tolerance and error <= tolerance:
                worst = max(worst, error); del remaining[index]; break
        else:
            check(False, f"no drill hit matches {hole['item']} at ({x:g}, {y:g}) mm, diameter {d:g} mm")
    return {'holes': len(holes), 'plated': sum(h['plated'] for h in holes),
            'nonPlated': sum(not h['plated'] for h in holes), 'maximumPositionError_mm': round(worst, 6),
            'tolerance_mm': round(tolerance, 6), 'files': [r['file'] for r in readings],
            'tools': sum(r['tools'] for r in readings)}
