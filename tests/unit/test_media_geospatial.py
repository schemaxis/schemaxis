# Copyright (C) 2026 David L F Gaden
"""Independent pixel, timing, workflow and vector-contract regression tests."""
import copy
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from schemaxis.core.faults import SchemaxisError
from schemaxis import png, workflow
from schemaxis.adaptors.ffmpeg import adaptor as video
from schemaxis.adaptors.qgis import adaptor as gis
from schemaxis.adaptors.godot import adaptor as godot


def png_bytes(width=4,height=2,colour=(20,80,160,255)):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+bytes(colour)*width for _ in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


def video_doc(files,codec='ffv1'):
    return {'version':'schemaxis.ffmpeg/1','nodes':[{'id':'movie','filter':'encodeFrames','options':{'files':files,'codec':codec,'fps':25}}]}


def gis_doc(path='/site.geojson'):
    return {'version':'schemaxis.qgis/1','nodes':[
        {'id':'site','filter':'readVector','options':{'file':path}},
        {'id':'metric','filter':'reproject','inputs':{'input':'site'},'options':{'crs':'EPSG:3857'}},
        {'id':'buffer','filter':'buffer','inputs':{'input':'metric'},'options':{'distance':100}},
        {'id':'clip','filter':'clip','inputs':{'input':'buffer'},'options':{'bounds':[-50,-50,50,50]}}],
        'output':'clip'}


class ImageContractTests(unittest.TestCase):
    def test_decode_exact_rgba_and_truncation(self):
        data=png_bytes();self.assertEqual(png.decode(data),(4,2,bytes((20,80,160,255))*8))
        for bad in (data[:-1],data+b'x',b'',data[:40]+b'bad'+data[43:]):
            with self.assertRaises(SchemaxisError):png.decode(bad)

    def test_all_png_scanline_filters(self):
        def chunk(kind,data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        rows=[bytes((13,27,51,255,30,80,200,128)),bytes((17,40,70,255,90,30,20,0))]
        for method in range(5):
            raw=bytearray();previous=bytes(8)
            for row in rows:
                raw.append(method)
                for i,value in enumerate(row):
                    a=row[i-4] if i>=4 else 0;b=previous[i];c=previous[i-4] if i>=4 else 0
                    if method==4:
                        p=a+b-c
                        predictor=min((a,b,c),key=lambda v:abs(p-v))
                    else:predictor=(0,a,b,(a+b)//2)[method]
                    raw.append((value-predictor)%256)
                previous=row
            data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
            self.assertEqual(png.decode(data),(2,2,b''.join(rows)))

    def test_compositing_and_size_contract(self):
        prepared=video.plan(video_doc(['/frame.png']))
        w,h,frames=video.frames(prepared,[png_bytes(colour=(100,200,50,128))])
        self.assertEqual(frames,[bytes((50,100,25))*8])
        d=video_doc(['/a','/b'])
        with self.assertRaises(SchemaxisError):video.frames(video.plan(d),[png_bytes(),png_bytes(2,2)])
        with self.assertRaises(SchemaxisError):video.frames(video.plan(video_doc(['/a'],'h264')),[png_bytes(3,2)])

    def test_sprite_timing_and_bounds(self):
        d={'version':'schemaxis.ffmpeg/1','nodes':[{'id':'movie','filter':'encodeSheet','options':{'file':'/a.png','metadata':'/a.json','fps':25,'codec':'ffv1'}}]}
        meta={'version':'schemaxis.aseprite.sheet/1','width':4,'height':2,'frames':[
            {'x':0,'y':0,'width':2,'height':2,'durationMS':120},
            {'x':2,'y':0,'width':2,'height':2,'durationMS':200}],'tags':[]}
        _,_,frames=video.frames(video.plan(d),[png_bytes(),json.dumps(meta).encode()]);self.assertEqual(len(frames),8)
        for key,value in [('durationMS',121),('x',4),('width',True)]:
            bad=copy.deepcopy(meta);bad['frames'][0][key]=value
            with self.assertRaises(SchemaxisError):video.frames(video.plan(d),[png_bytes(),json.dumps(bad).encode()])

    def test_frame_order_and_fidelity_are_verified(self):
        with self.assertRaises(SchemaxisError):video.compare([b'\0'*12,b'\xff'*12],b'\xff'*12+b'\0'*12,'ffv1')
        with self.assertRaises(SchemaxisError):video.compare([b'\0'*12],b'\0'*11,'h264')
        with self.assertRaises(SchemaxisError):video.compare([b'\0'*12],b'\xff'*12,'h264')

    def test_probe_timing_and_stream_membership(self):
        p={'streams':[{'codec_type':'video','codec_name':'ffv1','pix_fmt':'bgr0','width':4,'height':2,'nb_read_frames':'8','avg_frame_rate':'25/1'}],'format':{'duration':'0.32'}}
        options={'codec':'ffv1','fps':25};video.validate_probe(p,4,2,8,options)
        for field,value in [('width',8),('avg_frame_rate','24/1'),('nb_read_frames','7'),('pix_fmt','yuv420p')]:
            bad=copy.deepcopy(p);bad['streams'][0][field]=value
            with self.assertRaises(SchemaxisError):video.validate_probe(bad,4,2,8,options)

    def test_malformed_probe_is_always_a_structured_fault(self):
        options={'codec':'ffv1','fps':25}
        for bad in (None,[],{}, {'streams':None}, {'streams':{}},
                    {'streams':[None],'format':{}}, {'streams':[{}],'format':None}):
            with self.subTest(probe=bad),self.assertRaises(SchemaxisError) as caught:
                video.validate_probe(bad,4,2,8,options)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')


class MediaDeliverableTests(unittest.TestCase):
    def test_host_safe_policy_schema_and_defaults(self):
        document=video_doc(['/missing-frame.png'])
        document['deliverable']={'width':32,'height':24,'frames':2,
            'durationSeconds':.08,'maxBytes':100000,'maxMeanRGBError':0}
        before=copy.deepcopy(document);prepared=video.plan(document)
        self.assertEqual(document,before)
        self.assertEqual(prepared['deliverable']['durationToleranceSeconds'],.002)
        from jsonschema import Draft202012Validator
        Draft202012Validator(video.schema()).validate(document)
        self.assertEqual(prepared,video.plan(document))

    def test_invalid_requirements_fail_before_native_execution(self):
        for bad in (None,[],{}, {'durationToleranceSeconds':.002}, {'durationSeconds':0},
                    {'maxBytes':True}, {'maxBytes':0}, {'width':4097},
                    {'maxMeanRGBError':16.1}, {'maxMeanRGBError':float('nan')},
                    {'durationSeconds':1,'durationToleranceSeconds':-1}, {'arbitrary':1}):
            document=video_doc(['/missing.png']);document['deliverable']=bad
            with self.subTest(policy=bad),patch.object(video,'execute') as execute,self.assertRaises(SchemaxisError):
                video.run(document,'/irrelevant',executable='/bin/true')
            execute.assert_not_called()

    def test_acceptance_reports_every_requirement_and_next_action(self):
        policy=video.deliverable_policy({'width':32,'height':24,'frames':2,
            'durationSeconds':.1,'durationToleranceSeconds':.001,'maxBytes':100,'maxMeanRGBError':.5})
        report=video.assess_deliverable(policy,32,24,2,25,101,[.1,.6])
        self.assertFalse(report['accepted'])
        failures=[c['requirement'] for c in report['checks'] if not c['passed']]
        self.assertEqual(failures,['durationSeconds','maxBytes','maxMeanRGBError'])
        self.assertEqual(report['observed']['maximumMeanRGBError'],.6)
        self.assertIn('fps',report['checks'][3]['nextAction'])
        self.assertIn('FFV1',report['checks'][-1]['nextAction'])

    def fake_run(self, root, policy=None, codec='ffv1', decode_error=0):
        """Fixture makes trustworthy baseline evidence without launching native code."""
        image=root/'source.png';image.write_bytes(png_bytes())
        document=video_doc([str(image)],codec)
        if policy is not None:document['deliverable']=policy
        output=root/'run'
        def execute(command,directory,stage,timeout):
            from schemaxis.artifacts import atomic_json
            atomic_json(directory/(stage+'-submission.json'),{'exitCode':0,'nativeCommand':command,
                'interpreter':{'executable':command[0]}})
            if stage in ('decode','probe'):
                atomic_json(directory/(stage+'-inputs.json'),{str(directory/video.plan(document)['output']):
                    video.file_digest(directory/video.plan(document)['output'])})
            if stage=='encode':(directory/video.plan(document)['output']).write_bytes(b'synthetic video fixture')
            elif stage=='decode':(directory/'decoded.rgb').write_bytes(bytes(
                value+decode_error for value in (directory/'frames.rgb').read_bytes()))
            elif stage=='version':(directory/'version.stdout').write_text('ffmpeg fixture\n')
            elif stage=='probe':atomic_json(directory/'probe.stdout',{'streams':[{
                'codec_type':'video','codec_name':codec,'pix_fmt':'bgr0' if codec=='ffv1' else 'yuv420p','width':4,'height':2,
                'nb_read_frames':'1','avg_frame_rate':'25/1'}],'format':{'duration':'0.04'}})
        with patch.object(video,'execute',side_effect=execute),patch('os.access',return_value=True):
            video.run(document,output,executable='/native/ffmpeg')
        return output

    def test_regular_json_and_completed_exact_commands_are_required(self):
        for filename,value in (('result.json',[]),('verification.json',None),
                               ('encode-submission.json',{'exitCode':1}),('probe-submission.json',{}),
                               ('decode-submission.json',{'exitCode':0,'interpreter':[]})):
            with self.subTest(filename=filename),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);output=self.fake_run(root)
                (output/filename).write_text(json.dumps(value))
                with self.assertRaises(SchemaxisError) as caught:video.verify(output)
                self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
        for filename in ('authored.json','result.json','encode-submission.json'):
            with self.subTest(symlink=filename),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);output=self.fake_run(root);path=output/filename
                retained=root/'copy.json';path.rename(retained);path.symlink_to(retained)
                with self.assertRaises(SchemaxisError) as caught:video.verify(output)
                self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')

    def legacy_fixture(self, output):
        receipt=json.loads((output/'verification.json').read_text());del receipt['nativeReadback']
        (output/'verification.json').write_text(json.dumps(receipt))
        prepared=video.plan(json.loads((output/'authored.json').read_text()))
        commands=video.native_commands('/native/ffmpeg',output,prepared,4,2)
        for stage in ('decode','probe'):
            path=output/(stage+'-submission.json');submission=json.loads(path.read_text())
            submission['nativeCommand']=commands[stage];path.write_text(json.dumps(submission))
        return output

    def test_exact_legacy_decode_recipe_remains_verifiable(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.legacy_fixture(self.fake_run(Path(temp)));path=output/'decode-submission.json'
            submission=json.loads(path.read_text());command=submission['nativeCommand']
            index=command.index('-fps_mode');command[index:index+2]=['-vsync','0']
            path.write_text(json.dumps(submission));self.assertTrue(video.verify(output)['verified'])
            command[index+1]='1';path.write_text(json.dumps(submission))
            with self.assertRaises(SchemaxisError) as caught:video.verify(output)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')

    def test_exact_legacy_ffv1_version_three_recipe_remains_verifiable(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.legacy_fixture(self.fake_run(Path(temp)));path=output/'encode-submission.json'
            submission=json.loads(path.read_text());command=submission['nativeCommand']
            self.assertNotIn('-slices',command)
            index=command.index('-level');self.assertEqual(command[index+1],'1')
            command[index:index+2]=['-level','3','-slices','1']
            path.write_text(json.dumps(submission));self.assertTrue(video.verify(output)['verified'])
            command[index+3]='4';path.write_text(json.dumps(submission))
            with self.assertRaises(SchemaxisError) as caught:video.verify(output)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')

    def test_readback_bound_to_encoded_bytes_despite_refreshed_publication_hashes(self):
        from schemaxis.publication_metadata import finalise
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));self.assertTrue(video.verify(output)['nativeReadbackBound'])
            encoded=output/'video.mkv';encoded.write_bytes(b'\0'*encoded.stat().st_size)
            receipt=json.loads((output/'verification.json').read_text())
            receipt['artifacts'][0]['sha256']=video.file_digest(encoded)
            (output/'verification.json').write_text(json.dumps(receipt));finalise(output)
            with self.assertRaises(SchemaxisError) as caught:video.verify(output)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
            self.assertIn('consumed different encoded bytes',caught.exception.fault.message)

    def test_readback_launchers_bindings_and_completions_cannot_be_dropped(self):
        for name in ('decode-launcher.py','probe-inputs.json','decoded.rgb','probe.stdout'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                output=self.fake_run(Path(temp));path=output/name
                path.write_bytes(path.read_bytes()+b'corrupt')
                with self.assertRaises(SchemaxisError):video.verify(output)
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp));receipt=json.loads((output/'verification.json').read_text())
            del receipt['nativeReadback'];(output/'verification.json').write_text(json.dumps(receipt))
            with self.assertRaises(SchemaxisError):video.verify(output)

    @unittest.skipUnless(hasattr(os,'mkfifo'),'requires FIFO support')
    def test_fifos_rejected_without_open_or_native_launch_for_capture_and_fingerprint(self):
        import time
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fifo=root/'fifo';os.mkfifo(fifo);image=root/'frame.png';image.write_bytes(png_bytes())
            docs=[video_doc([str(fifo)]),{'version':'schemaxis.ffmpeg/1','nodes':[{'id':'movie',
                'filter':'encodeSheet','options':{'file':str(image),'metadata':str(fifo),'codec':'ffv1'}}]}]
            for doc in docs:
                start=time.monotonic()
                with patch.object(video,'execute') as execute:
                    for action in (lambda:video.reusableInputs(doc),lambda:video.read_sources(root,video.plan(doc),True)):
                        with self.assertRaises(SchemaxisError) as caught:action()
                        self.assertEqual(caught.exception.fault.code,'INVALID_RESOURCE')
                    execute.assert_not_called()
                self.assertLess(time.monotonic()-start,1)
            with patch.object(video.os,'open',side_effect=AssertionError('must reject before open')):
                with self.assertRaises(SchemaxisError):video.source_bytes(fifo)

    def test_nul_paths_and_excessive_source_files_fail_before_native_launch(self):
        bad=video_doc(['/absolute/null\0.png'])
        with patch.object(video,'execute') as execute,self.assertRaises(SchemaxisError) as caught:video.plan(bad)
        self.assertEqual(caught.exception.fault.code,'INVALID_RESOURCE');execute.assert_not_called()
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'large.png'
            with path.open('wb') as stream:stream.truncate(video.MAX_BYTES+1)
            with patch.object(video.os,'open',side_effect=AssertionError('size checked before open')):
                with self.assertRaises(SchemaxisError) as caught:video.reusableInputs(video_doc([str(path)]))
                self.assertEqual(caught.exception.fault.code,'RESOURCE_LIMIT')

    def test_forged_quality_and_byte_acceptance_cannot_bypass_actual_measurements(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp),{'maxBytes':1000,'maxMeanRGBError':0})
            self.assertTrue(video.verify(output)['deliverable']['accepted'])
            # Keep authored input, effective plan, output hashes and frame hashes
            # mutually consistent, but forge a passing size decision.
            authored=json.loads((output/'authored.json').read_text());authored['deliverable']['maxBytes']=1
            (output/'authored.json').write_text(json.dumps(authored))
            (output/'plan.json').write_text(json.dumps(video.plan(authored)))
            receipt=json.loads((output/'verification.json').read_text())
            forged=video.assess_deliverable({'maxBytes':1,'maxMeanRGBError':0},4,2,1,25,1,[0])
            receipt['deliverable']=forged;(output/'verification.json').write_text(json.dumps(receipt))
            with self.assertRaises(SchemaxisError) as caught:video.verify(output)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')
            receipt['deliverable']=video.assess_deliverable({'maxBytes':1,'maxMeanRGBError':0},4,2,1,25,
                (output/'video.mkv').stat().st_size,[0])
            (output/'verification.json').write_text(json.dumps(receipt))
            with self.assertRaises(SchemaxisError) as caught:video.verify(output)
            self.assertEqual(caught.exception.fault.code,'DELIVERABLE_NOT_MET')

    def test_forged_lossy_quality_with_matching_pixel_hashes_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp),{'maxMeanRGBError':2},codec='h264',decode_error=1)
            authored=json.loads((output/'authored.json').read_text());authored['deliverable']['maxMeanRGBError']=0
            (output/'authored.json').write_text(json.dumps(authored))
            (output/'plan.json').write_text(json.dumps(video.plan(authored)))
            receipt=json.loads((output/'verification.json').read_text())
            receipt['meanErrors']=[0]
            receipt['deliverable']=video.assess_deliverable({'maxMeanRGBError':0},4,2,1,25,
                (output/'video.mp4').stat().st_size,[0])
            # Publication and decoded/expected hashes still match the exact
            # retained bytes; false summaries cannot override actual RGB error.
            (output/'verification.json').write_text(json.dumps(receipt))
            with self.assertRaises(SchemaxisError) as caught:video.verify(output)
            self.assertEqual(caught.exception.fault.code,'VERIFICATION_FAILED')

    def test_unmet_policy_retains_explained_native_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaises(SchemaxisError) as caught:self.fake_run(root,{'width':8,'maxBytes':1})
            self.assertEqual(caught.exception.fault.code,'DELIVERABLE_NOT_MET')
            output=root/'run';receipt=json.loads((output/'verification.json').read_text())
            self.assertFalse(receipt['deliverable']['accepted'])
            self.assertTrue((output/'video.mkv').is_file())
            self.assertEqual(json.loads((output/'result.json').read_text())['fault']['code'],'DELIVERABLE_NOT_MET')

    def test_duration_acceptance_uses_native_observation(self):
        with tempfile.TemporaryDirectory() as temp:
            output=self.fake_run(Path(temp),{'durationSeconds':.04,'durationToleranceSeconds':0})
            probe=json.loads((output/'probe.stdout').read_text());probe['format']['duration']='0.041'
            (output/'probe.stdout').write_text(json.dumps(probe))
            receipt=json.loads((output/'verification.json').read_text())
            # Model a native probe that observed the new duration; update its own
            # output evidence as well as the independent deliverable decision.
            receipt['nativeReadback']['probe']['outputSHA256']=video.file_digest(output/'probe.stdout')
            receipt['deliverable']=video.assess_deliverable({'durationSeconds':.04,'durationToleranceSeconds':0},
                4,2,1,25,(output/'video.mkv').stat().st_size,[0],.041)
            (output/'verification.json').write_text(json.dumps(receipt))
            with self.assertRaises(SchemaxisError) as caught:video.verify(output)
            self.assertEqual(caught.exception.fault.code,'DELIVERABLE_NOT_MET')

    def test_total_deadline_also_bounds_offline_verification_before_publication(self):
        real_verify=video.verify
        with tempfile.TemporaryDirectory() as temp,patch.object(video.time,'monotonic',return_value=0) as clock:
            root=Path(temp)
            def finish_after_deadline(*args,**kwargs):
                result=real_verify(*args,**kwargs);clock.return_value=301
                return result
            with patch.object(video,'verify',side_effect=finish_after_deadline),self.assertRaises(SchemaxisError) as caught:
                self.fake_run(root)
            self.assertEqual(caught.exception.fault.code,'RUNNER_TIMED_OUT')
            self.assertEqual(json.loads((root/'run/result.json').read_text())['status'],'failed')


class ExpansionContractTests(unittest.TestCase):
    def test_planning_is_host_safe_and_immutable(self):
        d=gis_doc();before=copy.deepcopy(d)
        self.assertEqual(gis.plan(d),gis.plan(d));self.assertEqual(d,before)
        video.plan(video_doc(['/missing.png']))
        self.assertEqual(gis.schema()['properties']['version']['const'],'schemaxis.qgis/1')
        from schemaxis.adaptors.blender.integration import validateHandoff
        validateHandoff({'version':'schemaxis.blender/1'}, video_doc(['/frame.png']), 'movie')
        validateHandoff({'version':'schemaxis.blender/1','scenes':[{'meshes':['mesh']}]}, {}, 'legacy')

    def test_gis_rejects_bad_crs_geometry_and_dependencies(self):
        for index,key,value in [(1,'crs','+proj=anything'),(2,'distance',-1),(2,'segments',True),(3,'bounds',[1,1,0,0])]:
            d=gis_doc();d['nodes'][index]['options'][key]=value
            with self.assertRaises(SchemaxisError):gis.plan(d)
        d=gis_doc();d['nodes'][1]['inputs']['input']='later'
        with self.assertRaises(SchemaxisError):gis.plan(d)
        d=gis_doc();d['script']='anything'
        with self.assertRaises(SchemaxisError):gis.plan(d)

    def test_centroid_contract_rejects_options_and_forward_dependencies(self):
        d=gis_doc();d['nodes'].append({'id':'centre','filter':'centroid',
            'inputs':{'input':'clip'},'options':{}});d['output']='centre'
        self.assertEqual(gis.plan(d)['nodes'][-1]['filter'],'centroid')
        d['nodes'][-1]['options']['geodesic']=True
        with self.assertRaises(SchemaxisError):gis.plan(d)
        d['nodes'][-1]['options']={};d['nodes'][-1]['inputs']['input']='future'
        with self.assertRaises(SchemaxisError):gis.plan(d)

    def test_video_rejects_unbounded_or_executable_options(self):
        for key,value in [('files',[]),('files',['relative.png']),('codec','copy'),('fps',False),('threads',0),('args','-i anything')]:
            d=video_doc(['/a.png']);d['nodes'][0]['options'][key]=value
            with self.assertRaises(SchemaxisError):video.plan(d)

    def test_new_workflow_examples_plan_and_expand(self):
        from schemaxis.schema import expand_input
        root=Path(__file__).resolve().parents[2]
        for name in ('sprite-to-godot','sprite-to-video'):
            d=json.loads((root/'examples/schemaxis'/f'{name}.json').read_text())
            workflow.inspect_plan(d)
            expanded=expand_input(d)
            self.assertEqual(list(workflow.dependencies(expanded)),list(workflow.dependencies(d)))

    def test_godot_image_fingerprint(self):
        info=godot.image_info(png_bytes());self.assertEqual([info['width'],info['height']],[4,2])
        self.assertNotEqual(info['rgbaSHA256'],godot.image_info(png_bytes(colour=(0,0,0,0)))['rgbaSHA256'])

    def test_empty_native_exit_is_not_video_success(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'image.png';path.write_bytes(png_bytes())
            with patch.object(video,'execute'),patch('os.access',return_value=True),self.assertRaises(SchemaxisError):
                video.run(video_doc([str(path)]),Path(temp)/'run',executable='/bin/true')
            self.assertFalse(json.loads((Path(temp)/'run/result.json').read_text())['verified'])


@unittest.skipUnless(os.environ.get('FFMPEG_EXECUTABLE'),'explicit FFmpeg native runtime required')
class NativeVideoTests(unittest.TestCase):
    def test_lossless_and_lossy_native_decode_and_tamper(self):
        for codec in ('ffv1','h264'):
            with self.subTest(codec=codec),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);paths=[]
                for i,colour in enumerate(((220,30,10,255),(20,130,210,255))):
                    p=root/f'{i}.png';p.write_bytes(png_bytes(32,24,colour));paths.append(str(p))
                result=video.run(video_doc(paths,codec),root/'run',executable=os.environ['FFMPEG_EXECUTABLE'])
                self.assertTrue(result['verified']);self.assertEqual(video.verify(root/'run')['frames'],2)
                for p in paths:Path(p).unlink()
                self.assertTrue(video.verify(root/'run')['verified'])
                (root/'run/decoded.rgb').write_bytes(b'wrong')
                with self.assertRaises(SchemaxisError):video.verify(root/'run')
