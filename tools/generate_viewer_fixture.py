#!/usr/bin/env python3
"""Generate a reproducible mixed-media viewer collection (Pillow; optional FFmpeg).

Copyright (C) 2026 David L. F. Gaden.
SPDX-License-Identifier: Apache-2.0
"""
import argparse
import csv
import math
from pathlib import Path
import shutil
import struct
import subprocess
import wave

from PIL import Image, ImageDraw
from schemaxis.artifact_names import OutputSequence, stem
from schemaxis.publication_metadata import publish_artifacts


def frame(axis, variable, position, model, time=0):
    image = Image.new('RGB', (480, 300))
    pixels = image.load()
    for y in range(300):
        for x in range(480):
            v = .5 + .35 * math.sin(x/65 + time + position*4) * math.cos(y/45 + 'XYZ'.index(axis))
            if variable == 'p':
                v = 1-v
            pixels[x, y] = (int(230*v), int(160*(1-abs(2*v-1)))+35, int(230*(1-v)))
    draw = ImageDraw.Draw(image)
    if model:
        draw.ellipse((90, 105, 160, 185), fill='#374151', outline='white', width=3)
    draw.rectangle((0, 0, 480, 48), fill='#14202a')
    draw.text((12, 10), f'SYNTHETIC SAMPLE | {variable} | {axis}={position:g} | t={time:g}', fill='white')
    draw.text((12, 28), 'Procedural illustration; no solver was run.', fill='#b4c9d5')
    return image


def generate(destination, *, ffmpeg=None, video=True):
    destination = Path(destination).absolute()
    destination.mkdir(parents=True, exist_ok=False)
    sequence = OutputSequence(destination)
    artifacts = []

    def output(folder, fields, extension, *, worker=None, index=None):
        target = destination / folder
        target.mkdir(exist_ok=True)
        if worker is None:
            return sequence.path(target, fields, extension)
        return target / (stem(index, fields, worker=worker)+extension)

    def record(path, kind, **metadata):
        artifacts.append({'file': str(path), 'kind': kind, 'provenance': {'synthetic': True}, **metadata})

    for variable in ('U', 'p'):
        for axis in 'XYZ':
            for position in (-.0483, 0, .083, .2):
                for model in ('on', 'off'):
                    fields = {'kind': 'slice', 'axis': axis, 'pos': position, 'var': variable,
                              'time': 0, 'model': model, 'view': 0}
                    path = output('slices', fields, '.png')
                    frame(axis, variable, position, model == 'on').save(path)
                    # A registered, unit cube slice; viewport edges span the whole face.
                    corners = ([[position, 0, 1], [position, 1, 1], [position, 1, 0], [position, 0, 0]] if axis == 'X' else
                               [[0, position, 1], [1, position, 1], [1, position, 0], [0, position, 0]] if axis == 'Y' else
                               [[0, 1, position], [1, 1, position], [1, 0, position], [0, 0, position]])
                    normal = [int(a == axis) for a in 'XYZ']
                    origin = [position if a == axis else 0 for a in 'XYZ']
                    record(path, 'image', viewTime=0, spatial={'state': 'known', 'frame': 'synthetic-world', 'units': 'm',
                           'mapping': 'pixel-edge-rays-to-slice-plane', 'plane': {'origin': origin, 'normal': normal},
                           'corners': corners, 'cornerOrder': ['top-left', 'top-right', 'bottom-right', 'bottom-left'],
                           'pixelOrigin': 'top-left', 'rowDirection': 'down'})
    frames = []
    for i in range(12):
        image = frame('X', 'U', 0, True, i/4)
        frames.append(image)
        path = output('time', {'kind': 'image', 'var': 'U', 'time': i/4, 'view': 0}, '.png')
        image.save(path)
        record(path, 'image')
    path = output('media', {'kind': 'animation', 'var': 'U', 'name': 'pulse'}, '.gif')
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=125, loop=0)
    record(path, 'image')
    if video:
        executable = ffmpeg or shutil.which('ffmpeg')
        if not executable:
            raise RuntimeError('Supply --ffmpeg /path/to/ffmpeg with libx264, or use --no-video for a smaller fixture')
        path = output('media', {'kind': 'animation', 'var': 'U', 'name': 'pulse'}, '.mp4')
        subprocess.run([executable, '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '480x300',
                        '-framerate', '8', '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart', str(path)], input=b''.join(image.tobytes() for image in frames), check=True, timeout=60)
        record(path, 'video')
        path = output('media', {'kind': 'animation', 'var': 'U', 'name': 'browserPulse'}, '.webm')
        subprocess.run(['node', str(Path(__file__).with_name('generate_viewer_webm.mjs')), str(path)], check=True, timeout=60)
        record(path, 'video')
    path = output('media', {'kind': 'audio', 'name': 'tone'}, '.wav')
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b''.join(struct.pack('<h', int(2500*math.sin(2*math.pi*440*i/8000))) for i in range(8000)))
    record(path, 'audio')
    for delimiter, extension in ((',', '.csv'), ('\t', '.tsv')):
        path = output('tables', {'kind': 'table', 'name': 'forces', 'related': ['U', 'p']}, extension)
        with path.open('w', newline='') as stream:
            writer = csv.writer(stream, delimiter=delimiter)
            writer.writerow(['time_s', 'drag_N', 'lift_N', 'note'])
            for i in range(40):
                writer.writerow([i*.05, 2+math.sin(i/5)*.2, math.cos(i/5)*.1, 'quoted, field\nand second line' if i == 3 else 'sample'])
        record(path, 'table')
    path = output('geometry', {'kind': 'geometry', 'name': 'wedge'}, '.obj')
    path.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n')
    record(path, 'geometry', spatial={'state': 'known', 'frame': 'synthetic-world', 'units': 'm'})
    path = output('geometry', {'kind': 'geometry', 'name': 'triangle'}, '.stl')
    path.write_text('solid sample\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid sample\n')
    record(path, 'geometry')
    path = output('records', {'kind': 'text', 'name': 'run', 'tags': ['sample', 'review']}, '.log')
    path.write_text('SYNTHETIC VIEWER FIXTURE\nNo solver was run.\nINFO: export complete\nWARNING: sample warning for text search\n')
    record(path, 'text')
    index = sequence.reserve()
    for worker in (2, 20):
        path = output('edge-cases', {'kind': 'text', 'name': 'worker'}, '.txt', worker=worker, index=index)
        path.write_text(f'Independent worker identifier: {worker}\n')
        record(path, 'text')
    path = output('edge-cases', {'kind': 'image', 'var': 'wall_shear', 'related': ['A', '11'], 'normal': [-2.1, 1., 3]}, '.png')
    frames[0].save(path)
    record(path, 'image')
    # Deliberately unregistered and malformed names exercise fallback behaviour.
    for name in ('velocity_x_001.png', 'velocity_x_002.png', '000099__var_U__var_p.png'):
        frames[0].save(destination / 'edge-cases' / name)
    path = output('edge-cases', {'kind': 'slice', 'axis': 'X', 'pos': 123, 'var': 'p'}, '.png')
    frames[0].save(path)
    # Valid checked metadata contradicts the filename; metadata must win.
    conflict = {**artifacts[0], 'file': str(path), 'spatial': {**artifacts[0]['spatial'],
                'plane': {'origin': [0, 0, .5], 'normal': [0, 0, 1]},
                'corners': [[0, 1, .5], [1, 1, .5], [1, 0, .5], [0, 0, .5]]}}
    # Publish the complete membership once, including the conflicting-hint case.
    publish_artifacts(destination, artifacts+[conflict])
    (destination / 'README.txt').write_text('Synthetic viewer fixture; no solver was run.\n'
        'Try kind=slice, axis=X, var=U, model=on. Clear properties to explore other media.\n'
        'Slices have checked image-plane companions. edge-cases includes legacy names, escaped values,\n'
        'worker .2/.20, a malformed dictionary, an unregistered image, and contradictory filename hints.\n'
        'MP4/WebM/GIF contain actual animation. The WAV is a short quiet test tone.\n')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--ffmpeg')
    parser.add_argument('--no-video', action='store_true')
    args = parser.parse_args()
    print(generate(args.destination, ffmpeg=args.ffmpeg, video=not args.no_video))
