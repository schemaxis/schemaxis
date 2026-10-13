#!/usr/bin/env python3
"""Small CPU-only native acceptance run; requires a fresh output directory."""
import argparse
import json
from pathlib import Path
import subprocess

from schemaxis.adaptors.aseprite import run, verify
from schemaxis.artifacts import atomic_json


# Fixed qualification code, never interpolated authored source. Modify a copy,
# then prove the edited pixel and additional layer survive a fresh process.
EDIT = '''
local s = assert(app.open("sprite.aseprite"))
local l = s:newLayer(); l.name = "qualification-edit"
local im = Image(s.width,s.height,ColorMode.RGB)
im:drawPixel(0,0,app.pixelColor.rgba(7,19,31,255))
s:newCel(l,1,im,Point(0,0))
s:saveAs("editable-copy.aseprite")
'''
EDIT_REOPEN = '''
local s = assert(app.open("editable-copy.aseprite"))
local l = s.layers[#s.layers]
assert(l.name == "qualification-edit")
local c = assert(l:cel(1))
assert(c.image:getPixel(-c.position.x,-c.position.y) == app.pixelColor.rgba(7,19,31,255))
local f = assert(io.open("edit-verification.json","wb"))
f:write(json.encode({verified=true, freshProcess=true, width=s.width, height=s.height,
                    frames=#s.frames, layers=#s.layers, pixel={7,19,31,255}})); f:close()
'''


def qualify_edit(directory, executable, timeout):
    for stage, source in [('edit', EDIT), ('edit-reopen', EDIT_REOPEN)]:
        script = directory/(stage+'.lua')
        script.write_text(source)
        with (directory/(stage+'.log')).open('wb') as log:
            subprocess.run([executable, '--batch', '--script', str(script)], cwd=directory,
                           stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=True)
    return json.loads((directory/'edit-verification.json').read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args()
    args.output_directory = args.output_directory.absolute()
    args.output_directory.mkdir(parents=True, exist_ok=False)
    examples = Path(__file__).resolve().parents[1]/'examples'/'schemaxis'
    results = {}
    for label in ('icon', 'animation'):
        document = json.loads((examples/f'aseprite-{label}.json').read_text())
        directory = args.output_directory/label
        run(document, directory, args.executable, args.timeout)
        results[label] = verify(directory)
        edited = qualify_edit(directory, args.executable, args.timeout)
        assert edited == {'verified': True, 'freshProcess': True, 'width': results[label]['width'],
            'height': results[label]['height'], 'frames': results[label]['frames'],
            'layers': results[label]['layers']+1, 'pixel': [7,19,31,255]}
        results[label]['editableCopy'] = edited
    assert (results['animation']['frames'], results['animation']['layers']) == (2, 2)
    assert (results['icon']['width'], results['icon']['height']) == (8, 8)
    receipt = {'version': 'schemaxis.aseprite.qualification/1', 'verified': True,
               'execution': 'CPU batch; build and independent reopen processes', 'examples': results}
    atomic_json(args.output_directory/'qualification.json', receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
