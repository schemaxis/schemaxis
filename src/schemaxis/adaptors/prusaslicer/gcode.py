# Copyright (C) 2026 David L F Gaden
"""Independent bounded interpretation of the published FFF G-code.

This module does not reuse slicer code or trust native annotations. It replays
the motion and temperature commands that the adaptor's fixed policy can emit,
derives layers, extrusion envelopes, filament use and kinematic time bounds,
and separately extracts native comments so the two can be compared.
"""
import math
import re

MAX_BYTES = 64*1024*1024
MAX_LINE = 4096
# Commands that the fixed generation policy can emit. Anything else, including
# arcs, inch units, firmware retraction and tool changes, is rejected so the
# replay never silently ignores motion or temperature semantics.
MOTION = {'G0', 'G1'}
# Parameterless setup/finish commands from the fixed start/end G-code.
IGNORED = {'G21', 'M84'}
MODAL = {'G90', 'G91', 'G92', 'M82', 'M83'}
THERMAL = {'M104', 'M109', 'M140', 'M190'}
FAN = {'M106'}
WORD = re.compile(r'([A-Z])([-+]?(?:\d+(?:\.\d*)?|\.\d+))')
DURATION = re.compile(r'^(?:(\d+)d\s*)?(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?$')
STATISTICS = {
    'filament used [mm]': 'filamentLength_mm', 'filament used [cm3]': 'filamentVolume_cm3',
    'filament used [g]': 'filamentMass_g', 'total filament used [g]': 'totalFilamentMass_g',
    'estimated printing time (normal mode)': 'printTime_s',
    'estimated first layer printing time (normal mode)': 'firstLayerPrintTime_s'}


class GcodeError(ValueError):
    def __init__(self, message, **observed):
        super().__init__(message)
        self.observed = observed


def seconds(text):
    match = DURATION.match(text.strip())
    if not text.strip() or not match:
        raise GcodeError('native duration annotation is malformed', value=text)
    days, hours, minutes, secs = (int(value or 0) for value in match.groups())
    return ((days*24 + hours)*60 + minutes)*60 + secs


def _words(code, number):
    parts = code.split()
    command = parts[0]
    words = {}
    for part in parts[1:]:
        match = WORD.fullmatch(part)
        if not match or match.group(1) in words:
            raise GcodeError('G-code parameter is malformed or repeated', line=number, text=code[:120])
        value = float(match.group(2))
        if not math.isfinite(value):
            raise GcodeError('G-code parameter is not finite', line=number)
        words[match.group(1)] = value
    return command, words


def _trapezoid(distance, speed, acceleration):
    # Rest-to-rest time is an upper bound for any planner that respects the
    # same speed and acceleration limits; junction speeds can only shorten it.
    if distance >= speed*speed/acceleration:
        return distance/speed + speed/acceleration
    return 2*math.sqrt(distance/acceleration)


def interpret(data, limits):
    """Replay bounded G-code bytes.

    ``limits`` holds machine feedrate limits (mm/s) for x, y, z and e and one
    acceleration (mm/s^2) used by the adaptor's fixed time-estimate policy.
    """
    if len(data) > MAX_BYTES:
        raise GcodeError('G-code exceeds the 64 MiB publication budget', bytes=len(data))
    try:
        text = data.decode('ascii')
    except UnicodeError:
        raise GcodeError('G-code must be ASCII text') from None
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    header = lines[0] if lines else ''
    config, statistics, annotations = {}, {}, []
    in_config = False
    position = {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
    extruder = 0.0
    feed = None
    absolute_xyz, relative_e = True, False
    nozzle = bed = None
    fan = 0.0
    waits = []
    temperatures = []
    layers = {}
    order = []
    totals = {'extrusionMoves': 0, 'travelMoves': 0, 'retractions': 0, 'deretractions': 0,
              'retractedLength_mm': 0.0, 'extrudedLength_mm': 0.0, 'pathLength_mm': 0.0,
              'travelLength_mm': 0.0, 'maxTravelFeed_mm_s': 0.0, 'kinematicLowerBound_s': 0.0,
              'accelerationUpperBound_s': 0.0}
    bounds = {'min': [math.inf]*3, 'max': [-math.inf]*3}
    first_extrusion = None
    commands = {}
    for number, raw in enumerate(lines, 1):
        if len(raw) > MAX_LINE:
            raise GcodeError('G-code line exceeds the bounded length', line=number)
        line = raw.rstrip('\r')
        code, _, comment = line.partition(';')
        comment = comment.strip()
        if comment == 'prusaslicer_config = begin':
            if in_config or config:
                raise GcodeError('repeated native configuration block', line=number)
            in_config = True
            continue
        if comment == 'prusaslicer_config = end':
            if not in_config:
                raise GcodeError('native configuration block end without begin', line=number)
            in_config = False
            continue
        if in_config:
            # Use the raw line: empty values end in a significant space.
            if not line.startswith('; '):
                raise GcodeError('commands are not allowed inside the configuration block', line=number)
            key, separator, value = line[2:].partition(' = ')
            if not separator or key in config:
                raise GcodeError('malformed or repeated native configuration entry', line=number)
            config[key] = value
            continue
        if comment and not code.strip():
            key, separator, value = comment.partition(' = ')
            if separator and key in STATISTICS:
                if STATISTICS[key] in statistics:
                    raise GcodeError('repeated native statistic', line=number, key=key)
                try:
                    statistics[STATISTICS[key]] = seconds(value) if key.startswith('estimated') else float(value)
                except ValueError:
                    raise GcodeError('native statistic is not numeric', line=number, key=key) from None
            elif comment.startswith('Z:'):
                annotations.append(float(comment[2:]))
        code = code.strip()
        if not code:
            continue
        command, words = _words(code, number)
        commands[command] = commands.get(command, 0) + 1
        if command in MOTION:
            if 'F' in words:
                if words['F'] <= 0:
                    raise GcodeError('feedrate must be positive', line=number)
                feed = words['F']
            target = dict(position)
            for axis in 'XYZ':
                if axis in words:
                    target[axis] = words[axis] if absolute_xyz else position[axis]+words[axis]
            delta_e = 0.0
            if 'E' in words:
                delta_e = words['E'] if relative_e else words['E']-extruder
                extruder = extruder+words['E'] if relative_e else words['E']
            dx, dy, dz = (target[a]-position[a] for a in 'XYZ')
            planar = math.hypot(dx, dy)
            spatial = math.sqrt(dx*dx + dy*dy + dz*dz)
            if spatial > 0 or delta_e != 0:
                if feed is None:
                    raise GcodeError('motion before any feedrate', line=number)
                for index, axis in enumerate('XYZ'):
                    bounds['min'][index] = min(bounds['min'][index], target[axis])
                    bounds['max'][index] = max(bounds['max'][index], target[axis])
                distance = spatial if spatial > 0 else abs(delta_e)
                speed = feed/60
                if spatial > 0:
                    for axis, change in (('x', dx), ('y', dy), ('z', dz), ('e', delta_e)):
                        if change:
                            speed = min(speed, limits[axis]*distance/abs(change))
                else:
                    speed = min(speed, limits['e'])
                totals['kinematicLowerBound_s'] += distance/speed
                totals['accelerationUpperBound_s'] += _trapezoid(distance, speed, limits['acceleration'])
            if delta_e > 0 and planar > 0:
                if dz:
                    raise GcodeError('extrusion while changing Z is outside the planar-layer policy', line=number)
                z = round(position['Z'], 6)
                if z not in layers:
                    if order and z < order[-1]:
                        raise GcodeError('extrusion returned to a lower layer', line=number, z=z)
                    order.append(z)
                    layers[z] = {'z_mm': z, 'moves': 0, 'path_mm': 0.0, 'filament_mm': 0.0,
                                 'min': [math.inf, math.inf], 'max': [-math.inf, -math.inf],
                                 'maxFeed_mm_s': 0.0, 'nozzle': set(), 'bed': set(), 'fan': set()}
                elif order[-1] != z:
                    raise GcodeError('extrusion returned to an earlier layer', line=number, z=z)
                layer = layers[z]
                layer['moves'] += 1
                layer['path_mm'] += planar
                layer['filament_mm'] += delta_e
                layer['maxFeed_mm_s'] = max(layer['maxFeed_mm_s'], feed/60)
                for point in ((position['X'], position['Y']), (target['X'], target['Y'])):
                    for axis in range(2):
                        layer['min'][axis] = min(layer['min'][axis], point[axis])
                        layer['max'][axis] = max(layer['max'][axis], point[axis])
                layer['nozzle'].add(nozzle)
                layer['bed'].add(bed)
                layer['fan'].add(fan)
                totals['extrusionMoves'] += 1
                totals['extrudedLength_mm'] += delta_e
                totals['pathLength_mm'] += planar
                if first_extrusion is None:
                    first_extrusion = number
            elif delta_e < 0 and planar == 0 and dz == 0:
                totals['retractions'] += 1
                totals['retractedLength_mm'] += -delta_e
            elif delta_e > 0 and planar == 0 and dz == 0:
                totals['deretractions'] += 1
            elif delta_e == 0 and spatial > 0:
                totals['travelMoves'] += 1
                totals['travelLength_mm'] += spatial
                totals['maxTravelFeed_mm_s'] = max(totals['maxTravelFeed_mm_s'], feed/60)
            elif delta_e != 0:
                raise GcodeError('retracting or extruding move outside the fixed policy', line=number)
            position = target
        elif command in MODAL:
            if command != 'G92' and words:
                raise GcodeError('modal command has unexpected parameters', line=number, command=command)
            if command == 'G90':
                absolute_xyz = True
            elif command == 'G91':
                absolute_xyz = False
            elif command == 'M82':
                relative_e = False
            elif command == 'M83':
                relative_e = True
            elif command == 'G92':
                if set(words) - {'E'}:
                    raise GcodeError('only extruder G92 resets are supported', line=number)
                extruder = words.get('E', 0.0)
        elif command in THERMAL:
            if set(words) != {'S'} or not 0 <= words['S'] <= 500:
                raise GcodeError('temperature command needs one bounded S setpoint', line=number)
            if command in ('M104', 'M109'):
                nozzle = words['S']
            else:
                bed = words['S']
            entry = {'line': number, 'command': command, 'celsius': words['S'],
                     'beforeFirstExtrusion': first_extrusion is None}
            temperatures.append(entry)
            if command in ('M109', 'M190'):
                waits.append(entry)
        elif command in FAN:
            if set(words) - {'S'} or not 0 <= words.get('S', 255) <= 255:
                raise GcodeError('fan command needs a bounded S value', line=number)
            fan = words.get('S', 255)*100/255
        elif command == 'M107':
            if words:
                raise GcodeError('M107 has unexpected parameters', line=number)
            fan = 0.0
        elif command == 'G28':
            # The fixed start G-code homes once, before any motion. Homing is
            # modelled at the bed origin, as the native estimator does.
            if words or commands['G28'] > 1 or any(commands.get(m) for m in MOTION):
                raise GcodeError('only one bare G28 before any motion is supported', line=number)
            position = {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
        elif command in IGNORED:
            if words:
                raise GcodeError('fixed setup command has unexpected parameters', line=number, command=command)
        else:
            raise GcodeError('G-code command is outside the fixed generation policy', line=number, command=command)
    if in_config:
        raise GcodeError('native configuration block is not closed')
    if not order:
        raise GcodeError('G-code contains no planar extrusion')
    table = []
    for index, z in enumerate(order):
        layer = layers[z]
        for key in ('nozzle', 'bed', 'fan'):
            # None means no setpoint was commanded before that extrusion.
            layer[key] = sorted(layer[key], key=lambda value: (value is not None, value or 0))
        table.append({'layer': index+1, **layer})
    return {'header': header, 'config': config, 'statistics': statistics, 'annotations': annotations,
            'layers': table, 'totals': totals, 'bounds': bounds, 'temperatures': temperatures,
            'waits': waits, 'commands': commands, 'firstExtrusionLine': first_extrusion}
