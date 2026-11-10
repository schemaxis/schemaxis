"""Host tests of the declared surface of the five E3 operations: schema order and closure, conceptual guidance, discovery cases, readiness and Studio starters.

No native process runs. The expected operation lists and example names are literals written here.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from schemaxis.adaptors import registry  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor, capabilities, e3docs  # noqa: E402
from schemaxis.capabilities import CapabilityCatalogue  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from schemaxis.search_acceptance import check_cases  # noqa: E402
from schemaxis.studio_guidance import audit  # noqa: E402

PACKAGE = ROOT / 'src/schemaxis/adaptors/exiftool'
OPERATIONS = ['inventoryPhotos', 'inspectMetadata', 'auditMetadata', 'compareMetadata', 'editMetadata', 'removeMetadata', 'reconcileTime', 'locate', 'correctTime', 'setLocation', 'geotagFromTrack',
              'copyMetadata', 'applySidecar', 'exportSidecar', 'planNames', 'organiseCopies']
NEW = OPERATIONS[6:11]          # the E3 operations; the E4 operations append and are covered by test_exiftool_e4_surface
EXAMPLES = {'reconcileTime': 'exiftool-reconcile-time.json', 'locate': 'exiftool-locate-baseline.json', 'correctTime': 'exiftool-correct-time.json', 'setLocation': 'exiftool-set-location.json',
            'geotagFromTrack': 'exiftool-geotag-track.json'}
FORBIDDEN = ('catalogue', 'catalog', 'overlay', 'tag', 'flag', 'expression', 'argument', 'arguments', 'config', 'script', 'geotag', 'shiftExpression')


class Surface(unittest.TestCase):
    def test_the_schema_keeps_the_e1_and_e2_branches_where_they_were_and_appends_e3(self):
        schema = adaptor.schema()
        self.assertEqual([b['properties']['operation']['const'] for b in schema['oneOf']], OPERATIONS)
        self.assertEqual(schema['properties']['operation']['enum'], OPERATIONS)
        self.assertEqual(sorted(adaptor.DECLARATIONS), sorted(OPERATIONS))
        self.assertEqual(adaptor.OPERATION_ORDER, tuple(OPERATIONS))

    def test_no_e3_branch_can_name_a_native_tag_option_catalogue_flag_or_expression(self):
        schema = adaptor.schema()
        for branch in schema['oneOf'][6:11]:
            names = set(branch['properties'])
            self.assertFalse(names & set(FORBIDDEN), (branch['properties']['operation'], names & set(FORBIDDEN)))
            self.assertEqual(branch['additionalProperties'] if 'additionalProperties' in branch else False, False)

    def test_every_new_operation_is_described_discoverable_and_has_a_real_plannable_example(self):
        data = capabilities.catalogue()
        self.assertEqual(list(data['operations']), OPERATIONS)
        for name in NEW:
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
        self.assertEqual(report['counts']['pending'], 0)
        self.assertEqual(report['stale'], [])
        guide = json.loads((PACKAGE / 'guidance.json').read_text())
        for name in NEW:
            self.assertEqual(guide['operations'][name]['status'], 'reviewed', name)
            self.assertTrue(guide['operations'][name]['pitfalls'], name)

    def test_search_cases_make_geotag_and_time_shift_positive_and_keep_rename_raw_expression_and_reverse_geocoding_negative(self):
        catalogue = CapabilityCatalogue(providers=['exiftool'])
        self.assertTrue(check_cases(catalogue, 'exiftool')['complete'])
        found = lambda q: [i['id'].split('/')[-1] for i in catalogue.search(q, scope='app/exiftool', limit=100, max_bytes=65536)['items']]
        self.assertEqual(found('geotag photos'), ['geotagFromTrack'])
        self.assertEqual(found('shift photo capture time'), ['correctTime'])
        self.assertEqual(found('camera clock skew'), ['reconcileTime'])
        self.assertEqual(found('rename photos'), ['planNames'])          # E4 offers a naming plan for copies; originals are never renamed
        for query in ('reverse geocode photos', 'raw exiftool tag', 'shell expression to shift dates'):
            self.assertEqual(found(query), [], query)

    def test_readiness_examples_name_files_that_exist_and_the_invalid_ones_state_exact_faults(self):
        readiness = json.loads((PACKAGE / 'readiness.json').read_text())['routes']['schemaxis.exiftool/1']
        by = {e['id']: e for e in readiness['examples']}
        for name in ('reconcile-time', 'locate-baseline', 'correct-time', 'set-location', 'geotag-track'):
            self.assertTrue((ROOT / by[name]['reference']).is_file(), name)
        for name, code in (('correct-time-raw-argument-invalid', 'UNKNOWN_ARGUMENT'), ('set-location-range-invalid', 'INVALID_ARGUMENT'), ('geotag-native-invalid', 'UNKNOWN_ARGUMENT')):
            self.assertEqual((by[name]['expect'], by[name]['fault']), ('invalid', code))
            with self.assertRaises(SchemaxisError) as raised:
                adaptor.plan(json.loads((ROOT / by[name]['reference']).read_text()))
            self.assertEqual(raised.exception.fault.code, code)
        for path in readiness['conformance'] + readiness['acceptance']:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_five_editable_studio_starters_plan_and_carry_only_placeholder_paths(self):
        studio = json.loads((PACKAGE / 'studio.json').read_text())
        starters = {t['id']: t for t in studio['templates']}
        wanted = {'reconcile-clocks': 'reconcileTime', 'locate-photos': 'locate', 'correct-time-shift': 'correctTime', 'set-location': 'setLocation', 'geotag-track': 'geotagFromTrack'}
        for identity, operation in wanted.items():
            document = starters[identity]['document']
            self.assertEqual(document['operation'], operation)
            self.assertTrue(adaptor.plan(document))
            text = json.dumps(document)
            for value in (item['path'] for item in document['media']['items']):
                self.assertTrue(value.startswith('/replace/with/'), value)
            self.assertNotIn(str(Path.home()), text)
            self.assertTrue(starters[identity]['description'])

    def test_correct_time_publishes_json_reports_only_and_the_time_report_csv_belongs_to_reconcile_time(self):
        for apply in ('write', 'plan'):
            names = e3docs.names({'operation': 'correctTime', 'apply': apply})
            self.assertFalse([n for n in names if n.endswith('.csv')], names)
            self.assertIn('time-report.json', names)

    def test_the_route_accepts_image_and_text_artifacts_and_every_adaptor_resource_is_registered_json(self):
        meta = registry.metadata('exiftool')
        self.assertEqual(meta['routes']['schemaxis.exiftool/1']['acceptedArtifacts'], ['image', 'text'])
        for name in ('guidance.json', 'readiness.json', 'studio.json', 'assessment.json', 'search-cases.json', 'fields-3-additions.json', 'writes-3.json'):
            json.loads((PACKAGE / name).read_text())


if __name__ == '__main__':
    unittest.main()
