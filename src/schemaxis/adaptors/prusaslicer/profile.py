"""Render declared FFF intent into one complete, fixed-policy PrusaSlicer config.

Only the documented keys below reach the native process. Authored text never
becomes G-code, scripts, preset names or native option names.
"""
import math

START_GCODE = 'G21\nG90\nM83\nG28\nG92 E0'
END_GCODE = 'M104 S0\nM140 S0\nM107\nM84'
# Required by PrusaSlicer with relative extrusion to bound E rounding drift.
LAYER_GCODE = 'G92 E0'
# Policy machine limits that are not authored. Values are only used by the
# native time estimator (time_estimate_only); they are not emitted as commands.
Z_FEEDRATE = 12
E_FEEDRATE = 120
RETRACT_LENGTH = 0.8
RETRACT_SPEED = 35
SLOWDOWN_LAYER_TIME = 5
MIN_PRINT_SPEED = 10


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('configuration numbers must be finite')
    text = format(value, '.10g')
    return '0' if text == '-0' else text


def escape(text):
    return text.replace('\\', '\\\\').replace('\n', '\\n')


def entries(prepared):
    printer, material, settings = prepared['printer'], prepared['material'], prepared['print']
    width, depth = printer['bedSize_mm']
    a = number(printer['maxAcceleration_mm_s2'])
    w = number(settings['extrusionWidth_mm'])
    perimeter, infill = number(settings['perimeterSpeed_mm_s']), number(settings['infillSpeed_mm_s'])
    fan = number(material['fanSpeed_percent'])
    values = [
        ('printer_technology', 'FFF'),
        ('bed_shape', f'0x0,{number(width)}x0,{number(width)}x{number(depth)},0x{number(depth)}'),
        ('max_print_height', number(printer['maxPrintHeight_mm'])),
        ('nozzle_diameter', number(printer['nozzleDiameter_mm'])),
        ('gcode_flavor', printer['gcodeFlavour']),
        ('machine_limits_usage', 'time_estimate_only'),
        ('machine_max_feedrate_x', number(printer['maxFeedrate_mm_s'])),
        ('machine_max_feedrate_y', number(printer['maxFeedrate_mm_s'])),
        ('machine_max_feedrate_z', number(Z_FEEDRATE)),
        ('machine_max_feedrate_e', number(E_FEEDRATE)),
        ('machine_max_acceleration_x', a), ('machine_max_acceleration_y', a),
        ('machine_max_acceleration_z', a), ('machine_max_acceleration_e', a),
        ('machine_max_acceleration_extruding', a), ('machine_max_acceleration_retracting', a),
        ('machine_max_acceleration_travel', a),
        ('machine_min_extruding_rate', '0'), ('machine_min_travel_rate', '0'),
        ('silent_mode', '0'),
        ('retract_length', number(RETRACT_LENGTH)), ('retract_speed', number(RETRACT_SPEED)),
        ('deretract_speed', '0'), ('retract_lift', '0'), ('retract_restart_extra', '0'),
        ('retract_before_travel', '2'), ('retract_layer_change', '1'), ('wipe', '0'),
        ('travel_ramping_lift', '0'), ('travel_max_lift', '0'),
        ('use_firmware_retraction', '0'), ('use_relative_e_distances', '1'), ('z_offset', '0'),
        ('start_gcode', escape(START_GCODE)), ('end_gcode', escape(END_GCODE)),
        ('before_layer_gcode', ''), ('layer_gcode', escape(LAYER_GCODE)), ('toolchange_gcode', ''),
        ('between_objects_gcode', ''), ('color_change_gcode', ''), ('pause_print_gcode', ''),
        ('template_custom_gcode', ''),
        # Per-extruder lists need one explicit empty element; an empty list is
        # read past its end by the 2.9.6 G-code template processor.
        ('start_filament_gcode', '""'), ('end_filament_gcode', '""'),
        ('autoemit_temperature_commands', '1'), ('binary_gcode', '0'), ('gcode_comments', '0'),
        ('gcode_label_objects', 'disabled'), ('gcode_substitutions', ''), ('post_process', ''),
        ('thumbnails', ''), ('remaining_times', '0'),
        ('filament_type', material['type']),
        ('filament_diameter', number(material['filamentDiameter_mm'])),
        ('filament_density', number(material['density_g_cm3'])),
        ('temperature', number(material['nozzleTemperature_C'])),
        ('first_layer_temperature', number(material['firstLayerNozzleTemperature_C'])),
        ('bed_temperature', number(material['bedTemperature_C'])),
        ('first_layer_bed_temperature', number(material['firstLayerBedTemperature_C'])),
        ('extrusion_multiplier', '1'), ('filament_max_volumetric_speed', '0'), ('max_volumetric_speed', '0'),
        ('cooling', '1'), ('fan_always_on', '1'), ('min_fan_speed', fan), ('max_fan_speed', fan),
        ('bridge_fan_speed', fan), ('disable_fan_first_layers', '1'), ('full_fan_speed_layer', '0'),
        ('enable_dynamic_fan_speeds', '0'), ('fan_below_layer_time', '60'),
        ('slowdown_below_layer_time', number(SLOWDOWN_LAYER_TIME)), ('min_print_speed', number(MIN_PRINT_SPEED)),
        ('layer_height', number(settings['layerHeight_mm'])),
        ('first_layer_height', number(settings['firstLayerHeight_mm'])),
        ('perimeters', number(settings['perimeters'])),
        ('top_solid_layers', number(settings['topSolidLayers'])),
        ('bottom_solid_layers', number(settings['bottomSolidLayers'])),
        ('top_solid_min_thickness', '0'), ('bottom_solid_min_thickness', '0'),
        ('fill_density', number(settings['infillDensity_percent']) + '%'),
        ('fill_pattern', settings['infillPattern']), ('top_fill_pattern', 'rectilinear'),
        ('bottom_fill_pattern', 'rectilinear'), ('fill_angle', '45'), ('infill_every_layers', '1'),
        ('extrusion_width', w), ('first_layer_extrusion_width', w), ('perimeter_extrusion_width', w),
        ('external_perimeter_extrusion_width', w), ('infill_extrusion_width', w),
        ('solid_infill_extrusion_width', w), ('top_infill_extrusion_width', w),
        ('perimeter_speed', perimeter), ('small_perimeter_speed', perimeter),
        ('external_perimeter_speed', perimeter), ('infill_speed', infill), ('solid_infill_speed', infill),
        ('top_solid_infill_speed', infill), ('gap_fill_speed', infill), ('bridge_speed', infill),
        ('first_layer_speed', number(settings['firstLayerSpeed_mm_s'])),
        ('travel_speed', number(settings['travelSpeed_mm_s'])), ('travel_speed_z', '0'),
        ('enable_dynamic_overhang_speeds', '0'),
        ('skirts', '0'), ('brim_width', '0'), ('brim_type', 'no_brim'), ('support_material', '0'),
        ('support_material_auto', '0'), ('raft_layers', '0'), ('ironing', '0'), ('spiral_vase', '0'),
        ('complete_objects', '0'), ('wipe_tower', '0'), ('ooze_prevention', '0'),
        ('single_extruder_multi_material', '0'), ('avoid_crossing_perimeters', '0'),
        ('extra_perimeters', '0'), ('extra_perimeters_on_overhangs', '0'), ('thin_walls', '0'),
        ('xy_size_compensation', '0'), ('elefant_foot_compensation', '0'), ('arc_fitting', 'disabled'),
        ('seam_position', 'aligned'), ('fuzzy_skin', 'none'), ('infill_first', '0'),
        ('interface_shells', '0'), ('external_perimeters_first', '0'), ('gap_fill_enabled', '1'),
    ]
    keys = [key for key, _ in values]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate fixed configuration key')
    return values


def ini(values):
    return ('# Generated by Schemaxis from a declared schemaxis.prusaslicer/1 document.\n'
            + ''.join(f'{key} = {value}\n' for key, value in values)).encode('ascii')


def same(expected, observed):
    """Compare one written value with the native resolved value."""
    if expected == observed:
        return True
    try:
        left = float(expected.rstrip('%'))
        right = float(observed.rstrip('%'))
    except ValueError:
        return False
    return expected.endswith('%') == observed.endswith('%') and math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12)
