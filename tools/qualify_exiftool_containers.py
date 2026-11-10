#!/usr/bin/env python3
"""Native qualification of the ExifTool container family (TIFF, DNG, PNG, WebP, HEIF) against a genuine ExifTool 13.55.

Usage (repository root, PYTHONPATH=src; this tool works in its own fresh private directories and needs no shared native-qualification lock):

    PYTHONPATH=src python3 tools/qualify_exiftool_containers.py --exiftool /abs/exiftool-13.55/exiftool --output-directory /fresh/empty/dir

It runs the native flows of ``tests/unit/test_exiftool_e5_positive.py`` (one real run of one declared operation over one container, decoded against hand-written literals),
``_write.py`` (edits, removals, named refusals, the mailbox-7 Photoshop-tail cases, verify mutants with exact paths, a signature-versus-suffix case), ``_native.py`` (locators and the
generalised proof against native outputs), ``_metadata_first.py`` (every ordinary binding refreshed and ``publication_metadata.verify`` required to pass before the public ``verify`` must
refuse with one exact code, location and non-empty message) and the live process lifecycle of ``_lifecycle.py`` (a genuine Perl write process of editMetadata over each container held,
ended by the operation's own timeout and by its cancel, PID equal to PGID, the process and its group gone, no safety-net kill and no success publication; the empty ``-config`` argument
is preserved in the recorded argv). ``_completion.py`` (the completion-repair cases: the JPEG Photoshop tail for every IPTC rebuild, AVIF naming, the TIFF extent-count bound, the HEIF empty-item refusal and the published item bound) adds named refusals and controls only. The host-only reader, profile and proof suites run as controls. Every expected value is a hand-written literal in the test modules, never taken from
ExifTool or from the code under test.

The report lists one finite stable case row per test: ``id``, ``operation`` (a declared operation), ``container``, ``kind``, ``supported``, ``written`` and ``independentlyVerified`` (the test
passed and was not skipped). Only the explicit finite ``POSITIVE`` cases have ``kind`` supported, ``outcome`` succeeded and ``supported`` true. Refusals that a test itself proves (exact fault
code, nothing published for that item) are ``refused`` with ``written`` false. Lifecycle tests are ``lifecycle-control``, mutants and verification tests ``verification-control``, every other
test a neutral ``control``; none of those vouches for support and their ``written`` is null. This is host-driven native evidence of synthetic fixtures, not a certification and not a global
acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUITES = (('test_exiftool_e5_positive', ('Positive',)), ('test_exiftool_e5_write', ('Host', 'Native')), ('test_exiftool_e5_native', None), ('test_exiftool_e5_metadata_first', ('MetadataFirst',)),
          ('test_exiftool_e5_lifecycle', ('Lifecycle',)), ('test_exiftool_e5_tiff', None), ('test_exiftool_e5_png', None), ('test_exiftool_e5_riff', None), ('test_exiftool_e5_heif', None),
          ('test_exiftool_e5_profiles', None), ('test_exiftool_e5_proof', None), ('test_exiftool_e5_ops', ('Operations',)), ('test_exiftool_e5_minimise', ('Native',)), ('test_exiftool_e5_residual', ('Host', 'Native')),
          ('test_exiftool_e5_matrix', ('Matrix',)), ('test_exiftool_e5_ops_mutants', ('MetadataFirst',)), ('test_exiftool_e5_lifecycle_ops', ('LifecycleOps',)), ('test_exiftool_e5_workflow', ('Chain',)), ('test_exiftool_e5_controls', ('Controls',)),
          ('test_exiftool_e5_completion', None))
CONTAINERS = ('tiff', 'dng', 'png', 'webp', 'heif')
POSITIVE_BASE = 'test_exiftool_e5_positive.Positive.'
# The explicit, finite list of positive cases: each is a real native run of ONE declared operation whose published output the test decodes against hand-written literals.
POSITIVE = {**{POSITIVE_BASE + 'test_inspect_' + c: ('inspectMetadata', c) for c in CONTAINERS}, **{POSITIVE_BASE + 'test_edit_' + c: ('editMetadata', c) for c in CONTAINERS},
            **{POSITIVE_BASE + 'test_remove_' + c: ('removeMetadata', c) for c in ('tiff', 'dng', 'png', 'webp')},
            POSITIVE_BASE + 'test_audit_mixed_containers': ('auditMetadata', 'mixed'), POSITIVE_BASE + 'test_compare_mixed_containers': ('compareMetadata', 'mixed'),
            POSITIVE_BASE + 'test_plan_names_every_container_keeps_its_canonical_extension': ('planNames', 'mixed'), POSITIVE_BASE + 'test_organise_copies_every_container_is_an_exact_byte_copy': ('organiseCopies', 'mixed'),
            POSITIVE_BASE + 'test_export_sidecar_writes_the_container_payload_values_and_refuses_what_has_none': ('exportSidecar', 'mixed')}
OPS = 'test_exiftool_e5_ops.Operations.'
MATRIX = 'test_exiftool_e5_matrix.Matrix.'
CATEGORIES = ('location', 'captureTime', 'descriptive', 'rights', 'deviceIdentity')
# Per-cell positives of the later operations: ONE real native run per (operation, container) cell, never a mixed-container case standing in for an untested pair.
POSITIVE.update({OPS + 'test_%s_%s' % (name, c): (op, c) for c in CONTAINERS for name, op in (('correct_time', 'correctTime'), ('set_location', 'setLocation'), ('geotag', 'geotagFromTrack'),
                                                                                              ('copy_into', 'copyMetadata'), ('apply_sidecar', 'applySidecar'))})
POSITIVE.update({MATRIX + 'test_%s_%s' % (name, c): (op, c) for c in CONTAINERS for name, op in (('audit', 'auditMetadata'), ('compare', 'compareMetadata'), ('reconcile_time', 'reconcileTime'), ('locate', 'locate'),
                                                                                                  ('plan_names', 'planNames'), ('organise_copies', 'organiseCopies'), ('export_sidecar', 'exportSidecar'))})
POSITIVE.update({MATRIX + 'test_remove_%s_%s' % (category, c): ('removeMetadata', c, category) for c in ('tiff', 'dng', 'png', 'webp') for category in CATEGORIES})
POSITIVE.update({'test_exiftool_e5_minimise.Native.test_g6_png_minimise_keeps_gamma_profile_and_orientation_and_removes_exif_xmp_and_text': ('removeMetadata', 'png', 'minimise'),
                 'test_exiftool_e5_minimise.Native.test_w7_webp_minimise_removes_vp8x_and_leaves_exactly_the_bitstream': ('removeMetadata', 'webp', 'minimise')})
# the earlier mixed-container cases and the per-category loop of the first window remain controls: only the per-cell rows above are supported rows
for _ident in [i for i, v in POSITIVE.items() if v[1] == 'mixed' or (i.startswith(POSITIVE_BASE + 'test_remove_'))]:
    del POSITIVE[_ident]
WRITE = 'test_exiftool_e5_write.Native.'
# Refusals that the test itself proves (exact per-item fault code, nothing published for that item).
REFUSAL_PROVEN = {WRITE + 'test_h2_h4_heif_creation_and_removal_are_named_refusals_and_the_other_item_is_still_written': ('editMetadata', 'heif', 'HEIF_METADATA_ITEM_CREATION_UNSUPPORTED'),
                  WRITE + 'test_minimise_and_thumbnail_refusals_are_named_per_container': ('removeMetadata', 'tiff', 'MINIMISE_UNSUPPORTED_CONTAINER'),
                  WRITE + 'test_mailbox7_tiff_photoshop_block_clean_control_and_tail': ('editMetadata', 'tiff', 'IPTC_RESOURCE_TAIL_UNSUPPORTED'),
                  WRITE + 'test_mailbox7_jpeg_app13_tail_is_refused_for_iptc_changes_and_kept_otherwise': ('editMetadata', 'jpeg', 'IPTC_RESOURCE_TAIL_UNSUPPORTED')}
REFUSAL_PROVEN.update({MATRIX + 'test_minimise_is_refused_%s' % c: ('removeMetadata', c, 'HEIF_REMOVAL_UNSUPPORTED' if c == 'heif' else 'MINIMISE_UNSUPPORTED_CONTAINER') for c in ('tiff', 'dng', 'heif')})
REFUSAL_PROVEN.update({OPS + 'test_set_location_on_a_heif_without_an_exif_item_is_refused_before_native': ('setLocation', 'heif', 'HEIF_METADATA_ITEM_CREATION_UNSUPPORTED'),
                       'test_exiftool_e5_minimise.Native.test_an_orientation_outside_the_understood_values_is_refused_rendering_unpreserved': ('removeMetadata', 'png', 'MINIMISE_RENDERING_UNPRESERVED'),
                       'test_exiftool_e5_minimise.Native.test_w10_an_unknown_chunk_is_refused_at_plan_before_any_native_process': ('removeMetadata', 'webp', 'WEBP_METADATA_REMOVAL_LAYOUT_UNSUPPORTED')})
REFUSAL_PROVEN.update({OPS + 'test_a_transfer_that_needs_an_xmp_item_a_heif_does_not_have_is_refused_before_native': ('copyMetadata', 'heif', 'HEIF_METADATA_ITEM_CREATION_UNSUPPORTED'),
                       'test_exiftool_e5_residual.Native.test_d2_a_malformed_adobe_makn_private_block_is_refused_by_the_native_warning_gate_before_any_write': ('editMetadata', 'dng', 'WRITE_INPUT_NATIVE_WARNING'),
                       'test_exiftool_e5_residual.Native.test_a_65_mib_png_is_refused_by_its_signature_even_under_a_tif_name': ('editMetadata', 'png', 'PHOTO_RESOURCE_LIMIT'),
                       'test_exiftool_e5_residual.Native.test_a_sparse_png_just_over_64_mib_is_refused_at_stat_without_reading_it': ('editMetadata', 'png', 'PHOTO_RESOURCE_LIMIT')})
COMPLETION = 'test_exiftool_e5_completion.'
# the completion-repair refusals, each proved by its own test (exact fault code at its exact location, nothing written or published): the Photoshop tail of a JPEG is refused for every plan that would rebuild its IPTC,
# a HEIF clear that would empty an existing metadata item, and a TIFF whose declared extent count is over the bound
REFUSAL_PROVEN.update({COMPLETION + 'TailedJpeg.test_correct_time_into_a_tailed_block_that_holds_the_iptc_time_is_refused_before_native': ('correctTime', 'jpeg', 'IPTC_RESOURCE_TAIL_UNSUPPORTED'),
                       COMPLETION + 'TailedJpeg.test_copy_capture_time_into_a_tailed_block_is_refused_before_native': ('copyMetadata', 'jpeg', 'IPTC_RESOURCE_TAIL_UNSUPPORTED'),
                       COMPLETION + 'TailedJpeg.test_copy_descriptive_into_a_tailed_block_is_refused_before_native': ('copyMetadata', 'jpeg', 'IPTC_RESOURCE_TAIL_UNSUPPORTED'),
                       COMPLETION + 'TailedJpeg.test_apply_sidecar_into_a_tailed_block_is_refused_before_native': ('applySidecar', 'jpeg', 'IPTC_RESOURCE_TAIL_UNSUPPORTED'),
                       COMPLETION + 'HeifEmptyItem.test_title_clear_of_the_only_xmp_property_is_refused_before_native': ('editMetadata', 'heif', 'HEIF_EMPTY_METADATA_ITEM'),
                       COMPLETION + 'HeifEmptyItem.test_creator_clear_of_the_only_exif_entry_is_refused_before_native': ('editMetadata', 'heif', 'HEIF_EMPTY_METADATA_ITEM'),
                       COMPLETION + 'HeifEmptyItem.test_clearing_both_last_fields_of_both_items_names_both': ('editMetadata', 'heif', 'HEIF_EMPTY_METADATA_ITEM'),
                       COMPLETION + 'TiffExtentBoundNative.test_an_over_bound_tiff_is_refused_by_name_and_a_small_literal_control_is_written': ('editMetadata', 'tiff', 'TIFF_IFD_BUDGET')})
VERIFICATION_CLASSES = {'MetadataFirst'}
OPERATIONS = ('inspectMetadata', 'auditMetadata', 'compareMetadata', 'reconcileTime', 'locate', 'editMetadata', 'correctTime', 'setLocation', 'geotagFromTrack', 'copyMetadata', 'applySidecar', 'exportSidecar',
              'removeMetadata', 'planNames', 'organiseCopies')
# every supported cell the contract requires: each operation over each container, each removal category over the four removable containers, and minimise of PNG and WebP
REQUIRED_CELLS = ({(op, c, None) for op in OPERATIONS if op != 'removeMetadata' for c in CONTAINERS} | {('removeMetadata', c, cat) for c in ('tiff', 'dng', 'png', 'webp') for cat in CATEGORIES}
                  | {('removeMetadata', 'png', 'minimise'), ('removeMetadata', 'webp', 'minimise')})


def container_of(method, default='mixed'):
    for name in CONTAINERS:
        if method.endswith('_' + name) or ('_' + name + '_') in method or method.startswith('test_' + name + '_'):
            return name
    return default


def classify(ident, klass, method, status):
    passed = status == 'passed'
    if ident in POSITIVE:
        row = {'kind': 'supported', 'outcome': 'succeeded', 'supported': passed, 'written': None if POSITIVE[ident][0] in ('inspectMetadata', 'auditMetadata', 'compareMetadata', 'reconcileTime', 'locate', 'planNames') else True}
        if len(POSITIVE[ident]) > 2:
            row['category'] = POSITIVE[ident][2]
        return row
    if ident in REFUSAL_PROVEN:
        return {'kind': 'refusal', 'outcome': 'refused', 'supported': False, 'written': False, 'faultCode': REFUSAL_PROVEN[ident][2]}
    if klass in ('Lifecycle', 'LifecycleOps'):
        return {'kind': 'lifecycle-control', 'supported': False, 'written': None}
    if klass == 'Chain':
        return {'kind': 'workflow-control', 'supported': False, 'written': None}
    if klass in VERIFICATION_CLASSES or 'mutant' in method:
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


def flatten(tests):
    for test in tests:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def operation_of(ident, module, method):
    if ident in POSITIVE:
        return POSITIVE[ident][0]
    if ident in REFUSAL_PROVEN:
        return REFUSAL_PROVEN[ident][0]
    lowered = method.lower()
    if module == 'test_exiftool_e5_lifecycle' or module == 'test_exiftool_e5_metadata_first':
        return 'editMetadata'
    if module == 'test_exiftool_e5_lifecycle_ops':
        return {'minimise': 'removeMetadata'}.get(method.split('_')[1], method.split('_')[1])
    if module == 'test_exiftool_e5_ops_mutants':
        return {'time': 'correctTime', 'location': 'setLocation', 'copy': 'copyMetadata', 'minimise': 'removeMetadata'}[method.split('_')[1]]
    if module == 'test_exiftool_e5_completion':
        for prefix, op in (('test_correct_time', 'correctTime'), ('test_copy', 'copyMetadata'), ('test_apply_sidecar', 'applySidecar'), ('test_plan_names', 'planNames'), ('test_organise', 'organiseCopies'),
                           ('test_keep_original', 'organiseCopies'), ('test_the_published', 'inspectMetadata'), ('test_a_jpeg_only', 'inspectMetadata'), ('test_every_other', 'planNames'), ('test_a_large', 'inspectMetadata'),
                           ('test_the_item_limit', 'inspectMetadata'), ('test_the_canonical', 'planNames'), ('test_the_other', 'planNames'), ('test_the_avif', 'organiseCopies')):
            if method.startswith(prefix):
                return op
        return 'editMetadata'
    if module == 'test_exiftool_e5_workflow':
        return 'workflow'
    if module == 'test_exiftool_e5_controls':
        return 'correctTime'
    if module in ('test_exiftool_e5_ops', 'test_exiftool_e5_matrix', 'test_exiftool_e5_minimise', 'test_exiftool_e5_residual'):
        for prefix, op in (('test_correct_time', 'correctTime'), ('test_set_location', 'setLocation'), ('test_geotag', 'geotagFromTrack'), ('test_copy', 'copyMetadata'), ('test_a_png_source', 'copyMetadata'),
                           ('test_apply_sidecar', 'applySidecar'), ('test_export_sidecar', 'exportSidecar'), ('test_audit', 'auditMetadata'), ('test_compare', 'compareMetadata'),
                           ('test_reconcile', 'reconcileTime'), ('test_locate', 'locate'), ('test_plan_names', 'planNames'), ('test_organise', 'organiseCopies'), ('test_remove', 'removeMetadata'),
                           ('test_minimise', 'removeMetadata'), ('test_d4', 'removeMetadata'), ('test_g', 'removeMetadata'), ('test_w', 'removeMetadata'), ('test_a_png_without', 'removeMetadata'),
                           ('test_a_png_with_nothing', 'removeMetadata'), ('test_an_', 'removeMetadata'), ('test_item_bound', 'inspectMetadata'), ('test_a_sparse_file', 'inspectMetadata')):
            if method.startswith(prefix):
                return op
        return 'editMetadata'
    if 'remov' in lowered or 'minimise' in lowered or '_tr1_' in lowered:
        return 'removeMetadata'
    if 'inspect' in lowered or module in ('test_exiftool_e5_tiff', 'test_exiftool_e5_png', 'test_exiftool_e5_riff', 'test_exiftool_e5_heif', 'test_exiftool_e5_profiles', 'test_exiftool_e5_proof', 'test_exiftool_e5_native'):
        return 'inspectMetadata'
    return 'editMetadata'


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
        if names is None:
            loaded = list(flatten(unittest.defaultTestLoader.loadTestsFromModule(modules[name])))
            klasses = [(type(case).__name__, case) for case in loaded]
        else:
            klasses = []
            for klass in names:
                klasses += [(klass, case) for case in unittest.defaultTestLoader.loadTestsFromTestCase(getattr(modules[name], klass))]
        for klass, case in klasses:
            suite.addTest(case)
            classes[case.id()] = (name, klass, case._testMethodName)
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stderr, resultclass=Recorder)
    result = runner.run(suite)
    metadata_first = sorted(list(modules['test_exiftool_e5_metadata_first'].RESULTS.values()) + list(modules['test_exiftool_e5_ops_mutants'].RESULTS.values()), key=lambda r: r['id'])
    lifecycle = modules['test_exiftool_e5_lifecycle'].Lifecycle.RESULTS
    lifecycle_ops = {k: v for k, v in modules['test_exiftool_e5_lifecycle'].Lifecycle.RESULTS.items() if k.split('-')[0] in ('correctTime', 'setLocation', 'copyMetadata', 'minimise')}
    lifecycle = {k: v for k, v in lifecycle.items() if k not in lifecycle_ops}
    rows = []
    for test_id, (module, klass, method) in sorted(classes.items()):
        status = result.rows.get(test_id, 'failed')
        ident = '%s.%s.%s' % (module, klass, method)
        operation = operation_of(ident, module, method)
        container = POSITIVE[ident][1] if ident in POSITIVE else REFUSAL_PROVEN[ident][1] if ident in REFUSAL_PROVEN else container_of(method)
        rows.append({'id': ident, 'operation': operation, 'container': container, 'status': status, **classify(ident, klass, method, status), 'independentlyVerified': status == 'passed'})
    failed = [str(t) for t, _ in result.failures + result.errors]
    covered = {(r['operation'], r['container'], r.get('category')) for r in rows if r.get('outcome') == 'succeeded' and r['supported']}
    required = REQUIRED_CELLS
    report = {'version': 'schemaxis.exiftool.containers-qualification/1', 'runtime': 'exiftool 13.55', 'executable': str(exiftool), 'startedUnix': int(started), 'seconds': round(time.time() - started, 1),
              'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped), 'failed': failed,
              'verified': result.wasSuccessful() and not result.skipped and all(r['independentlyVerified'] for r in rows) and required <= covered and len(lifecycle) == 2 * len(CONTAINERS) and len(lifecycle_ops) == 2 * 8
                          and len(metadata_first) >= 20 and all(r['publicationMetadataVerified'] for r in metadata_first),
              'cases': rows, 'operations': sorted({r['operation'] for r in rows}), 'containers': sorted({r['container'] for r in rows}), 'metadataFirstMutants': metadata_first, 'writeStageLifecycle': lifecycle, 'writeStageLifecycleOperations': lifecycle_ops, 'requiredCells': len(REQUIRED_CELLS), 'coveredCells': len(REQUIRED_CELLS & covered),
              'workflowChains': modules['test_exiftool_e5_workflow'].Chain.RESULTS,
              'scope': 'Host-driven serial native runs of hand-built synthetic container files against one ExifTool 13.55: no pixel decode, not MPI, not exhaustive ExifTool behaviour, not a certification of capture time, location, authorship or privacy.'}
    out.mkdir(parents=True)
    (out / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + '\n')
    print(json.dumps({k: report[k] for k in ('verified', 'tests', 'failures', 'errors', 'skipped', 'seconds')}))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
