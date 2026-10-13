"""Corrected ParaView text: discovery semantics, field and operation guidance and Studio recipes.

These pin text fixes whose source facts were settled against the bundled ParaView 5.13.3
sources or bounded native probes (see the ledger evidence in the commit that added them).
They are host-only checks of Schemaxis's shipped text.
"""
import json
import re
import unittest
from importlib.resources import files
from pathlib import Path
from schemaxis.adaptors.paraview.capabilities import catalogue as discovery
from schemaxis.adaptors.paraview.filters import catalogue as declarations
from schemaxis.studio_guidance import load

ROOT = Path(__file__).resolve().parents[2]
GUIDE = load('paraview')
FIELDS = GUIDE['routes']['schemaxis/1']['fields']
OPERATIONS = GUIDE['operations']
DECLARED = declarations()


def text(record):
    """Every prose value of a guidance record."""
    return ' '.join([record.get('explanation', ''), record.get('defaultMeaning', ''), *record.get('pitfalls', [])])


def field(address):
    return FIELDS['/$defs/options-' + address]


class DiscoverySemanticsTests(unittest.TestCase):
    """Upstream operation text that is wrong must not reach agents through discovery."""

    @classmethod
    def setUpClass(cls):
        cls.operations = discovery()['operations']

    def semantics(self, name):
        return ' '.join(self.operations[name]['semantics'])

    def test_csv_reader_outputs_a_table_not_a_rectilinear_grid(self):
        text_ = self.semantics('pvCSVReader')
        self.assertIn('vtkTable', text_)
        self.assertNotIn('into a 1D rectilinear grid. If the file', text_)
        self.assertIn('Schemaxis correction', text_)

    def test_wind_blade_ports_follow_the_xml_output_port_order(self):
        text_ = self.semantics('pvWindBladereader')
        self.assertIn('port 0 (Field)', text_)
        self.assertLess(text_.index('port 1 (Blade)'), text_.index('port 2 (Ground)'))

    def test_time_source_is_an_unstructured_grid(self):
        text_ = self.semantics('pvTimeSource')
        self.assertIn('vtkUnstructuredGrid', text_)
        self.assertNotIn('single cell uniform grid', text_)

    def test_wavelet_formula_is_a_sum_of_terms(self):
        text_ = self.semantics('pvWavelet')
        self.assertNotIn('M * G', text_)
        self.assertIn('terms are added, not multiplied', text_)

    def test_axes_scalars_are_documented_as_values_not_colours(self):
        text_ = self.semantics('pvAxes')
        self.assertIn('0 on the X line, 0.25 on Y, 0.5 on Z', text_)
        self.assertNotIn('X axis will be drawn as a blue line', text_)

    def test_visit_readers_are_described_by_what_they_read(self):
        samrai = self.operations['pvVisItSAMRAIReader']
        self.assertNotIn('Specific Absorption Rate', samrai['purpose'])
        self.assertIn('SAMRAI', samrai['purpose'])
        claw = self.operations['pvVisItClawReader']
        self.assertNotIn('material-ordered', claw['purpose'])
        self.assertIn('Clawpack', claw['purpose'])

    def test_captured_text_is_kept_as_provenance_next_to_the_correction(self):
        context = json.loads(files('schemaxis.adaptors.paraview').joinpath('native-context.json').read_text())['operations']
        for identity in ('sources/CSVReader', 'sources/WindBladeReader', 'sources/TimeSource', 'sources/RTAnalyticSource',
                         'sources/Axes', 'sources/VisItSAMRAIReader', 'sources/VisItClawReader'):
            with self.subTest(identity=identity):
                self.assertEqual(context[identity]['basis'], 'curated correction of installed native documentation')
                self.assertTrue(context[identity]['long'])
        self.assertIn('Specific Absorption Rate', context['sources/VisItSAMRAIReader']['long'])
        self.assertIn('1D rectilinear grid', context['sources/CSVReader']['long'])


class FieldTextTests(unittest.TestCase):
    def test_no_op_particle_tracer_settings_say_so(self):
        for address in ('pvStreakLine/properties/ForceReinjectionEveryNSteps', 'pvStreakLine/properties/StaticSeeds',
                        'pvStreakLine/properties/DisableResetCache', 'pvParticlePath/properties/StaticSeeds',
                        'pvParticleTracer/properties/StaticSeeds'):
            with self.subTest(address=address):
                self.assertIn('Has no effect', field(address)['explanation'])
                self.assertTrue(any('vtkParticleTracerBase' in s or 'vtkStreaklineFilter' in s for s in field(address)['sources']))

    def test_animate_vibrations_false_still_applies_the_requested_time(self):
        self.assertIn('still scaled by cos(2π t)', field('pvAnimateModes/properties/AnimateVibrations')['explanation'])

    def test_xdmf_mesh_static_over_time_changes_single_step_storage(self):
        for address in ('pvWriteXdmfWriter', 'pvWriteXdmfWriter/properties/MeshStaticOverTime'):
            with self.subTest(address=address):
                self.assertIn('/Topology_<grid>', field(address)['explanation'])
        self.assertNotIn('no practical effect', field('pvWriteXdmfWriter')['explanation'])

    def test_time_array_none_entry_is_not_called_default(self):
        records = [(a, r) for a, r in FIELDS.items() if a.endswith('/TimeArray')]
        self.assertEqual(len(records), 36)  # 18 option records and 18 readback copies
        for address, record in records:
            with self.subTest(address=address):
                self.assertNotIn('If set to Default', record['explanation'])
                self.assertIn('"None"', record['explanation'])

    def test_point_interpolator_null_points_default_is_null_value(self):
        for operation in ('pvPointDatasetInterpolator', 'pvPointLineInterpolator', 'pvPointPlaneInterpolator', 'pvPointVolumeInterpolator'):
            with self.subTest(operation=operation):
                explanation = field(operation + '/properties/NullPointsStrategy')['explanation']
                self.assertNotIn('default strategy ClosestPoint', explanation)
                self.assertIn('default, entry 1', explanation)

    def test_wavelet_fields_describe_the_sum_formula(self):
        for address in ('pvWavelet/properties/XMag', 'pvWavelet/properties/ZFreq', 'pvWavelet/properties/Center', 'wavelet/properties/centre'):
            with self.subTest(address=address):
                self.assertNotIn('in the equation', field(address)['explanation'])
                self.assertIn('adds them', field(address)['explanation'])
        self.assertIn('ZMag·cos(ZFreq·z)', field('pvWavelet/properties/ZMag')['explanation'])

    def test_mpi_move_data_output_type_is_polydata_when_omitted(self):
        self.assertNotIn('must be set', field('pvMPIMoveData')['explanation'])
        self.assertIn('PolyData', field('pvMPIMoveData')['explanation'])
        self.assertNotIn('no static default', ' '.join(OPERATIONS['pvMPIMoveData']['pitfalls']))
        self.assertNotIn('declared in advance', OPERATIONS['pvMPIMoveData']['explanation'])

    def test_extract_subset_states_the_include_boundary_override(self):
        self.assertIn("overriding ParaView's false", field('extractSubset')['explanation'])
        self.assertTrue(declarations()['extractSubset']['options']['includeBoundary']['value'])

    def test_stale_source_citations_are_repointed(self):
        blob = json.dumps(GUIDE)
        self.assertNotIn('(relative reader paths, line 242)', blob)
        self.assertNotIn('docs/studio-guide.md:241-244', blob)
        self.assertEqual(blob.count('docs/studio-guide.md#choosing-an-openfoam-case (relative reader paths)'), 5)
        for pattern in ('v9.4.1/IO/Exodus/vtkExodusIIReader', 'v9.4.1/IO/ParallelExodus', 'v9.4.1/IO/Image/vtkSEPReader',
                        'v9.4.1/IO/Image/vtkTIFFReader'):
            self.assertNotIn(pattern, blob)
        self.assertIn('ParaView 5.13.3 VTK/IO/Image/vtkSEPReader.cxx (ReadData)', blob)

    def test_ioss_selector_node_names_get_a_leading_underscore(self):
        for selector in ('EdgeBlock', 'ElementBlock', 'NodeSet', 'SideSet'):
            with self.subTest(selector=selector):
                pitfalls = field('pvWriteIOSSWriter/properties/%sSelectors/anyOf/0/items' % selector)['pitfalls']
                self.assertTrue(any('"_3D"' in p for p in pitfalls))
                self.assertFalse(any('cannot start with a digit' in p for p in pitfalls))

    def test_writer_array_lists_start_empty(self):
        records = [r for a, r in FIELDS.items() if re.search(r'^/\$defs/options-pvWrite\w+/properties/\w+Arrays/anyOf/0/items$', a)
                   and 'defaultMeaning' in r]
        self.assertGreaterEqual(len(records), 60)
        for record in records:
            self.assertNotIn('has not verified', record['defaultMeaning'])
            self.assertIn('starts this list empty', record['defaultMeaning'])
            self.assertIn('ARRAY_SELECTION_UNVERIFIABLE', record['defaultMeaning'])
        for address, record in FIELDS.items():
            if 'pvWrite' in address and 'Arrays' in address:
                self.assertNotIn('makes verification fail', text(record), address)


class WriterQualificationTests(unittest.TestCase):
    def test_every_writer_qualification_note_follows_one_template_and_the_recorded_outcome(self):
        recorded = json.loads((ROOT / 'verification/2026-09-16-catalogue-expansion.json').read_text())['writerQualification']
        outcome = {row['operation']: row['status'] for row in recorded['results']}
        checked = 0
        for name, declaration in DECLARED.items():
            if declaration.get('role') != 'writer':
                continue
            notes = [p for p in OPERATIONS[name].get('pitfalls', []) if 'native acceptance check' in p]
            if not notes:
                continue
            checked += 1
            with self.subTest(operation=name):
                self.assertEqual(len(notes), 1)
                note = notes[0]
                self.assertNotIn('has not run a native acceptance check for this writer', note)
                self.assertTrue(note.startswith('An earlier catalogue run (verification/2026-09-16-catalogue-expansion.json, writerQualification) '
                                                + ('passed only on' if outcome[name] == 'passed' else 'failed on') + ' a small serial fixture'))
                self.assertIn('no current native acceptance check is recorded', note)
                self.assertEqual('Precision 17' in note, 'Precision' in declaration['options'])
                self.assertEqual('WriteTimeValue false' in note, 'WriteTimeValue' in declaration['options'])
                self.assertEqual('tolerance of 1e-6' in note, declaration['publication']['comparison'] == 'geometry')
                self.assertEqual('pixel tolerance of 3' in note, declaration['native'] == 'JPEGWriter')
        self.assertGreaterEqual(checked, 40)

    def test_recorded_failures_are_stated(self):
        self.assertIn('pixel values changed beyond tolerance', ' '.join(OPERATIONS['pvWriteTIFFWriter']['pitfalls']))
        self.assertIn('failed on', ' '.join(OPERATIONS['pvWriteOpenVDBWriter']['pitfalls']))

    def test_partitioned_hyper_tree_grid_crash_is_attributed_to_the_reader(self):
        pitfalls = OPERATIONS['pvWriteXMLPHyperTreeGridWriter']['pitfalls']
        self.assertIn('XMLPHyperTreeGridReader crashes', pitfalls[0])
        self.assertIn('completes the write', pitfalls[0])
        self.assertIn('segmentation fault', ' '.join(pitfalls))


class ProbeObservationTests(unittest.TestCase):
    """Defaults that a bounded native probe observed, in place of earlier guesses."""

    def test_slice_offsets_omitted_still_cut_once(self):
        record = field('pvSlice/properties/SliceOffsetValues/anyOf/0/items')
        self.assertIn('one cut surface', record['defaultMeaning'])
        self.assertFalse(any('ParaView chooses the initial list' in p for p in record['pitfalls']))

    def test_line_endpoints_are_never_the_static_default(self):
        for operation in ('pvPlotOverLine', 'pvResampleToLine'):
            for point in ('Point1', 'Point2'):
                with self.subTest(operation=operation, point=point):
                    meaning = field('%s/properties/%s/anyOf/0/items' % (operation, point))['defaultMeaning']
                    self.assertIn('never the static [0, 0, 0]', meaning)
            self.assertIn('(-1, -1, -1)', ' '.join(OPERATIONS[operation]['pitfalls']))
            self.assertNotIn('statically to [0, 0, 0]', ' '.join(OPERATIONS[operation]['pitfalls']))

    def test_slice_along_poly_line_tolerance_is_not_ten(self):
        explanation = field('pvSliceAlongPolyLine')['explanation']
        self.assertIn('never the XML\'s static 10', explanation)
        self.assertIn('1.4879', explanation)

    def test_axis_aligned_slice_offsets_need_not_be_given(self):
        self.assertNotIn('give at least one value', field('pvAxisAlignedSlice')['explanation'])
        self.assertNotIn('gives no slice', field('pvAxisAlignedSlice/properties/OffsetValues/anyOf/0/items')['defaultMeaning'])

    def test_hyper_tree_grid_reflection_defaults_to_the_x_plane(self):
        operation = ' '.join(OPERATIONS['pvHyperTreeGridAxisReflection']['pitfalls'])
        self.assertIn('"X Axis"', operation)
        self.assertIn('x = PlanePosition', operation)
        self.assertNotIn('is ignored', field('pvHyperTreeGridAxisReflection/properties/PlaneNormal')['defaultMeaning'])
        self.assertNotIn('PlanePosition is unused', field('pvHyperTreeGridAxisReflection')['explanation'])

    def test_normal_glyph_scale_factor_is_one(self):
        meaning = field('pvNormalGlyphs/properties/GlyphScaleFactor')['defaultMeaning']
        self.assertIn('1.0', meaning)
        self.assertNotIn('derive about a tenth', meaning)

    def test_visit_omitted_selections_report_the_probe_not_an_unconfirmed_belief(self):
        blob = json.dumps({a: r for a, r in FIELDS.items() if 'VisIt' in a})
        self.assertNotIn('not confirmed', blob)
        self.assertNotIn('has not confirmed', blob)
        self.assertNotIn('observed for the BOV reader', blob)
        meshes = field('pvVisItClawReader/properties/Meshes/anyOf/0/items')['explanation']
        self.assertIn('could not distinguish first-only from all', meshes)
        meaning = field('pvVisItBOVReader/properties/MeshStatus')['defaultMeaning']
        self.assertIn('read back', meaning)
        self.assertIn('--dr', meaning)
        self.assertIn("Load All Variables", field('pvVisItBOVReader/properties/CellArrayStatus')['defaultMeaning'])


class ReviewedFixesTests(unittest.TestCase):
    def test_static_seeds_names_the_operations_where_it_acts(self):
        for operation in ('pvStreakLine', 'pvParticlePath', 'pvParticleTracer'):
            explanation = field(operation + '/properties/StaticSeeds')['explanation']
            self.assertIn('pvLegacyParticlePath, pvLegacyStreakLine and pvInSituParticlePath', explanation)
            self.assertNotIn('does not expose', explanation)
        for name in ('pvLegacyParticlePath', 'pvLegacyStreakLine', 'pvInSituParticlePath'):
            self.assertIn(name, DECLARED)

    def test_wind_blade_output_is_an_unstructured_grid(self):
        self.assertIn('unstructured grid', OPERATIONS['pvWindBladereader']['explanation'])
        self.assertNotIn('polydata', OPERATIONS['pvWindBladereader']['explanation'])
        self.assertIn('UnstructuredGrid', ' '.join(discovery()['operations']['pvWindBladereader']['semantics']))

    def test_curated_context_keeps_the_captured_upstream_text(self):
        context = json.loads(files('schemaxis.adaptors.paraview').joinpath('native-context.json').read_text())['operations']
        self.assertIn('OS = M * G', context['sources/RTAnalyticSource']['captured']['description'])
        self.assertIn('blue line', context['sources/Axes']['captured']['description'])
        self.assertIn('uniform grid', context['sources/TimeSource']['captured']['description'])
        self.assertIn('PolyData', context['sources/WindBladeReader']['captured']['description'])
        self.assertIn('1D rectilinear grid', context['sources/CSVReader']['captured']['description'])
        self.assertIn('Specific Absorption Rate', context['sources/VisItSAMRAIReader']['captured']['selection'])
        self.assertIn('IOUT=1', context['sources/VisItClawReader']['captured']['selection'])

    def test_recapture_keeps_corrections_only_while_the_upstream_text_is_unchanged(self):
        import sys
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            from capture_paraview_context import corrected_record, CORRECTED
        finally:
            sys.path.pop(0)
        old = {'basis': CORRECTED, 'selection': 'Corrected selection', 'description': 'Old corrected description',
               'captured': {'description': 'Wrong upstream description'}}
        record = {'short': 'Short help', 'description': 'Wrong upstream description'}
        kept = corrected_record('sources/X', old, record, 'Short help')
        self.assertEqual(kept['description'], 'Old corrected description')
        self.assertEqual(kept['selection'], 'Short help')  # never corrected: taken from the new capture
        with self.assertRaises(ValueError) as error:
            corrected_record('sources/X', old, {'short': 'Short help', 'description': 'Changed upstream'}, 'Short help')
        self.assertIn('review the Schemaxis correction for sources/X', str(error.exception))

    def test_hyper_tree_grid_reflection_separates_observation_from_source(self):
        meaning = field('pvHyperTreeGridAxisReflection/properties/PlaneNormal')['defaultMeaning']
        self.assertIn('did not obtain valid output bounds', meaning)
        self.assertFalse(any('v9.4.1' in s and 'HyperTreeGridAxisReflection' in s for s in field('pvHyperTreeGridAxisReflection')['sources']))

    def test_slice_offsets_do_not_claim_equivalence_with_zero(self):
        meaning = field('pvSlice/properties/SliceOffsetValues/anyOf/0/items')['defaultMeaning']
        self.assertNotIn('same as [0]', meaning)
        self.assertIn('26 and 28 cells', meaning)
        origin = [r for a, r in FIELDS.items() if a.startswith('/$defs/options-pvSlice/properties/SliceType') and a.endswith('/properties/Origin')]
        self.assertTrue(any('batch run' in r['defaultMeaning'] and '[0, 0, 0]' in r['defaultMeaning'] for r in origin))

    def test_line_endpoint_wording_is_not_generalised(self):
        for operation in ('pvPlotOverLine', 'pvResampleToLine'):
            blob = ' '.join(OPERATIONS[operation]['pitfalls']) + field(operation + '/properties/Point1/anyOf/0/items')['defaultMeaning']
            self.assertNotIn('degenerate', blob)
            self.assertNotIn('never a fixed value', blob)
            self.assertIn('polydata upstream', blob)

    def test_pio_time_array_lists_its_three_choices(self):
        self.assertIn('CycleIndex or PIOFileIndex', field('pvPIOReader/properties/TimeArray')['explanation'])

    def test_mpi_move_data_none_is_the_no_default_keyword(self):
        self.assertIn('"none" is ParaView\'s keyword', field('pvMPIMoveData/properties/OutputDataType')['defaultMeaning'])

    def test_partitioned_hyper_tree_grid_piece_reader_is_named(self):
        self.assertIn('pvHyperTreeGridReader', OPERATIONS['pvWriteXMLPHyperTreeGridWriter']['pitfalls'][0])

    def test_ioss_qualification_note_follows_the_template(self):
        notes = [p for p in OPERATIONS['pvWriteIOSSWriter']['pitfalls'] if 'native acceptance check' in p]
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0].startswith('An earlier catalogue run (verification/2026-09-16-catalogue-expansion.json, writerQualification) passed only on'))


class StudioRecipeTests(unittest.TestCase):
    def test_csv_export_snippets_write_full_precision(self):
        studio = json.loads(files('schemaxis.adaptors.paraview').joinpath('studio.json').read_text())
        found = []

        def walk(node, snippet):
            if isinstance(node, dict):
                if node.get('writer') == 'pvWriteCSVWriter':
                    found.append(snippet)
                    self.assertEqual(node.get('options'), {'Precision': 17}, snippet)
                for child in node.values():
                    walk(child, snippet)
            elif isinstance(node, list):
                for child in node:
                    walk(child, snippet)

        for snippet in studio['snippets']:
            walk(snippet.get('inserts', []), snippet['id'])
        self.assertEqual(sorted(found), ['export-csv', 'line-profile-csv'])


if __name__ == '__main__':
    unittest.main()
