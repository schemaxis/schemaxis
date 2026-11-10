#!/usr/bin/env python3
"""Native qualification of the ExifTool time and location family (reconcileTime, locate, correctTime, setLocation, geotagFromTrack) against a genuine ExifTool 13.55.

Usage (repository root, PYTHONPATH=src; this tool works in its own fresh private directories and needs no shared native-qualification lock):

    PYTHONPATH=src python3 tools/qualify_exiftool_time_location.py --exiftool /abs/exiftool-13.55/exiftool --output-directory /fresh/empty/dir

It runs the native flows of ``tests/unit/test_exiftool_e3_read.py``, ``_correct.py``, ``_place.py`` and ``_geotag.py`` (real writes read back by independent standard-library
walkers, partial outcomes, plan-only runs and plan application, the cross-operation altitude-meaning cases in both orders and the byte-level mutants), the metadata-first
semantic mutants of ``_metadata_first.py`` (every ordinary binding refreshed and ``publication_metadata.verify`` required to pass before the public ``verify`` must refuse with
one exact code, location and non-empty message) and the live write-stage lifecycle of ``_lifecycle.py`` (a genuine Perl write process of each new write operation held, ended by
the operation's own timeout and by its cancel, PID equal to PGID, the process and its group gone, no safety-net kill and no success publication; the empty ``-config`` argument is
preserved in the recorded argv). Every expected value is a hand-written literal in the test modules, never taken from ExifTool.

The report lists one finite stable case row per test: ``id``, ``operation`` (a declared operation), ``container`` (jpeg), ``kind``, ``supported``, ``written`` and
``independentlyVerified`` (the test passed and was not skipped). Only the explicit finite ``POSITIVE`` cases (real native runs decoded against hand-written literals, at least one per
operation) have ``kind`` supported, ``outcome`` succeeded and ``supported`` true. Operation refusals that the test itself proves (exact fault code, nothing published) are
``refused`` with ``written`` false. Lifecycle tests are ``lifecycle-control``, mutants and verification tests ``verification-control`` and every other test a neutral ``control``;
none of those vouches for support, and their ``written`` is null because several first create real outputs. The exact metadata-first mutant and lifecycle records follow separately.
This is host-driven native evidence of
synthetic fixtures, not a certification and not a global acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUITES = (('test_exiftool_e3_read', ('Native',)), ('test_exiftool_e3_correct', ('Native', 'PlanAndMutants')), ('test_exiftool_e3_place', ('Native', 'CrossOperation', 'Mutants')),
          ('test_exiftool_e3_geotag', ('Native', 'Mutants')), ('test_exiftool_e3_metadata_first', ('CorrectTimeMetadataFirst', 'SetLocationMetadataFirst', 'GeotagMetadataFirst')),
          ('test_exiftool_e3_lifecycle', ('Lifecycle',)))
OPERATION_OF = {'test_exiftool_e3_correct': 'correctTime', 'test_exiftool_e3_place': 'setLocation', 'test_exiftool_e3_geotag': 'geotagFromTrack'}
VERIFICATION_CLASSES = {'PlanAndMutants', 'Mutants', 'CorrectTimeMetadataFirst', 'SetLocationMetadataFirst', 'GeotagMetadataFirst'}
WRITE_OPERATIONS = ('correctTime', 'setLocation', 'geotagFromTrack')
# The explicit, finite list of positive cases: each is a real native run whose published outputs the test decodes against hand-written literals (a stated skew, exact decimals, calendar
# arithmetic, equator positions). Only these rows are ``supported`` with outcome ``succeeded``; every other test is a neutral control that never vouches for support.
POSITIVE = {'test_exiftool_e3_read.Native.test_T6_T7_T8_native': 'reconcileTime', 'test_exiftool_e3_read.Native.test_R60_coordinate_matrix': 'locate',
            'test_exiftool_e3_correct.Native.test_T1_a_reference_correction_rewrites_exif_xmp_and_iptc_exactly': 'correctTime',
            'test_exiftool_e3_place.Native.test_L7_the_stored_rationals_are_the_native_quantisation_published_exactly_and_within_the_bound': 'setLocation',
            'test_exiftool_e3_geotag.Native.test_G1_photographs_are_placed_on_and_between_fixes_with_stamps_and_datum': 'geotagFromTrack'}
# Operation refusals that the test itself proves (exact fault code, nothing published): only these rows are ``refused`` with ``written`` false.
REFUSAL_PROVEN = {'test_exiftool_e3_correct.Native.test_every_item_refused_fails_the_run_with_no_success_publication': ('correctTime', 'NO_USABLE_ITEMS'),
                  'test_exiftool_e3_geotag.Native.test_a_refused_or_unsupported_track_fails_the_run_before_anything_is_written': ('geotagFromTrack', 'TRACK_DTD_REFUSED,TRACK_NOT_GPX,TRACK_ENCODING_UNSUPPORTED,TRACK_HASH_MISMATCH')}


def classify(ident, klass, method, status, operation):
    """The qualifier row fields of one test (finite and protected by tests/unit/test_exiftool_e3_qualifier_rows.py)."""
    passed = status == 'passed'
    if ident in POSITIVE:
        return {'kind': 'supported', 'outcome': 'succeeded', 'supported': passed, 'written': True if operation in WRITE_OPERATIONS else None}
    if ident in REFUSAL_PROVEN:
        return {'kind': 'refusal', 'outcome': 'refused', 'supported': False, 'written': False, 'faultCode': REFUSAL_PROVEN[ident][1]}
    if klass == 'Lifecycle':
        return {'kind': 'lifecycle-control', 'supported': False, 'written': None}
    if klass in VERIFICATION_CLASSES or method.startswith('test_M_'):
        return {'kind': 'verification-control', 'supported': False, 'written': None}
    return {'kind': 'control', 'supported': False, 'written': None}


class Recorder(unittest.TextTestResult):
    """A text result that also keeps one row per test."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = {}

    def mark(self, test, status):
        self.rows[test.id()] = status

    def addSuccess(self, test):
        super().addSuccess(test)
        self.mark(test, 'passed')

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.mark(test, 'failed')

    def addError(self, test, err):
        super().addError(test, err)
        self.mark(test, 'failed')

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.mark(test, 'skipped')


def operation_of(module, klass, method):
    if '%s.%s.%s' % (module, klass, method) in POSITIVE:
        return POSITIVE['%s.%s.%s' % (module, klass, method)]
    if module == 'test_exiftool_e3_read':
        return 'locate' if 'locate' in method.lower() or '_L' in method else 'reconcileTime'
    if module == 'test_exiftool_e3_lifecycle':
        return 'correctTime' if 'correct_time' in method else 'setLocation' if 'set_location' in method else 'geotagFromTrack'
    if module == 'test_exiftool_e3_metadata_first':
        return {'CorrectTimeMetadataFirst': 'correctTime', 'SetLocationMetadataFirst': 'setLocation', 'GeotagMetadataFirst': 'geotagFromTrack'}[klass]
    return OPERATION_OF[module]


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
    import importlib
    modules = {name: importlib.import_module(name) for name, _ in SUITES}
    started = time.time()
    suite, classes = unittest.TestSuite(), {}
    for name, names in SUITES:
        for klass in names:
            loaded = unittest.defaultTestLoader.loadTestsFromTestCase(getattr(modules[name], klass))
            suite.addTests(loaded)
            for case in loaded:
                classes[case.id()] = (name, klass, case._testMethodName)
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stderr, resultclass=Recorder)
    result = runner.run(suite)
    metadata_first = modules['test_exiftool_e3_metadata_first'].RESULTS
    lifecycle = modules['test_exiftool_e3_lifecycle'].Lifecycle.RESULTS
    rows = []
    for test_id, (module, klass, method) in sorted(classes.items()):
        status = result.rows.get(test_id, 'failed')
        ident = '%s.%s.%s' % (module, klass, method)
        row = {'id': ident, 'operation': operation_of(module, klass, method), 'container': 'jpeg', 'status': status, **classify(ident, klass, method, status, operation_of(module, klass, method)),
               'independentlyVerified': status == 'passed'}
        rows.append(row)
    failed = [str(t) for t, _ in result.failures + result.errors]
    report = {'version': 'schemaxis.exiftool.time-location-qualification/1', 'runtime': 'exiftool 13.55', 'executable': str(exiftool), 'startedUnix': int(started), 'seconds': round(time.time() - started, 1),
              'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped), 'failed': failed,
              'verified': result.wasSuccessful() and not result.skipped and all(r['independentlyVerified'] for r in rows) and {r['operation'] for r in rows if r.get('outcome') == 'succeeded' and r['supported']} == set(POSITIVE.values()),
              'cases': rows, 'operations': sorted({r['operation'] for r in rows}),
              'metadataFirstMutants': sorted(metadata_first.values(), key=lambda r: r['id']), 'writeStageLifecycle': {k: lifecycle[k] for k in sorted(lifecycle)},
              'scope': 'genuine ExifTool 13.55 writes and verification replays of synthetic jpeg fixtures; refusal controls are not support; not an MPI, exhaustive or certification claim'}
    out.mkdir(parents=True)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('verified', 'tests', 'failures', 'errors', 'skipped', 'seconds', 'operations')}, indent=2))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
