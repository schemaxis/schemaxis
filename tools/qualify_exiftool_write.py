#!/usr/bin/env python3
"""Native qualification of the ExifTool write family (editMetadata, removeMetadata) against a genuine ExifTool 13.55.

Usage (repository root, PYTHONPATH=src; the shared native-qualification lock is only needed for the legacy conformance kit, not for this tool,
which works in its own fresh directories):

    PYTHONPATH=src python3 tools/qualify_exiftool_write.py --exiftool /abs/exiftool-13.55/exiftool --output-directory /fresh/empty/dir

It authors the synthetic write fixtures, then runs the native flows of ``tests/unit/test_exiftool_write.py`` (class ``Native``): edits with exact
Unicode, creators, language alternatives and legacy IPTC; progressive, restart and multi-scan JPEGs; stable partial-set artifact slots; removal
with absence proofs and the residual inventory; exact semantic and integrity mutants against ``verify``; and the public workflow chain from a
produced image into ``inspectMetadata``; and the completion flows of ``tests/unit/test_exiftool_write_complete.py``: the rendering-preserving
minimise over ten items, the XMP qualifier refusal, the independent non-target Exif proof, metadata-first semantic mutants (every ordinary binding
refreshed and ``publication_metadata.verify`` required to pass before the public ``verify`` is asked for one exact code and location) and the live
write-stage lifecycle (a genuine Perl write process held, then ended by the operation's own timeout or cancel). Every expected value is a literal in
the test module, never taken from ExifTool. The ``NativeFamily`` flows add native keyword add and remove, the typed companion loss at the 32-byte IPTC
By-line limit (with the exact boundary) and NFC/NFD exactness, each read back from the output bytes by independent local parsers. The report records the runtime, the clocks, each test result, the mutant outcomes and the lifecycle
observations; this is host-driven native evidence, not a certification. ``tools/qualify_exiftool_write_loop.py`` runs the public agent loop and the
produced-image workflow chain separately.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--exiftool', required=True, help='absolute ExifTool 13.55 script')
    parser.add_argument('--output-directory', required=True, help='fresh directory for report.json')
    args = parser.parse_args()
    out = Path(args.output_directory).absolute()
    if out.exists():
        raise SystemExit('the output directory already exists: select a fresh one')
    exiftool = Path(args.exiftool)
    if not exiftool.is_absolute() or not exiftool.is_file():
        raise SystemExit('--exiftool must be an absolute path to the ExifTool script')
    os.environ['SCHEMAXIS_EXIFTOOL'] = str(exiftool)
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit'), str(ROOT / 'tools')]
    import test_exiftool_write as module
    import test_exiftool_write_complete as complete
    started = time.time()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (module.Native, complete.Native, complete.NativeFamily, complete.MetadataFirst, complete.Lifecycle))
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stderr).run(suite)
    out.mkdir(parents=True)
    failed = [str(t) for t, _ in result.failures + result.errors]
    report = {'version': 'schemaxis.exiftool.write-qualification/1', 'runtime': 'exiftool 13.55', 'executable': str(exiftool), 'startedUnix': int(started), 'seconds': round(time.time() - started, 1),
              'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped), 'failed': failed,
              'verified': result.wasSuccessful() and not result.skipped,
              'metadataFirstMutants': complete.MetadataFirst.RESULTS, 'writeStageLifecycle': complete.Lifecycle.RESULTS,
              'scope': 'genuine ExifTool 13.55 writes and verification replays of synthetic fixtures; not an MPI, exhaustive or certification claim'}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
