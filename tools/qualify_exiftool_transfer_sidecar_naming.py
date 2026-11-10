#!/usr/bin/env python3
"""Native qualification of the ExifTool copy, sidecar and naming family (copyMetadata, applySidecar, exportSidecar, planNames, organiseCopies) against a genuine ExifTool 13.55.

Usage (repository root, PYTHONPATH=src; this tool works in its own fresh private directories and needs no shared native-qualification lock):

    PYTHONPATH=src python3 tools/qualify_exiftool_transfer_sidecar_naming.py --exiftool /abs/exiftool-13.55/exiftool --output-directory /fresh/empty/dir

It runs the native flows of ``tests/unit/test_exiftool_e4_sidecar.py``, ``_transfer.py`` and ``_organise.py`` (real runs read back by independent standard-library readers and compared
with hand-written literals, partial outcomes, the mutants of the three new proofs), the metadata-first semantic mutants (every ordinary binding refreshed and
``publication_metadata.verify`` required to pass before the public ``verify`` must refuse with one exact code, location and non-empty message) and the live process lifecycle of
``_lifecycle.py`` (a genuine Perl write or listing process of each operation held, ended by the operation's own timeout and by its cancel, PID equal to PGID, the process and its group
gone, no safety-net kill and no success publication; the empty ``-config`` argument is preserved in the recorded argv). Every expected value is a hand-written literal in the test
modules, never taken from ExifTool or from the code under test.

The report lists one finite stable case row per test: ``id``, ``operation`` (a declared operation), ``container`` (jpeg), ``kind``, ``supported``, ``written`` and ``independentlyVerified``
(the test passed and was not skipped). Only the explicit finite ``POSITIVE`` cases (a real native run decoded against hand-written literals, one per operation) have ``kind`` supported,
``outcome`` succeeded and ``supported`` true. Operation refusals that the test itself proves (exact fault code, nothing published) are ``refused`` with ``written`` false (and, where the run-level code is NO_USABLE_ITEMS, the ``itemFaultCode`` the test proves for the unusable item). Lifecycle
tests are ``lifecycle-control``, mutants and verification tests ``verification-control`` and every other test a neutral ``control``; none of those vouches for support, and their
``written`` is null because several first create real outputs. The exact metadata-first mutant and lifecycle records follow separately. This is host-driven native evidence of
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
SUITES = (('test_exiftool_e4_sidecar', ('Native', 'NativeLocation')), ('test_exiftool_e4_transfer', ('Native', 'Location', 'CaptureTime', 'Mixed', 'Mutants', 'Repair')), ('test_exiftool_e4_organise', ('Names', 'Organise')), ('test_exiftool_e4_lifecycle', ('Lifecycle',)))
OPERATIONS = ('copyMetadata', 'applySidecar', 'exportSidecar', 'planNames', 'organiseCopies')
VERIFICATION_CLASSES = {'Mutants'}
# The explicit, finite list of positive cases: each is a real native run whose published outputs the test decodes against hand-written literals. Only these rows are ``supported`` with
# outcome ``succeeded``; every other test is a neutral control that never vouches for support.
POSITIVE = {'test_exiftool_e4_transfer.Native.test_C1_a_rich_source_transfers_exact_text_languages_lists_and_rational_pairs': ('copyMetadata', True),
            'test_exiftool_e4_transfer.Native.test_A1_a_declared_sidecar_applies_its_values_and_A2_an_item_without_one_keeps_its_slot': ('applySidecar', True),
            'test_exiftool_e4_sidecar.Native.test_S1_native_export_writes_the_planned_values_and_every_property_is_anchored': ('exportSidecar', True),
            'test_exiftool_e4_organise.Names.test_N1_recorded_local_names_with_the_manifest_ordered_collision_suffix': ('planNames', False),
            'test_exiftool_e4_organise.Organise.test_O1_every_output_is_the_capture_byte_for_byte_with_the_sidecar_beside_it': ('organiseCopies', True)}
# The finite per-claim positives of the public group claims (a real native run decoded against hand-written literals each): the capture-time, location and mixed-selection groups of the two
# transfer operations, including a destination that records no capture time, a three-family (EXIF, XMP, IPTC) destination, a destination whose only capture time is the IPTC date with its time, a blank destination (neither Exif nor XMP) that receives a whole-second time in one new XMP carrier, and a source that spreads one capture time over carriers (the Exif local time with its offset or fraction stated by IPTC or XMP) into each of those destinations. A row is ``supported`` with its ``claim``; there is still exactly one
# operation-level positive per operation in ``POSITIVE``.
POSITIVE_CLAIMS = {'test_exiftool_e4_transfer.Repair.test_E4R1_a_captured_time_is_set_into_an_exififd_that_records_none': ('copyMetadata', 'captureTime into a destination without a capture time'),
                   'test_exiftool_e4_transfer.CaptureTime.test_C_E3a_local_time_offset_and_fraction_are_carried_by_the_e3_time_writer': ('copyMetadata', 'captureTime'),
                   'test_exiftool_e4_transfer.CaptureTime.test_a_declared_sidecar_carries_its_time_into_the_copy': ('applySidecar', 'captureTime'),
                   'test_exiftool_e4_transfer.Location.test_C_E3_the_position_and_its_ellipsoidal_height_are_written_by_the_location_writer': ('copyMetadata', 'location'),
                   'test_exiftool_e4_transfer.Mixed.test_descriptive_capture_time_and_location_are_written_together_and_proved_together': ('copyMetadata', 'mixed selection'),
                   'test_exiftool_e4_transfer.Mixed.test_a_declared_sidecar_composes_descriptive_and_capture_time': ('applySidecar', 'mixed selection'),
                   'test_exiftool_e4_transfer.Repair.test_E4R5_every_selection_with_the_capture_time_succeeds_into_a_three_family_destination': ('copyMetadata', 'mixed selection into an EXIF, XMP and IPTC time destination'),
                   'test_exiftool_e4_transfer.Repair.test_E4F1_a_single_captured_time_is_written_and_verified_into_an_iptc_only_time_destination_with_and_without_an_exif_block': ('copyMetadata', 'captureTime into an IPTC-only time destination'),
                   'test_exiftool_e4_transfer.Repair.test_E4F1_a_mixed_selection_with_a_captured_time_is_written_and_verified_into_an_iptc_only_time_destination_with_and_without_an_exif_block': ('copyMetadata', 'mixed selection into an IPTC-only time destination'),
                   'test_exiftool_e4_transfer.Repair.test_E4F2_a_whole_second_exif_or_iptc_time_is_written_and_verified_into_a_blank_destination_as_a_single_selection': ('copyMetadata', 'whole-second captureTime into a blank destination'),
                   'test_exiftool_e4_transfer.Repair.test_E4F2_a_whole_second_exif_or_iptc_time_is_written_and_verified_into_a_blank_destination_in_a_mixed_selection': ('copyMetadata', 'whole-second mixed selection into a blank destination'),
                   'test_exiftool_e4_transfer.Repair.test_E4G1_a_time_spread_over_carriers_is_written_and_verified_into_destinations_that_record_a_time_or_none_as_a_single_selection': ('copyMetadata', 'captureTime spread over carriers'),
                   'test_exiftool_e4_transfer.Repair.test_E4G1_a_time_spread_over_carriers_is_written_and_verified_into_an_iptc_only_time_destination_when_it_has_no_fraction': ('copyMetadata', 'captureTime spread over carriers into an IPTC-only time destination'),
                   'test_exiftool_e4_transfer.Repair.test_E4G1_a_time_spread_over_carriers_is_written_and_verified_in_a_mixed_selection': ('copyMetadata', 'mixed selection with a captureTime spread over carriers')}
# Operation refusals that the test itself proves (exact fault code, nothing published): only these rows are ``refused`` with ``written`` false.
REFUSAL_PROVEN = {'test_exiftool_e4_sidecar.Native.test_all_items_refused_is_no_success': ('exportSidecar', 'NO_USABLE_ITEMS'),
                  'test_exiftool_e4_organise.Organise.test_all_items_refused_is_no_success_and_no_copy_exists': ('organiseCopies', 'NO_USABLE_ITEMS'),
                  'test_exiftool_e4_transfer.Native.test_C8_a_destination_equal_to_its_source_is_transfer_self': ('copyMetadata', 'NO_USABLE_ITEMS'),
                  'test_exiftool_e4_transfer.Repair.test_E4H1_a_source_whose_offset_or_fraction_is_stated_only_by_a_carrier_without_its_own_time_is_refused_before_any_write_in_every_destination': ('copyMetadata', 'NO_USABLE_ITEMS'),
                  'test_exiftool_e4_transfer.Repair.test_E4H1_the_orphan_source_is_refused_in_a_mixed_selection_and_nothing_is_published': ('copyMetadata', 'NO_USABLE_ITEMS'),
                  'test_exiftool_e4_transfer.Repair.test_E4H1_a_destination_whose_offset_is_stated_only_by_an_iptc_time_without_its_date_is_refused_before_any_write': ('copyMetadata', 'NO_USABLE_ITEMS')}
# The item fault that a refusal row proves as the first fault of the unusable item, where the row's run-level fault code (NO_USABLE_ITEMS) alone would not say what was refused: an orphan capture-time
# component (an offset or fraction stated only by a carrier without its own local time) is refused before any write; these rows are refusal evidence, never support.
REFUSAL_ITEM_FAULT = {'test_exiftool_e4_transfer.Repair.test_E4H1_a_source_whose_offset_or_fraction_is_stated_only_by_a_carrier_without_its_own_time_is_refused_before_any_write_in_every_destination': 'TRANSFER_TIME_COMPONENT_UNANCHORED',
                      'test_exiftool_e4_transfer.Repair.test_E4H1_the_orphan_source_is_refused_in_a_mixed_selection_and_nothing_is_published': 'TRANSFER_TIME_COMPONENT_UNANCHORED',
                      'test_exiftool_e4_transfer.Repair.test_E4H1_a_destination_whose_offset_is_stated_only_by_an_iptc_time_without_its_date_is_refused_before_any_write': 'TRANSFER_TIME_COMPONENT_UNANCHORED'}


def classify(ident, klass, method, status, operation):
    """The qualifier row fields of one test (finite and protected by tests/unit/test_exiftool_e4_surface.py and test_exiftool_e4_qualifier_rows.py)."""
    passed = status == 'passed'
    if ident in POSITIVE:
        return {'kind': 'supported', 'outcome': 'succeeded', 'supported': passed, 'written': True if POSITIVE[ident][1] else None}
    if ident in POSITIVE_CLAIMS:
        return {'kind': 'supported', 'outcome': 'succeeded', 'supported': passed, 'written': True, 'claim': POSITIVE_CLAIMS[ident][1]}
    if ident in REFUSAL_PROVEN:
        return {'kind': 'refusal', 'outcome': 'refused', 'supported': False, 'written': False, 'faultCode': REFUSAL_PROVEN[ident][1], **({'itemFaultCode': REFUSAL_ITEM_FAULT[ident]} if ident in REFUSAL_ITEM_FAULT else {})}
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

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows[test.id()] = 'passed'

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows[test.id()] = 'failed'

    def addError(self, test, err):
        super().addError(test, err)
        self.rows[test.id()] = 'failed'

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.rows[test.id()] = 'skipped'


def operation_of(module, klass, method):
    ident = '%s.%s.%s' % (module, klass, method)
    if ident in POSITIVE:
        return POSITIVE[ident][0]
    if ident in REFUSAL_PROVEN:
        return REFUSAL_PROVEN[ident][0]
    if module == 'test_exiftool_e4_sidecar':
        return 'exportSidecar'
    if module == 'test_exiftool_e4_organise':
        return 'planNames' if klass == 'Names' else 'organiseCopies'
    if module == 'test_exiftool_e4_lifecycle':
        return next(op for op in OPERATIONS if op in method)
    lowered = method.lower()
    return 'applySidecar' if 'apply' in lowered or 'sidecar' in lowered or '_a1_' in lowered else 'copyMetadata'


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
    fixtures = importlib.import_module('exiftool_e4_fixtures')
    recorded = sorted((v for k, v in fixtures.RESULTS.items() if k.startswith('mf:')), key=lambda r: r['id'])
    # a mutant that ends in the generic VERIFICATION_FAILED (a flipped capture byte) is an integrity control, kept separate from the semantic mutants with an exact semantic code
    metadata_first = [{**r, 'kind': 'integrity-control' if r['code'] == 'VERIFICATION_FAILED' else 'semantic-mutant'} for r in recorded]
    lifecycle = modules['test_exiftool_e4_lifecycle'].Lifecycle.RESULTS
    rows = []
    for test_id, (module, klass, method) in sorted(classes.items()):
        status = result.rows.get(test_id, 'failed')
        ident = '%s.%s.%s' % (module, klass, method)
        operation = operation_of(module, klass, method)
        rows.append({'id': ident, 'operation': operation, 'container': 'jpeg', 'status': status, **classify(ident, klass, method, status, operation), 'independentlyVerified': status == 'passed'})
    failed = [str(t) for t, _ in result.failures + result.errors]
    positives = {r['operation'] for r in rows if r.get('outcome') == 'succeeded' and r['supported']}
    report = {'version': 'schemaxis.exiftool.transfer-sidecar-naming-qualification/1', 'runtime': 'exiftool 13.55', 'executable': str(exiftool), 'startedUnix': int(started), 'seconds': round(time.time() - started, 1),
              'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped), 'failed': failed,
              'verified': result.wasSuccessful() and not result.skipped and all(r['independentlyVerified'] for r in rows) and positives == set(OPERATIONS) and len(lifecycle) == 2 * len(OPERATIONS)
                          and sum(1 for r in metadata_first if r['kind'] == 'semantic-mutant') >= 10 and all(r['publicationMetadataVerified'] for r in metadata_first),
              'cases': rows, 'operations': sorted({r['operation'] for r in rows}), 'metadataFirstMutants': metadata_first, 'writeStageLifecycle': lifecycle,
              'scope': 'Host-driven serial native runs of synthetic photographs against one ExifTool 13.55: not MPI, not exhaustive ExifTool behaviour, not a certification of capture time, location, authorship or privacy, and not a global acceptance.'}
    out.mkdir(parents=True)
    (out / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + '\n')
    print(json.dumps({k: report[k] for k in ('verified', 'tests', 'failures', 'errors', 'skipped', 'seconds')}))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
