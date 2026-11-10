#!/usr/bin/env python3
"""Create a mixed-layout viewer collection with Schemaxis and legacy names.

Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import struct
import zlib

from schemaxis.artifact_names import OutputSequence
from schemaxis.adaptors.paraview.output_names import image_properties


def png(phase, width=240, height=150):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    pixels = b''.join(b'\0' + bytes(component for x in range(width)
                      for component in ((x + phase * 30) % 256, (y * 2) % 256, (x + y + phase * 40) % 256))
                      for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def add_legacy_examples(destination):
    """Append tiny legacy fixtures; names and directories carry the test data."""
    destination = Path(destination)
    names = []
    for folder in ('folders/alpha/icons', 'folders/beta/icons'):
        names += [f'{folder}/file-{code}-{i}-name.png' for i, code in enumerate(('AAA', 'AAB', 'AAC', 'AAD'))]
    names += [f'legacy/numeric/shot-{i:03d}.png' for i in (1, 2, 10)]
    names += [f'legacy/alphabetic/phase-{code}.png' for code in ('A', 'B', 'Z', 'AA')]
    names += [f'legacy/slices/{name}.png' for name in ('Slices.X.001', 'slices.X.002', 'Slices.Y.003', 'Slices.Z.010', 'model')]
    names += [f'legacy/tags/file-{code}-{i}-tags-{tags}-enclosedByDashes-name.png'
              for i, (code, tags) in enumerate((('AAA', 'red.blue'), ('AAB', 'blue.green'), ('AAC', 'red.green'), ('AAD', 'DOT.SEPERATED.TAGS')))]
    for index, name in enumerate(names):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(png(index, 16, 16))
    (destination / 'legacy/slices/error.log').write_text('This filename must receive no grep capture values.\n')
    examples = {'version': 'artifact.filename-rules/1', 'rules': [
        {'name': 'Slices', 'enabled': True, 'pattern': r'[sS]lices[._-]([XYZ])[._-]([0-9]+)',
         'columns': [{'index': 1, 'key': 'axis', 'type': 'text'}, {'index': 2, 'key': 'number', 'type': 'number'}]},
        {'name': 'Dot-separated tags', 'enabled': True, 'pattern': '-tags-([^-]+)-enclosedByDashes-',
         'columns': [{'index': 1, 'key': 'tags', 'type': 'tags', 'separator': '.'}]},
        {'name': 'File code and index', 'enabled': True, 'pattern': r'file-([A-Z]+)-([0-9]+)-',
         'columns': [{'index': 1, 'key': 'code', 'type': 'text'}, {'index': 2, 'key': 'index', 'type': 'number'}]},
    ]}
    (destination / 'legacy/filename-rules.examples.json').write_text(json.dumps(examples, indent=2)+'\n')


def generate(destination, *, video=None):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    sequence = OutputSequence(destination)

    def artifact(properties, extension, content, **metadata):
        target = sequence.path(destination, properties, extension)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
        companion = {'version': 'schemaxis.artifact-metadata/1',
                     'artifact': {'file': target.name, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()},
                     'provenance': {'synthetic': True}, **metadata}
        target.with_name(target.name + '.metadata.json').write_text(json.dumps(companion, indent=2) + '\n')

    for variable in ('U', 'p'):
        for axis in 'XYZ':
            for index, position in enumerate((.1, .4, .9)):
                corners = ([[position, 0, 1], [position, 1, 1], [position, 1, 0], [position, 0, 0]] if axis == 'X' else
                           [[0, position, 1], [1, position, 1], [1, position, 0], [0, position, 0]] if axis == 'Y' else
                           [[0, 1, position], [1, 1, position], [1, 0, position], [0, 0, position]])
                plane = {'origin': [position if a == axis else 0 for a in 'XYZ'], 'normal': [int(a == axis) for a in 'XYZ']}
                scene = {'id': f'slice{axis}{index:02d}', 'appearances': [{'cut': {'field': ['POINTS', field]}} for field in ('U', 'p')]}
                for model in ('on', 'off'):
                    properties = image_properties(scene, {'cut': {'field': ['POINTS', variable]}}, plane, 0, ('U', 'p').index(variable))
                    properties.update(model=model, view=0)
                    artifact(properties, '.png', png(index + ord(axis) + (3 if model == 'on' else 0)),
                             spatial={'state': 'known', 'frame': 'sample-world', 'units': 'm',
                                      'mapping': 'pixel-edge-rays-to-slice-plane', 'corners': corners,
                                      'plane': plane,
                                      'cornerOrder': ['top-left', 'top-right', 'bottom-right', 'bottom-left']})
    for index, name in enumerate(('arrival', 'setup', 'inspection', 'finish')):
        artifact({'kind': 'image', 'series': 'photos', 'name': name, 'tags': ['review', 'photos']}, '.png', png(index))
    for index in range(5):
        artifact({'kind': 'image', 'series': 'pulse', 'var': 'U', 'time': index * .25}, '.png', png(index))
    artifact({'kind': 'geometry', 'name': 'domain'}, '.obj', 'v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n',
             spatial={'state': 'known', 'frame': 'sample-world', 'units': 'm'})
    artifact({'kind': 'geometry', 'name': 'triangle'}, '.stl', 'solid sample\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid sample\n')
    artifact({'kind': 'text', 'name': 'solver'}, '.log', 'SYNTHETIC SAMPLE; no solver was run.\n'
             + ''.join(f'Time={i/10:.1f} U={2+i/100:.2f} residual={1/(i+1):.5f}\n' for i in range(450))
             + 'WARNING: sample warning\nINFO: done\n')
    for extension, delimiter in (('csv', ','), ('tsv', '\t')):
        stream = io.StringIO(newline='')
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerow(['time_s', 'drag_N', 'lift_N', 'note'])
        writer.writerows((i / 10, 2 + i / 100, (i % 7) / 10, 'quoted, field\nand newline' if i == 3 else 'sample') for i in range(250))
        artifact({'kind': 'table', 'name': 'forces', 'related': ['U', 'p']}, '.' + extension, stream.getvalue())
    if video is not None:
        artifact({'kind': 'animation', 'series': 'pulse', 'var': 'U'}, '.webm', video)
    add_legacy_examples(destination)
    (destination / 'README.txt').write_text('SYNTHETIC ACCEPTANCE FOLDER - no solver was run.\n'
             'Root media use the actual Schemaxis filename serializer; folders/ and legacy/ exercise other naming conventions.\n'
             'Choose kind=slice, then group by var > axis > model; these properties come from filenames.\n'
             'Slice names use the same image_properties helper as the ParaView adaptor.\n'
             'Companions supply checked spatial placement only; no group/properties/sequence labels.\n'
             'Try var=U, axis=X, model=on. Select matching / Deselect matching.\n'
             'Choose series=photos for manually named photo playback; series=pulse for time frames.\n'
             '3D space: Show all selected image planes with the domain mesh.\n'
             'Open name=solver: Find, Enter/Shift+Enter, F3, whole words; Grep + Regex:\n'
             r'Time=(?<time>[\d.]+) U=(?<velocity>[\d.]+) residual=([\d.]+)' + '\n'
             'Toggle individual capture columns; export matches CSV.\n'
             'CSV/TSV: quoted fields, paging, search, selectable numeric graph axes.\n'
             'STL/OBJ: orbit, pan, zoom, fit. kind=animation selects the optional WebM.\n')
    with (destination / 'README.txt').open('a') as stream:
        stream.write('\nFOLDER AND LEGACY RULE CHECKS (16x16 synthetic icons)\n'
                     'folders/alpha/icons and folders/beta/icons: group by folder, then auto.number1 or auto.letters1.\n'
                     'legacy/numeric: shot-001/002/010; legacy/alphabetic: phase-A/B/Z/AA.\n'
                     'Filename rules: Add slice example and Add tags example, then Apply filename rules.\n'
                     'Or Import filename rules from legacy/filename-rules.examples.json (includes file code/index).\n'
                     'legacy/slices: grep.axis and grep.number. model.png and error.log get no capture values.\n'
                     'legacy/tags: grep.tags checklist. red OR blue matches three files; combine grep.code with tags.\n'
                     'Any tag means no tag filter. Selected values within a key use OR; different keys use AND.\n'
                     'Auto sequence groups are inferred filename order, never physical image placement.\n')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--video', type=Path, help='Optional previously generated synthetic WebM')
    args = parser.parse_args()
    print(generate(args.destination, video=args.video.read_bytes() if args.video else None))
