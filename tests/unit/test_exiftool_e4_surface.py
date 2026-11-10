"""E4 surface: the schema, discovery, guidance, readiness, Studio starters and the byte-frozen older data of the ExifTool route (host only, no native process)."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit')]

from schemaxis.adaptors import registry  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, capabilities, catalogue, e4copy, writes  # noqa: E402
from schemaxis.capabilities import CapabilityCatalogue  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from schemaxis.search_acceptance import check_cases  # noqa: E402
from schemaxis.studio_guidance import audit  # noqa: E402

PACKAGE = ROOT / 'src/schemaxis/adaptors/exiftool'
E4 = ['copyMetadata', 'applySidecar', 'exportSidecar', 'planNames', 'organiseCopies']
EXAMPLES = {'copyMetadata': 'exiftool-copy-metadata.json', 'applySidecar': 'exiftool-apply-sidecar.json', 'exportSidecar': 'exiftool-export-sidecar.json', 'planNames': 'exiftool-plan-names.json',
            'organiseCopies': 'exiftool-organise-copies.json'}
STARTERS = {'copy-metadata': 'copyMetadata', 'apply-sidecar': 'applySidecar', 'export-sidecar': 'exportSidecar', 'plan-names': 'planNames', 'organise-copies': 'organiseCopies'}
FORBIDDEN = ('catalogue', 'catalog', 'overlay', 'tag', 'tags', 'flag', 'expression', 'argument', 'arguments', 'config', 'script', 'tagsFromFile', 'template', 'regex', 'property', 'xmpProperty')
# SHA-256 of the exact bytes of every pre-E4 catalogue and write table: E4 adds new files and never edits these
FROZEN = {
    "fields.json": "1785f956c2ad54c301eb7e9558790018d2b4ccd3adce2c91c3f7334b4d296c67",
    "fields-2.json": "bce7b860bab934e26cb5bdb9a03dbfa5e48617df86066429ad02e25d11237432",
    "fields-3-additions.json": "04d5c0f6410b50fe23b5a65dba3ed50c58acfc27b6971413d834fb1d77bb143e",
    "writes.json": "4878f3af1568797b702e63fc6fe3e5aa93d0335bcd191b0dbb359709a4596477",
    "writes-3.json": "51c2d45caa70498759f2281875629d521fbef369a55dd0d0b11ed4cd39203773"
}
# plan hashes of every pre-E4 example document, computed under the frozen E3R4 candidate (the E1, E2 and E3 plans are byte for byte unchanged)
OLD_PLAN_HASHES = {
    'exiftool-audit-baseline.json': '8b9ab9abefc28518b618653f755406ce40e922bcd1857d7686047abfc4cf9752',
    'exiftool-baseline-missing-invalid.json': 'FAULT:INVALID_BASELINE',
    'exiftool-baseline.json': 'c5119bc8968c31737f0a4b047328bb0591147a166a99546abeaf4682b718971f',
    'exiftool-compare-baseline.json': '4d4d522dcccb730a8323feb0287fcd4df8f5680d00331c3740c2147ce2bcd447',
    'exiftool-correct-time-raw-argument-invalid.json': 'FAULT:UNKNOWN_ARGUMENT',
    'exiftool-correct-time.json': 'a347c63a87c8c304f34c503a3168aa1e6dd23bf7d52e725ed6679a023a96c76f',
    'exiftool-duplicate-id-invalid.json': 'FAULT:DUPLICATE_PHOTO_ID',
    'exiftool-edit-baseline.json': '44465fa2408b8d1005029e46c294dc2a4c38fcc2b0f1e7e2337bf96e966e6e21',
    'exiftool-edit-empty-invalid.json': 'FAULT:EDIT_EMPTY_VALUE',
    'exiftool-edit-keywords.json': 'ecd797a651f5213087af56d4bf5ea4cb5de5fd208d8673305f08e4e4df084442',
    'exiftool-edit-raw-tag-invalid.json': 'FAULT:UNKNOWN_ARGUMENT',
    'exiftool-edit-sidecar-invalid.json': 'FAULT:WRITE_SIDECAR_UNSUPPORTED',
    'exiftool-edit-variant.json': 'dc1b837314768200e60fa35174b3f674ff3321c6e063661b3c08583403047774',
    'exiftool-geotag-native-invalid.json': 'FAULT:UNKNOWN_ARGUMENT',
    'exiftool-geotag-track.json': 'b6c1a57cc6e3af4af7ab3be6a4789e799b07cd3791afc913e271aead4e22a93f',
    'exiftool-hash-invalid.json': 'FAULT:INVALID_SHA256',
    'exiftool-id-invalid.json': 'FAULT:INVALID_PHOTO_ID',
    'exiftool-inspect-baseline.json': 'e0e96ffbdf7596fb20bde076ed902e07c55d710f00c7bf06759024b8b974b7a3',
    'exiftool-inspect-variant.json': '3d5a90bfda75be70a14354d11b8af1c9f09940f016d0bf3230d619a1ed23b129',
    'exiftool-locate-baseline.json': '6a481cc2fe364c47e367b2a9e6f61b2c6faea10e21bbbb252274b5ca21c24578',
    'exiftool-media-both-invalid.json': 'FAULT:INVALID_ARGUMENT',
    'exiftool-minimise-baseline.json': 'c8b90069756d26a1477472777826d25cd71b144dfa94f92061b2d378fb3d5bd9',
    'exiftool-minimise-combined-invalid.json': 'FAULT:INVALID_ARGUMENT',
    'exiftool-path-relative-invalid.json': 'FAULT:INVALID_PHOTO_SOURCE',
    'exiftool-profile-invalid.json': 'FAULT:INVALID_ARGUMENT',
    'exiftool-reconcile-time.json': 'ce84e830261ada6ddac7b4ba1bb650f39c301aa4096be4c9598c553e08ba275d',
    'exiftool-remove-baseline.json': '75e24e1f1aae0e44970474085caaa7added7bebc3c402b2e6c0abfce12308161',
    'exiftool-remove-category-invalid.json': 'FAULT:INVALID_ARGUMENT',
    'exiftool-remove-variant.json': '6a8a1a0eca4ba36a3eac21b261768d352ff4440d8fd86ff69ce05ebd3464558f',
    'exiftool-require-without-rule-invalid.json': 'FAULT:INVALID_AUDIT',
    'exiftool-set-location-range-invalid.json': 'FAULT:INVALID_ARGUMENT',
    'exiftool-set-location.json': 'd8d7541e165bdc38b93668a2cba35b933eba38d31c9b277953c81e83b9a83728',
    'exiftool-variant.json': 'f64a1056d09a83b092af902a1a0fadf9e495c06e9c5b88a89efb22fcd3cbc483'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Surface(unittest.TestCase):
    def test_the_sixteen_branches_keep_the_older_order_and_e4_appends(self):
        schema = adaptor.schema()
        ops = [b['properties']['operation']['const'] for b in schema['oneOf']]
        self.assertEqual(ops[:11], ['inventoryPhotos', 'inspectMetadata', 'auditMetadata', 'compareMetadata', 'editMetadata', 'removeMetadata', 'reconcileTime', 'locate', 'correctTime', 'setLocation', 'geotagFromTrack'])
        self.assertEqual(ops[11:], E4)
        self.assertEqual(adaptor.OPERATION_ORDER, tuple(ops))

    def test_no_e4_branch_can_name_a_native_tag_option_property_template_or_expression(self):
        for branch in adaptor.schema()['oneOf'][11:]:
            names = set(branch['properties'])
            self.assertFalse(names & set(FORBIDDEN), (branch['properties']['operation'], names & set(FORBIDDEN)))
            self.assertEqual(branch.get('additionalProperties', False), False)

    def test_every_e4_operation_is_described_discoverable_and_has_a_real_plannable_example(self):
        data = capabilities.catalogue()
        for name in E4:
            entry = data['operations'][name]
            self.assertTrue(entry['purpose'] and entry['keywords'] and entry['semantics'] and entry['related'], name)
            self.assertEqual([e['reference'] for e in entry['examples']][0], 'examples/schemaxis/' + EXAMPLES[name])         # E5 adds one container example after the JPEG example
            self.assertLessEqual(len(entry['examples']), 2, name)
            document = json.loads((ROOT / 'examples/schemaxis' / EXAMPLES[name]).read_text())
            self.assertEqual(document['operation'], name)
            self.assertTrue(adaptor.plan(document))
            self.assertNotIn(str(Path.home()), json.dumps(document))

    def test_conceptual_guidance_is_complete_reviewed_and_free_of_pending_records(self):
        report = audit('exiftool')
        self.assertTrue(report['complete'], {k: v for k, v in report.items() if k in ('stale', 'counts', 'linkIssues')})
        self.assertEqual((report['counts']['pending'], report['stale']), (0, []))
        guide = json.loads((PACKAGE / 'guidance.json').read_text())
        for name in E4:
            self.assertEqual(guide['operations'][name]['status'], 'reviewed', name)
            self.assertTrue(guide['operations'][name]['pitfalls'], name)

    def test_search_cases_offer_naming_and_sidecars_and_keep_raw_expression_and_geocoding_negative(self):
        catalogue_ = CapabilityCatalogue(providers=['exiftool'])
        self.assertTrue(check_cases(catalogue_, 'exiftool')['complete'])
        found = lambda q: [i['id'].split('/')[-1] for i in catalogue_.search(q, scope='app/exiftool', limit=100, max_bytes=65536)['items']]
        self.assertEqual(found('rename photos'), ['planNames'])
        self.assertEqual(found('export XMP sidecar'), ['exportSidecar'])
        self.assertEqual(found('organise photos'), ['organiseCopies', 'planNames'])
        for query in ('reverse geocode photos', 'raw exiftool tag', 'shell expression to shift dates'):
            self.assertEqual(found(query), [], query)

    def test_readiness_examples_name_files_that_exist_and_the_invalid_ones_state_exact_faults(self):
        readiness = json.loads((PACKAGE / 'readiness.json').read_text())['routes']['schemaxis.exiftool/1']
        by = {e['id']: e for e in readiness['examples']}
        for name in ('copy-metadata', 'apply-sidecar', 'export-sidecar', 'plan-names', 'organise-copies'):
            self.assertTrue((ROOT / by[name]['reference']).is_file(), name)
        for name, code in (('copy-metadata-raw-tag-invalid', 'UNKNOWN_ARGUMENT'), ('plan-names-template-invalid', 'INVALID_ARGUMENT')):
            self.assertEqual((by[name]['expect'], by[name]['fault']), ('invalid', code))
            with self.assertRaises(SchemaxisError) as raised:
                adaptor.plan(json.loads((ROOT / by[name]['reference']).read_text()))
            self.assertEqual(raised.exception.fault.code, code)
        for path in readiness['conformance'] + readiness['acceptance']:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_five_editable_studio_starters_plan_and_carry_only_placeholder_paths(self):
        studio = json.loads((PACKAGE / 'studio.json').read_text())
        starters = {t['id']: t for t in studio['templates']}
        for identity, operation in STARTERS.items():
            document = starters[identity]['document']
            self.assertEqual(document['operation'], operation)
            self.assertTrue(adaptor.plan(document))
            text = json.dumps(document)
            self.assertNotIn(str(Path.home()), text)
            self.assertNotIn('"/tmp/', text)
            paths = [i['path'] for i in document['media'].get('items', [])] + [i['sidecar'] for i in document['media'].get('items', []) if 'sidecar' in i] + ([document['media']['folder']['path']] if 'folder' in document['media'] else [])
            self.assertTrue(paths and all(v.startswith('/replace/with/') for v in paths), paths)
            self.assertTrue(starters[identity]['description'])

    def test_the_older_catalogue_and_write_tables_keep_their_exact_bytes_and_pins(self):
        for name, wanted in FROZEN.items():
            self.assertEqual(sha(PACKAGE / name), wanted, name)
        self.assertEqual(writes.PIN, FROZEN['writes.json'])
        self.assertEqual(catalogue.digest(catalogue.VERSION), FROZEN['fields.json'])
        self.assertEqual(catalogue.digest(catalogue.VERSION_MWG), FROZEN['fields-2.json'])
        self.assertEqual(sha(PACKAGE / 'fields-4-additions.json'), catalogue.ADDITIONS[catalogue.VERSION_E4][1])
        self.assertEqual(sha(PACKAGE / 'writes-4.json'), e4copy.PIN)

    def test_the_e4_catalogue_view_only_adds_ids_so_every_older_field_is_byte_identical(self):
        older, view = catalogue.fields(catalogue.VERSION_E3), catalogue.fields(catalogue.VERSION_E4)
        self.assertTrue(all(view[k] == v for k, v in older.items()))
        self.assertEqual([k for k in view if k not in older], ['bodySerialNumberE4', 'exposureBiasE4', 'exposureTimeE4', 'fNumberE4', 'focalLength35mmE4', 'focalLengthE4', 'isoSpeedE4', 'lensMakeE4', 'lensModelE4', 'lensSerialNumberE4'])

    def test_every_pre_e4_example_plans_to_its_frozen_plan_hash_or_fault_code(self):
        for name, wanted in OLD_PLAN_HASHES.items():
            document = json.loads((ROOT / 'examples/schemaxis' / name).read_text())
            try:
                found = adaptor.plan_hash(adaptor.plan(document))
            except SchemaxisError as error:
                found = 'FAULT:' + error.fault.code
            self.assertEqual(found, wanted, name)

    def test_the_route_accepts_image_and_text_artifacts_and_every_new_resource_is_registered_json(self):
        meta = registry.metadata('exiftool')
        self.assertEqual(meta['routes']['schemaxis.exiftool/1']['acceptedArtifacts'], ['image', 'text'])
        for name in ('guidance.json', 'readiness.json', 'studio.json', 'assessment.json', 'search-cases.json', 'fields-4-additions.json', 'writes-4.json'):
            json.loads((PACKAGE / name).read_text())

    def test_a_plan_never_echoes_a_native_name_or_the_sidecar_property_names_as_authored_input(self):
        plan = adaptor.plan(json.loads((ROOT / 'examples/schemaxis/exiftool-export-sidecar.json').read_text()))
        self.assertEqual(set(plan['transfer']), {'groups', 'fields'})
        self.assertNotIn('XMP-', json.dumps({k: v for k, v in plan.items() if k not in ('losses', 'settings')}))


try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


class PublicPolicySchema(unittest.TestCase):
    """The root ``policies`` property of the public schema declares the policy keys of every operation group (the write group's and the host group's), while each operation branch keeps
    its own strict policy object: the valid exportSidecar example and the E4 policies are accepted, unknown and cross-operation policy keys are not. Every expectation is a literal."""
    EXPORT = {'ambiguous', 'altitude', 'existingSidecar'}

    @staticmethod
    def policy_keys(schema):
        alternatives = schema.get('anyOf', [schema])
        return set().union(*(set(a['properties']) for a in alternatives))

    def test_the_root_policies_property_declares_the_export_sidecar_keys_and_the_write_keys(self):
        schema = adaptor.schema()
        root = self.policy_keys(schema['properties']['policies'])
        self.assertTrue(self.EXPORT <= root, sorted(self.EXPORT - root))
        self.assertTrue({'existing', 'absent', 'iptc', 'otherLanguages', 'exifEncoding', 'companionLoss'} <= root)      # the keys that were already declared are still declared

    def test_the_export_sidecar_branch_keeps_exactly_its_own_policy_keys_and_the_copy_branch_does_not_accept_them(self):
        branches = {b['properties']['operation']['const']: b for b in adaptor.schema()['oneOf']}
        export = branches['exportSidecar']['properties']['policies']
        self.assertEqual((set(export['properties']), export['additionalProperties']), (self.EXPORT, False))
        copy = branches['copyMetadata']['properties']['policies']
        self.assertFalse({'altitude', 'existingSidecar'} & self.policy_keys(copy))                      # 'ambiguous' is a policy of both operations

    @unittest.skipIf(Draft202012Validator is None, 'optional jsonschema developer dependency unavailable')
    def test_the_valid_export_sidecar_example_is_accepted_and_unknown_or_cross_operation_policies_are_rejected(self):
        valid = Draft202012Validator(adaptor.schema()).is_valid
        example = json.loads((ROOT / 'examples/schemaxis/exiftool-export-sidecar.json').read_text())
        self.assertEqual(example['policies'], {'ambiguous': 'skipField', 'altitude': 'omitUnlessReferenceKnown'})
        self.assertTrue(valid(example))
        self.assertTrue(valid({**example, 'policies': {'existingSidecar': 'refuse'}}))
        self.assertFalse(valid({**example, 'policies': {'bogus': 'x'}}))                                  # an unknown key
        self.assertFalse(valid({**example, 'policies': {'existing': 'replace'}}))                         # another operation's key
        self.assertFalse(valid({**example, 'policies': {'altitude': 'neverHeardOf'}}))                    # a value outside the declared enumeration
        copy = {'version': example['version'], 'operation': 'copyMetadata', 'media': example['media'], 'source': {'item': 'cam_b_1'}, 'transfer': example['transfer'], 'policies': {'existing': 'replace'}}
        self.assertTrue(valid(copy))
        self.assertFalse(valid({**copy, 'policies': {'existingSidecar': 'ignore'}}))                      # an export-only key in a copy


if __name__ == '__main__':
    unittest.main()
