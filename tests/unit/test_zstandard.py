"""Semantic validation and exact native-control translation at the host boundary."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from schemaxis.adaptors.zstandard import adaptor as a
from schemaxis.core.faults import SchemaxisError


class ZstandardPlans(unittest.TestCase):
    def document(self,**values):
        return {'version':a.VERSION,'operation':'compress','source':'/example/data.bin',**values}

    def refuses(self,document,code):
        with self.assertRaises(SchemaxisError) as caught:a.plan(document)
        self.assertEqual(caught.exception.fault.code,code)

    def test_selected_schema_refuses_other_task_fields_and_accepts_shared_inputs(self):
        from jsonschema import Draft202012Validator
        from schemaxis.schema import export_schema
        literal = Draft202012Validator(export_schema(version=a.VERSION))
        self.assertTrue(literal.is_valid(self.document()))
        self.assertFalse(literal.is_valid(self.document(samples=['/example/x']*8)))
        self.assertFalse(literal.is_valid(self.document(operation='restore', level=4)))
        authored = self.document(operation={'$document': '/definitions/task'})
        authored['definitions'] = {'task': 'compress'}
        authored['dimensions'] = {'level': {'$analytic': {'type': 'values', 'values': [2, 5]}}}
        authored['level'] = {'$document': '/dimensions/level'}
        self.assertTrue(Draft202012Validator(export_schema(version=a.VERSION, authored=True)).is_valid(authored))
        plans = a.plan(authored)
        self.assertEqual([visit['plan']['level'] for visit in plans['visits']], [2, 5])

    def test_fast_and_level_are_alternative_intents(self):
        self.refuses(self.document(fast=3,level=6),'INVALID_ZSTANDARD_OPTION')
        command=a._compression(a.plan(self.document(fast=3)))
        self.assertIn('--fast=3',command)
        self.assertNotIn('-3',command)

    def test_native_controls_have_explicit_stable_cli_spelling(self):
        p=a.plan(self.document(level=22,threads=2,checksum=False,dictionaryID=False,
            longWindowLog=25,rsyncable=True,literals='raw',tuning={'windowLog':25,'strategy':'btultra2','minMatch':4}))
        self.assertEqual(a._compression(p),['--quiet','--no-progress','--keep','--format=zstd','-T2',
            '--ultra','-22','--no-check','--no-dictID','--long=25','--rsyncable',
            '--no-compress-literals','--zstd=wlog=25,mml=4,strat=9'])

    def test_compatibility_codec_cannot_silently_ignore_zstandard_options(self):
        for change in ({'dictionary':'/example/dict'}, {'checksum':False}, {'dictionaryID':False},
                       {'literals':'raw'}, {'chunkBytes':100}, {'fast':2}, {'tuning':{'minMatch':4}}, {'level':10}):
            with self.subTest(change=change):self.refuses(self.document(format='gzip',**change),'INVALID_ZSTANDARD_OPTION')

    def test_conflicting_worker_and_window_intents_are_refused(self):
        for change in ({'singleThread':True,'threads':2},{'singleThread':True,'rsyncable':True},
                       {'longWindowLog':9},{'longWindowLog':25,'tuning':{'windowLog':24}}):
            with self.subTest(change=change):self.refuses(self.document(**change),'INVALID_ZSTANDARD_OPTION')

    def test_training_split_maps_fraction_to_native_integer_percent(self):
        p=a.plan({'version':a.VERSION,'operation':'trainDictionary',
                  'samples':['/example/record-'+str(i) for i in range(8)],'trainingFraction':.75})
        self.assertIn('--train-fastcover=steps=4,split=75,f=20,accel=1',a._training(p))
        for fraction in (.1,.751):
            with self.subTest(fraction=fraction):self.refuses({**p,'version':a.VERSION,'trainingFraction':fraction},'INVALID_ZSTANDARD_OPTION')

    def test_training_algorithm_specific_controls_are_not_ignored(self):
        base={'version':a.VERSION,'operation':'trainDictionary','samples':['/example/'+str(i) for i in range(8)]}
        for change in ({'algorithm':'legacy','steps':4},{'algorithm':'cover','frequencyLog':20},
                       {'algorithm':'fastCover','shrink':True},{'algorithm':'fastCover','selectivity':9}):
            with self.subTest(change=change):self.refuses({**base,**change},'INVALID_ZSTANDARD_OPTION')

    def test_delta_requires_one_zstandard_frame_and_its_reference(self):
        for change in ({'format':'xz'},{'dictionary':'/example/dict'},{'chunkBytes':1024}):
            with self.subTest(change=change):self.refuses(self.document(operation='encodeDelta',reference='/example/old',**change),'INVALID_ZSTANDARD_OPTION')

    def test_restore_and_inspect_cannot_supply_two_dictionary_mechanisms(self):
        for operation in ('restore','inspect'):
            with self.subTest(operation=operation):self.refuses(self.document(operation=operation,dictionary='/example/dict',reference='/example/old'),'INVALID_ZSTANDARD_OPTION')

    def test_source_paths_and_corpus_members_are_explicit(self):
        self.refuses(self.document(source='relative'),'INVALID_ZSTANDARD_SOURCE')
        self.refuses(self.document(source='/tmp/a\x00b'),'INVALID_ZSTANDARD_SOURCE')
        self.refuses({'version':a.VERSION,'operation':'concatenate','sources':['/tmp/a','/tmp/a']},'INVALID_ZSTANDARD_SOURCE')
        self.refuses([],'INVALID_ZSTANDARD_DOCUMENT')

    def test_reuse_identity_follows_bytes_at_same_source_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'source';source.write_bytes(b'first')
            doc=self.document(source=str(source));before=a.reusableInputs(doc)
            source.write_bytes(b'second')
            self.assertNotEqual(before,a.reusableInputs(doc))

    def test_symlink_is_refused_before_native_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'source';source.write_bytes(b'hello')
            link=Path(temporary)/'link';link.symlink_to(source)
            with self.assertRaises(SchemaxisError) as caught:a.reusableInputs(self.document(source=str(link)))
            self.assertEqual(caught.exception.fault.code,'INVALID_ZSTANDARD_SOURCE')

    def test_existing_output_never_overwrites_prior_evidence(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(a,'_identity') as native:
            marker=Path(temporary)/'authored.json';marker.write_text('old intent')
            with self.assertRaises(SchemaxisError) as caught:a.run(self.document(),temporary)
            self.assertEqual(caught.exception.fault.code,'OUTPUT_EXISTS')
            self.assertEqual(marker.read_text(),'old intent');native.assert_not_called()

    def test_fifo_is_refused_without_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipe=Path(temporary)/'pipe';os.mkfifo(pipe)
            with self.assertRaises(SchemaxisError) as caught:a.reusableInputs(self.document(source=str(pipe)))
            self.assertEqual(caught.exception.fault.code,'ZSTANDARD_BUDGET')

    def test_nonsensical_timeout_is_refused_before_runtime(self):
        for timeout in (True,0,-1,float('inf'),float('nan'),3601):
            with self.subTest(timeout=timeout),self.assertRaises(SchemaxisError) as caught:a.run(self.document(),'/unused',timeout=timeout)
            self.assertEqual(caught.exception.fault.code,'INVALID_ARGUMENT')


class StudioTaskSelection(unittest.TestCase):
    def test_all_closed_task_choices_have_guided_document_selectors(self):
        from schemaxis.studio_catalogue import catalogue
        from schemaxis.adaptors.zstandard.adaptor import OPTIONS
        choices={item['operation']:item for item in catalogue('zstandard')['items'] if item.get('operation')}
        self.assertEqual(set(choices),set(OPTIONS))
        for name,item in choices.items():
            self.assertEqual(item['at'],'/operation')
            self.assertEqual(item['schema']['const'],name)
            self.assertIn(item['guidance']['status'],('reviewed','reference'))
