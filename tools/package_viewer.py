#!/usr/bin/env python3
"""Package the independent viewer and optional sample folder as a portable ZIP.

Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
"""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]

LAUNCH = '''# Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from schemaxis_viewer.__main__ import main
if __name__ == '__main__':
    args = sys.argv[1:]
    sample = Path(__file__).resolve().parent / 'sample'
    if not args and sample.is_dir():
        args = [str(sample)]
    main(args)
'''

README = '''ARTIFACT - independent local data viewer
Copyright (C) 2026 David L. F. Gaden. Apache-2.0; see LICENSE and NOTICE.

1. Extract this entire ZIP to a folder.
2. Install Python 3.10+ if it is not already available.
3. Windows: double-click start-viewer.cmd (uses the Python launcher).
   Linux/macOS: run python3 launch.py, or sh start-viewer.sh.
   To open your results directly: python3 launch.py /path/to/results
   Windows example: py -3 launch.py "C:\\Users\\me\\Results"

Your browser opens automatically. With a bundled sample, launching without
arguments opens the sample; otherwise use Open folder or Add files.
Keep the terminal open while viewing; Ctrl+C stops the local server.
Use --no-browser to print its URL, or --port 8080 to choose a port.

No Schemaxis installation, native application, pip packages, account, CDN or
upload service is required. Python standard library + a current WebGL browser.
All file viewing is read-only. Selections do not move or delete files.
The server binds to this computer's loopback interface. Share this ZIP and
your result files with colleagues; each person runs their own local viewer.
The local session URL is for this computer; this is not a hosted team service.

Images, photo series, animation, checked spatial image planes, STL/OBJ, video,
audio, text Find/Grep with capture columns, CSV/TSV tables and numeric plots.
Group by folders, key-value filename properties, automatic number/letter sequences,
or editable filename capture rules. Split captures into tags with checkbox filters.
The sample contains 16x16 legacy icons and legacy/filename-rules.examples.json.
Workbook files (XLSX/ODS) need sheets exported as CSV/TSV; no workbook engine.
Video decoding depends on the browser codec. See GUIDE.md for format limits,
metadata, grouping and selection. Any sample data is synthetic, not a CFD result.
'''


def package(output, sample=None):
    output = Path(output)
    if output.exists():
        raise ValueError(f'Output already exists: {output}')
    entries = {'launch.py': LAUNCH.encode(), 'README.txt': README.encode(),
               'start-viewer.sh': b'#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec python3 launch.py "$@"\n',
               'start-viewer.cmd': b'@echo off\r\npy -3 "%~dp0launch.py" %*\r\npause\r\n',
               'LICENSE': (ROOT / 'LICENSE').read_bytes(),
               'NOTICE': (ROOT / 'NOTICE').read_bytes(),
               'GUIDE.md': (ROOT / 'docs/artifact-viewer.md').read_bytes()}
    for name in ('output-metadata.md', 'output-filenames.md'):
        entries[name] = (ROOT / 'docs' / name).read_bytes()
    for path in (ROOT / 'LICENSES').rglob('*'):
        if path.is_file():
            entries['LICENSES/' + path.relative_to(ROOT / 'LICENSES').as_posix()] = path.read_bytes()
    source = ROOT / 'src/schemaxis_viewer'
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in {'.py', '.mjs', '.css', '.html'} and '__pycache__' not in path.parts:
            entries['schemaxis_viewer/' + path.relative_to(source).as_posix()] = path.read_bytes()
    if sample:
        sample = Path(sample).resolve(strict=True)
        if not sample.is_dir():
            raise ValueError('Sample must be a directory')
        for path in sample.rglob('*'):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(sample) and '.output-index' not in path.parts:
                entries['sample/' + path.relative_to(sample).as_posix()] = path.read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'x', compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(entries.items()):
            info = ZipInfo('artifact-viewer/' + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
            archive.writestr(info, content)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--sample', type=Path, help='Explicit sample folder to include')
    args = parser.parse_args()
    print(package(args.output, args.sample))
