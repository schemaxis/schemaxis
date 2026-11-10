"""Pinned Blender files share a closed host/schema consumption policy."""
import copy,tempfile,unittest
from pathlib import Path
from schemaxis.adaptors.blender.captured_inputs import accept_resource
from schemaxis.captured_inputs import adopt,consume
from schemaxis.errors import SchemaxisError
from schemaxis.schema_authoring import version_schema
from schemaxis.studio_guidance import fields


class BlenderCapturedInputs(unittest.TestCase):
    def test_declared_consumers_have_host_and_authored_schema_routes(self):
        resource={'kind':'file','member':'source.blend'}
        p={'images':[{'id':'image','file':'file.png'}],'assets':[{'id':'asset','file':'source.blend','format':'blend'}]}
        documents=[
            ({'version':'schemaxis.blender.production/1','production':p},['/production/images/0/file','/production/assets/0/file']),
            ({'version':'schemaxis.blender/1','scenes':[{'production':p}],'nodes':[{'filter':reader,'options':{'file':'source'}} for reader in ('readGltf','readSTL','readPLY','curveFromCSV')]},['/scenes/0/production/images/0/file','/scenes/0/production/assets/0/file',*[f'/nodes/{n}/options/file' for n in range(4)]]),
            ({'version':'schemaxis.blender.render/1','sceneFile':'file.blend'},['/sceneFile'])]
        for document,pointers in documents:
            with self.subTest(version=document['version']):
                for pointer in pointers:
                    self.assertIn('reader',accept_resource(document,pointer,resource))
                    for wrong in ({'kind':'directory','member':'source.blend'},{'kind':'fileSet','member':'source.blend'},{'kind':'file','member':None}):
                        with self.assertRaises(SchemaxisError):accept_resource(document,pointer,wrong)
                schema=version_schema(document['version'],authored=True,artifact=True)
                references=[path for path,node in fields(schema) if node.get('$ref')=='#/$defs/capturedInput']
                self.assertEqual(len(references),len(pointers),references)
                literal=version_schema(document['version'],authored=True)
                self.assertNotIn('capturedInput',literal['$defs'])
        document=documents[1][0]
        for pointer in ('/scenes/0/render/file','/scenes/0/production/images/1/file','/nodes/4/options/file','/nodes/00/options/file','/nodes/²/options/file','/nodes/'+('9'*5000)+'/options/file','/nodes/0/inputs/file','/nodes/0/options/file/extra','/production/assets/0/file'):
            with self.subTest(pointer=pointer),self.assertRaises(SchemaxisError):accept_resource(document,pointer,resource)
        bad=copy.deepcopy(document);bad['nodes'][0]['filter']='material'
        with self.assertRaises(SchemaxisError):accept_resource(bad,'/nodes/0/options/file',resource)

    def test_true_pinned_file_consumption_and_digest_tamper_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'label.png';source.write_bytes(b'fixture')
            pinned=adopt(source,root/'snapshot')
            document={'version':'schemaxis.blender.production/1','production':{'images':[{'id':'label','file':pinned['reference']}]}}
            resolved,evidence=consume(document,'document')
            self.assertEqual(Path(resolved['production']['images'][0]['file']).read_bytes(),b'fixture')
            self.assertEqual(evidence[0]['policy']['reader'],'image')
            self.assertEqual(document['production']['images'][0]['file'],pinned['reference'])
            for malformed in (
                {'version':'schemaxis.blender.production/1','production':{'images':{'0':{'file':pinned['reference']}}}},
                {'version':'schemaxis.blender/1','nodes':{'0':{'filter':'readSTL','options':{'file':pinned['reference']}}}},
                {'version':'schemaxis.blender/1','scenes':{'0':{'production':{'assets':[{'file':pinned['reference']}]}}}}):
                with self.subTest(malformed=malformed),self.assertRaises(SchemaxisError) as caught:consume(malformed,'document')
                self.assertEqual(caught.exception.fault.code,'UNSUPPORTED_RESOURCE')
            member=Path(resolved['production']['images'][0]['file']);member.write_bytes(b'changed')
            with self.assertRaises(SchemaxisError):consume(document,'document')

    def test_authored_workflow_schema_admits_only_declared_resource_fields(self):
        import jsonschema
        from schemaxis.adaptors.blender.production_job import lower
        reference={'$resource':'/snapshot','digest':'a'*64,'member':'source.png'}
        production={'version':'schemaxis.blender.production/1','production':{'images':[{'id':'label','file':'source.png'}],
            'assets':[{'id':'model','file':'source.blend','format':'blend'}],
            'objects':[{'id':'patch','kind':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]]}]}}
        dag=lower(production);dag['nodes'].append({'id':'read','filter':'readSTL','options':{'file':'mesh.stl'}})
        saved={'version':'schemaxis.blender.render/1','sceneFile':'source.blend','cameras':[{}]}
        for document in (production,dag,saved):
            validator=jsonschema.Draft202012Validator(version_schema(document['version'],authored=True,artifact=True))
            validator.validate(document)
            for pointer in ('/sceneFile',) if document is saved else (('/production/images/0/file','/production/assets/0/file') if document is production else ('/nodes/1/options/file','/scenes/0/production/images/0/file','/scenes/0/production/assets/0/file')):
                changed=copy.deepcopy(document);parent=changed;parts=pointer.split('/')[1:]
                for part in parts[:-1]:parent=parent[int(part)] if isinstance(parent,list) else parent[part]
                parent[parts[-1]]=reference;validator.validate(changed)
            bad=copy.deepcopy(document)
            if document is saved:bad['cameras']=reference
            elif document is production:bad['production']['images'][0]['colourSpace']=reference
            else:bad['nodes'][0]['filter']=reference
            self.assertFalse(validator.is_valid(bad))


if __name__=='__main__':unittest.main()
