"""Stream promises, algorithm applicability and bounded hostile evidence."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from schemaxis.adaptors.zstandard import adaptor as a,frames
from schemaxis.core.faults import SchemaxisError
from schemaxis.dispatch import allocation


class StreamingPlans(unittest.TestCase):
    def doc(self,**values):return {'version':a.VERSION,'operation':'compress','source':'/example/source',**values}

    def test_inapplicable_native_tuning_is_refused(self):
        for options in ({'strategy':'fast','chainLog':10},{'strategy':'lazy2','targetLength':64},
                        {'targetLength':64},{'windowLog':10,'searchLog':10},
                        {'ldmMinMatch':32},{'chainLog':10},{'searchLog':10},
                        {'strategy':'fast','searchLog':10},{'strategy':'doubleFast','searchLog':10},
                        {'minMatch':3},{'minMatch':7},{'strategy':'fast','minMatch':3},
                        {'strategy':'greedy','minMatch':3},{'strategy':'doubleFast','minMatch':7},
                        {'strategy':'btopt','minMatch':7}):
            with self.subTest(options=options),self.assertRaises(SchemaxisError) as caught:a.plan(self.doc(tuning=options))
            self.assertEqual(caught.exception.fault.code,'INVALID_ZSTANDARD_OPTION')
        for tuning in ({'strategy':'fast','minMatch':7},{'strategy':'btopt','minMatch':3},
                       {'strategy':'doubleFast','chainLog':10,'minMatch':6}):
            with self.subTest(tuning=tuning):self.assertEqual(a.plan(self.doc(tuning=tuning))['tuning'],tuning)
        with self.assertRaises(SchemaxisError):a.plan({'version':a.VERSION,'operation':'benchmark','source':'/example/data','tuning':{'strategy':'fast','searchLog':10}})

    def test_worker_and_stream_controls_cannot_be_silently_ignored(self):
        for options in ({'singleThread':True,'jobBytes':524288},{'singleThread':True,'adaptive':{}},
                        {'jobBytes':100},{'jobBytes':524288,'level':9,'tuning':{'overlapLog':9}},
                        {'jobBytes':524288,'tuning':{'windowLog':20}}, {'targetBlockBytes':1},{'pledgedBytes':0},
                        {'sizeHintBytes':1024},{'streamInput':True,'contentSize':'require'},
                        {'streamInput':True,'pledgedBytes':0,'sizeHintBytes':1},
                        {'adaptive':{'minLevel':6,'maxLevel':9}},
                        {'longWindowLog':20,'jobBytes':524288,'tuning':{'overlapLog':9}}):
            with self.subTest(options=options),self.assertRaises(SchemaxisError) as caught:a.plan(self.doc(**options))
            self.assertEqual(caught.exception.fault.code,'INVALID_ZSTANDARD_OPTION')

    def test_exact_stream_pledge_is_checked_before_native_identity(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(a,'_identity') as native:
            source=Path(temporary)/'source';source.write_bytes(b'abc')
            with self.assertRaises(SchemaxisError) as caught:a.run(self.doc(source=str(source),streamInput=True,pledgedBytes=4),Path(temporary)/'run')
            self.assertEqual(caught.exception.fault.code,'INVALID_ZSTANDARD_OPTION');native.assert_not_called()

    def test_explicit_control_spelling_and_header_expectation(self):
        p=a.plan(self.doc(streamInput=True,pledgedBytes=3,contentSize='require',targetBlockBytes=1024,
                          jobBytes=1048576,longWindowLog=20,tuning={'overlapLog':9,'ldmHashLog':16,'ldmHashRateLog':4,'ldmMinMatch':32,'ldmBucketSizeLog':3}))
        command=a._compression(p)
        self.assertIn('--stream-size=3',command);self.assertIn('--content-size',command)
        self.assertIn('--target-compressed-block-size=1024',command);self.assertIn('-B1048576',command)
        self.assertIn('--zstd=ovlog=9,lhrlog=4,lhlog=16,lmml=32,lblog=3',command)
        self.assertEqual(a.compression_options.declared_sizes(p,[3]),[3])
        p['contentSize']='omit';self.assertEqual(a.compression_options.declared_sizes(p,[3]),[None])

    def test_delta_refuses_native_overridden_window_and_job_controls(self):
        for options in ({'tuning':{'windowLog':10}}, {'longWindowLog':20},
                        {'jobBytes':524288,'tuning':{'windowLog':10,'overlapLog':9}}):
            with self.subTest(options=options), self.assertRaises(SchemaxisError) as caught:
                a.plan(self.doc(operation='encodeDelta',reference='/example/reference',**options))
            self.assertEqual(caught.exception.fault.code,'INVALID_ZSTANDARD_OPTION')

    def test_raw_dictionary_has_no_invented_numeric_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'dictionary';path.write_bytes(b'raw history that is not a trained header')
            self.assertEqual(a._dictionary(path,{'dictionaryMode':'raw'}),0)
            with self.assertRaises(SchemaxisError):a._dictionary(path,{'dictionaryMode':'trained'})
            path.write_bytes(b'\x37\xa4\x30\xec\x50\xc3\0\0')
            with self.assertRaises(SchemaxisError):a._dictionary(path,{'dictionaryMode':'raw'})

    def test_malformed_membership_and_duplicate_evidence_keys_are_refused(self):
        p=a.plan(self.doc())
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for value in ({},[False],[{'index':False}]):
                (root/'inputs.json').write_text(json.dumps(value))
                with self.subTest(value=value),self.assertRaises(SchemaxisError):a._inputs(root,p)
            (root/'inputs.json').write_text('{"same":1,"same":2}')
            with self.assertRaises(ValueError):a._json(root/'inputs.json')

    def test_unhashable_operation_and_bad_resource_reservation_are_structured(self):
        with self.assertRaises(SchemaxisError) as caught:a.plan(self.doc(operation=[]))
        self.assertEqual(caught.exception.fault.code,'UNKNOWN_FILTER')
        for threads in ('two',True,0):
            with self.subTest(threads=threads),self.assertRaises(SchemaxisError) as caught:a.resources(self.doc(),{'threads':threads},'job')
            self.assertEqual(caught.exception.fault.code,'INVALID_EXECUTION')

    def test_host_frame_and_checksum_work_observe_cancellation(self):
        cancel=threading.Event();cancel.set()
        with allocation({'threads':1},cancel):
            for action in (lambda:frames.inspect(bytes.fromhex('502a4d1800000000')),lambda:frames.xxh64(b'a'*32768)):
                with self.assertRaises(SchemaxisError) as caught:action()
                self.assertEqual(caught.exception.fault.code,'RUNNER_CANCELLED')
