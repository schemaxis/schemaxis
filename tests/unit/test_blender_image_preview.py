import copy,os,struct,tempfile,unittest,zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from schemaxis.adaptors.blender.production import validate,schema
from schemaxis.adaptors.blender.node_catalogue import validate_graph
from schemaxis.adaptors.blender.image_assets import admit_file,capture_file,digest_file,MAX_FILE_BYTES,MAX_CAPTURE_BYTES
from schemaxis.adaptors.blender.settings import render_settings
from schemaxis.core.faults import SchemaxisError


def graph():
    return {'id':'surface','nodes':[{'id':'emit','kind':'emission'},{'id':'finish','kind':'output'}],
            'links':[{'from':{'node':'emit','socket':'shader'},'to':{'node':'finish','socket':'surface'}}]}


def png_header(width,height):
    body=b'IHDR'+struct.pack('>IIBBBBB',width,height,8,6,0,0,0)
    return b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+body+struct.pack('>I',zlib.crc32(body)&0xffffffff)


class ImagePreview(unittest.TestCase):
    def test_studio_starter_keeps_a_required_image_path_without_a_default(self):
        from schemaxis.studio_library import load_library,instantiate_item
        from schemaxis.unfilled import find_unfilled
        from schemaxis.adaptors.blender.adaptor import plan
        library=load_library('blender');item=next(x for x in library['templates'] if x['id']=='image-preview')
        self.assertNotIn('default',item['fields']['imageFile'])
        self.assertEqual(item['fields']['imageFile']['type'],'path')
        self.assertTrue(item['fields']['imageFile']['required'])
        draft=instantiate_item(library,item,filled=False)
        self.assertEqual([x['pointer'] for x in find_unfilled(draft)],['/production/images/0/file'])
        filled=instantiate_item(library,item);plan(filled)
        self.assertEqual(filled['production']['materialGraphs'][0]['displayTexture'],{'kind':'image','image':'fieldImage'})

    def test_image_resource_faults_and_public_capture_recovery(self):
        from schemaxis.adaptors.blender.adaptor import run
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'missing.png'
            def refusal(call,code):
                with self.assertRaises(SchemaxisError) as error:call()
                self.assertEqual(error.exception.fault.code,code)
            for reader in (admit_file,digest_file):
                refusal(lambda:reader(source,'image'),'RESOURCE_NOT_FOUND')
                refusal(lambda:reader(root,'image'),'INVALID_RESOURCE')
                with patch('os.open',side_effect=PermissionError('denied')):
                    refusal(lambda:reader(source,'image'),'RESOURCE_UNREADABLE')
            fifo=root/'pipe';os.mkfifo(fifo)
            refusal(lambda:admit_file(fifo,'image'),'INVALID_RESOURCE')
            target=root/'partial.png';target.write_bytes(b'old')
            refusal(lambda:capture_file(source,target,0,'image'),'RESOURCE_NOT_FOUND')
            self.assertFalse(target.exists())
            document={'version':'schemaxis.blender.production/1','prepareOnly':True,'production':{'images':[{'id':'label','file':str(source)}]}}
            document['production']['objects']=[{'id':'patch','kind':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]]}]
            # Full public construction reaches real capture; only the runtime
            # probe is replaced so failures cannot start an application worker.
            with patch('schemaxis.adaptors.blender.adaptor.Interpreter.probe',return_value=SimpleNamespace(version='5.2.3')):
                refusal(lambda:run(document,root/'missing-run',executable='/unused'),'RESOURCE_NOT_FOUND')
                document['production']['images'][0]['file']=str(fifo)
                refusal(lambda:run(document,root/'fifo-run',executable='/unused'),'INVALID_RESOURCE')
                source.write_bytes(png_header(8,8))
                document['production']['images'][0]['file']=str(source)
                real_admit=admit_file
                def removed_during_admission(path,where,total=0):
                    path.unlink();return real_admit(path,where,total)
                with patch('schemaxis.adaptors.blender.image_assets.admit_file',side_effect=removed_during_admission):
                    refusal(lambda:run(document,root/'vanished-run',executable='/unused'),'RESOURCE_NOT_FOUND')
                source.write_bytes(png_header(8,8))
                self.assertEqual(admit_file(source,'image'),33)
                self.assertEqual(capture_file(source,target,33,'image'),digest_file(source,'image'))

    def test_display_image_reference_is_typed_and_independent_of_shader_nodes(self):
        material=graph();material['displayTexture']={'kind':'image','image':'label'}
        authored={'images':[{'id':'label','file':'label.png'}],'materialGraphs':[material]};before=copy.deepcopy(authored)
        result=validate(authored,{})
        self.assertEqual(authored,before);self.assertEqual(validate(result,{}),result)
        self.assertEqual(result['materialGraphs'][0]['displayTexture'],material['displayTexture'])
        self.assertEqual(result['images'][0]['alphaMode'],'straight')
        self.assertEqual(validate({'materialGraphs':[graph()]},{})['materialGraphs'][0]['displayTexture'],{'kind':'none'})
        self.assertIn('displayTexture',schema()['properties']['materialGraphs']['items']['properties'])

    def test_unknown_images_missing_payload_and_group_display_are_refused(self):
        for selection in ({'kind':'image','image':'missing'},{'kind':'image'},{'kind':'none','image':'label'}):
            material=graph();material['displayTexture']=selection
            with self.assertRaises(SchemaxisError):validate({'materialGraphs':[material]}, {})
        material=graph();material['displayTexture']={'kind':'none'}
        with self.assertRaises(SchemaxisError):validate_graph(material,'material','group')

    def test_alpha_modes_and_texture_renderer_defaults_are_idempotent(self):
        for mode in ('straight','premultiplied','channelPacked','ignore'):
            result=validate({'images':[{'id':'label','file':'label.png','alphaMode':mode}]},{})
            self.assertEqual(validate(result,{}),result)
        with self.assertRaises(SchemaxisError):validate({'images':[{'id':'label','file':'label.png','alphaMode':'arbitrary'}]}, {})
        render=render_settings({'renderer':{'kind':'workbench','colourSource':{'kind':'texture'}}})
        self.assertEqual(render_settings(render),render)

    def test_png_dimensions_refuse_before_native_decode(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'input.png';path.write_bytes(png_header(2048,2048))
            self.assertEqual(admit_file(path,'image'),33)
            for width,height in ((2049,2048),(8193,1),(0,1)):
                path.write_bytes(png_header(width,height))
                with self.assertRaises(SchemaxisError):admit_file(path,'image')
            damaged=bytearray(png_header(2,2));damaged[-1]^=1;path.write_bytes(damaged)
            with self.assertRaises(SchemaxisError):admit_file(path,'image')

    def test_jpeg_header_and_file_aggregate_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'input.jpg'
            def header(width,height):return b'\xff\xd8\xff\xc0'+struct.pack('>H',11)+struct.pack('>BHHBBBB',8,height,width,1,1,17,0)
            path.write_bytes(header(256,128));self.assertEqual(admit_file(path,'image'),path.stat().st_size)
            path.write_bytes(header(4096,2048))
            with self.assertRaises(SchemaxisError):admit_file(path,'image')
            path.write_bytes(header(32,32))
            with self.assertRaises(SchemaxisError):admit_file(path,'image',MAX_CAPTURE_BYTES)
            with path.open('wb') as stream:stream.truncate(MAX_FILE_BYTES+1)
            with self.assertRaises(SchemaxisError):admit_file(path,'image')

    def test_bounded_capture_preserves_bytes_and_refuses_changed_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'source.png';target=Path(temporary)/'capture.png'
            source.write_bytes(png_header(8,8))
            self.assertEqual(capture_file(source,target,33,'image'),digest_file(source,'image'))
            self.assertEqual(source.read_bytes(),target.read_bytes())
            for wrong_size in (32,34):
                with self.assertRaises(SchemaxisError) as error:capture_file(source,target,wrong_size,'image')
                self.assertEqual(error.exception.fault.code,'INPUT_CHANGED');self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
